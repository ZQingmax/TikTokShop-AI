"""1688 货源中心 API 集成测试（隔离 PostgreSQL）。CLI 由 FakeTransport 代替，夹具均为 TEST_ONLY 脱敏数据，
不代表真实商品，也不是真实联调验收。"""
import copy

import pytest
from sqlalchemy import func, select

from app.models.sourcing import SourcingCandidate, SourcingSupplier
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider
from app.services.alibaba1688.runner import CliResult
from tests.conftest import TestSessionLocal

OFFER_ID = '700000000001'
SEARCH = {'keyword': 'TEST_ONLY', 'total': 1, 'offers': [
    {'offerId': OFFER_ID, 'title': 'TEST_ONLY 露营灯', 'price': {'text': '¥14.5', 'min': 14.5, 'max': 16},
     'supplier': {'name': 'TEST_ONLY 照明厂', 'shopUrl': 'http://shoptest01.1688.com', 'years': 8},
     'verified': {'factory': True}, 'isP4P': False, 'url': f'https://detail.1688.com/offer/{OFFER_ID}.html',
     'image': 'https://img.example.test/1.jpg,https://img.example.test/2.jpg'}]}
OFFER = {'offerId': OFFER_ID, 'title': 'TEST_ONLY 露营灯 详情标题', 'priceMin': 12.5, 'priceMax': 15.125, 'minOrderQty': 2,
         'priceTiers': [{'minQty': 2, 'price': 15.125}], 'supplier': {'name': 'TEST_ONLY 照明厂', 'memberId': 'b2b-000test'},
         'skus': [{'skuId': '11', 'specs': '白色', 'price': 12.5}, {'skuId': '12', 'specs': '黑色', 'price': 13.255}],
         'mainImage': 'https://img.example.test/main.jpg', 'images': ['https://img.example.test/1.jpg'],
         'freight': {'province': '广东', 'city': '深圳'}}


class FakeTransport:
    def __init__(self):
        self.responses = {'search': SEARCH, 'offer': OFFER, 'image_search': SEARCH}
        self.errors = {}
        self.calls = []

    def available(self):
        return True

    async def run(self, command, params, timeout, **extra):
        self.calls.append(command)
        if command in self.errors:
            raise self.errors[command]
        return CliResult(copy.deepcopy(self.responses[command]), 1)


@pytest.fixture
def cli(monkeypatch):
    transport = FakeTransport()
    provider = Alibaba1688Provider(Alibaba1688Settings(_env_file=None, min_interval=0), transport)
    monkeypatch.setattr('app.api.v1.alibaba1688.get_provider', lambda: provider)
    return transport


async def register(client, name):
    r = await client.post('/api/v1/auth/register', json={'username': f'{name}@example.com', 'password': 'securepass123', 'nickname': name})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


@pytest.fixture
async def headers(client):
    return await register(client, 'cli1688')


async def candidates(client, headers, **params):
    r = await client.get('/api/v1/sourcing/candidates', headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_search_detail_save_and_reload(client, headers, cli):
    r = await client.get('/api/v1/sourcing/1688/search', headers=headers, params={'keyword': 'TEST_ONLY', 'max': 20})
    assert r.status_code == 200, r.text
    item = r.json()['items'][0]
    assert item['offer_id'] == OFFER_ID and 'raw' not in item and item['min_order_quantity'] is None
    r = await client.get(f'/api/v1/sourcing/1688/products/{OFFER_ID}', headers=headers)
    assert r.status_code == 200 and r.json()['skus'][1]['price'] == 13.255 and r.json()['raw']['offerId'] == OFFER_ID

    r = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID, 'target_market': 'TH'})
    assert r.status_code == 201, r.text
    assert r.json()['status'] == 'imported' and r.json()['detail_fetched'] is True
    page = await candidates(client, headers, data_source='1688_cli')
    assert page['total'] == 1
    c = page['items'][0]
    assert c['name'] == 'TEST_ONLY 露营灯 详情标题' and c['source_product_id'] == OFFER_ID and c['currency'] == 'CNY'
    assert c['purchase_price'] == '12.50' and float(c['source_price_max']) == 15.125 and c['min_order_quantity'] == 2
    # 超过两位小数的 SKU 价不取整，置空并保留在原始数据中
    assert [s['purchase_price'] for s in c['skus']] == ['12.50', None]
    assert c['completeness'] == 'ready' and c['trust_status'] == 'platform_session' and c['sourcing_status'] == 'saved'
    assert c['supplier_ref_id'] and c['raw_data']['cli_offer']['offerId'] == OFFER_ID and c['fetched_at']
    async with TestSessionLocal() as db:
        supplier = await db.get(SourcingSupplier, c['supplier_ref_id'])
        assert supplier.supplier_key == 'member:b2b-000test' and supplier.company_name == 'TEST_ONLY 照明厂'


