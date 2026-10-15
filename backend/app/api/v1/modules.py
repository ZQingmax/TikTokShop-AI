"""Pricing, listing, fulfillment, customer service and finance API stubs."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.finance import FinanceRecord
from app.models.fulfillment import PurchaseOrder, Shipment
from app.models.order import Order
from app.models.user import User
from app.services.fulfillment_service import FulfillmentService
from app.services.listing_service import ListingService
from app.services.pricing_service import PricingService


# --- Schemas ---
class PricingCalculateRequest(BaseModel):
    cost_price_cny: str
    target_market: str
    logistics_cost_cny: str = "0.00"


class MatchCategoryRequest(BaseModel):
    product_name: str
    description: str = ""


# --- Pricing ---
pricing_router = APIRouter(prefix="/v1/pricing", tags=["Pricing"])


@pricing_router.post("/calculate")
async def calculate_pricing(
    request: PricingCalculateRequest,
    current_user: User = Depends(get_current_user),
):
    """Calculate product cost and pricing."""
    result = await PricingService.calculate_cost(
        cost_price_cny=Decimal(request.cost_price_cny),
        target_market=request.target_market,
        logistics_cost_cny=Decimal(request.logistics_cost_cny),
    )
    return result


@pricing_router.get("/suggestions")
async def get_pricing_suggestions(
    product_id: str = None,
    target_market: str = "US",
    current_user: User = Depends(get_current_user),
):
    """Get pricing suggestions."""
    result = await PricingService.get_pricing_suggestions(product_id or "", target_market)
    return result


# --- Listing ---
listing_router = APIRouter(prefix="/v1/listing", tags=["Listing"])


@listing_router.post("/match-category")
async def match_category(
    request: MatchCategoryRequest,
    current_user: User = Depends(get_current_user),
):
    """Match TikTok Shop category."""
    result = await ListingService.match_category(request.product_name, request.description)
    return result


# --- Fulfillment ---
fulfillment_router = APIRouter(prefix="/v1/fulfillment", tags=["Fulfillment"])


def _iso(value):
    return value.isoformat() if value else None


@fulfillment_router.get("/summary")
async def fulfillment_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Counts for the fulfillment page: packages to ship, overdue, shipped; purchase orders by status."""
    now = datetime.now(timezone.utc)
    to_ship = await db.scalar(select(func.count()).select_from(Order).where(Order.app_package_status == "wait_seller_send"))
    overdue = await db.scalar(select(func.count()).select_from(Order).where(
        Order.app_package_status == "wait_seller_send", Order.ship_by_at < now))
    shipped = await db.scalar(select(func.count()).select_from(Order).where(Order.app_package_status == "wait_receiver_confirm"))
    po_rows = (await db.execute(select(PurchaseOrder.status, func.count()).group_by(PurchaseOrder.status))).all()
    return {"to_ship": to_ship or 0, "overdue": overdue or 0, "shipped": shipped or 0,
            "purchase_orders": {str(k): v for k, v in po_rows}}


