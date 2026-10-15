"""Dashboard API endpoints. Everything is computed from synced data; empty data stays empty.

Days follow Beijing time (the operators' and Miaoshou's clock). Sales are CNY from finance records
derived from orders; amounts without a known CNY rate are reported separately, never mixed in."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.finance import FinanceRecord
from app.models.listing import ListingTask
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.services import order_sync_service

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])
CHINA = ZoneInfo("Asia/Shanghai")

STATUS_NAME_MAP = {
    "pending": "待付款 / 待审核",
    "confirmed": "待发货",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
    "refunding": "售后中",
    "refunded": "已退款",
}


def day_range(day):
    start = datetime.combine(day, time.min, tzinfo=CHINA)
    return start, start + timedelta(days=1)


def change(today, yesterday):
    """Percent change vs yesterday; None when there is nothing to compare with."""
    if not yesterday:
        return None
    return round(float((Decimal(today) - Decimal(yesterday)) / Decimal(yesterday) * 100), 1)


async def day_orders(db, day):
    start, end = day_range(day)
    ordered = func.coalesce(Order.ordered_at, Order.created_at)
    return await db.scalar(select(func.count()).select_from(Order).where(ordered >= start, ordered < end)) or 0


async def day_sales(db, day):
    start, end = day_range(day)
    query = select(func.sum(FinanceRecord.cny_amount)).where(
        FinanceRecord.type == "income", FinanceRecord.created_at >= start, FinanceRecord.created_at < end)
    return await db.scalar(query) or Decimal("0")


@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard statistics cards."""
    today = datetime.now(CHINA).date()
    yesterday = today - timedelta(days=1)
    today_orders, yesterday_orders = await day_orders(db, today), await day_orders(db, yesterday)
    today_sales, yesterday_sales = await day_sales(db, today), await day_sales(db, yesterday)
    to_ship = await db.scalar(select(func.count()).select_from(Order).where(Order.app_package_status == "wait_seller_send")) or 0
    overdue = await db.scalar(select(func.count()).select_from(Order).where(
        Order.app_package_status == "wait_seller_send", Order.ship_by_at < datetime.now(CHINA))) or 0
    product_rows = (await db.execute(select(Product.miaoshou_status, func.count()).group_by(Product.miaoshou_status))).all()
    products = {str(k or "local"): v for k, v in product_rows}
    unconverted = await db.scalar(select(func.count()).select_from(FinanceRecord).where(
        FinanceRecord.type == "income", FinanceRecord.cny_amount.is_(None))) or 0
    listing_active = await db.scalar(select(func.count()).select_from(ListingTask).where(
        ListingTask.status.in_(["queued", "running", "waiting"]))) or 0
    return {
        "today_orders": today_orders,
        "today_sales": str(today_sales),
        "sales_currency": "CNY",
        "pending_orders": to_ship,
        "overdue_orders": overdue,
        "total_products": sum(products.values()),
        "published_products": products.get("published", 0),
        "unpublished_products": products.get("notPublished", 0),
        "listing_tasks_active": listing_active,
        "unconverted_income_records": unconverted,
        "order_trend": change(today_orders, yesterday_orders),
        "sales_trend": change(today_sales, yesterday_sales),
        "sync": await order_sync_service.states(db),
    }


@router.get("/recent-orders")
async def get_recent_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent 10 orders."""
    query = select(Order).order_by(desc(func.coalesce(Order.ordered_at, Order.created_at))).limit(10)
    orders = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(o.id),
            "tiktok_order_id": o.tiktok_order_id or "",
            "status": o.status,
            "status_text": o.status_text,
            "total_amount": str(o.total_amount),
            "currency": o.currency,
            "shop_name": o.shop_name or "",
            "site": o.site or "",
            "created_at": (o.ordered_at or o.created_at).isoformat() if (o.ordered_at or o.created_at) else "",
        }
        for o in orders
    ]


@router.get("/sales-trend")
async def get_sales_trend(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Last 7 days: CNY sales and order counts per Beijing day."""
    today = datetime.now(CHINA).date()
    dates, sales, orders = [], [], []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        dates.append(day.strftime("%m-%d"))
        sales.append(float(await day_sales(db, day)))
        orders.append(await day_orders(db, day))
    return {"dates": dates, "sales": sales, "orders": orders, "currency": "CNY"}


@router.get("/order-status-distribution")
async def get_order_status_distribution(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Order count by status."""
    rows = (await db.execute(select(Order.status, func.count()).group_by(Order.status).order_by(func.count().desc()))).all()
    return {"data": [{"name": STATUS_NAME_MAP.get(status, status), "value": count} for status, count in rows]}
