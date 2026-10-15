"""PostgreSQL collection/sync tests; upstream data are labelled fixtures."""
import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError, MiaoshouResponse, SHOPS, LIST, DETAIL, FETCH
from app.models.sourcing import MiaoshouSyncTask, SourcingCandidate, SourcingTask
from app.services.miaoshou_sync_worker import MiaoshouSyncWorker
from app.services.sourcing_config import SourcingSettings
from app.services.miaoshou_mapping import store_detail, public_raw
from app.services.sourcing_sources import MiaoshouSourceAdapter
from tests.conftest import TestSessionLocal

DETAIL_DATA = {'commonCollectBoxDetailId': 42, 'title': 'UNIT_ONLY 真响应结构样本', 'imgUrls': ['https://example.com/a.jpg'],
               'price': 1.7, 'stock': 100, 'weight': 0.025,
               'skuMap': {'black;short': {'itemNum': None, 'price': 2.3, 'oriPrice': 1.8, 'stock': 40, 'weight': 0.015, 'packageLength': 12.5}},
               'sourceSupplierInfo': {'companyName': 'UNIT_ONLY', 'authToken': 'NOT_FOR_UI'},
               'sourceMataInfo': {'minimumOrder': 2},
               'sourceList': [{'source': '1688', 'sourceItemId': '635021027818', 'sourceItemUrl': 'http://detail.1688.com/offer/635021027818.html'}]}


def response(data, path=DETAIL):
    env = {'result': 'success', 'code': 'success', 'data': copy.deepcopy(data)}
    return MiaoshouResponse(copy.deepcopy(data), env, json.dumps(env), path, 'UNIT_HASH')


class FixtureClient:
    configured = True
    def __init__(self, uncertain=False, existing=False):
        self.writes = 0
        self.platform_exists = existing
        self.uncertain = uncertain
    async def get_common_list(self, **kwargs):
        rows = [{'commonCollectBoxDetailId': 42, 'sourceList': DETAIL_DATA['sourceList']}] if self.platform_exists else []
        return response({'detailList': rows, 'total': len(rows)}, LIST)
    async def get_common_detail(self, id):
        return response({'editCommonCollectBoxDetail': copy.deepcopy(DETAIL_DATA), 'ossMd5': 'UNIT_OSS'})
    async def fetch_items(self, links):
        self.writes += 1
        self.platform_exists = True
        if self.uncertain:
            raise MiaoshouError('timeout', 'timeout', 'UNIT_ONLY uncertain result', uncertain=True)
        return response({'sourceItemIdAndDetailIdMap': {'635021027818': 42}}, FETCH)
    async def get_shop_detail(self, detail_id, shop_id):
        self.shop_detail_args = (detail_id, shop_id)
        info = {'title': 'UNIT_ONLY TK 标题', 'skuMap': {'1;2': {'price': 9.9, 'stock': 3}}, 'accessToken': 'NOT_FOR_UI'}
        return response({'ossMd5': 'UNIT_OSS', 'shopCollectItemInfo': info})


@pytest.fixture
async def headers(client, monkeypatch):
    monkeypatch.setattr('app.api.v1.miaoshou.MiaoshouClient', lambda: FixtureClient())
    r = await client.post('/api/v1/auth/register', json={'username': 'miaoshou@example.com', 'password': 'securepass123', 'nickname': '妙手测试操作人'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def input_data(**changes):
    return {'request_key': str(uuid.uuid4()), 'links': ['https://detail.1688.com/offer/635021027818.html?tracking=UNIT'],
            'target_market': 'TH', 'currency': 'CNY', **changes}


async def post_collect(client, headers, data):
    result = await client.post('/api/v1/sourcing/miaoshou/collect', headers=headers, json=data)
    assert result.status_code == 202, result.text
    return result.json()


def worker(upstream):
    return MiaoshouSyncWorker(TestSessionLocal, SourcingSettings(_env_file=None), upstream)


async def test_collect_map_raw_units_dedupe_and_ai_entry(client, headers):
    upstream = FixtureClient()
    w = worker(upstream)
    data = input_data(analyze_after_sync=True)
    job = await post_collect(client, headers, data)
    repeated = await post_collect(client, headers, data)
    assert job['id'] == repeated['id'] and repeated['reused']
    assert await w.process_one()
    result = (await client.get('/api/v1/sourcing/miaoshou/tasks/' + job['id'], headers=headers)).json()
    assert result['status'] == 'succeeded' and result['completed'] == 1 and upstream.writes == 1
    item = result['items'][0]
    assert item['common_detail_id'] == '42' and item['analysis_task_id']
    candidate = (await client.get('/api/v1/sourcing/candidates/' + item['candidate_id'], headers=headers)).json()
    assert candidate['raw_data']['detail_response']['data']['editCommonCollectBoxDetail']['skuMap'] == DETAIL_DATA['skuMap']
    assert candidate['source_weight'] == 0.025 and candidate['source_stock'] == 100
    assert candidate['source_meta_info'] == {'minimumOrder': 2}
    assert candidate['source_supplier_info']['authToken'] == '[redacted]'
    assert candidate['skus'][0]['purchase_price'] is None
    assert candidate['raw_data']['price_meanings']['tiktok_sale_price'].startswith('尚未设置')
    assert candidate['raw_data']['units']['skuMap.packageLength'] == 'cm'
    assert candidate['original_url'] == DETAIL_DATA['sourceList'][0]['sourceItemUrl']
    async with TestSessionLocal() as db:
        task = await db.get(SourcingTask, uuid.UUID(item['analysis_task_id']))
        assert task.snapshot['source_details']['skuMap'] == DETAIL_DATA['skuMap']
    # Fresh intentional request finds the platform record; it only synchronizes, never collects twice.
    second = await post_collect(client, headers, input_data())
    await w.process_one()
    assert upstream.writes == 1
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SourcingCandidate)) == 1
        assert (await db.get(SourcingCandidate, uuid.UUID(item['candidate_id']))).version == candidate['version']


