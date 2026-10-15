"""Per-scenario Bailian model choices and the model usage ledger.

Candidate model IDs, tiers and prices were checked on 2026-10-15 against the official Model Studio docs
(help.aliyun.com/zh/model-studio: text-generation-model, vision-model, image-model, model-pricing,
qwen-mt-image-api) and against GET {BAILIAN_BASE_URL}/models for the configured key. Prices are the
China (Beijing) list prices at that date and are shown only as a guide.

Without a saved choice a scenario keeps the model from WorkbenchSettings (.env / defaults), so nothing
changes until an admin picks a model.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import null, select
from sqlalchemy.dialects.postgresql import insert

from app.models.system_settings import ModelSetting, ModelUsageLog

logger = logging.getLogger(__name__)

# Chat candidates for the workbench: every one accepts text + image input, JSON output and enable_thinking=false,
# which the OCR / copy / fill prompts rely on.
CHAT_CANDIDATES = [
    {'id': 'qwen3.8-max', 'tier': '旗舰',
     'note': '千问当前能力最强的旗舰，推理和复杂资料理解最好；响应最慢、价格最高。',
     'price': '输入 12 元 / 输出 36 元（每百万 tokens）'},
    {'id': 'qwen3.7-plus', 'tier': '均衡',
     'note': '官方推荐的能力与成本均衡款，效果接近旗舰；速度中等。',
     'price': '输入 2 元 / 输出 8 元（每百万 tokens，≤256K，官方限时 8 折）'},
    {'id': 'qwen3.5-plus', 'tier': '均衡（上一代）',
     'note': '当前默认模型，上一代均衡款，已在本系统实测可用；速度中等、价格较低。',
     'price': '输入 0.8 元 / 输出 4.8 元（每百万 tokens，≤128K）'},
    {'id': 'qwen3.8-flash', 'tier': '轻量',
     'note': '轻量低成本，官方称效果接近旗舰；响应快，输出价格低于 qwen3.5-plus。',
     'price': '输入 0.8 元 / 输出 2.7 元（每百万 tokens）'},
    {'id': 'qwen3.7-flash', 'tier': '轻量',
     'note': '最便宜的一档，响应快；复杂类目属性推理能力弱于 plus / max。',
     'price': '输入 0.2 元 / 输出 0.8 元（每百万 tokens，≤32K）'},
]

# Image models of the Qwen-Image family; all support text-to-image and image editing.
IMAGE_CANDIDATES = [
    {'id': 'qwen-image-3.0', 'tier': '均衡',
     'note': '当前默认模型，千问图像 3.0 标准版，兼顾质量与速度，已在本系统实测可用。',
     'price': '输入 0.02 元/张，输出 0.18 元/张'},
    {'id': 'qwen-image-3.0-pro', 'tier': '旗舰',
     'note': '千问图像 3.0 旗舰版，文字渲染和真实质感最好；比标准版慢、贵。',
     'price': '输入 0.02 元/张，输出 0.25 元/张（1K）、0.5 元/张（2K）'},
    {'id': 'qwen-image-2.1-pro', 'tier': '均衡（上一代）',
     'note': '上一代中官方称速度、效果、成本最均衡的版本，支持最多 10 张参考图。',
     'price': '输出 0.25 元/张'},
    {'id': 'qwen-image-2.0', 'tier': '加速（上一代）',
     'note': '上一代加速版，兼顾效果与响应速度；画质弱于 3.0。',
     'price': '输出 0.2 元/张'},
]

TRANSLATE_CANDIDATES = [
    {'id': 'qwen-mt-image-2.0', 'tier': '标准',
     'note': '当前默认模型，支持 55 种语言互译和商品主体检测，已在本系统实测可用。',
     'price': '0.004 元/张'},
    {'id': 'qwen-mt-image', 'tier': '上一代',
     'note': '上一代图片翻译，仅支持中/英与其他语种互译（源或目标须为中文或英文）。',
     'price': '0.003 元/张'},
]

SCENARIOS = [
    {'key': 'workbench_ocr', 'label': '图片文字识别', 'used_in': '商品工作台 · 识别图片文字',
     'unit': 'tokens', 'setting': 'workbench_text_model', 'candidates': CHAT_CANDIDATES},
    {'key': 'workbench_copy', 'label': '商品文案生成', 'used_in': '商品工作台 · 生成标题 / 卖点 / 描述',
     'unit': 'tokens', 'setting': 'workbench_text_model', 'candidates': CHAT_CANDIDATES},
    {'key': 'workbench_fill', 'label': '类目与属性填充', 'used_in': '商品工作台 · AI 填充类目、属性、规格和重量',
     'unit': 'tokens', 'setting': 'workbench_text_model', 'candidates': CHAT_CANDIDATES},
    {'key': 'workbench_image', 'label': '图片生成 / 编辑', 'used_in': '商品工作台 · AI 生图、改图',
     'unit': 'images', 'setting': 'workbench_image_model', 'candidates': IMAGE_CANDIDATES},
    {'key': 'workbench_translate', 'label': '图片翻译', 'used_in': '商品工作台 · 图片文字翻译',
     'unit': 'images', 'setting': 'workbench_translation_model', 'candidates': TRANSLATE_CANDIDATES},
]
SCENARIO_BY_KEY = {s['key']: s for s in SCENARIOS}

# Workbench task kind -> scenario.
KIND_SCENARIO = {'ocr': 'workbench_ocr', 'copy': 'workbench_copy', 'fill': 'workbench_fill',
                 'generate': 'workbench_image', 'edit': 'workbench_image', 'translate': 'workbench_translate'}

# Labels for usage rows from calls whose model is not chosen here (DeepSeek runs on its own key and .env setting).
USAGE_LABELS = {**{s['key']: s['label'] for s in SCENARIOS},
                'sourcing_text': '选品 AI 评估（DeepSeek）', 'sourcing_vision': '选品图片评估（百炼视觉）',
                'discovery_planner': '自动发现 · 关键词规划（DeepSeek）', 'discovery_scoring': '自动发现 · 排名评分（DeepSeek）',
                'market_evidence': '市场证据分析（DeepSeek）', 'deepseek': 'DeepSeek（未分类）', 'bailian': '百炼（未分类）'}

# Tests point this at their own database; the app and workers use the default engine.
session_factory = None


def default_model(settings, scenario):
    return getattr(settings, SCENARIO_BY_KEY[scenario]['setting'])


async def saved_models(db):
    return {row.scenario: row for row in (await db.scalars(select(ModelSetting))).all()}


async def effective_models(db, settings):
    saved = await saved_models(db)
    return {key: saved[key].model if key in saved else default_model(settings, key) for key in SCENARIO_BY_KEY}


def _int(value):
    return value if type(value) is int and value >= 0 else None


def parse_usage(usage):
    """Read counts exactly as returned. Missing fields stay None; nothing is estimated."""
    usage = usage if isinstance(usage, dict) else {}
    return {'input_tokens': _int(usage.get('prompt_tokens', usage.get('input_tokens'))),
            'output_tokens': _int(usage.get('completion_tokens', usage.get('output_tokens'))),
            'total_tokens': _int(usage.get('total_tokens')),
            'input_images': _int(usage.get('input_image_count')),
            'output_images': _int(usage.get('output_image_count', usage.get('image_count')))}


async def record_usage(*, provider, scenario, model, usage, status='succeeded', request_id=None,
                       source_type=None, source_id=None, user_id=None, sessions=None):
    """Append one ledger row in its own transaction. Never raises: a ledger failure must not fail the business call."""
    try:
        if sessions is None:
            sessions = session_factory
        if sessions is None:
            from app.core.database import async_session_factory
            sessions = async_session_factory
        values = {'provider': provider, 'scenario': scenario, 'model': str(model or '')[:100] or 'unknown',
                  # SQL NULL (not JSON null) marks "usage not returned".
                  'status': status, 'usage': usage if isinstance(usage, dict) else null(),
                  'request_id': str(request_id)[:200] if request_id else None,
                  'source_type': source_type, 'source_id': str(source_id) if source_id else None,
                  'user_id': user_id, 'called_at': datetime.now(timezone.utc), **parse_usage(usage)}
        statement = insert(ModelUsageLog).values(**values)
        if values['request_id']:
            statement = statement.on_conflict_do_nothing(index_elements=['provider', 'request_id'],
                                                         index_where=ModelUsageLog.request_id.isnot(None))
        async with sessions() as db, db.begin():
            await db.execute(statement)
    except Exception as error:  # noqa: BLE001
        logger.warning('Model usage not recorded for %s/%s: %s', scenario, model, type(error).__name__)
