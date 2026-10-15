"""PostgreSQL integration tests. Provider fixtures are never real-model acceptance."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from app.models.sourcing import SourcingCandidate, SourcingEvaluation, SourcingReview, SourcingTask
from app.schemas.sourcing import CandidateInput, VisionOutput
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError, CompatibleProvider, fetch_image
from app.services.sourcing_sources import MiaoshouSourceAdapter
from app.services.sourcing_worker import SourcingWorker
from tests.conftest import TestSessionLocal

DATA = {'product_url': 'https://detail.1688.com/offer/123456789.html', 'name': '自动测试样本：清洁刷',
        'main_image': 'https://example.com/brush.jpg', 'purchase_price': '12.50', 'target_market': 'TH',
        'source_note': '仅自动测试 fixture；不代表真实商品或模型验收'}
VISION = {'visual_score': 74.0, 'product_type': '清洁刷', 'visual_selling_points': ['刷毛可见'],
          'presentation_quality': '主体清晰', 'potential_risks': [{'kind': 'needs_verification', 'detail': '耐用性需测试'}],
          'score_basis': ['主体展示完整'], 'limitations': ['无真实销量、利润或供应商资质证据']}
TEXT = {'advantages': ['体积小'], 'disadvantages': ['需核实耐用性'], 'differentiation': ['测试配色'],
        'cost_risks': ['运费未知'], 'english_title_suggestion': 'Cleaning Brush', 'worth_review': True,
        'recommendation_reasons': ['建议人工核实后决策'], 'limitations': ['无市场调查证据'],
        'market_fit_suggestions': [{'target_market': 'TH', 'suggestion': '可测试泰语素材', 'basis': '用途可展示', 'limitation': '当地需求未知'}]}


@pytest.fixture
async def headers(client):
    r = await client.post('/api/v1/auth/register', json={'username': 'sourcing@example.com', 'password': 'securepass123', 'nickname': '测试操作人'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


async def create(client, headers, **changes):
    r = await client.post('/api/v1/sourcing/candidates', headers=headers, json={**DATA, **changes})
    assert r.status_code == 201, r.text
    return r.json()['id']


async def submit(client, headers, ids):
    r = await client.post('/api/v1/sourcing/analyses', headers=headers, json={'candidate_ids': ids})
    assert r.status_code == 202, r.text
    return r.json()['tasks']


class FixtureVision:
    calls = 0
    def __init__(self, *args): pass
    async def analyze_image(self, snapshot):
        type(self).calls += 1
        return {'output': VISION, 'provider': 'TEST_FIXTURE', 'model': 'TEST_ONLY', 'request_id': 'fixture', 'usage': None, 'images': []}


class FixtureText:
    calls = 0
    error = None
    def __init__(self, *args): pass
    async def analyze(self, snapshot):
        type(self).calls += 1
        if type(self).error:
            raise type(self).error
        return {'output': {'market_basis': [], 'matching_facts': ['测试用途'], 'differences': [], 'recommendation_reasons': ['待核实'], 'information_gaps': ['运费未知'], 'limitations': ['市场未知']}, 'provider': 'TEST_FIXTURE', 'model': 'TEST_ONLY', 'request_id': 'fixture', 'usage': None}


def worker():
    FixtureVision.calls = FixtureText.calls = 0
    FixtureText.error = None
    return SourcingWorker(TestSessionLocal, SourcingSettings(_env_file=None, DEEPSEEK_API_KEY='test-only'), evidence_factory=FixtureText)


async def force_text_configuration(ids, enabled=True):
    async with TestSessionLocal() as db:
        for task_id in ids:
            task = await db.get(SourcingTask, uuid.UUID(task_id))
            task.model_config = {**task.model_config, 'text_enabled': enabled}
        await db.commit()


async def get_candidate(client, headers, id):
    r = await client.get('/api/v1/sourcing/candidates/' + id, headers=headers)
    assert r.status_code == 200
    return r.json()


async def review(client, headers, candidate, action='approve'):
    return await client.post(f"/api/v1/sourcing/candidates/{candidate['id']}/review", headers=headers,
                             json={'evaluation_id': candidate['evaluation']['id'], 'input_version': candidate['version'], 'action': action, 'note': '自动测试审核'})


async def test_import_dedupe_incomplete_filter_and_source_fields(client, headers):
    id = await create(client, headers)
    r = await client.post('/api/v1/sourcing/candidates', headers=headers, json={**DATA, 'product_url': DATA['product_url'] + '?tracking=1'})
    assert r.json() == {'id': id, 'status': 'duplicate'}
    incomplete = await create(client, headers, product_url='https://detail.1688.com/offer/222.html', name=None, main_image=None, purchase_price=None)
    r = await client.post('/api/v1/sourcing/analyses', headers=headers, json={'candidate_ids': [incomplete]})
    assert r.status_code == 422
    r = await client.get('/api/v1/sourcing/candidates?min_price=12&max_price=13&currency=CNY&keyword=清洁刷', headers=headers)
    assert r.json()['total'] == 1
    candidate = await get_candidate(client, headers, id)
    assert candidate['trust_status'] == 'user_provided'
    assert candidate['original_source_id'] == '123456789'
    assert candidate['original_url'] == DATA['product_url']


async def test_csv_json_partial_import_and_invalid_input(client, headers):
    r = await client.post('/api/v1/sourcing/candidates/import', headers=headers,
                         json={'format': 'json', 'content': json.dumps([DATA, {'product_url': 'https://not1688.com/p'}, DATA]), 'target_market': 'TH'})
    assert r.json()['imported'] == 1 and r.json()['invalid'] == 1 and r.json()['duplicates'] == 1
    r = await client.post('/api/v1/sourcing/candidates/import', headers=headers,
                         json={'format': 'csv', 'content': 'product_url,name,purchase_price\nhttps://detail.1688.com/offer/234.html,CSV测试商品,0\n', 'target_market': 'MY'})
    assert r.json()['imported'] == 1
    for change in [{'purchase_price': '-1'}, {'source_product_id': 'wrong'}, {'trust_status': 'verified'}, {'name': ''}]:
        r = await client.post('/api/v1/sourcing/candidates', headers=headers, json={**DATA, **change})
        assert r.status_code == 422


async def test_batch_progress_review_persistence_and_stale(client, headers):
    ids = [await create(client, headers), await create(client, headers, product_url='https://detail.1688.com/offer/234.html')]
    submitted = await submit(client, headers, ids)
    repeated = await submit(client, headers, ids)
    assert {x['id'] for x in submitted} == {x['id'] for x in repeated}
    assert all(x['reused'] for x in repeated)
    await force_text_configuration([t['id'] for t in submitted])
    w = worker()
    assert await w.process_one()
    assert await w.process_one()
    assert not await w.process_one()
    states = (await client.get('/api/v1/sourcing/tasks', headers=headers)).json()['items']
    assert all(t['status'] == 'succeeded' for t in states)
    candidate = await get_candidate(client, headers, ids[0])
    assert candidate['evaluation']['market_metrics'] is None
    assert candidate['evaluation']['text_status'] == 'succeeded'
    assert (await review(client, headers, candidate)).status_code == 200
    assert (await review(client, headers, candidate)).json()['reused']
    await review(client, headers, candidate, 'favorite')
    reread = await get_candidate(client, headers, ids[0])
    assert reread['review_status'] == 'approved' and reread['favorite']
    history = (await client.get('/api/v1/sourcing/reviews', headers=headers)).json()
    assert history['total'] == 2
    assert all(x['evaluation_id'] == candidate['evaluation']['id'] and x['reviewer_id'] for x in history['items'])
    r = await client.patch('/api/v1/sourcing/candidates/' + ids[0], headers=headers, json={**DATA, 'name': '修改后的样本'})
    assert r.status_code == 200
    changed = await get_candidate(client, headers, ids[0])
    assert changed['version'] == 2 and changed['evaluation']['stale'] and changed['review_status'] == 'approved' and changed['favorite']
    assert (await review(client, headers, candidate)).status_code == 409
    assert (await client.get('/api/v1/products', headers=headers)).json()['total'] == 0


async def test_text_failure_retry_without_vision_and_new_id(client, headers):
    id = await create(client, headers)
    task = (await submit(client, headers, [id]))[0]
    await force_text_configuration([task['id']])
    w = worker()
    FixtureText.error = AnalysisError('upstream_401', '模型凭证无效')
    assert await w.process_one()
    failed = (await client.get('/api/v1/sourcing/tasks/' + task['id'], headers=headers)).json()
    assert failed['status'] == 'failed' and failed['partial_vision'] is None
    assert failed['evaluation'] is None
    r = await client.post('/api/v1/sourcing/tasks/' + task['id'] + '/retry', headers=headers)
    assert r.status_code == 202 and r.json()['id'] != task['id']
    FixtureText.error = None
    assert await w.process_one()
    assert FixtureVision.calls == 0 and FixtureText.calls == 2
    succeeded = await get_candidate(client, headers, id)
    assert succeeded['evaluation'] and not succeeded['evaluation']['stale']


async def test_claim_concurrency_expired_lease_and_attempt_bound(client, headers):
    id = await create(client, headers)
    t = (await submit(client, headers, [id]))[0]
    w = worker()
    claims = await asyncio.gather(w.claim(), w.claim())
    assert sum(x is not None for x in claims) == 1
    async with TestSessionLocal() as db:
        task = await db.get(SourcingTask, uuid.UUID(t['id']))
        task.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    await w.recover_expired()
    failed = (await client.get('/api/v1/sourcing/tasks/' + t['id'], headers=headers)).json()
    assert failed['status'] == 'failed' and failed['error_code'] == 'worker_interrupted'
    retry = await client.post('/api/v1/sourcing/tasks/' + t['id'] + '/retry', headers=headers)
    await force_text_configuration([retry.json()['id']])
    FixtureText.error = AnalysisError('upstream_429', '限流', retryable=True)
    for attempt in range(3):
        assert await w.process_one()
        async with TestSessionLocal() as db:
            task = await db.get(SourcingTask, uuid.UUID(retry.json()['id']))
            task.next_attempt_at = None
            await db.commit()
    result = (await client.get('/api/v1/sourcing/tasks/' + retry.json()['id'], headers=headers)).json()
    assert result['status'] == 'failed' and result['attempts'] == 3


async def test_owner_isolation_and_missing_provider_no_score(client, headers):
    id = await create(client, headers)
    r = await client.post('/api/v1/auth/register', json={'username': 'other@example.com', 'password': 'securepass123', 'nickname': '另一个用户'})
    other = {'Authorization': 'Bearer ' + r.json()['access_token']}
    assert (await client.get('/api/v1/sourcing/candidates/' + id, headers=other)).status_code == 404
    assert (await client.get('/api/v1/sourcing/candidates', headers=other)).json()['total'] == 0
    assert (await client.get('/api/v1/sourcing/providers/status')).status_code == 403
    status = (await client.get('/api/v1/sourcing/providers/status', headers=headers)).json()
    assert 'api_key' not in json.dumps(status).lower()
    task = (await submit(client, headers, [id]))[0]
    w = SourcingWorker(TestSessionLocal, SourcingSettings(_env_file=None, BAILIAN_API_KEY='', DEEPSEEK_API_KEY=''))
    assert await w.process_one()
    r = (await client.get('/api/v1/sourcing/tasks/' + task['id'], headers=headers)).json()
    assert r['status'] == 'failed' and r['error_code'] == 'provider_not_configured' and r['evaluation'] is None


async def test_input_edit_during_text_execution(client, headers):
    id = await create(client, headers)
    t = (await submit(client, headers, [id]))[0]
    await force_text_configuration([t['id']], False)
    w = worker()
    task = await w.claim()
    await client.patch('/api/v1/sourcing/candidates/' + id, headers=headers, json={**DATA, 'purchase_price': '14.00'})
    with pytest.raises(AnalysisError, match='修改'):
        await w.execute(task)
    second = (await submit(client, headers, [id]))[0]
    await force_text_configuration([second['id']], False)
    assert await w.process_one()
    candidate = await get_candidate(client, headers, id)
    assert candidate['evaluation']['text_status'] == 'succeeded' and candidate['evaluation']['visual_score'] is None


def test_strict_schema_and_image_private_address(monkeypatch):
    for changes in [{'visual_score': 101}, {'visual_score': '75'}, {'sales': 1000}, {'score_basis': []}]:
        with pytest.raises(ValidationError):
            VisionOutput.model_validate({**VISION, **changes})
    import socket
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('127.0.0.1', 443))])
    with pytest.raises(AnalysisError, match='私有网络'):
        fetch_image('https://example.com/a.jpg')


def test_dashscope_key_fallback_and_trusted_proxy_boundary(monkeypatch):
    s = SourcingSettings(_env_file=None, BAILIAN_API_KEY='', DASHSCOPE_API_KEY='TEST_FALLBACK_ONLY')
    assert s.bailian_api_key.get_secret_value() == 'TEST_FALLBACK_ONLY'
    from app.services.sourcing_providers import fetch_trusted_cdn_via_proxy
    for url in ['https://evil.cbu01.alicdn.com/private', 'https://127.0.0.1/private', 'https://cbu01.alicdn.com.evil.invalid/a.jpg']:
        with pytest.raises(AnalysisError):
            fetch_trusted_cdn_via_proxy(url, 'http://127.0.0.1:1')


async def test_provider_wire_validation_and_error_redaction(monkeypatch):
    real_client = httpx.AsyncClient
    async def handler(request):
        payload = json.loads(request.content)
        assert payload['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(VISION)}}], 'id': 'test-wire', 'usage': {'total_tokens': 1}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    provider = CompatibleProvider('TEST_ONLY', 'https://provider.invalid/v1', 'test', 5, 'test')
    assert (await provider.request('JSON', VisionOutput))['request_id'] == 'test-wire'
    async def invalid(request):
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"visual_score":999}'}}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(invalid)))
    with pytest.raises(AnalysisError, match='校验'):
        await provider.request('JSON', VisionOutput)
    async def unauthorized(request):
        return httpx.Response(401, text='DO_NOT_EXPOSE_TEST_SECRET')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(unauthorized)))
    with pytest.raises(AnalysisError) as error:
        await provider.request('JSON', VisionOutput)
    assert error.value.code == 'upstream_401' and 'SECRET' not in str(error.value)


async def test_miaoshou_signing_readonly_and_mapping(monkeypatch, client, headers):
    import hashlib, hmac
    real_client = httpx.AsyncClient
    async def handler(request):
        path = request.url.path
        timestamp = request.headers['x-timestamp']
        expected = hmac.new(b'TEST_SECRET', ('TEST_SECRET' + path + timestamp + 'TEST_KEY' + request.content.decode() + 'TEST_SECRET').encode(), hashlib.sha256).hexdigest()
        assert request.headers['x-sign'] == expected
        assert path.endswith('get_common_collect_box_list') or path.endswith('get_common_collect_box_detail')
        if path.endswith('_list'):
            data = {'detailList': [{'commonCollectBoxDetailId': 11, 'title': '测试授权商品'}], 'total': 1}
        else:
            data = {'editCommonCollectBoxDetail': {'title': '测试授权商品', 'price': 10, 'imgUrls': ['https://example.com/a.jpg'], 'sourceList': [{'sourceItemId': '123', 'sourceItemUrl': 'https://detail.1688.com/offer/123.html'}]}}
        return httpx.Response(200, json={'result': 'success', 'code': 'success', 'data': data})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    adapter = MiaoshouSourceAdapter(SourcingSettings(_env_file=None, miaoshou_app_key='TEST_KEY', miaoshou_app_secret='TEST_SECRET'))
    assert (await adapter.search(1, 20))['total'] == 1
    record = await adapter.detail('11')
    candidate = adapter.normalize(record, record['editCommonCollectBoxDetail']['sourceList'][0], 'TH', 'CNY')
    from app.services.sourcing_service import import_one
    from app.models.user import User
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User))
        result = await import_one(db, candidate, owner.id, 'miaoshou_api', {'common_collect_box_id': '11', 'source': record['editCommonCollectBoxDetail']['sourceList'][0]})
        await db.commit()
    reread = await get_candidate(client, headers, result['id'])
    assert reread['miaoshou_detail_id'] == '11' and reread['trust_status'] == 'authorized_account'
