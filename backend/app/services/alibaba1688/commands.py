"""白名单命令构造。客户端只能选择命令名与受校验的参数，不能传入任意 CLI 参数。

所有位置参数放在 `--` 之后，避免以 `-` 开头的关键词被 CLI 当作选项解析。
只读命令以外（login/logout/cart/checkout/seller/feedback）不在白名单中，无法被调用。
"""
import re
from decimal import Decimal

from app.services.alibaba1688.errors import Alibaba1688Error

OFFER_ID = re.compile(r'^\d{6,20}$')
MEMBER_ID = re.compile(r'^b2b-[A-Za-z0-9_-]{1,64}$')
SORTS = ('relevance', 'best-selling', 'price-asc', 'price-desc')
VERIFIED = ('any', 'factory', 'business', 'super-factory')
# 关键词：去掉控制字符、长度限制，不允许以 - 开头
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def clean_keyword(value: str, max_len: int = 50) -> str:
    value = ' '.join(CONTROL.sub(' ', value or '').split())
    if not value:
        raise Alibaba1688Error('bad_input', '关键词不能为空')
    if len(value) > max_len:
        raise Alibaba1688Error('bad_input', f'关键词不能超过 {max_len} 个字符')
    if value.startswith('-'):
        raise Alibaba1688Error('bad_input', '关键词不能以 - 开头')
    return value


def check_offer_id(value: str) -> str:
    value = str(value or '').strip()
    if not OFFER_ID.match(value):
        raise Alibaba1688Error('bad_input', '1688 商品 ID 必须是 6–20 位数字')
    return value


def check_supplier_target(value: str) -> str:
    value = str(value or '').strip()
    if not (OFFER_ID.match(value) or MEMBER_ID.match(value)):
        raise Alibaba1688Error('bad_input', '供应商标识必须是商品 ID 或 b2b- 开头的 memberId')
    return value


def _price(value) -> str | None:
    if value is None:
        return None
    d = Decimal(str(value))
    if not d.is_finite() or d < 0 or d > 1_000_000:
        raise Alibaba1688Error('bad_input', '价格区间无效')
    return format(d.normalize(), 'f')


def build(command: str, params: dict, max_results: int) -> tuple[list[str], list[str]]:
    """返回 (选项参数, 位置参数)。"""
    p = params or {}
    if command == 'doctor':
        return ['doctor', '--no-launch', '--json'], []
    if command == 'whoami':
        return ['whoami', '--json'], []
    if command == 'daemon_status':
        return ['daemon', 'status', '--json'], []
    if command == 'version':
        return ['--version'], []
    if command == 'search':
        n = int(p.get('max', 20))
        if not 1 <= n <= max_results:
            raise Alibaba1688Error('bad_input', f'单次结果数量须在 1–{max_results} 之间')
        sort = p.get('sort') or 'relevance'
        verified = p.get('verified') or 'any'
        if sort not in SORTS or verified not in VERIFIED:
            raise Alibaba1688Error('bad_input', '排序或认证筛选值无效')
        opts = ['search', '--max', str(n), '--sort', sort, '--verified', verified]
        lo, hi = _price(p.get('price_min')), _price(p.get('price_max'))
        if lo is not None and hi is not None and Decimal(lo) > Decimal(hi):
            raise Alibaba1688Error('bad_input', '最低价不能高于最高价')
        if lo is not None:
            opts += ['--price-min', lo]
        if hi is not None:
            opts += ['--price-max', hi]
        if p.get('exclude_ads'):
            opts.append('--exclude-ads')
        return opts + ['--json'], [clean_keyword(p.get('keyword', ''))]
    if command == 'offer':
        return ['offer', '--json'], [check_offer_id(p.get('offer_id'))]
    if command == 'image_search':
        n = int(p.get('max', 20))
        if not 1 <= n <= max_results:
            raise Alibaba1688Error('bad_input', f'单次结果数量须在 1–{max_results} 之间')
        path = p.get('path')
        if not path:
            raise Alibaba1688Error('bad_input', '缺少图片')
        return ['image-search', '--max', str(n), '--json'], [str(path)]
    if command == 'supplier_search':
        n = int(p.get('max', 20))
        if not 1 <= n <= max_results:
            raise Alibaba1688Error('bad_input', f'单次结果数量须在 1–{max_results} 之间')
        opts = ['supplier', 'search', '--max', str(n), '--enrich', '0']
        if p.get('factory_only'):
            opts.append('--factory-only')
        if p.get('province'):
            opts += ['--province', clean_keyword(p['province'], 20)]
        return opts + ['--json'], [clean_keyword(p.get('keyword', ''))]
    if command == 'supplier_inspect':
        return ['supplier', 'inspect', '--json'], [check_supplier_target(p.get('target'))]
    raise Alibaba1688Error('bad_input', '不支持的 1688 命令')


READ_ONLY_COMMANDS = ('doctor', 'whoami', 'daemon_status', 'version', 'search', 'offer', 'image_search',
                      'supplier_search', 'supplier_inspect')
