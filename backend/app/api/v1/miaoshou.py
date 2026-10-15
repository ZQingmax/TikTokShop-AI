"""Miaoshou sourcing endpoints. Publishing/claiming/purchasing are excluded."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sourcing import MiaoshouSyncTask
from app.schemas.miaoshou import CollectInput, SyncInput
from app.services.miaoshou_mapping import public_raw, UNITS, PRICE_MEANINGS
from app.services.miaoshou_tasks import create_task, owned_task, task_dto
from app.services.sourcing_providers import AnalysisError
from app.services.sourcing_sources import MiaoshouSourceAdapter

router = APIRouter(prefix='/v1/sourcing/miaoshou', tags=['Miaoshou Sourcing'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)


def raise_source_error(error):
    raise HTTPException(424, error.message, headers={'X-Miaoshou-Error-Code': error.code}) from None


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以提交货源采集与同步')


@router.get('/status')
async def status(user: User = AUTH):
    return {'configured': MiaoshouClient().configured, 'connected': None, 'reason': '配置状态与真实鉴权不同，请验证连接',
            'operations': ['shops', 'collect', 'common_list', 'common_detail'], 'max_collect_links': 50}


class ShopQuery(BaseModel):
    platform: Literal['tiktok', 'tiktokGlobal', 'pddkj', 'pddkjChoice', 'shopee', 'shopeeGlobal', 'mercadolibre', 'ozon'] = 'tiktok'
    site: str = Field(default='MY', min_length=1, max_length=32)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


@router.post('/connection-check')
async def connection_check(data: ShopQuery, user: User = AUTH):
    client = MiaoshouClient()
    try:
        result = await client.get_shops(data.platform, data.site, data.page, data.page_size)
        return {'configured': client.configured, 'connected': True, 'verified_at': datetime.now(timezone.utc),
                'platform': data.platform, 'site': data.site, 'shop_count': len(result.data['shopList']),
                'shops': public_raw(result.data['shopList']), 'result': result.envelope['result'], 'code': result.envelope['code']}
    except MiaoshouError as error:
        return {'configured': client.configured, 'connected': False, 'error_code': error.code,
                'error_category': error.category, 'reason': error.message}


@router.get('/shops')
async def shops(platform: str = 'tiktok', site: str = Query('MY', max_length=32), page: int = Query(1, ge=1),
                page_size: int = Query(20, ge=1, le=100), user: User = AUTH):
    try:
        result = await MiaoshouClient().get_shops(platform, site, page, page_size)
        return {'items': public_raw(result.data['shopList']), 'page': page, 'page_size': page_size}
    except MiaoshouError as error:
        raise_source_error(error)


@router.get('/common-products/{common_detail_id}')
async def detail(common_detail_id: str, user: User = AUTH):
    try:
        result = await MiaoshouClient().get_common_detail(common_detail_id)
        return {'common_detail_id': common_detail_id, 'data': public_raw(result.data), 'units': UNITS, 'price_meanings': PRICE_MEANINGS}
    except MiaoshouError as error:
        raise_source_error(error)


@router.post('/collect', status_code=202)
async def collect(data: CollectInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    if not MiaoshouClient().configured:
        raise HTTPException(424, '妙手服务端凭证未配置')
    job, reused = await create_task(db, user.id, data, 'collect')
    return {**task_dto(job), 'reused': reused}


@router.post('/sync', status_code=202)
async def sync(data: SyncInput, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    job, reused = await create_task(db, user.id, data, 'sync')
    return {**task_dto(job), 'reused': reused}


@router.get('/tasks')
async def tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: AsyncSession = DB, user: User = AUTH):
    query = select(MiaoshouSyncTask).where(MiaoshouSyncTask.owner_id == user.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(MiaoshouSyncTask.status.in_(['queued', 'running', 'waiting']).desc(), MiaoshouSyncTask.created_at.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [task_dto(x) for x in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/tasks/{task_id}')
async def task(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    return task_dto(await owned_task(db, task_id, user.id))


@router.post('/tasks/{task_id}/reconcile', status_code=202)
async def reconcile(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    operator(user)
    job = await owned_task(db, task_id, user.id, lock=True)
    if job.status not in ('failed', 'uncertain'):
        raise HTTPException(409, '只有失败或不确定任务需要重新查询平台状态')
    job.status, job.stage, job.poll_count, job.next_poll_at = 'waiting', 'reconcile', 0, datetime.now(timezone.utc)
    job.finished_at = None
    return task_dto(job)


@router.get('/tiktok-products')
async def tiktok_products(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                          source_id: str | None = Query(None, max_length=255),
                          status: Literal['notPublished', 'timingPublish', 'published'] | None = None, user: User = AUTH):
    """TikTok 采集箱（#15）只读列表。平台响应未提供总数，按本页是否满额判断是否有下一页。"""
    try:
        result = await MiaoshouClient().get_tiktok_list(page, page_size, source_id, status)
    except MiaoshouError as error:
        raise_source_error(error)
    rows = result.data['detailList']
    items = [{'id': str(x.get('collectBoxDetailId')), 'title': x.get('title'), 'thumbnail': x.get('thumbnail'),
              'price': x.get('price'), 'stock': x.get('stock'), 'item_num': x.get('itemNum'),
              'common_detail_id': x.get('commonCollectBoxDetailId'), 'group': x.get('collectBoxGroupName'),
              'shop_ids': [s.get('shopId') for s in x.get('collectBoxDetailShopList') or []],
              'created_at': x.get('gmtCreate'), 'remark': x.get('remark')} for x in rows]
    return {'items': items, 'page': page, 'page_size': page_size, 'has_more': len(rows) >= page_size,
            'total': result.data.get('total')}


@router.get('/tiktok-products/{detail_id}')
async def tiktok_product(detail_id: str = Path(pattern=r'^[1-9]\d{0,18}$'),
                         shop_id: str = Query(pattern=r'^[1-9]\d{0,18}$'), user: User = AUTH):
    """TikTok 采集箱店铺模式详情（#16）只读查看；不保存、不发布。"""
    try:
        result = await MiaoshouClient().get_shop_detail(detail_id, shop_id)
    except MiaoshouError as error:
        raise_source_error(error)
    return {'detail_id': detail_id, 'shop_id': shop_id, 'data': public_raw(result.data['shopCollectItemInfo'])}
