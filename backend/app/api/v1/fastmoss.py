import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, engine
from app.core.security import get_current_user
from app.models.user import User
from app.models.fastmoss import FastmossCatalog, FastmossTask
from app.schemas.sourcing import Market
from app.services.fastmoss.browser import Browser, BrowserError, load_catalog
from app.services.fastmoss.locking import browser_lock

router = APIRouter(prefix='/v1/sourcing/fastmoss', tags=['FastMoss'])


class CreateTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID
    target_market: Market = 'MY'
    category_ids: list[str] = Field(min_length=1, max_length=20)
    pages: int = Field(default=3, ge=1, le=10)


def task_dto(task):
    return {k: getattr(task, k) for k in ('id', 'target_market', 'categories', 'pages', 'status', 'progress',
        'category_results', 'report_id', 'row_count', 'truncated', 'error', 'created_at', 'finished_at')}


async def owned(db, task_id, owner_id):
    task = await db.scalar(select(FastmossTask).where(FastmossTask.id == task_id, FastmossTask.owner_id == owner_id))
    if not task:
        raise HTTPException(404, '抓取任务不存在')
    return task


@router.get('/status')
async def status(user: User = Depends(get_current_user)):
    return await asyncio.to_thread(Browser().status)


@router.get('/categories')
async def categories(target_market: Market = 'MY', db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    catalog = await db.scalar(select(FastmossCatalog).where(FastmossCatalog.owner_id == user.id,
                             FastmossCatalog.target_market == target_market))
    return {'items': catalog.categories if catalog else [], 'updated_at': catalog.updated_at if catalog else None}


@router.post('/categories/refresh')
async def refresh_categories(target_market: Market = 'MY', db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    async with browser_lock(engine) as conn:
        if conn is None:
            raise HTTPException(409, '浏览器正在抓取，请完成后刷新分类')
        try:
            items = await asyncio.to_thread(load_catalog, target_market)
        except BrowserError as exc:
            raise HTTPException(422, str(exc)) from None
        await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        catalog = await db.scalar(select(FastmossCatalog).where(FastmossCatalog.owner_id == user.id,
                                 FastmossCatalog.target_market == target_market))
        if catalog is None:
            catalog = FastmossCatalog(owner_id=user.id, target_market=target_market, categories=items)
            db.add(catalog)
        else:
            catalog.categories = items
        catalog.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return {'items': items, 'updated_at': catalog.updated_at}


@router.post('/tasks', status_code=201)
async def create_task(data: CreateTask, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    existing = await db.scalar(select(FastmossTask).where(FastmossTask.owner_id == user.id, FastmossTask.request_key == data.request_key))
    ids = set(data.category_ids)
    if existing:
        if existing.target_market != data.target_market or existing.pages != data.pages or {c['id'] for c in existing.categories} != ids:
            raise HTTPException(409, '相同请求标识不能用于不同抓取条件')
        return task_dto(existing)
    catalog = await db.scalar(select(FastmossCatalog).where(FastmossCatalog.owner_id == user.id,
                             FastmossCatalog.target_market == data.target_market))
    choices = [c for c in catalog.categories if c['id'] in ids] if catalog else []
    if len(choices) != len(ids):
        raise HTTPException(422, '分类不存在或已失效，请刷新分类后重新选择')
    check = await asyncio.to_thread(Browser().status)
    if not check['ready']:
        raise HTTPException(422, check['message'])
    task = FastmossTask(owner_id=user.id, request_key=data.request_key, target_market=data.target_market,
                        categories=choices, pages=data.pages)
    db.add(task)
    await db.flush()
    return task_dto(task)


@router.get('/tasks')
async def tasks(target_market: Market = 'MY', page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(FastmossTask).where(FastmossTask.owner_id == user.id, FastmossTask.target_market == target_market)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = (await db.scalars(query.order_by(FastmossTask.created_at.desc()).offset((page - 1) * 20).limit(20))).all()
    return {'items': [task_dto(t) for t in items], 'total': total, 'page': page, 'page_size': 20}


@router.get('/tasks/{task_id}')
async def task(task_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return task_dto(await owned(db, task_id, user.id))


@router.get('/tasks/{task_id}/csv')
async def download(task_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = await owned(db, task_id, user.id)
    if task.raw_csv is None:
        raise HTTPException(409, '本次任务没有可下载的 CSV')
    return Response(task.raw_csv.encode('utf-8'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="fastmoss-{task.id}.csv"'})
