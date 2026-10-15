"""商品上架：TK 采集箱商品预检与（批量）发布到店铺。"""
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.miaoshou import raise_source_error
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.listing import ListingTask
from app.models.user import User
from app.services.listing_publish_service import PENDING, create_task, owned_task, task_dto
from app.services.miaoshou_mapping import public_raw

router = APIRouter(prefix='/v1/listing', tags=['Listing'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)
ID = r'^[1-9]\d{0,18}$'


class ListingItem(BaseModel):
    detail_id: str = Field(pattern=ID)
    shop_id: str = Field(pattern=ID)


class ListingInput(BaseModel):
    request_key: uuid.UUID
    kind: Literal['check', 'publish']
    market: Literal['TH', 'VN', 'MY', 'SG', 'PH', 'ID', 'US', 'GB'] = 'MY'
    items: list[ListingItem] = Field(min_length=1, max_length=200)


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以预检或发布商品')


@router.post('/tasks', status_code=202)
async def create(data: ListingInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    if not MiaoshouClient().configured:
        raise HTTPException(424, '妙手服务端凭证未配置')
    task, reused = await create_task(db, user.id, data)
    return {**task_dto(task), 'reused': reused}


@router.get('/tasks')
async def tasks(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50), db: AsyncSession = DB, user: User = AUTH):
    total = await db.scalar(select(func.count()).select_from(ListingTask).where(ListingTask.owner_id == user.id))
    rows = (await db.scalars(select(ListingTask).where(ListingTask.owner_id == user.id).order_by(ListingTask.created_at.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [task_dto(x) for x in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/tasks/{task_id}')
async def task(task_id: uuid.UUID, db: AsyncSession = DB, user: User = AUTH):
    return task_dto(await owned_task(db, task_id, user.id))


@router.post('/tasks/{task_id}/reconcile', status_code=202)
async def reconcile(task_id: uuid.UUID, db: AsyncSession = DB, user: User = AUTH):
    """Re-query results of items whose publish outcome is unknown. Never resubmits."""
    operator(user)
    job = await owned_task(db, task_id, user.id, lock=True)
    if job.status != 'uncertain' or not any(x['state'] in PENDING for x in job.items):
        raise HTTPException(409, '只有结果未确认的发布任务需要重新查询')
    job.status, job.stage, job.poll_count, job.next_poll_at = 'waiting', 'waiting_result', 0, datetime.now(timezone.utc)
    job.finished_at = job.error_code = job.error_message = None
    return task_dto(job)


@router.get('/records')
async def records(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = AUTH):
    """妙手发布记录列表（#26）原样只读展示。"""
    try:
        result = await MiaoshouClient().get_publish_records(page, page_size)
    except MiaoshouError as error:
        raise_source_error(error)
    return {'items': public_raw(result.data.get('moveCollectDetailList') or []), 'total': result.data.get('total'),
            'page': page, 'page_size': page_size}
