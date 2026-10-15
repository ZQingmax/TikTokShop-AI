"""1688 货源中心 API（只读，经 Alibaba1688Provider 调用用户本机 1688 CLI）。

路由层只做参数校验与错误转换；不直接调用 subprocess，不接受任意 CLI 参数。
"""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.sourcing import Market
from app.services.alibaba1688.candidates import save_candidate
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import get_provider

router = APIRouter(prefix='/v1/sourcing/1688', tags=['Sourcing-1688'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)


def fail(e: Alibaba1688Error):
    raise HTTPException(e.http_status, e.to_dict()) from None


def public(item: dict) -> dict:
    """列表接口不返回 raw，减少响应体；详情接口保留 raw 以便追溯。"""
    return {k: v for k, v in item.items() if k != 'raw'}


@router.get('/status')
async def status(refresh: bool = False, user: User = AUTH):
    return await get_provider().status(refresh=refresh)


@router.get('/search')
async def search(keyword: str = Query(min_length=1, max_length=50),
                 limit: int = Query(20, ge=1, le=40, alias='max'),
                 sort: Literal['relevance', 'best-selling', 'price-asc', 'price-desc'] = 'relevance',
                 price_min: Decimal | None = Query(None, ge=0, le=1_000_000), price_max: Decimal | None = Query(None, ge=0, le=1_000_000),
                 exclude_ads: bool = False, factory_only: bool = False, user: User = AUTH):
    provider = get_provider()
    try:
        result = await provider.search(keyword, min(limit, provider.settings.max_results), sort, price_min, price_max,
                                       exclude_ads, factory_only)
    except Alibaba1688Error as e:
        fail(e)
    return {**result, 'items': [public(x) for x in result['items']]}


@router.post('/image-search')
async def image_search(image: UploadFile = File(...), limit: int = Form(20, ge=1, le=40, alias='max'), user: User = AUTH):
    provider = get_provider()
    max_bytes = provider.settings.image_max_bytes
    content = await image.read(max_bytes + 1)  # 只读上限 + 1 字节，超限直接拒绝
    if len(content) > max_bytes:
        fail(Alibaba1688Error('bad_input', f'图片不能超过 {max_bytes // 1024 // 1024} MB'))
    try:
        result = await provider.image_search(content, min(limit, provider.settings.max_results))
    except Alibaba1688Error as e:
        fail(e)
    return {**result, 'items': [public(x) for x in result['items']]}


@router.get('/products/{offer_id}')
async def product(offer_id: str, refresh: bool = False, user: User = AUTH):
    try:
        return await get_provider().offer(offer_id, refresh=refresh)
    except Alibaba1688Error as e:
        fail(e)


@router.get('/suppliers/search')
async def supplier_search(keyword: str = Query(min_length=1, max_length=50), limit: int = Query(20, ge=1, le=40, alias='max'),
                          factory_only: bool = False, province: str | None = Query(None, max_length=20), user: User = AUTH):
    provider = get_provider()
    try:
        result = await provider.supplier_search(keyword, min(limit, provider.settings.max_results), factory_only, province)
    except Alibaba1688Error as e:
        fail(e)
    return {**result, 'items': [public(x) for x in result['items']]}


@router.get('/suppliers/{supplier_id}')
async def supplier(supplier_id: str, user: User = AUTH):
    """supplier_id：商品 offerId，或 b2b- 开头的 memberId。"""
    try:
        return await get_provider().supplier_inspect(supplier_id)
    except Alibaba1688Error as e:
        fail(e)


class SaveCandidate(BaseModel):
    offer_id: str = Field(pattern=r'^\d{6,20}$')
    target_market: Market = 'MY'
    use_detail: bool = True


@router.post('/candidates', status_code=201)
async def add_candidate(data: SaveCandidate, db: AsyncSession = DB, user: User = AUTH):
    try:
        return await save_candidate(db, get_provider(), user.id, data.offer_id, data.target_market, data.use_detail)
    except Alibaba1688Error as e:
        fail(e)
