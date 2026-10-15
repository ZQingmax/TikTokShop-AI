"""我的采集箱：本系统的数据空间。同步到妙手：采集进公共采集箱，TikTok 再认领到 TK 采集箱；不发布、不上架。"""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.collect_box import CollectBoxItem as Item
from app.models.sourcing import MiaoshouSyncTask, SourcingReview as Review
from app.models.user import User
from app.schemas.sourcing import Market
from app.services import sourcing_service as service
from app.services.miaoshou_tasks import item_done

router = APIRouter(prefix='/v1/collect-box', tags=['My Collect Box'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)
SNAPSHOT = ('source_product_id', 'product_url', 'name', 'main_image', 'purchase_price', 'currency', 'category', 'supplier', 'target_market')


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以操作采集箱')


def dto(item):
    return {k: getattr(item, k) for k in ('id', 'candidate_id', *SNAPSHOT, 'note', 'miaoshou_box', 'miaoshou_detail_id',
                                          'sync_status', 'sync_task_id', 'sync_error', 'synced_at', 'created_at', 'updated_at')}


def apply_task(item, task):
    """按本系统发起的采集任务结果更新同步状态；平台未确认前不标记成功。"""
    if not task:
        return
    entry = next((x for x in task.items if x.get('source_item_id') == item.source_product_id), None)
    if entry and item_done(entry):
        # TikTok 采集箱记录平台采集箱 ID，公用采集箱记录公共采集箱 ID
        detail_id = entry.get('platform_detail_id') if entry.get('claim_platform') else entry.get('common_detail_id')
        item.sync_status, item.miaoshou_detail_id, item.sync_error = 'synced', detail_id, None
        item.synced_at = item.synced_at or task.finished_at or datetime.now(timezone.utc)
    elif task.status in ('failed', 'uncertain'):
        item.sync_status = 'failed'
        item.sync_error = (entry or {}).get('error') or task.error_message or '妙手未确认采集结果，请在任务记录中查询平台状态'
    else:
        item.sync_status, item.sync_error = 'syncing', None


async def refresh_sync(db, items, user_id):
    ids = {x.sync_task_id for x in items if x.sync_task_id and x.sync_status in ('syncing', 'failed')}
    if not ids:
        return
    tasks = {t.id: t for t in (await db.scalars(select(MiaoshouSyncTask).where(
        MiaoshouSyncTask.id.in_(ids), MiaoshouSyncTask.owner_id == user_id))).all()}
    for item in items:
        if item.sync_task_id in ids:
            apply_task(item, tasks.get(item.sync_task_id))
    await db.flush()


@router.get('/items')
async def items(target_market: Market | None = None, keyword: str | None = Query(None, max_length=100),
                sync_status: Literal['not_synced', 'syncing', 'synced', 'failed'] | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: AsyncSession = DB, user: User = AUTH):
    query = select(Item).where(Item.owner_id == user.id)
    if target_market:
        query = query.where(Item.target_market == target_market)
    if keyword:
        query = query.where(or_(Item.name.ilike(f'%{keyword}%'), Item.source_product_id.ilike(f'%{keyword}%')))
    # 先刷新进行中的同步，再按状态筛选，避免筛选结果滞后
    pending = (await db.scalars(query.where(Item.sync_status.in_(['syncing', 'failed']), Item.sync_task_id.is_not(None)))).all()
    await refresh_sync(db, pending, user.id)
    if sync_status:
        query = query.where(Item.sync_status == sync_status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(Item.created_at.desc(), Item.id).offset((page - 1) * page_size).limit(page_size))).all()
    counts = dict((await db.execute(select(Item.sync_status, func.count()).where(Item.owner_id == user.id, *(
        [Item.target_market == target_market] if target_market else [])).group_by(Item.sync_status))).all())
    return {'items': [dto(x) for x in rows], 'total': total, 'page': page, 'page_size': page_size, 'counts': counts}


class AddInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_ids: list[UUID] = Field(min_length=1, max_length=100)


@router.post('/items', status_code=201)
async def add(data: AddInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    ids = list(dict.fromkeys(data.candidate_ids))
    existing = set((await db.scalars(select(Item.candidate_id).where(Item.owner_id == user.id, Item.candidate_id.in_(ids)))).all())
    added = []
    for id in ids:
        if id in existing:
            continue
        candidate = await service.owned(db, id, user.id, lock=True)
        if candidate.review_status == 'rejected':
            raise HTTPException(409, f'「{candidate.name or candidate.source_product_id}」已排除，请先恢复')
        item = Item(owner_id=user.id, candidate_id=candidate.id, note='', **{k: getattr(candidate, k) for k in SNAPSHOT})
        db.add(item)
        added.append(item)
        if candidate.review_status != 'approved':
            candidate.review_status = 'approved'
            db.add(Review(candidate_id=candidate.id, evaluation_id=None, input_version=candidate.version, reviewer_id=user.id,
                          action='approve', note='加入我的采集箱', input_snapshot=service.analysis_snapshot(candidate)))
    await db.flush()
    return {'added': len(added), 'skipped': len(existing), 'items': [dto(x) for x in added]}


class NoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(max_length=2000)


@router.patch('/items/{item_id}')
async def edit(item_id: UUID, data: NoteInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    item = await db.scalar(select(Item).where(Item.id == item_id, Item.owner_id == user.id))
    if not item:
        raise HTTPException(404, '采集箱商品不存在')
    item.note = data.note
    await db.flush()
    return dto(item)


class RemoveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ids: list[UUID] = Field(min_length=1, max_length=100)


@router.post('/items/remove')
async def remove(data: RemoveInput, db: AsyncSession = DB, user: User = AUTH):
    """只移出本系统采集箱；已同步到妙手的商品不会从妙手删除。"""
    operator(user)
    rows = (await db.scalars(select(Item).where(Item.owner_id == user.id, Item.id.in_(data.ids)))).all()
    await refresh_sync(db, rows, user.id)
    if any(x.sync_status == 'syncing' for x in rows):
        raise HTTPException(409, '同步中的商品不能移出，请等待任务完成')
    for row in rows:
        await db.delete(row)
    await db.flush()
    return {'removed': len(rows)}


@router.get('/candidate-ids')
async def candidate_ids(db: AsyncSession = DB, user: User = AUTH):
    return {'items': [str(x) for x in (await db.scalars(select(Item.candidate_id).where(Item.owner_id == user.id))).all()]}


class SyncInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID
    ids: list[UUID] = Field(min_length=1, max_length=50)
    box: Literal['common', 'tiktok'] = 'common'


@router.post('/sync', status_code=202)
async def sync(data: SyncInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    raise HTTPException(409, {'message': '请进入商品编辑工作台，检查并确认加工草稿后再同步妙手',
                              'workbench_url': '/collect?tab=workbench'})
