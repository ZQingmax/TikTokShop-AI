"""Orders, purchase orders, finance and dashboard from Miaoshou. Upstream values are labelled fixtures."""
import copy
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.clients.miaoshou_client import MiaoshouError
from app.models.finance import ExchangeRate, FinanceRecord
from app.models.product import Product
from app.services import order_sync_service
from tests.conftest import TestSessionLocal

PACKAGE = {
    'opOrderPackageId': '9001', 'shopId': 19282337, 'shopNick': 'UNIT_ONLY shop', 'site': 'MY',
    'appPackageStatus': 'wait_seller_send', 'appPackageStatusText': '待发货', 'logisticsNo': None,
    'fulfillmentType': 'sellerFulfillment', 'consigneeInfo': {'country': 'MY', 'state': 'Selangor', 'city': 'Shah Alam'},
    'orderInfo': {'platformOrderSn': 'TT-UNIT-1', 'currency': 'MYR', 'orderAmount': '20.00', 'productAmount': '20.00',
                  'commissionFee': '1.20', 'gmtPay': '2026-10-15 10:00:00', 'gmtLastDelivery': '2026-10-01 10:00:00'},
    'items': [{'title': 'UNIT_ONLY Set Sticker', 'platformItemNum': 'B-UNIT', 'platformOuterSkuId': 'SKU-1',
               'quantity': 2, 'discountedPrice': '10.00', 'picUrl': 'https://example.com/i.jpg'}],
}
PURCHASE = {'goodsPurchaseOrderId': 501, 'goodsPurchaseOrderInternalSn': 'PO-UNIT-1', 'goodsPurchaseOrderSn': '1688-UNIT-1',
            'status': 'waitReceive', 'goodsPurchaseOrderAmount': '11.20', 'gmtCreate': '2026-10-15 11:00:00',
            'goodsPurchaseOrderSupplier': {'shopName': 'UNIT_ONLY supplier'}, 'warehouse': {'warehouseName': 'UNIT_ONLY 仓'},
            'goodsPurchaseOrderSkuList': [{'goodsName': 'UNIT_ONLY sticker', 'purchaseNum': '2', 'purchasePrice': '5.60'}],
            'shippingList': [{'packageList': [{'goodsPurchaseOrderShippingPackageId': '77', 'logisticsName': '中通', 'waybillCode': 'ZT-UNIT'}]}]}


class Upstream:
    configured = True

    def __init__(self):
        self.packages, self.purchases, self.package_calls = [copy.deepcopy(PACKAGE)], [copy.deepcopy(PURCHASE)], []
        self.error = None

    async def get_packages(self, page=1, page_size=50, platform='tiktok', modified_from=None):
        self.package_calls.append(modified_from)
        if self.error:
            raise self.error
        return self.packages if page == 1 else []

    async def get_purchase_orders(self, page=1, page_size=50):
        return self.purchases if page == 1 else []


@pytest.fixture
def upstream(monkeypatch):
    value = Upstream()
    monkeypatch.setattr('app.api.v1.orders.MiaoshouClient', lambda: value)
    monkeypatch.setattr('app.api.v1.orders.async_session_factory', TestSessionLocal)
    return value


