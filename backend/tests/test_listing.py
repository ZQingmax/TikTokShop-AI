"""Listing (publish to shop) tests. All upstream values are labelled fixtures; nothing reaches Miaoshou."""
import copy
import uuid
import pytest
from sqlalchemy import select
from app.clients.miaoshou_client import MiaoshouError
from app.models.listing import ListingTask
from app.services.listing_worker import ListingWorker
from app.services.sourcing_config import SourcingSettings
from tests.conftest import TestSessionLocal
from tests.test_miaoshou_integration import response

ROOT = '/api/v1/listing'
READY = {'title': 'UNIT_ONLY Durable household storage rack for kitchen', 'notes': 'UNIT_ONLY description', 'site': 'MY',
         'imgUrls': ['https://example.com/a.jpg'], 'cid': '7', 'weight': 0.2, 'packageLength': 10, 'packageWidth': 10,
         'packageHeight': '5', 'isCodOpen': '0', 'skuPropertyList': [], 'productAttributes': [],
         'skuMap': {';': {'price': 10.5, 'stock': 99, 'isDelete': '0', 'shopIdToWarehouseIdAndStockMap': {'99': {'8': '99'}}}}}


class Upstream:
    configured = True

    def __init__(self):
        self.details = {'101': copy.deepcopy(READY), '102': {**copy.deepcopy(READY), 'cid': None}, '103': copy.deepcopy(READY)}
        self.published, self.publish_calls, self.records = set(), [], []
        self.publish_error = None
        self.land_on_publish = True

    async def get_shops(self, platform, site, page=1, page_size=100):
        return response({'shopList': [{'shopId': 99, 'site': 'MY', 'platform': 'tiktok'}]})

    async def get_categories(self, site):
        return response({'cateTree': {'7': {'cid': 7, 'name': 'UNIT_ONLY', 'isLastLevel': '1', 'disabled': False}}})

    async def get_category_metadata(self, site, cid, shop_id):
        return response({'categoryMetadata': {'categoryConfig': {}, 'categoryProductAttrList': [], 'categorySaleAttrList': []}})

    async def get_warehouses(self, shop_id):
        return response({'shopWarehouseList': [{'shopId': 99, 'warehouseList': [{'warehouseId': '8', 'warehouseEffectStatus': '1'}]}]})

    async def get_shop_detail(self, detail_id, shop_id):
        return response({'ossMd5': 'UNIT', 'shopCollectItemInfo': copy.deepcopy(self.details[detail_id])})

    async def get_tiktok_list(self, page=1, page_size=20, source_id=None, status=None):
        rows = [{'collectBoxDetailId': x} for x in sorted(self.published)] if status == 'published' else []
        return response({'detailList': rows})

    async def get_publish_records(self, page=1, page_size=100):
        return response({'moveCollectDetailList': self.records, 'total': len(self.records)})

    async def publish(self, detail_ids, shop_ids):
        self.publish_calls.append((list(detail_ids), list(shop_ids)))
        if self.land_on_publish:
            self.published.update(detail_ids)
        if self.publish_error:
            raise self.publish_error
        return response({})


@pytest.fixture
def upstream(monkeypatch):
    value = Upstream()
    monkeypatch.setattr('app.api.v1.listing.MiaoshouClient', lambda: value)
    return value


