"""订单、履约与财务的数据来源：妙手（只读）。

- 订单 = 妙手包裹（#150，platform=tiktok）。一个 TikTok 订单可能拆成多个包裹，以包裹 ID 为键。
  妙手以 result=fail +「没有符合条件的数据」表示空结果，由客户端转成空列表。
- 订单行替换为包裹当前的商品；能按 TikTok 商品 ID 或货号对上本地商品时建立关联。
- 财务记录由包裹金额派生：income = 订单金额，fee = 平台佣金，cost = 关联商品成本价 × 数量（仅成本为 CNY 时）。
  已取消 / 已退款的包裹不计收入，删除其派生记录。CNY 金额只用已配置的汇率换算，没有汇率时留空。
- 采购单 = 妙手采购单（#161）；其运单包裹写入 shipments。
- 时间字段按妙手（北京时间）解析。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload
from app.clients.miaoshou_client import MiaoshouError
from app.models.finance import ExchangeRate, FinanceRecord
from app.models.fulfillment import PurchaseOrder, Shipment
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.sync_state import MiaoshouSyncState
from app.services.miaoshou_mapping import public_raw

CHINA = ZoneInfo('Asia/Shanghai')
MAX_PAGES = 200
PAGE_SIZE = 50
STATUS = {'unpaid': 'pending', 'wait_confirmed': 'pending', 'wait_seller_send': 'confirmed',
          'wait_receiver_confirm': 'shipped', 'finished': 'completed', 'cancelled': 'cancelled',
          'returned': 'refunded', 'refunding': 'refunding'}
NO_INCOME = ('cancelled', 'returned')


def decimal(value):
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except InvalidOperation:
        return None


def moment(value):
    if not value or not isinstance(value, str):
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value[:19], fmt).replace(tzinfo=CHINA)
        except ValueError:
            continue
    return None


async def state(db, kind):
    row = await db.scalar(select(MiaoshouSyncState).where(MiaoshouSyncState.kind == kind).with_for_update())
    if not row:
        row = MiaoshouSyncState(kind=kind, status='never', counts={})
        db.add(row)
        await db.flush()
    return row


async def cny_rates(db):
    # Oldest first so the most recently updated row wins if a currency has several.
    rows = (await db.scalars(select(ExchangeRate).where(ExchangeRate.base_currency == 'CNY')
                             .order_by(ExchangeRate.updated_at))).all()
    return {r.target_currency: r.rate for r in rows if r.rate}


async def recompute_cny(db, currency, rate, only_missing=True):
    """Re-derive cny_amount for finance records in `currency`; by default only those still without a rate."""
    query = select(FinanceRecord).where(FinanceRecord.currency == currency)
    if only_missing:
        query = query.where(FinanceRecord.cny_amount.is_(None))
    records = (await db.scalars(query)).all()
    for record in records:
        record.exchange_rate, record.cny_amount = to_cny(record.amount, currency, {currency: rate})
    return len(records)


async def fill_missing_cny(db, rates):
    """Convert records left without CNY because their rate was entered after (or while) they were synced."""
    currencies = (await db.scalars(select(FinanceRecord.currency).distinct()
                                   .where(FinanceRecord.cny_amount.is_(None)))).all()
    return sum([await recompute_cny(db, c, rates[c]) for c in currencies if c in rates])


def to_cny(amount, currency, rates):
    if amount is None:
        return None, None
    if currency == 'CNY':
        return Decimal('1'), amount
    rate = rates.get(currency)
    return (rate, (amount / rate).quantize(Decimal('0.01'))) if rate else (None, None)


async def upsert_finance(db, order, kind, amount, currency, rates, description):
    record = await db.scalar(select(FinanceRecord).where(FinanceRecord.miaoshou_package_id == order.miaoshou_package_id,
                                                         FinanceRecord.type == kind))
    if amount is None:
        if record:
            await db.delete(record)
        return
    if not record:
        record = FinanceRecord(miaoshou_package_id=order.miaoshou_package_id, type=kind)
        db.add(record)
    rate, cny = to_cny(amount, currency, rates)
    record.order_id, record.amount, record.currency = order.id, amount, currency
    record.exchange_rate, record.cny_amount = rate, cny
    record.description, record.site = description, order.site
    # Keep finance dated by the order, not by when it was synced.
    if order.ordered_at:
        record.created_at = order.ordered_at


async def apply_package(db, package, products, rates, now):
    info = package.get('orderInfo') or {}
    package_id = str(package.get('opOrderPackageId') or '')
    if not package_id:
        return None
    order = await db.scalar(select(Order).options(selectinload(Order.items)).where(Order.miaoshou_package_id == package_id))
    created = order is None
    if created:
        order = Order(miaoshou_package_id=package_id, items=[])
        db.add(order)
    app_status = package.get('appPackageStatus') or info.get('appOrderStatus')
    logistics = package.get('logisticsAgentProductInfo') or {}
    order.tiktok_order_id = info.get('platformOrderSn')
    order.app_package_status, order.status = app_status, STATUS.get(app_status, 'pending')
    order.status_text = package.get('appPackageStatusText') or info.get('appOrderStatusText')
    order.platform_status = package.get('platformPackageStatus') or info.get('platformOrderStatus')
    order.shop_id = str(package.get('shopId') or info.get('shopId') or '') or None
    order.shop_name = package.get('shopNick') or package.get('shopName')
    order.site = package.get('site') or info.get('site')
    order.currency = info.get('currency') or order.currency or 'USD'
    order.total_amount = decimal(info.get('orderAmount')) or decimal(info.get('payAmount')) or Decimal('0')
    order.product_amount = decimal(info.get('productAmount'))
    order.commission_fee = decimal(info.get('commissionFee'))
    order.escrow_amount = decimal(info.get('escrowAmount'))
    order.shipping_fee = decimal(info.get('actualShippingCost')) or decimal(info.get('estimatedShippingFee'))
    order.ordered_at = moment(info.get('gmtPay')) or moment(info.get('gmtOrderStart'))
    order.paid_at, order.ship_by_at = moment(info.get('gmtPay')), moment(info.get('gmtLastDelivery'))
    order.shipped_at = moment(info.get('gmtDelivery'))
    order.fulfillment_type = package.get('fulfillmentType')
    order.tracking_number = package.get('logisticsNo') or logistics.get('logisticsNo')
    order.logistics = public_raw(logistics) or None
    # Only region-level consignee fields are returned; no buyer name or phone is stored.
    order.shipping_address = public_raw(package.get('consigneeInfo') or {}) or None
    order.remark = info.get('buyerMessage') or info.get('sellerNote')
    order.raw, order.synced_at = public_raw(package), now
    order.items.clear()
    cost = Decimal('0')
    cost_known = True
    for item in package.get('items') or []:
        quantity = int(item.get('quantity') or 0) or 1
        price = decimal(item.get('discountedPrice')) or decimal(item.get('originalPrice')) or Decimal('0')
        product = products.get(('tiktok', str(item.get('platformItemId')))) or products.get(('item_num', str(item.get('platformItemNum'))))
        order.items.append(OrderItem(product_id=product.id if product else None, product_name=(item.get('title') or '未知商品')[:500],
                                     sku_code=(item.get('platformOuterSkuId') or item.get('skuSubName') or None),
                                     platform_sku_id=item.get('platformSkuId'), quantity=quantity, unit_price=price,
                                     subtotal=price * quantity, image_url=item.get('picUrl')))
        if product and product.cost_price is not None and product.cost_currency == 'CNY':
            cost += product.cost_price * quantity
        else:
            cost_known = False
    await db.flush()
    if app_status in NO_INCOME:
        await db.execute(delete(FinanceRecord).where(FinanceRecord.miaoshou_package_id == package_id))
    else:
        label = f'订单 {order.tiktok_order_id or package_id}'
        await upsert_finance(db, order, 'income', order.total_amount or None, order.currency, rates, f'{label} 订单金额')
        await upsert_finance(db, order, 'fee', order.commission_fee, order.currency, rates, f'{label} 平台佣金')
        await upsert_finance(db, order, 'cost', cost if cost_known and order.items else None, 'CNY', rates, f'{label} 货源成本')
    return created


async def sync_orders(db, client):
    record = await state(db, 'orders')
    now = datetime.now(timezone.utc)
    # After the first full pass, only re-read packages modified since the last success (with a day of overlap).
    since = (record.succeeded_at - timedelta(days=1)).astimezone(CHINA).strftime('%Y-%m-%d %H:%M:%S') if record.succeeded_at else None
    products = {}
    for p in (await db.scalars(select(Product).where(or_(Product.tiktok_product_id.is_not(None), Product.item_num.is_not(None))))).all():
        if p.tiktok_product_id:
            products[('tiktok', p.tiktok_product_id)] = p
        if p.item_num:
            products[('item_num', p.item_num)] = p
    rates = await cny_rates(db)
    counts = {'created': 0, 'updated': 0, 'total': 0}
    for page in range(1, MAX_PAGES + 1):
        packages = await client.get_packages(page, PAGE_SIZE, modified_from=since)
        for package in packages:
            created = await apply_package(db, package, products, rates, now)
            if created is not None:
                counts['created' if created else 'updated'] += 1
                counts['total'] += 1
        if len(packages) < PAGE_SIZE:
            break
    await fill_missing_cny(db, await cny_rates(db))
    return counts


async def sync_purchase_orders(db, client):
    now = datetime.now(timezone.utc)
    counts = {'created': 0, 'updated': 0, 'total': 0}
    for page in range(1, MAX_PAGES + 1):
        rows = await client.get_purchase_orders(page, PAGE_SIZE)
        for row in rows:
            po_id = str(row.get('goodsPurchaseOrderId') or '')
            if not po_id:
                continue
            po = await db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.shipments)).where(PurchaseOrder.miaoshou_po_id == po_id))
            counts['created' if po is None else 'updated'] += 1
            counts['total'] += 1
            if po is None:
                po = PurchaseOrder(miaoshou_po_id=po_id, shipments=[])
                db.add(po)
            supplier = row.get('goodsPurchaseOrderSupplier') or {}
            po.po_sn = row.get('goodsPurchaseOrderInternalSn')
            po.alibaba_order_id = row.get('goodsPurchaseOrderSn') or None
            po.status = row.get('status') or 'unknown'
            po.total_amount = decimal(row.get('goodsPurchaseOrderAmount')) or decimal(row.get('goodsPurchaseTotalPrice')) or Decimal('0')
            po.currency = 'CNY'
            po.supplier_name = supplier.get('shopName')
            po.items = [{'name': s.get('goodsName'), 'spec': s.get('goodsSkuSubName'), 'sku': s.get('goodsSkuOuterId'),
                         'image': s.get('logoUrl'), 'quantity': s.get('purchaseNum'), 'received': s.get('receiveNum'),
                         'price': s.get('purchasePrice')} for s in row.get('goodsPurchaseOrderSkuList') or []]
            po.ordered_at, po.remark = moment(row.get('gmtCreate')), row.get('accountNote')
            po.raw, po.synced_at = public_raw(row), now
            await db.flush()
            warehouse = (row.get('warehouse') or {}).get('warehouseName')
            existing = {s.miaoshou_package_id: s for s in po.shipments}
            for shipping in row.get('shippingList') or []:
                for parcel in shipping.get('packageList') or []:
                    parcel_id = str(parcel.get('goodsPurchaseOrderShippingPackageId') or '')
                    if not parcel_id or not parcel.get('waybillCode'):
                        continue
                    shipment = existing.get(parcel_id)
                    if not shipment:
                        shipment = Shipment(miaoshou_package_id=parcel_id, purchase_order_id=po.id)
                        po.shipments.append(shipment)
                        existing[parcel_id] = shipment
                    shipment.carrier, shipment.tracking_number = parcel.get('logisticsName'), parcel['waybillCode']
                    shipment.status = 'delivered' if row.get('status') in ('finished', 'received') else 'in_transit'
                    shipment.origin, shipment.destination = supplier.get('shopName'), warehouse
            po.tracking_number = next((s.tracking_number for s in po.shipments if s.tracking_number), po.tracking_number)
        if len(rows) < PAGE_SIZE:
            break
    return counts


async def run(sessions, client, kinds=('orders', 'purchase_orders')):
    """Runs each sync in its own transaction and records the outcome. Returns {kind: state dict}."""
    jobs = {'orders': sync_orders, 'purchase_orders': sync_purchase_orders}
    result = {}
    for kind in kinds:
        async with sessions() as db, db.begin():
            record = await state(db, kind)
            record.started_at, record.status = datetime.now(timezone.utc), 'running'
        try:
            async with sessions() as db, db.begin():
                counts = await jobs[kind](db, client)
            outcome = {'status': 'succeeded', 'counts': counts, 'error': None}
        except MiaoshouError as error:
            outcome = {'status': 'failed', 'counts': {}, 'error': error.message}
        async with sessions() as db, db.begin():
            record = await state(db, kind)
            record.finished_at, record.status, record.error = datetime.now(timezone.utc), outcome['status'], outcome['error']
            if outcome['status'] == 'succeeded':
                record.succeeded_at, record.counts = record.started_at, outcome['counts']
            result[kind] = state_dto(record)
    return result


def state_dto(record):
    if not record:
        return {'status': 'never', 'succeeded_at': None, 'finished_at': None, 'counts': {}, 'error': None}
    iso = lambda v: v.isoformat() if v else None
    return {'status': record.status, 'succeeded_at': iso(record.succeeded_at), 'finished_at': iso(record.finished_at),
            'counts': record.counts or {}, 'error': record.error}


async def states(db):
    rows = {r.kind: r for r in (await db.scalars(select(MiaoshouSyncState))).all()}
    return {kind: state_dto(rows.get(kind)) for kind in ('orders', 'purchase_orders')}
