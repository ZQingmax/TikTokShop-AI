"""Product API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.core.database import get_db
from app.core.security import get_current_user
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.models.product import Product
from app.services import product_sync_service
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter(prefix="/v1/products", tags=["Products"])


def money(value):
    return str(value) if value is not None else None


def dto(p: Product) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description or "",
        "category_id": str(p.category_id) if p.category_id else None,
        "cost_price": money(p.cost_price),
        "cost_currency": p.cost_currency,
        "sale_price": money(p.sale_price),
        "sale_price_max": money(p.sale_price_max),
        "sale_currency": p.sale_currency,
        "cost_source": p.cost_source,
        "sku_count": p.sku_count,
        "status": p.status,
        "miaoshou_status": p.miaoshou_status,
        "score": money(p.score),
        "tiktok_product_id": p.tiktok_product_id or "",
        "miaoshou_detail_id": p.miaoshou_detail_id,
        "common_detail_id": p.common_detail_id,
        "market": p.market,
        "shop_ids": p.shop_ids or [],
        "thumbnail": p.thumbnail,
        "item_num": p.item_num,
        "stock": p.stock,
        "sourcing_candidate_id": str(p.sourcing_candidate_id) if p.sourcing_candidate_id else None,
        "source_url": p.source_url or "",
        "source_product_id": p.source_product_id,
        "synced_at": p.synced_at.isoformat() if p.synced_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


@router.post("/sync")
async def sync_products(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """从妙手 TikTok 采集箱同步商品（只读妙手）。"""
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="只有管理员或运营人员可以同步商品")
    client = MiaoshouClient()
    if not client.configured:
        raise HTTPException(status_code=424, detail="妙手服务端凭证未配置")
    try:
        result = await product_sync_service.sync(db, client)
    except MiaoshouError as error:
        raise HTTPException(status_code=424, detail=error.message) from None
    await db.commit()
    return result


@router.get("/summary")
async def products_summary(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (await db.execute(select(Product.miaoshou_status, func.count()).group_by(Product.miaoshou_status))).all()
    last = await db.scalar(select(func.max(Product.synced_at)))
    return {"counts": {str(k or "local"): v for k, v in rows}, "synced_at": last.isoformat() if last else None}


@router.get("", response_model=PaginatedResponse)
async def list_products(
    pagination: PaginationParams = Depends(),
    keyword: str = Query("", description="Search keyword"),
    status: str | None = Query(None),
    miaoshou_status: str | None = Query(None),
    market: str | None = Query(None, max_length=2),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List products with pagination and filters."""
    query = select(Product)
    if miaoshou_status:
        query = query.where(Product.miaoshou_status == miaoshou_status)
    if market:
        query = query.where(Product.market == market)

    if keyword:
        like = f"%{keyword}%"
        query = query.where(Product.name.ilike(like) | Product.miaoshou_detail_id.ilike(like)
                            | Product.source_product_id.ilike(like) | Product.item_num.ilike(like))
    if status:
        query = query.where(Product.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Product.created_at.desc())
    query = query.offset(pagination.offset).limit(pagination.page_size)
    result = await db.execute(query)
    products = result.scalars().all()

    items = [dto(p) for p in products]
    return PaginatedResponse(
        items=items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new product."""
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return dto(product)


@router.get("/{product_id}")
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return dto(product)


@router.put("/{product_id}")
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update product."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)
    return dto(product)