async def test_duplicate_save_preserves_operator_fields(client, headers, cli):
    await client.get('/api/v1/sourcing/1688/search', headers=headers, params={'keyword': 'TEST_ONLY'})
    first = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID, 'use_detail': False})
    assert first.status_code == 201 and first.json()['detail_fetched'] is False
    cid = first.json()['id']
    r = await client.patch(f'/api/v1/sourcing/candidates/{cid}/operations', headers=headers,
                           json={'favorite': True, 'operator_note': '人工备注', 'sourcing_status': 'to_review'})
    assert r.status_code == 200 and r.json()['version'] == 1
    # 之后获取详情再次保存：平台字段升级，人工信息与商品资料版本不变
    second = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID, 'target_market': 'MY'})
    assert second.json() == {'id': cid, 'status': 'duplicate', 'detail_fetched': True, 'detail_error': None}
    c = (await client.get(f'/api/v1/sourcing/candidates/{cid}', headers=headers)).json()
    assert c['favorite'] is True and c['operator_note'] == '人工备注' and c['sourcing_status'] == 'to_review'
    assert c['name'] == 'TEST_ONLY 露营灯' and c['version'] == 1 and c['target_market'] == 'MY'
    assert c['min_order_quantity'] == 2 and c['source_record']['detail_fetched'] is True
    # 搜索列表数据不会覆盖已有详情数据
    await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID, 'use_detail': False})
    c = (await client.get(f'/api/v1/sourcing/candidates/{cid}', headers=headers)).json()
    assert c['min_order_quantity'] == 2 and c['source_record']['detail_fetched'] is True
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SourcingCandidate)) == 1

    other_market = await client.post('/api/v1/sourcing/1688/candidates', headers=headers,
        json={'offer_id': OFFER_ID, 'target_market': 'VN'})
    assert other_market.json()['status'] == 'imported' and other_market.json()['id'] != cid


async def test_detail_failure_falls_back_to_cached_search_item(client, headers, cli):
    cli.errors['offer'] = Alibaba1688Error('not_logged_in')
    await client.get('/api/v1/sourcing/1688/search', headers=headers, params={'keyword': 'TEST_ONLY'})
    r = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID})
    assert r.status_code == 201 and r.json()['detail_fetched'] is False and '未登录' in r.json()['detail_error']
    c = (await candidates(client, headers))['items'][0]
    assert c['purchase_price'] == '14.50' and c['min_order_quantity'] is None and '未获取详情' in c['source_note']


async def test_save_without_cli_data_is_refused(client, headers, cli):
    cli.errors['offer'] = Alibaba1688Error('not_logged_in')
    r = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID})
    assert r.status_code == 424 and r.json()['detail']['state'] == 'not_logged_in' and '1688 login' in r.json()['detail']['hint']
    r = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': '700000000099', 'use_detail': False})
    assert r.status_code == 422 and r.json()['detail']['state'] == 'bad_input'
    assert (await candidates(client, headers))['total'] == 0


@pytest.mark.parametrize('state,status', [('risk_control', 424), ('timeout', 504), ('cli_not_installed', 503),
                                          ('busy', 429), ('contract_changed', 502)])
async def test_cli_errors_map_to_http(client, headers, cli, state, status):
    cli.errors['search'] = Alibaba1688Error(state)
    r = await client.get('/api/v1/sourcing/1688/search', headers=headers, params={'keyword': 'TEST_ONLY'})
    assert r.status_code == status and r.json()['detail']['state'] == state
    if state == 'risk_control':
        assert '--headed' in r.json()['detail']['hint']