@pytest.fixture
async def headers(client, upstream):
    r = await client.post('/api/v1/auth/register', json={'username': 'listing@example.com', 'password': 'securepass123', 'nickname': 'UNIT_ONLY'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def worker(upstream):
    return ListingWorker(TestSessionLocal, SourcingSettings(_env_file=None), upstream)


async def submit(client, headers, kind, ids, shop='99'):
    body = {'request_key': str(uuid.uuid4()), 'kind': kind, 'market': 'MY', 'items': [{'detail_id': x, 'shop_id': shop} for x in ids]}
    r = await client.post(ROOT + '/tasks', headers=headers, json=body)
    assert r.status_code == 202, r.text
    return r.json(), body


async def run(upstream, task_id, times=1):
    for _ in range(times):
        async with TestSessionLocal() as db, db.begin():
            await db.execute(ListingTask.__table__.update().where(ListingTask.id == uuid.UUID(task_id)).values(next_poll_at=None))
        await worker(upstream).process_one()


async def fetch(client, headers, task_id):
    return (await client.get(f'{ROOT}/tasks/{task_id}', headers=headers)).json()


async def test_check_reports_missing_rules_without_writing(client, headers, upstream):
    task, _ = await submit(client, headers, 'check', ['101', '102'])
    await run(upstream, task['id'])
    result = await fetch(client, headers, task['id'])
    states = {x['detail_id']: x for x in result['items']}
    assert result['status'] == 'partial' and upstream.publish_calls == []
    assert states['101']['state'] == 'ready' and states['101']['errors'] == []
    assert states['102']['state'] == 'blocked' and any(e['field'] == 'cid' for e in states['102']['errors'])


async def test_publish_submits_passing_items_once_and_confirms(client, headers, upstream):
    task, body = await submit(client, headers, 'publish', ['101', '102', '103'])
    await run(upstream, task['id'])
    assert upstream.publish_calls == [(['101', '103'], ['99'])]
    result = await fetch(client, headers, task['id'])
    assert result['status'] == 'partial' and result['counts'] == {'published': 2, 'blocked': 1}
    # Same request_key returns the same task; an already published product is not published again.
    again = await client.post(ROOT + '/tasks', headers=headers, json=body)
    assert again.json()['id'] == task['id'] and again.json()['reused']
    second, _ = await submit(client, headers, 'publish', ['101'])
    await run(upstream, second['id'])
    result = await fetch(client, headers, second['id'])
    assert result['status'] == 'failed' and result['items'][0]['errors'][0]['field'] == 'status'
    assert len(upstream.publish_calls) == 1


async def test_uncertain_publish_is_only_queried_and_blocks_duplicates(client, headers, upstream):
    upstream.land_on_publish = False
    upstream.publish_error = MiaoshouError('timeout', 'timeout', 'UNIT_ONLY lost acknowledgement', uncertain=True)
    task, _ = await submit(client, headers, 'publish', ['101'])
    await run(upstream, task['id'])
    result = await fetch(client, headers, task['id'])
    assert result['status'] == 'waiting' and result['items'][0]['state'] == 'uncertain'
    conflict = await client.post(ROOT + '/tasks', headers=headers, json={'request_key': str(uuid.uuid4()), 'kind': 'publish', 'market': 'MY',
                                                                         'items': [{'detail_id': '101', 'shop_id': '99'}]})
    assert conflict.status_code == 409
    upstream.published.add('101')
    await run(upstream, task['id'])
    result = await fetch(client, headers, task['id'])
    assert result['status'] == 'succeeded' and result['items'][0]['state'] == 'published'
    assert len(upstream.publish_calls) == 1


async def test_failed_publish_record_is_reported(client, headers, upstream):
    upstream.land_on_publish = False
    upstream.records = [{'collectBoxDetailId': '101', 'status': 'fail', 'failReason': 'UNIT_ONLY category not allowed'}]
    task, _ = await submit(client, headers, 'publish', ['101'])
    await run(upstream, task['id'])
    item = (await fetch(client, headers, task['id']))['items'][0]
    assert item['state'] == 'failed' and item['error'] == 'UNIT_ONLY category not allowed'


async def test_interrupted_submit_is_never_resent(client, headers, upstream):
    task, _ = await submit(client, headers, 'publish', ['101'])
    async with TestSessionLocal() as db, db.begin():
        job = await db.get(ListingTask, uuid.UUID(task['id']))
        job.items = [{**job.items[0], 'state': 'submitting'}]
        job.status, job.lease_until = 'running', job.created_at
    await worker(upstream).recover_expired()
    upstream.published.add('101')
    await run(upstream, task['id'])
    result = await fetch(client, headers, task['id'])
    assert result['items'][0]['state'] == 'published' and upstream.publish_calls == []


async def test_validation_and_owner_scope(client, headers, upstream):
    bad = await client.post(ROOT + '/tasks', headers=headers, json={'request_key': str(uuid.uuid4()), 'kind': 'publish', 'market': 'MY',
                                                                    'items': [{'detail_id': 'abc', 'shop_id': '99'}]})
    assert bad.status_code == 422
    task, _ = await submit(client, headers, 'check', ['101'])
    other = await client.post('/api/v1/auth/register', json={'username': 'listing-other@example.com', 'password': 'securepass123', 'nickname': 'Other'})
    other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get(f'{ROOT}/tasks/{task["id"]}', headers=other_headers)).status_code == 404
    assert (await client.get(ROOT + '/tasks', headers=other_headers)).json()['total'] == 0


def test_custom_attribute_value_stored_by_name_is_accepted():
    from app.services import workbench_service as rules
    rule = {'attrId': '100701', 'name': 'Bahan', 'isCustomized': True, 'isMultipleSelected': True, 'values': [{'id': '1000007', 'name': 'Plastik'}]}
    metadata = {'categoryConfig': {}, 'categoryProductAttrList': [rule], 'categorySaleAttrList': []}
    category = {'cid': 7, 'isLastLevel': '1', 'disabled': False}
    warehouses = {'shopWarehouseList': [{'shopId': 99, 'warehouseList': [{'warehouseId': '8', 'warehouseEffectStatus': '1'}]}]}
    from app.services.listing_publish_service import normalize
    def errors(values, customizable=True):
        content = normalize({**READY, 'productAttributes': [{'attributeId': '100701', 'attributeValues': values}]})
        return rules.validate_content(content, '99', category, {**metadata, 'categoryProductAttrList': [{**rule, 'isCustomized': customizable}]}, warehouses)['errors']
    assert errors([{'valueName': 'Lain-lain', 'valueId': None}]) == []
    assert errors([{'valueName': 'Lain-lain', 'valueId': None}], customizable=False)
    assert errors([{'valueName': '', 'valueId': None}])
