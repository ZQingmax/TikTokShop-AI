"""Auto-discovery agent API. Owner-scoped, real JWT. No publishing, purchasing or fulfillment."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.discovery import DiscoveryResult, DiscoveryTask
from app.models.sourcing import MiaoshouSyncTask, SourcingCandidate
from app.models.user import User
from app.schemas.discovery import ConfirmCollectInput, DiscoveryTaskInput
from app.services.discovery import service
from app.services.discovery.adapters import Alibaba1688OfficialSearchAdapter, default_adapter
from app.services.discovery.config import DiscoverySettings
from app.services.discovery.scoring import NOT_CONNECTED, WEIGHTS
from app.services.miaoshou_tasks import task_dto as miaoshou_task_dto
from app.services.sourcing_config import SourcingSettings
from app.clients.miaoshou_client import MiaoshouClient

router = APIRouter(prefix='/v1/sourcing/discovery', tags=['Sourcing Discovery'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以创建发现任务或提交采集')


@router.get('/status')
async def status(user: User = AUTH):
    settings, sourcing = DiscoverySettings(), SourcingSettings()
    return {'sources': [default_adapter().status(), Alibaba1688OfficialSearchAdapter().status()],
            'planner': {'provider': 'deepseek', 'model': sourcing.deepseek_model, 'configured': bool(sourcing.deepseek_api_key.get_secret_value())},
            'vision': {'provider': 'bailian', 'model': sourcing.bailian_vision_model, 'configured': False},
            'collector': {'provider': 'miaoshou', 'configured': MiaoshouClient().configured, 'operation': 'fetch_item（单次提交，超时只查询）'},
            'limits': settings.limits(), 'ranking_weights': {}, 'not_connected': NOT_CONNECTED,
            'data_policy': '1688真实资料与用户导入榜单分别保留；不计算视觉评分、热度或利润；人工勾选后才采集到妙手'}


@router.post('/tasks', status_code=202)
async def create(data: DiscoveryTaskInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    task, reused = await service.create_task(db, user.id, data, DiscoverySettings())
    return {**service.task_dto(task), 'reused': reused}


async def counts(db, task_ids):
    rows = (await db.execute(select(DiscoveryResult.task_id, DiscoveryResult.status, func.count())
                             .where(DiscoveryResult.task_id.in_(task_ids)).group_by(DiscoveryResult.task_id, DiscoveryResult.status))).all()
    result = {}
    for task_id, status, n in rows:
        result.setdefault(task_id, {})[status] = n
    return result


@router.get('/tasks')
async def history(status: str | None = Query(None, max_length=30), page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100), db: AsyncSession = DB, user: User = AUTH):
    query = select(DiscoveryTask).where(DiscoveryTask.owner_id == user.id)
    if status:
        query = query.where(DiscoveryTask.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(DiscoveryTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    count_map = await counts(db, [t.id for t in rows]) if rows else {}
    return {'items': [service.task_dto(t, count_map.get(t.id, {})) for t in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/tasks/{task_id}')
async def detail(task_id: UUID, sort: Literal['rank', 'search'] = 'rank', db: AsyncSession = DB, user: User = AUTH):
    task = await service.owned_task(db, task_id, user.id)
    rows = (await db.scalars(select(DiscoveryResult).where(DiscoveryResult.task_id == task.id))).all()
    candidate_ids = {r.candidate_id for r in rows if r.candidate_id}
    candidates = {c.id: c for c in (await db.scalars(select(SourcingCandidate).where(
        SourcingCandidate.id.in_(candidate_ids), SourcingCandidate.owner_id == user.id)))} if candidate_ids else {}
    if sort == 'rank':
        rows = sorted(rows, key=lambda r: (r.rank_position is None, r.rank_position or 0, r.search_position))
    else:
        rows = sorted(rows, key=lambda r: (r.search_keyword, r.search_position))
    collect = None
    if task.collect_task_id:
        job = await db.get(MiaoshouSyncTask, task.collect_task_id)
        collect = miaoshou_task_dto(job) if job and job.owner_id == user.id else None
    count_map = await counts(db, [task.id])
    return {**service.task_dto(task, count_map.get(task.id, {})), 'collect_task': collect,
            'results': [service.result_dto(r, candidates.get(r.candidate_id)) for r in rows]}


@router.post('/tasks/{task_id}/confirm-collect', status_code=202)
async def confirm_collect(task_id: UUID, data: ConfirmCollectInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    task = await service.owned_task(db, task_id, user.id, lock=True)
    await service.confirm_collect(db, task, data.source_item_ids)
    return service.task_dto(task)


@router.post('/tasks/{task_id}/cancel')
async def cancel(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    task = await service.owned_task(db, task_id, user.id, lock=True)
    await service.cancel(db, task)
    return service.task_dto(task)
