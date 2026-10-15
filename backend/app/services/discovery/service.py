"""Transactional API-side operations for discovery tasks."""
import copy
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.discovery import ACTIVE_STATUSES, DiscoveryResult, DiscoveryTask
from app.models.user import User
from app.services.discovery.config import DiscoverySettings

STATUS_LABELS = {'queued': '排队中', 'planning': '规划搜索关键词', 'searching': '搜索真实货源', 'filtering': '去重筛选',
                 'awaiting_confirmation': '等待确认采集', 'collecting': '妙手采集中', 'analyzing': '文字证据分析',
                 'completed': '已完成', 'partial_failed': '部分失败', 'failed': '失败', 'cancelled': '已取消'}


def now():
    return datetime.now(timezone.utc)


def fingerprint(goal: dict) -> str:
    return hashlib.sha256(json.dumps(goal, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def create_task(db, user_id, data, settings: DiscoverySettings):
    if data.auto_collect:
        raise HTTPException(422, '请在候选库人工勾选后采集；AI 选品不执行妙手采集')
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())  # serialize per user
    goal = data.goal()
    goal['workflow_version'] = 2
    goal['market_evidence'] = []
    if data.report_id:
        from app.models.sourcing import MarketReport
        report = await db.scalar(select(MarketReport).where(MarketReport.id == data.report_id, MarketReport.owner_id == user_id))
        if not report or report.target_market != data.target_market:
            raise HTTPException(422, '榜单不存在或地区不匹配')
        chosen = set(data.report_rows)
        rows = [r for r in report.rows if r['row_number'] in chosen]
        if not chosen or len(rows) != len(chosen):
            raise HTTPException(422, '请选择本榜单的 1–20 条记录')
        goal['market_evidence'] = [{**r, 'evidence_id': f'{report.id}:{r["row_number"]}',
                                   'report_name': report.name, 'scope': report.scope} for r in rows]
    elif data.report_rows:
        raise HTTPException(422, '请先选择榜单')
    goal['max_candidates'] = min(goal['max_candidates'], settings.discovery_max_results)
    signature = fingerprint(goal)
    existing = await db.scalar(select(DiscoveryTask).where(DiscoveryTask.owner_id == user_id, DiscoveryTask.request_key == data.request_key))
    if existing:
        if existing.fingerprint != signature or existing.auto_collect != data.auto_collect:
            raise HTTPException(409, '相同 request_key 不能用于不同的选品目标')
        return existing, True
    active = await db.scalar(select(DiscoveryTask).where(DiscoveryTask.owner_id == user_id, DiscoveryTask.fingerprint == signature,
                                                         DiscoveryTask.status.in_(ACTIVE_STATUSES)))
    if active:
        return active, True
    limits = settings.limits()
    task = DiscoveryTask(owner_id=user_id, request_key=data.request_key, fingerprint=signature, goal=goal,
                         auto_collect=data.auto_collect, status='queued', resume_stage='planning', progress_message='已创建，等待 Worker',
                         search_log=[], stage_errors=[], attempts=0,
                         budget={'search_calls': limits['max_search_calls'], 'model_calls': limits['max_model_calls'],
                                 'collect': limits['max_collect'], 'keywords': limits['max_keywords'],
                                 'pages_per_keyword': limits['pages_per_keyword']},
                         usage={'search_calls': 0, 'model_calls': 0, 'collect': 0}, next_run_at=now())
    db.add(task)
    await db.flush()
    return task, False


async def owned_task(db, task_id, user_id, lock=False):
    query = select(DiscoveryTask).where(DiscoveryTask.id == task_id, DiscoveryTask.owner_id == user_id)
    task = await db.scalar(query.with_for_update() if lock else query)
    if not task:
        raise HTTPException(404, '发现任务不存在')
    return task


async def confirm_collect(db, task, source_item_ids):
    raise HTTPException(409, '流程已更新，请到统一候选库勾选采集')


async def cancel(db, task):
    if task.status not in ('queued', 'awaiting_confirmation') or task.lease_token is not None:
        raise HTTPException(409, '只能取消尚未执行或等待确认的任务；执行中的外部调用不能中途撤回')
    task.status, task.cancelled_at, task.finished_at = 'cancelled', now(), now()
    task.progress_message = '用户已取消，未执行的阶段不会再运行'
    task.next_run_at = None
    await db.flush()
    await db.refresh(task)
    return task


def result_dto(row: DiscoveryResult, candidate=None):
    snippet = row.snippet_title if row.snippet_expires_at and row.snippet_expires_at > now() else None
    data = {k: getattr(row, k) for k in ('id', 'source_platform', 'source_item_id', 'canonical_url', 'provider', 'search_keyword',
                                        'search_query', 'search_position', 'discovered_at', 'status', 'status_reason',
                                        'prior_candidate_id', 'candidate_id', 'analysis_task_id', 'evaluation_id',
                                        'assessment', 'rank_score', 'rank_position')}
    data['snippet_title'] = snippet
    data['snippet_note'] = '1688 搜索结果标题；规格与采购条件仍需核实' if snippet else None
    if candidate is not None:
        data['candidate'] = {'id': candidate.id, 'name': candidate.name, 'main_image': candidate.main_image,
                             'images': candidate.images, 'purchase_price': candidate.purchase_price, 'currency': candidate.currency,
                             'category': candidate.category, 'product_url': candidate.product_url,
                             'original_url': candidate.original_url, 'completeness': candidate.completeness,
                             'review_status': candidate.review_status, 'version': candidate.version,
                             'data_source': candidate.data_source, 'miaoshou_detail_id': candidate.miaoshou_detail_id}
    return data


def task_dto(task: DiscoveryTask, counts: dict | None = None):
    data = {k: getattr(task, k) for k in ('id', 'goal', 'auto_collect', 'status', 'resume_stage', 'progress_message', 'plan',
                                         'search_log', 'budget', 'usage', 'stage_errors', 'collect_task_id', 'attempts',
                                         'created_at', 'updated_at', 'cancelled_at', 'finished_at')}
    data['status_label'] = STATUS_LABELS.get(task.status, task.status)
    data['running'] = task.lease_token is not None
    data['search_log'] = [{k: v for k, v in e.items() if k != 'offers'} for e in copy.deepcopy(task.search_log or [])]
    if counts is not None:
        data['result_counts'] = counts
    return data