@pytest.fixture
async def headers(client, upstream):
    r = await client.post('/api/v1/auth/register', json={'username': 'order-sync@example.com', 'password': 'securepass123', 'nickname': 'UNIT_ONLY'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


async def test_empty_dashboard_has_no_mock_numbers(client, headers):
    stats = (await client.get('/api/v1/dashboard/stats', headers=headers)).json()
    assert stats['today_orders'] == 0 and stats['today_sales'] == '0' and stats['order_trend'] is None
    assert (await client.get('/api/v1/dashboard/sales-trend', headers=headers)).json()['sales'] == [0.0] * 7
    assert (await client.get('/api/v1/dashboard/order-status-distribution', headers=headers)).json() == {'data': []}


async def test_sync_orders_purchase_orders_finance_and_dashboard(client, headers, upstream):
    async with TestSessionLocal() as db, db.begin():
        db.add(Product(name='UNIT_ONLY sticker', item_num='B-UNIT', cost_price=Decimal('5.60'), cost_currency='CNY'))
        db.add(ExchangeRate(base_currency='CNY', target_currency='MYR', rate=Decimal('0.65')))
    r = await client.post('/api/v1/orders/sync', headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['orders']['status'] == 'succeeded' and r.json()['orders']['counts']['created'] == 1
    assert r.json()['purchase_orders']['counts']['created'] == 1

    orders = (await client.get('/api/v1/orders', headers=headers)).json()['items']
    assert len(orders) == 1
    order = orders[0]
    assert order['tiktok_order_id'] == 'TT-UNIT-1' and order['status'] == 'confirmed' and order['site'] == 'MY'
    assert order['total_amount'] == '20.00' and order['currency'] == 'MYR' and order['item_count'] == 2
    detail = (await client.get('/api/v1/orders/' + order['id'], headers=headers)).json()
    assert detail['items'][0]['product_id'] and detail['items'][0]['subtotal'] == '20.00'
    finance = {f['type']: f for f in detail['finance']}
    # 20 MYR / 0.65 = 30.77 CNY; cost is the linked product's CNY cost × quantity.
    assert finance['income']['cny_amount'] == '30.77' and finance['fee']['amount'] == '1.20'
    assert finance['cost']['amount'] == '11.20' and finance['cost']['currency'] == 'CNY'
    assert (await client.put(f"/api/v1/orders/{order['id']}/status", headers=headers, json={'status': 'completed'})).status_code == 409

    fulfillment = (await client.get('/api/v1/fulfillment/summary', headers=headers)).json()
    assert fulfillment['to_ship'] == 1 and fulfillment['overdue'] == 1
    outbound = (await client.get('/api/v1/fulfillment/outbound', headers=headers)).json()['items']
    assert outbound[0]['tiktok_order_id'] == 'TT-UNIT-1' and outbound[0]['items'][0]['quantity'] == 2
    purchase = (await client.get('/api/v1/fulfillment/purchase-orders', headers=headers)).json()['items'][0]
    assert purchase['po_sn'] == 'PO-UNIT-1' and purchase['supplier_name'] == 'UNIT_ONLY supplier' and purchase['tracking_number'] == 'ZT-UNIT'
    shipment = (await client.get('/api/v1/fulfillment/shipments', headers=headers)).json()['items'][0]
    assert shipment['carrier'] == '中通' and shipment['po_sn'] == 'PO-UNIT-1'

    summary = (await client.get('/api/v1/finance/summary', headers=headers)).json()
    assert summary['total_revenue'] == '30.77' and summary['total_fee'] == '1.85' and summary['unconverted'] == {}
    stats = (await client.get('/api/v1/dashboard/stats', headers=headers)).json()
    assert stats['today_orders'] in (0, 1) and stats['pending_orders'] == 1 and stats['overdue_orders'] == 1
    assert stats['sync']['orders']['status'] == 'succeeded'

    # Cancelling removes derived income; the second run is incremental and does not duplicate rows.
    upstream.packages[0]['appPackageStatus'] = 'cancelled'
    await client.post('/api/v1/orders/sync', headers=headers)
    assert upstream.package_calls[0] is None and upstream.package_calls[1] is not None
    async with TestSessionLocal() as db:
        assert (await db.scalars(select(FinanceRecord))).all() == []
    assert (await client.get('/api/v1/orders', headers=headers)).json()['total'] == 1


async def test_sync_failure_is_recorded_and_unconverted_income_is_not_mixed(client, headers, upstream):
    upstream.error = MiaoshouError('accountApiQpsRateLimit', 'rate_limit', 'UNIT_ONLY 限流')
    r = await client.post('/api/v1/orders/sync', headers=headers)
    assert r.json()['orders'] == {**r.json()['orders'], 'status': 'failed', 'error': 'UNIT_ONLY 限流'}
    upstream.error = None
    await client.post('/api/v1/orders/sync', headers=headers)
    summary = (await client.get('/api/v1/finance/summary', headers=headers)).json()
    # No MYR rate configured: income stays out of the CNY totals and is reported per currency.
    assert summary['total_revenue'] == '0' and summary['unconverted'] == {'MYR': 2}
    assert summary['by_currency']['MYR']['income'] == '20.00'


def test_moment_parses_beijing_time():
    value = order_sync_service.moment('2026-10-15 10:00:00')
    assert value.utcoffset().total_seconds() == 8 * 3600 and order_sync_service.moment('bad') is None
