"""Order API routes. Orders are Miaoshou packages synced by order_sync_service."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import PaginationParams
from app.clients.miaoshou_client import MiaoshouClient
from app.core.database import async_session_factory, get_db
from app.core.security import get_current_user
from app.models.finance import FinanceRecord
from app.models.order import Order, OrderItem
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.order import OrderStatusUpdate
from app.services import order_sync_service

router = APIRouter(prefix="/v1/orders", tags=["Orders"])


def iso(value):
    return value.isoformat() if value else None


def money(value):
    return str(value) if value is not None else None


def order_dto(o: Order) -> dict:
    return {
        "id": str(o.id),
        "tiktok_order_id": o.tiktok_order_id or "",
        "miaoshou_package_id": o.miaoshou_package_id,
        "status": o.status,
        "app_package_status": o.app_package_status,
        "status_text": o.status_text,
        "platform_status": o.platform_status,
        "total_amount": money(o.total_amount),
        "product_amount": money(o.product_amount),
        "commission_fee": money(o.commission_fee),
        "escrow_amount": money(o.escrow_amount),
        "shipping_fee": money(o.shipping_fee),
        "currency": o.currency,
        "shop_id": o.shop_id,
        "shop_name": o.shop_name,
        "site": o.site,
        "buyer_name": o.buyer_name or "",
        "shipping_address": o.shipping_address or {},
        "tracking_number": o.tracking_number or "",
        "fulfillment_type": o.fulfillment_type,
        "remark": o.remark or "",
        "ordered_at": iso(o.ordered_at),
        "ship_by_at": iso(o.ship_by_at),
        "shipped_at": iso(o.shipped_at),
        "synced_at": iso(o.synced_at),
        "created_at": iso(o.created_at) or "",
        "updated_at": iso(o.updated_at) or "",
    }


@router.post("/sync")
async def sync_orders(current_user: User = Depends(get_current_user)):
    """从妙手同步订单（包裹）与采购单（只读妙手）。"""
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="只有管理员或运营人员可以同步订单")
    client = MiaoshouClient()
    if not client.configured:
        raise HTTPException(status_code=424, detail="妙手服务端凭证未配置")
    return await order_sync_service.run(async_session_factory, client)


@router.get("/sync-state")
async def sync_state(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await order_sync_service.states(db)


@router.get("/summary")
async def orders_summary(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (await db.execute(select(Order.app_package_status, func.count()).group_by(Order.app_package_status))).all()
    return {"counts": {str(k or "local"): v for k, v in rows}}


@router.get("", response_model=PaginatedResponse)
async def list_orders(
    pagination: PaginationParams = Depends(),
    status: str | None = Query(None),
    app_package_status: str | None = Query(None),
    site: str | None = Query(None, max_length=8),
    search: str = Query("", description="Order ID, package ID or product name"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List orders with pagination and filters."""
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    if app_package_status:
        query = query.where(Order.app_package_status == app_package_status)
    if site:
        query = query.where(Order.site == site)
    if search:
        like = f"%{search}%"
        matching_items = select(OrderItem.order_id).where(OrderItem.product_name.ilike(like))
        query = query.where(or_(Order.tiktok_order_id.ilike(like), Order.miaoshou_package_id.ilike(like),
                                Order.tracking_number.ilike(like), Order.id.in_(matching_items)))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(func.coalesce(Order.ordered_at, Order.created_at).desc())
    query = query.options(selectinload(Order.items)).offset(pagination.offset).limit(pagination.page_size)
    orders = (await db.execute(query)).scalars().all()
    items = []
    for o in orders:
        items.append({**order_dto(o), "item_count": sum(i.quantity for i in o.items),
                      "first_item": {"name": o.items[0].product_name, "image_url": o.items[0].image_url} if o.items else None})
    return PaginatedResponse(items=items, total=total, page=pagination.page, page_size=pagination.page_size)


@router.get("/{order_id}")
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get order details with items and derived finance records."""
    order = await db.scalar(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    finance = (await db.scalars(select(FinanceRecord).where(FinanceRecord.order_id == order.id))).all()
    return {
        **order_dto(order),
        "logistics": order.logistics or {},
        "items": [{"id": str(i.id), "product_id": str(i.product_id) if i.product_id else None, "product_name": i.product_name,
                   "sku_code": i.sku_code, "quantity": i.quantity, "unit_price": money(i.unit_price),
                   "subtotal": money(i.subtotal), "image_url": i.image_url} for i in order.items],
        "finance": [{"type": f.type, "amount": money(f.amount), "currency": f.currency, "cny_amount": money(f.cny_amount),
                     "description": f.description} for f in finance],
    }


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: UUID,
    data: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the status of a local order. Miaoshou-synced orders follow Miaoshou."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.miaoshou_package_id:
        raise HTTPException(status_code=409, detail="该订单来自妙手，状态以妙手为准，下次同步会覆盖本地修改")

    order.status = data.status
    if data.remark:
        order.remark = data.remark

    await db.commit()
    return {"message": "Order status updated"}