@fulfillment_router.get("/outbound")
async def list_outbound(
    state: str = "to_ship",
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Packages to ship (wait_seller_send, earliest deadline first) or in transit to buyers."""
    status = {"to_ship": "wait_seller_send", "shipped": "wait_receiver_confirm"}.get(state, "wait_seller_send")
    query = select(Order).options(selectinload(Order.items)).where(Order.app_package_status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = Order.ship_by_at.asc().nulls_last() if state == "to_ship" else Order.shipped_at.desc().nulls_last()
    rows = (await db.scalars(query.order_by(order).offset((page - 1) * page_size).limit(page_size))).all()
    items = [{
        "id": str(o.id), "tiktok_order_id": o.tiktok_order_id or "", "miaoshou_package_id": o.miaoshou_package_id,
        "status_text": o.status_text, "shop_name": o.shop_name, "site": o.site,
        "items": [{"name": i.product_name, "sku": i.sku_code, "quantity": i.quantity, "image_url": i.image_url} for i in o.items],
        "ship_by_at": _iso(o.ship_by_at), "shipped_at": _iso(o.shipped_at), "tracking_number": o.tracking_number or "",
        "carrier": (o.logistics or {}).get("logisticsCompany") or (o.logistics or {}).get("productName") or "",
        "fulfillment_type": o.fulfillment_type,
    } for o in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@fulfillment_router.get("/purchase-orders")
async def list_purchase_orders(
    status: str = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List purchase orders synced from Miaoshou."""
    query = select(PurchaseOrder)
    if status:
        query = query.where(PurchaseOrder.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(func.coalesce(PurchaseOrder.ordered_at, PurchaseOrder.created_at).desc())
    orders = (await db.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
    items = [
        {
            "id": str(po.id),
            "po_sn": po.po_sn or "",
            "alibaba_order_id": po.alibaba_order_id or "",
            "supplier_name": po.supplier_name or "",
            "status": po.status,
            "total_amount": str(po.total_amount),
            "currency": po.currency,
            "items": po.items or [],
            "tracking_number": po.tracking_number or "",
            "remark": po.remark or "",
            "ordered_at": _iso(po.ordered_at),
            "synced_at": _iso(po.synced_at),
            "created_at": _iso(po.created_at) or "",
        }
        for po in orders
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@fulfillment_router.get("/shipments")
async def list_shipments(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inbound parcels of purchase orders (supplier to warehouse)."""
    query = (
        select(Shipment)
        .options(selectinload(Shipment.purchase_order))
        .order_by(Shipment.created_at.desc())
    )
    total = await db.scalar(select(func.count()).select_from(Shipment)) or 0
    shipments = (await db.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
    items = [
        {
            "id": str(s.id),
            "tracking_number": s.tracking_number,
            "status": s.status,
            "carrier": s.carrier or "",
            "origin": s.origin or "",
            "destination": s.destination or "",
            "po_sn": s.purchase_order.po_sn or "" if s.purchase_order else "",
            "alibaba_order_id": s.purchase_order.alibaba_order_id or "" if s.purchase_order else "",
            "created_at": _iso(s.created_at) or "",
        }
        for s in shipments
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# --- Customer Service ---
cs_router = APIRouter(prefix="/v1/customer-service", tags=["CustomerService"])


@cs_router.get("/sessions")
async def list_cs_sessions(
    status: str = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
):
    """List customer service sessions."""
    return {"items": [], "total": 0, "page": page, "page_size": page_size}


# --- Finance ---
finance_router = APIRouter(prefix="/v1/finance", tags=["Finance"])


@finance_router.get("/summary")
async def get_finance_summary(
    period: str = "month",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Financial summary from records derived from synced orders.

    Totals are in CNY and only include records with a known CNY rate; `unconverted` lists the rest per
    currency so nothing is silently dropped or mixed across currencies."""
    rows = (await db.execute(
        select(FinanceRecord.type, FinanceRecord.currency, func.sum(FinanceRecord.amount),
               func.sum(FinanceRecord.cny_amount), func.count(), func.count(FinanceRecord.cny_amount))
        .group_by(FinanceRecord.type, FinanceRecord.currency)
    )).all()
    cny = {kind: Decimal("0") for kind in ("income", "cost", "refund", "fee", "withdrawal")}
    by_currency, unconverted = {}, {}
    for kind, currency, amount, cny_amount, count, converted in rows:
        cny[kind] = cny.get(kind, Decimal("0")) + (cny_amount or Decimal("0"))
        by_currency.setdefault(currency, {})[kind] = str(amount or 0)
        if converted < count:
            unconverted.setdefault(currency, 0)
            unconverted[currency] += count - converted
    order_count = await db.scalar(
        select(func.count(func.distinct(FinanceRecord.order_id))).where(FinanceRecord.order_id.isnot(None))
    ) or 0
    revenue = cny["income"]
    net_profit = revenue - cny["cost"] - cny["fee"] - cny["refund"]
    return {
        "total_revenue": str(revenue),
        "total_cost": str(cny["cost"]),
        "total_refund": str(cny["refund"]),
        "total_fee": str(cny["fee"]),
        "total_withdrawal": str(cny["withdrawal"]),
        "net_profit": str(net_profit),
        "profit_rate": float(net_profit / revenue) if revenue > 0 else 0.0,
        "order_count": order_count,
        "currency": "CNY",
        "by_currency": by_currency,
        "unconverted": unconverted,
    }


@finance_router.get("/transactions")
async def list_transactions(
    type: str = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List financial transactions."""
    query = select(FinanceRecord).order_by(FinanceRecord.created_at.desc())
    count_query = select(func.count()).select_from(FinanceRecord)

    if type:
        query = query.where(FinanceRecord.type == type)
        count_query = count_query.where(FinanceRecord.type == type)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    records = result.scalars().all()

    items = [
        {
            "id": str(r.id),
            "order_id": str(r.order_id) if r.order_id else "",
            "type": r.type,
            "amount": str(r.amount),
            "currency": r.currency,
            "exchange_rate": str(r.exchange_rate) if r.exchange_rate is not None else None,
            "cny_amount": str(r.cny_amount) if r.cny_amount is not None else None,
            "description": r.description or "",
            "site": r.site or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