async def test_uncertain_collection_queries_without_resubmit(client, headers):
    upstream = FixtureClient(uncertain=True)
    w = worker(upstream)
    job = await post_collect(client, headers, input_data())
    await w.process_one()
    async with TestSessionLocal() as db:
        task = await db.get(MiaoshouSyncTask, uuid.UUID(job['id']))
        assert task.status == 'waiting' and task.external_started_at is not None
        task.next_poll_at = None
        await db.commit()
    await w.process_one()
    result = (await client.get('/api/v1/sourcing/miaoshou/tasks/' + job['id'], headers=headers)).json()
    assert result['status'] == 'succeeded' and upstream.writes == 1


async def test_restart_lease_and_manual_reconcile_never_write(client, headers):
    upstream = FixtureClient()
    w = worker(upstream)
    job = await post_collect(client, headers, input_data())
    claims = await asyncio.gather(w.claim(), w.claim())
    assert sum(x is not None for x in claims) == 1
    async with TestSessionLocal() as db:
        task = await db.get(MiaoshouSyncTask, uuid.UUID(job['id']))
        task.external_started_at = datetime.now(timezone.utc)
        task.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    await w.recover_expired()
    w.settings.miaoshou_max_polls = 1
    await w.process_one()
    result = (await client.get('/api/v1/sourcing/miaoshou/tasks/' + job['id'], headers=headers)).json()
    assert result['status'] == 'uncertain' and upstream.writes == 0
    r = await client.post('/api/v1/sourcing/miaoshou/tasks/' + job['id'] + '/reconcile', headers=headers)
    assert r.status_code == 202
    upstream.platform_exists = True
    await w.process_one()
    assert upstream.writes == 0
    assert (await client.get('/api/v1/sourcing/miaoshou/tasks/' + job['id'], headers=headers)).json()['status'] == 'succeeded'


async def test_read_only_sync_and_owner_scope(client, headers):
    upstream = FixtureClient(existing=True)
    data = {'request_key': str(uuid.uuid4()), 'common_detail_ids': ['42'], 'target_market': 'TH', 'currency': 'CNY'}
    r = await client.post('/api/v1/sourcing/miaoshou/sync', headers=headers, json=data)
    assert r.status_code == 202
    await worker(upstream).process_one()
    assert upstream.writes == 0
    other = await client.post('/api/v1/auth/register', json={'username': 'miaoshou-other@example.com', 'password': 'securepass123', 'nickname': 'Other'})
    other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get('/api/v1/sourcing/miaoshou/tasks/' + r.json()['id'], headers=other_headers)).status_code == 404
    assert (await client.get('/api/v1/sourcing/miaoshou/tasks', headers=other_headers)).json()['total'] == 0
    assert (await client.post('/api/v1/sourcing/miaoshou/collect', json=input_data())).status_code == 403


async def test_core_sync_changes_version_and_preserves_missing_price(client, headers):
    from app.models.user import User
    upstream = FixtureClient(existing=True)
    adapter = MiaoshouSourceAdapter(SourcingSettings(_env_file=None), upstream)
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        record = {'editCommonCollectBoxDetail': copy.deepcopy(DETAIL_DATA), 'ossMd5': 'UNIT'}
        first = await store_detail(db, adapter, record, '42', user.id, 'TH', 'CNY')
        record['editCommonCollectBoxDetail']['price'] = None
        record['editCommonCollectBoxDetail']['weight'] = 0.037
        second = await store_detail(db, adapter, record, '42', user.id, 'TH', 'CNY')
        await db.commit()
        assert first['id'] == second['id'] and second['input_version'] == first['input_version'] + 1
        candidate = await db.get(SourcingCandidate, uuid.UUID(first['id']))
        assert candidate.purchase_price is None and candidate.completeness == 'needs_details'
        assert candidate.raw_data['detail_response']['data']['editCommonCollectBoxDetail']['price'] is None
        assert candidate.source_weight == __import__('decimal').Decimal('0.037')
        # Supplier/meta changes matter even when the normalized title and price stay the same.
        from app.models.sourcing import SourcingEvaluation
        task = SourcingTask(candidate_id=candidate.id, owner_id=user.id, batch_id=uuid.uuid4(),
                            input_version=candidate.version, snapshot={}, signature='UNIT_ONLY', model_config={})
        db.add(task)
        await db.flush()
        evaluation = SourcingEvaluation(candidate_id=candidate.id, task_id=task.id, input_version=candidate.version,
                                       visual_score=50, vision={}, text_status='not_configured', rule_score=0, rule_basis=[], evidence={})
        db.add(evaluation)
        await db.flush()
        record['editCommonCollectBoxDetail']['sourceMataInfo'] = {'minimumOrder': 20}
        third = await store_detail(db, adapter, record, '42', user.id, 'TH', 'CNY')
        await db.refresh(evaluation)
        assert third['input_version'] == second['input_version'] + 1 and evaluation.stale


async def test_tiktok_box_detail_is_read_only_and_redacted(client, headers):
    url = '/api/v1/sourcing/miaoshou/tiktok-products/3454529857'
    r = await client.get(url, headers=headers, params={'shop_id': '19282337'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['shop_id'] == '19282337' and body['data']['title'] == 'UNIT_ONLY TK 标题'
    assert body['data']['accessToken'] == '[redacted]'
    assert (await client.get(url, headers=headers)).status_code == 422
    assert (await client.get(url, headers=headers, params={'shop_id': 'abc'})).status_code == 422
    assert (await client.get(url, params={'shop_id': '19282337'})).status_code == 403
