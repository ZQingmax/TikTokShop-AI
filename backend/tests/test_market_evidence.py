"""Isolated PostgreSQL regression tests. All external responses are TEST fixtures."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from tests.conftest import TestSessionLocal
from app.models.sourcing import MarketReport, SourcingCandidate, SourcingReview, SourcingTask, MiaoshouSyncTask
from app.models.discovery import DiscoveryTask
from app.services.discovery.base import SearchHit, SearchPage, SourceSearchAdapter
from app.services.discovery.orchestrator import DiscoveryOrchestrator
from app.services.discovery.config import DiscoverySettings
from app.services.sourcing_worker import SourcingWorker
from app.services.sourcing_config import SourcingSettings

ROOT = '/api/v1/sourcing'
OFFER = '635021027818'
LINK = f'https://detail.1688.com/offer/{OFFER}.html'
REPORT = {'name': 'TEST 榜单', 'format': 'csv', 'scope': 'market', 'target_market': 'MY',
    'content': 'name,source_platform,source_url,observed_on,target_market,rank\nTEST 收纳盒,TEST榜单,https://example.com/p,2026-10-13,MY,1\n'}


@pytest.fixture
async def headers(client):
    r = await client.post('/api/v1/auth/register', json={'username': 'evidence@example.com', 'password': 'securepass123', 'nickname': 'TEST'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


async def candidate(client, headers, **changes):
    r = await client.post(ROOT + '/candidates', headers=headers,
        json={'product_url': LINK, 'name': 'TEST 收纳盒', **changes})
    assert r.status_code == 201, r.text
    return (await client.get(ROOT + '/candidates/' + r.json()['id'], headers=headers)).json()


async def test_preview_import_and_owner_isolation(client, headers):
    r = await client.post(ROOT + '/market-reports/preview', headers=headers, json=REPORT)
    assert r.status_code == 200 and r.json()['rows'][0]['sales'] is None
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MarketReport)) == 0
    r = await client.post(ROOT + '/market-reports', headers=headers, json=REPORT)
    again = await client.post(ROOT + '/market-reports', headers=headers, json=REPORT)
    assert r.json()['id'] == again.json()['id'] and again.json()['reused']
    other = await client.post('/api/v1/auth/register', json={'username': 'other@example.com', 'password': 'securepass123', 'nickname': 'TEST'})
    other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get(ROOT + '/market-reports', headers=other_headers)).json()['total'] == 0
    task = await client.post(ROOT + '/discovery/tasks', headers=other_headers, json={'request_key': str(uuid.uuid4()),
        'category': '收纳', 'report_id': r.json()['id'], 'report_rows': [2]})
    assert task.status_code == 422


async def test_no_visual_required_decision_versions_and_collect_idempotency(client, headers, monkeypatch):
    from app.clients.miaoshou_client import MiaoshouClient
    monkeypatch.setattr(MiaoshouClient, 'configured', property(lambda self: True))
    c = await candidate(client, headers)
    assert c['target_market'] == 'MY' and c['evaluation'] is None
    assert (await client.post(ROOT + f'/candidates/{c["id"]}/review', headers=headers,
        json={'input_version': c['version'], 'action': 'favorite'})).status_code == 200
    payload = {'request_key': str(uuid.uuid4()), 'candidates': [{'id': c['id'], 'version': c['version']}]}
    r = await client.post(ROOT + '/candidates/collect', headers=headers, json=payload)
    assert r.status_code == 202, r.text
    again = await client.post(ROOT + '/candidates/collect', headers=headers, json=payload)
    assert again.status_code == 202 and again.json()['id'] == r.json()['id']
    listed = (await client.get(ROOT + '/candidates', headers=headers)).json()['items'][0]
    assert listed['collection']['status'] == 'queued' and listed['favorite']
    async with TestSessionLocal() as db:
        reviews = (await db.scalars(select(SourcingReview).where(SourcingReview.action == 'approve'))).all()
        assert len(reviews) == 1 and reviews[0].evaluation_id is None
        assert reviews[0].input_snapshot['name'] == 'TEST 收纳盒'
    stale = {**payload, 'request_key': str(uuid.uuid4()), 'candidates': [{'id': c['id'], 'version': 99}]}
    assert (await client.post(ROOT + '/candidates/collect', headers=headers, json=stale)).status_code == 409
    c2 = await candidate(client, headers, product_url='https://detail.1688.com/offer/700000000001.html')
    overlap = {**payload, 'request_key': str(uuid.uuid4()), 'candidates': payload['candidates'] + [{'id': c2['id'], 'version': c2['version']}]}
    assert (await client.post(ROOT + '/candidates/collect', headers=headers, json=overlap)).status_code == 409


class FixtureProvider:
    name = 'TEST'
    async def search(self, *args):
        return SearchPage([SearchHit(LINK, 'TEST 收纳盒', '', 1, {'offer_id': OFFER, 'product_url': LINK,
            'title': 'TEST 收纳盒', 'price': {'min': '8.50', 'max': '10'}, 'images': []})], False)


class FixtureAdapter(SourceSearchAdapter):
    def status(self): return {'available': True}
    def build_query(self, keyword, exclude): return keyword


class FixturePlanner:
    async def plan(self, goal, limit):
        assert goal.get('workflow_version') == 2
        return {'keywords': [{'keyword': '收纳盒', 'rationale': 'TEST'}]}


class FixtureEvidence:
    calls = 0
    def __init__(self, *args): pass
    async def analyze(self, snapshot):
        type(self).calls += 1
        return {'output': {'market_basis': [{'evidence_id': e['evidence_id'], 'reason': 'TEST 来源相关'} for e in snapshot.get('market_evidence', [])],
            'matching_facts': ['TEST 用途相符'], 'differences': ['尺寸未知'], 'recommendation_reasons': ['TEST 进一步核实'],
            'information_gaps': ['运费、资质未知'], 'limitations': ['无增长或利润结论']}, 'provider': 'TEST'}


async def test_discovery_persists_before_collection_and_text_only(client, headers, monkeypatch):
    monkeypatch.setattr('app.services.market_evidence.EvidenceProvider', FixtureEvidence)
    report = (await client.post(ROOT + '/market-reports', headers=headers, json=REPORT)).json()
    r = await client.post(ROOT + '/discovery/tasks', headers=headers, json={'request_key': str(uuid.uuid4()),
        'category': '收纳', 'report_id': report['id'], 'report_rows': [2], 'price_max': 20})
    assert r.status_code == 202, r.text
    o = DiscoveryOrchestrator(TestSessionLocal, DiscoverySettings(_env_file=None),
        adapter=FixtureAdapter(FixtureProvider()), planner=FixturePlanner())
    assert await o.process_one()
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MiaoshouSyncTask)) == 0
        c = await db.scalar(select(SourcingCandidate))
        assert c.market_evidence[0]['rank'] == 1 and c.purchase_price == 8.5
        assert c.main_image is None  # no image needed for text analysis
    def forbidden(*args): raise AssertionError('No image model may be constructed')
    w = SourcingWorker(TestSessionLocal, SourcingSettings(_env_file=None), vision_factory=forbidden)
    assert await w.process_one()
    async with TestSessionLocal() as db, db.begin():
        t = await db.get(DiscoveryTask, uuid.UUID(r.json()['id']))
        t.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await o.process_one()
    result = (await client.get(ROOT + '/candidates', headers=headers)).json()['items'][0]
    assert result['evaluation']['visual_score'] is None and result['evaluation']['vision'] is None
    assert result['evaluation']['text_analysis']['market_basis'][0]['evidence_id'].startswith(report['id'])
    assert result['collection'] is None
    task = (await client.get(ROOT + '/discovery/tasks/' + r.json()['id'], headers=headers)).json()
    assert task['status'] == 'completed' and task['results'][0]['rank_score'] is None
    assert (await client.post(ROOT + '/discovery/tasks', headers=headers, json={'request_key': str(uuid.uuid4()),
        'category': '收纳', 'auto_collect': True})).status_code == 422


async def test_excluded_decision_survives_edits(client, headers):
    c = await candidate(client, headers)
    r = await client.patch(ROOT + f'/candidates/{c["id"]}/operations', headers=headers,
        json={'review_status': 'rejected', 'input_version': c['version'], 'favorite': True, 'operator_note': 'TEST保留'})
    assert r.status_code == 200
    r = await client.patch(ROOT + f'/candidates/{c["id"]}', headers=headers,
        json={'product_url': LINK, 'name': 'TEST 改名'})
    assert r.status_code == 200
    assert r.json()['review_status'] == 'rejected' and r.json()['favorite'] and r.json()['operator_note'] == 'TEST保留'
