"""Persistent idempotency and progress for collect and common-box sync."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.sourcing import MiaoshouSyncTask
from app.models.user import User
from app.schemas.miaoshou import normalized_link

ACTIVE = ['queued', 'running', 'waiting', 'uncertain']


async def create_task(db, user_id, data, kind):
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if kind == 'collect':
        unique = {}
        for link in data.links:
            item = normalized_link(link)
            unique.setdefault(item.source_product_id, {'source_item_id': item.source_product_id,
                              'url': item.product_url, 'submitted_url': link, 'common_detail_id': None, 'state': 'pending'})
        items = list(unique.values())
        # One external collection remains active per URL set across target markets.
        identity = {'kind': kind, 'sources': sorted(unique)}
        if data.claim_platform:
            identity['claim_platform'] = data.claim_platform
            for item in items:
                item['claim_platform'] = data.claim_platform
    else:
        items = [{'common_detail_id': id, 'state': 'pending'} for id in sorted(data.common_detail_ids)]
        identity = {'kind': kind, 'ids': sorted(data.common_detail_ids), 'market': data.target_market, 'currency': data.currency}
    for item in items:
        item['analyze_after_sync'] = data.analyze_after_sync
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    existing = await db.scalar(select(MiaoshouSyncTask).where(MiaoshouSyncTask.owner_id == user_id, MiaoshouSyncTask.request_key == data.request_key))
    if existing:
        if existing.fingerprint != signature or existing.target_market != data.target_market or existing.currency != data.currency or existing.items[0].get('analyze_after_sync', False) != data.analyze_after_sync:
            raise HTTPException(409, '相同 request_key 不能用于不同请求')
        return existing, True
    active = await db.scalar(select(MiaoshouSyncTask).where(MiaoshouSyncTask.owner_id == user_id, MiaoshouSyncTask.fingerprint == signature, MiaoshouSyncTask.status.in_(ACTIVE)))
    if active:
        if active.items[0].get('analyze_after_sync', False) != data.analyze_after_sync:
            raise HTTPException(409, f'已有任务 {active.id} 的分析选项不同，请等待完成后从候选池操作')
        if active.target_market != data.target_market or active.currency != data.currency:
            raise HTTPException(409, f'同链接已有未完成采集任务 {active.id}，请先查询，再同步到其他站点')
        return active, True
    if kind == 'collect':
        # Serialize overlapping batches as well as exact URL sets, including across markets.
        jobs = (await db.scalars(select(MiaoshouSyncTask).where(MiaoshouSyncTask.owner_id == user_id,
            MiaoshouSyncTask.kind == 'collect', MiaoshouSyncTask.status.in_(ACTIVE + ['failed'])))).all()
        wanted = set(unique)
        for previous in jobs:
            unresolved = {x.get('source_item_id') for x in previous.items if x.get('state') != 'saved'}
            if wanted & unresolved and (previous.status in ACTIVE or previous.external_started_at is not None):
                raise HTTPException(409, f'部分商品已有未确认采集任务 {previous.id}，请先查询平台状态')
    task = MiaoshouSyncTask(owner_id=user_id, request_key=data.request_key, fingerprint=signature, kind=kind,
                           target_market=data.target_market, currency=data.currency, items=items)
    db.add(task)
    await db.flush()
    return task, False


def task_dto(task):
    fields = ('id', 'kind', 'target_market', 'currency', 'status', 'stage', 'poll_count', 'error_code', 'error_message',
              'created_at', 'updated_at', 'external_started_at', 'finished_at')
    item_fields = ('source_item_id', 'url', 'common_detail_id', 'candidate_id', 'state', 'error_code', 'error',
                   'analysis_task_id', 'sync_status', 'completeness', 'updated', 'reused_platform',
                   'claim_platform', 'platform_detail_id')
    return {**{k: getattr(task, k) for k in fields},
            'items': [{k: x[k] for k in item_fields if k in x} for x in task.items],
            'completed': sum(item_done(x) for x in task.items), 'total': len(task.items)}


def item_done(item):
    """公共采集箱详情已入库；需要认领的商品还须在平台采集箱中确认。"""
    return item.get('state') == 'saved' and (not item.get('claim_platform') or bool(item.get('platform_detail_id')))


async def owned_task(db, id, user_id, lock=False):
    query = select(MiaoshouSyncTask).where(MiaoshouSyncTask.id == id, MiaoshouSyncTask.owner_id == user_id)
    task = await db.scalar(query.with_for_update() if lock else query)
    if not task:
        raise HTTPException(404, '妙手采集同步任务不存在')
    return task
