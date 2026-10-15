"""PostgreSQL integration tests for the discovery agent.

Search hits, Miaoshou responses and model outputs below are labelled TEST fixtures. They exercise
the workflow, idempotency and recovery only; they are NOT real search, collection or model acceptance.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.discovery import DiscoveryResult, DiscoveryTask
from app.models.sourcing import MiaoshouSyncTask, SourcingCandidate, SourcingTask
from app.services.discovery.base import DiscoveryError, SearchHit, SearchPage, SourceSearchAdapter
from app.services.discovery.config import DiscoverySettings
from app.services.discovery.orchestrator import DiscoveryOrchestrator
from app.services.discovery.planner import SearchQueryPlanner
from app.services.discovery.scoring import DiscoveryScoringService
from app.services.miaoshou_sync_worker import MiaoshouSyncWorker
from app.services.sourcing_config import SourcingSettings
from tests.conftest import TestSessionLocal
from tests.test_miaoshou_integration import FixtureClient
from tests.test_sourcing import worker as analysis_worker

OFFER = '635021027818'  # same ID the Miaoshou fixture client maps to commonCollectBoxDetailId 42
OTHER = '700000000001'


class FixtureProvider:
    name = 'TEST_FIXTURE_SEARCH'

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def status(self):
        return {'name': self.name, 'available': True, 'reason': 'TEST_ONLY'}

    async def search(self, query, page=0, count=20):
        self.calls.append((query, page))
        if self.error:
            raise self.error
        return SearchPage(hits=[
            SearchHit(f'https://detail.1688.com/offer/{OFFER}.html', 'TEST_ONLY 收纳盒', '', 1, {'offer_id': OFFER, 'product_url': f'https://detail.1688.com/offer/{OFFER}.html', 'title': 'TEST_ONLY 收纳盒', 'price': {'min': 1.7}}),
            SearchHit(f'https://m.1688.com/offer/{OTHER}.html', 'TEST_ONLY 置物架', '', 2, {'offer_id': OTHER, 'product_url': f'https://detail.1688.com/offer/{OTHER}.html', 'title': 'TEST_ONLY 置物架', 'price': {'min': 1.7}}),
            SearchHit('https://s.1688.com/selloffer/offer_search.htm', 'TEST_ONLY 搜索页', '', 3),
            SearchHit('https://detail.1688.com/offer/700000000002.html', 'TEST_ONLY 二手收纳', '', 4),
        ], more_available=False, meta={'http_status': 200})


class FixtureAdapter(SourceSearchAdapter):
    source_platform = '1688'

    def status(self):
        return {'name': 'TEST_FIXTURE', 'available': True}

    def build_query(self, keyword, exclude_words):
        return f'site:detail.1688.com {keyword}'


class FixtureModel:
    """Stands in for DeepSeek planner/assessment requests; returns schema-valid TEST outputs."""
    calls = 0

    def __init__(self, kind):
        self.kind = kind

    async def request(self, content, schema, system=None, max_tokens=3500):
        type(self).calls += 1
        if self.kind == 'plan':
            output = {'keywords': [{'keyword': '厨房收纳', 'angle': '场景', 'rationale': 'TEST_ONLY'},
                                   {'keyword': '桌面整理', 'angle': '场景', 'rationale': 'TEST_ONLY'}], 'notes': []}
        else:
            dim = lambda s, l='low': {'score': s, 'level': l, 'explanation': 'TEST_ONLY', 'evidence': ['TEST_ONLY']}
            output = {'selling_points': ['TEST_ONLY'], 'short_video_potential': dim(70, 'medium'), 'market_fit': dim(60, 'medium'),
                      'homogeneity_risk': dim(50, 'medium'), 'ip_compliance_risk': dim(10), 'compliance_flags': [],
                      'summary': 'TEST_ONLY', 'limitations': ['无销量与市场数据']}
        schema.model_validate(output)
        return {'output': output, 'provider': 'TEST_FIXTURE', 'model': 'TEST_ONLY', 'request_id': 'fixture', 'usage': None}


def orchestrator(provider=None, **settings):
    FixtureModel.calls = 0
    provider = provider or FixtureProvider()
    s = DiscoverySettings(_env_file=None, discovery_poll_interval=1, **settings)
    o = DiscoveryOrchestrator(TestSessionLocal, s, SourcingSettings(_env_file=None), FixtureAdapter(provider),
                              SearchQueryPlanner(provider_factory=lambda: FixtureModel('plan')),
                              DiscoveryScoringService(provider_factory=lambda: FixtureModel('assess')))
    return o, provider


@pytest.fixture
async def headers(client):
    r = await client.post('/api/v1/auth/register', json={'username': 'discovery@example.com', 'password': 'securepass123', 'nickname': '发现测试'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def goal(**changes):
    return {'request_key': str(uuid.uuid4()), 'target_market': 'TH', 'category': '家居用品', 'price_min': '1.00',
            'price_max': '30.00', 'keywords': [], 'exclude_words': ['二手'], 'max_candidates': 30, **changes}


async def create(client, headers, **changes):
    r = await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json=goal(**changes))
    assert r.status_code == 202, r.text
    return r.json()


async def run_until_idle(o, rounds=10):
    for _ in range(rounds):
        async with TestSessionLocal() as db:
            await db.execute(DiscoveryTask.__table__.update().where(DiscoveryTask.next_run_at.is_not(None))
                             .values(next_run_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            await db.commit()
        if not await o.process_one():
            return


async def detail(client, headers, task_id):
    r = await client.get(f'/api/v1/sourcing/discovery/tasks/{task_id}', headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_task_creation_is_idempotent_and_auto_collect_gated(client, headers):
    data = goal()
    first = (await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json=data)).json()
    again = (await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json=data)).json()
    same_goal = (await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json={**data, 'request_key': str(uuid.uuid4())})).json()
    assert first['id'] == again['id'] == same_goal['id'] and again['reused'] and same_goal['reused']
    conflict = await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json={**data, 'category': '其他'})
    assert conflict.status_code == 409
    gated = await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json=goal(auto_collect=True))
    assert gated.status_code == 422 and '人工勾选' in gated.json()['detail']
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DiscoveryTask)) == 1
    cancelled = await client.post(f"/api/v1/sourcing/discovery/tasks/{first['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    o, provider = orchestrator()
    assert not await o.process_one() and provider.calls == []
    other = await client.post('/api/v1/auth/register', json={'username': 'd-other@example.com', 'password': 'securepass123', 'nickname': 'O'})
    other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get(f"/api/v1/sourcing/discovery/tasks/{first['id']}", headers=other_headers)).status_code == 404


async def test_full_flow_search_pool_text_analysis_without_collection(client, headers):
    task = await create(client, headers)
    o, provider = orchestrator()
    await run_until_idle(o, 1)
    d = await detail(client, headers, task['id'])
    assert d['status'] == 'analyzing'
    assert len(d['results']) == 2 and len(provider.calls) == 2
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MiaoshouSyncTask)) == 0
        assert await db.scalar(select(func.count()).select_from(SourcingCandidate)) == 2
    ai = analysis_worker()
    assert await ai.process_one() and await ai.process_one()
    await run_until_idle(o, 1)
    d = await detail(client, headers, task['id'])
    assert d['status'] == 'completed' and d['usage']['model_calls'] == 3
    assert all(r['status'] == 'analyzed' and r['rank_score'] is None for r in d['results'])
    second = await create(client, headers, category='其他收纳')
    await run_until_idle(o, 1)
    d2 = await detail(client, headers, second['id'])
    assert d2['status'] == 'completed' and d2['usage']['model_calls'] == 1
    assert all(r['prior_candidate_id'] for r in d2['results'])
    assert d2['collect_task'] is None
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SourcingCandidate)) == 2
        assert await db.scalar(select(func.count()).select_from(SourcingTask)) == 2


async def test_restart_resumes_without_repeating_finished_searches(client, headers):
    task = await create(client, headers)
    o, provider = orchestrator()
    claimed = await o.claim()
    await o.stage_planning(claimed)
    # Simulate a crash after planning: the lease expires while the task is mid-flight.
    async with TestSessionLocal() as db:
        row = await db.get(DiscoveryTask, uuid.UUID(task['id']))
        assert row.status == 'searching' and row.plan
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    await o.recover_expired()
    calls_before = FixtureModel.calls
    await run_until_idle(o)
    d = await detail(client, headers, task['id'])
    assert d['status'] == 'analyzing' and FixtureModel.calls == calls_before  # plan was not regenerated
    assert len(provider.calls) == 2 and any(e['code'] == 'worker_interrupted' for e in d['stage_errors'])
    # Running again does not search again.
    await run_until_idle(o)
    assert len(provider.calls) == 2


async def test_search_budget_and_unconfigured_source_are_reported(client, headers):
    task = await create(client, headers)
    async with TestSessionLocal() as db:
        row = await db.get(DiscoveryTask, uuid.UUID(task['id']))
        row.budget = {**row.budget, 'search_calls': 1}
        await db.commit()
    o, provider = orchestrator()
    await run_until_idle(o)
    d = await detail(client, headers, task['id'])
    assert d['status'] == 'analyzing' and d['usage']['search_calls'] == 1
    assert [e['state'] for e in d['search_log']] == ['done', 'skipped_budget']
    blocked = await create(client, headers, category='厨房')
    o2, _ = orchestrator(FixtureProvider(error=DiscoveryError('not_configured', 'TEST 未配置', 'configuration')))
    await run_until_idle(o2)
    d = await detail(client, headers, blocked['id'])
    assert d['status'] == 'failed' and '未伪造' in d['progress_message']
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DiscoveryResult).where(DiscoveryResult.task_id == uuid.UUID(blocked['id']))) == 0


async def test_price_outside_goal_is_filtered_before_model_cost(client, headers):
    task = await create(client, headers, price_min='10.00', price_max='20.00')  # fixture SPU price is 1.7 CNY
    o, _ = orchestrator()
    await run_until_idle(o)
    d = await detail(client, headers, task['id'])
    row = {x['source_item_id']: x for x in d['results']}[OFFER]
    assert row['status'] == 'price_filtered' and '不在设定区间' in row['status_reason']
    assert d['status'] == 'completed' and d['usage']['model_calls'] == 1
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SourcingTask)) == 0


async def test_snippets_are_purged_after_retention(client, headers):
    task = await create(client, headers)
    o, _ = orchestrator()
    await run_until_idle(o)
    async with TestSessionLocal() as db:
        await db.execute(DiscoveryResult.__table__.update().values(snippet_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await db.commit()
    assert all(r['snippet_title'] is None for r in (await detail(client, headers, task['id']))['results'])
    await o.purge_snippets()
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DiscoveryResult).where(DiscoveryResult.snippet_title.is_not(None))) == 0
        assert await db.scalar(select(func.count()).select_from(DiscoveryResult)) == 2  # IDs and links remain
