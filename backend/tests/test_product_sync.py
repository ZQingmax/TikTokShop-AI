"""Products synced from the Miaoshou TikTok collect box. Upstream values are labelled fixtures."""
import pytest
from app.clients.miaoshou_client import MiaoshouError
from tests.test_miaoshou_integration import response

ROW = {'collectBoxDetailId': '3454529857', 'title': 'UNIT_ONLY Christmas sticker', 'price': '5.60', 'stock': '3999763',
       'itemNum': 'B-UNIT', 'thumbnail': 'https://example.com/t.jpg', 'commonCollectBoxDetailId': '4067002823',
       'collectBoxDetailShopList': [{'shopId': '19282337'}]}


class Upstream:
    configured = True

    def __init__(self):
        self.rows = [ROW, {**ROW, 'collectBoxDetailId': '3454388014', 'title': 'UNIT_ONLY basket', 'commonCollectBoxDetailId': '999',
                           'collectBoxDetailShopList': []}]
        self.published = {'3454529857'}
        self.detail_error = None
        self.details = {'3454529857': {'title': 'UNIT_ONLY Set Sticker Krismas', 'site': 'MY', 'skuMap': {
            ';1;': {'price': 10, 'originPrice': 5.6, 'stock': '60', 'isDelete': '0'},
            ';2;': {'price': '12.5', 'originPrice': 6, 'stock': 40, 'isDelete': '0'},
            ';3;': {'price': 1, 'originPrice': 1, 'stock': 999, 'isDelete': '1'}}}}

    async def get_shop_detail(self, detail_id, shop_id):
        if self.detail_error:
            raise self.detail_error
        return response({'ossMd5': 'UNIT', 'shopCollectItemInfo': self.details[detail_id]})

    async def get_tiktok_list(self, page=1, page_size=20, source_id=None, status=None):
        rows = [r for r in self.rows if status is None or (status == 'published' and r['collectBoxDetailId'] in self.published)]
        return response({'detailList': rows if page == 1 else []})

    async def get_shops(self, platform, site, page=1, page_size=100):
        return response({'shopList': [{'shopId': 19282337, 'site': 'MY', 'platform': 'tiktok'}] if site == 'MY' else []})


@pytest.fixture
def upstream(monkeypatch):
    value = Upstream()
    monkeypatch.setattr('app.api.v1.products.MiaoshouClient', lambda: value)
    return value


@pytest.fixture
async def headers(client, upstream):
    r = await client.post('/api/v1/auth/register', json={'username': 'product-sync@example.com', 'password': 'securepass123', 'nickname': 'UNIT_ONLY'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


async def test_sync_upserts_links_cost_and_marks_removed(client, headers, upstream):
    from app.models.sourcing import SourcingCandidate
    from app.models.user import User
    from sqlalchemy import select
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as db, db.begin():
        owner = await db.scalar(select(User.id).where(User.username == 'product-sync@example.com'))
        db.add(SourcingCandidate(owner_id=owner, identity_key='unit-sync', source_platform='1688', product_url='https://detail.1688.com/offer/1.html',
                                 source_product_id='1084756960831', miaoshou_detail_id='4067002823', purchase_price=5.6, currency='CNY', target_market='MY', completeness='ready'))
    r = await client.post('/api/v1/products/sync', headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['created'] == 2
    items = {x['miaoshou_detail_id']: x for x in (await client.get('/api/v1/products', headers=headers)).json()['items']}
    sticker, basket = items['3454529857'], items['3454388014']
    assert sticker['miaoshou_status'] == 'published' and sticker['status'] == 'listed'
    # Sale side comes from the shop-mode detail (deleted SKUs ignored), not the list's source price.
    assert sticker['name'] == 'UNIT_ONLY Set Sticker Krismas' and sticker['market'] == 'MY' and sticker['sale_currency'] == 'MYR'
    assert (sticker['sale_price'], sticker['sale_price_max'], sticker['stock'], sticker['sku_count']) == ('10.00', '12.50', 100, 2)
    assert sticker['cost_price'] == '5.60' and sticker['cost_source'] == 'sourcing' and sticker['source_product_id'] == '1084756960831'
    assert basket['miaoshou_status'] == 'notPublished' and basket['market'] is None
    assert basket['sale_price'] is None and basket['cost_price'] is None and basket['name'] == 'UNIT_ONLY basket'
    upstream.rows = upstream.rows[:1]
    upstream.detail_error = MiaoshouError('timeout', 'timeout', 'UNIT_ONLY timeout')
    r = await client.post('/api/v1/products/sync', headers=headers)
    assert r.json()['removed'] == 1 and r.json()['updated'] == 1 and r.json()['detail_failed'] == 1
    kept = (await client.get('/api/v1/products', headers=headers, params={'miaoshou_status': 'published'})).json()['items'][0]
    assert kept['sale_price'] == '10.00' and kept['stock'] == 100
    removed = (await client.get('/api/v1/products', headers=headers, params={'miaoshou_status': 'removed'})).json()['items']
    assert [x['miaoshou_detail_id'] for x in removed] == ['3454388014']
    summary = (await client.get('/api/v1/products/summary', headers=headers)).json()
    assert summary['counts'] == {'published': 1, 'removed': 1} and summary['synced_at']