async def test_input_validation(client, headers, cli):
    for params in ({'keyword': ''}, {'keyword': 'x' * 51}, {'keyword': 'a', 'max': 41}, {'keyword': 'a', 'sort': 'x'},
                   {'keyword': 'a', 'price_min': -1}):
        assert (await client.get('/api/v1/sourcing/1688/search', headers=headers, params=params)).status_code == 422
    assert (await client.get('/api/v1/sourcing/1688/products/abc', headers=headers)).status_code == 422
    assert (await client.get('/api/v1/sourcing/1688/suppliers/shopxyz', headers=headers)).status_code == 422
    assert (await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': '1; rm'})).status_code == 422
    assert cli.calls == []
    assert (await client.get('/api/v1/sourcing/1688/search', params={'keyword': 'a'})).status_code in (401, 403)


async def test_image_upload_validation(client, headers, cli):
    r = await client.post('/api/v1/sourcing/1688/image-search', headers=headers,
                          files={'image': ('x.jpg', b'<svg onload=alert(1)>', 'image/jpeg')})
    assert r.status_code == 422 and r.json()['detail']['state'] == 'bad_input'
    r = await client.post('/api/v1/sourcing/1688/image-search', headers=headers,
                          files={'image': ('x.png', b'\x89PNG\r\n\x1a\n' + b'0' * (6 * 1024 * 1024), 'image/png')})
    assert r.status_code == 422
    assert cli.calls == []
    r = await client.post('/api/v1/sourcing/1688/image-search', headers=headers,
                          files={'image': ('x.png', b'\x89PNG\r\n\x1a\n' + b'0' * 100, 'image/png')}, data={'max': '10'})
    assert r.status_code == 200 and r.json()['items'][0]['offer_id'] == OFFER_ID and cli.calls == ['image_search']
    # 请求的数量上限必须生效（联调发现：曾被图片字节上限变量覆盖，始终返回 20 条）
    many = {'offers': [{**SEARCH['offers'][0], 'offerId': str(700000000100 + i)} for i in range(5)]}
    cli.responses['image_search'] = many
    r = await client.post('/api/v1/sourcing/1688/image-search', headers=headers,
                          files={'image': ('y.png', b'\x89PNG\r\n\x1a\n' + b'1' * 100, 'image/png')}, data={'max': '3'})
    assert r.status_code == 200 and len(r.json()['items']) == 3 and r.json()['total'] == 3


async def test_operations_are_owner_scoped_and_validated(client, headers, cli):
    await client.get('/api/v1/sourcing/1688/search', headers=headers, params={'keyword': 'TEST_ONLY'})
    cid = (await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID})).json()['id']
    other = await register(client, 'other1688')
    assert (await client.patch(f'/api/v1/sourcing/candidates/{cid}/operations', headers=other, json={'favorite': True})).status_code == 404
    assert (await client.patch(f'/api/v1/sourcing/candidates/{cid}/operations', headers=headers,
                               json={'sourcing_status': 'published'})).status_code == 422
    r = await client.patch(f'/api/v1/sourcing/candidates/{cid}/operations', headers=headers, json={'sourcing_status': 'to_analyze'})
    assert r.json()['sourcing_status'] == 'to_analyze'
    assert (await candidates(client, headers, sourcing_status='to_analyze'))['total'] == 1
    assert (await candidates(client, headers, sourcing_status='to_review'))['total'] == 0
    assert (await candidates(client, other))['total'] == 0


async def test_existing_record_from_other_source_is_not_overwritten(client, headers, cli):
    r = await client.post('/api/v1/sourcing/candidates', headers=headers, json={
        'product_url': f'https://detail.1688.com/offer/{OFFER_ID}.html', 'name': '人工录入名称', 'purchase_price': '9.90',
        'main_image': 'https://img.example.test/manual.jpg', 'target_market': 'MY', 'source_note': 'TEST_ONLY'})
    assert r.status_code == 201
    saved = await client.post('/api/v1/sourcing/1688/candidates', headers=headers, json={'offer_id': OFFER_ID})
    assert saved.json()['status'] == 'duplicate' and saved.json()['id'] == r.json()['id']
    c = (await client.get(f'/api/v1/sourcing/candidates/{r.json()["id"]}', headers=headers)).json()
    assert c['name'] == '人工录入名称' and c['purchase_price'] == '9.90' and c['data_source'] == 'manual'
    assert c['supplier_ref_id'] and c['raw_data'] is None
