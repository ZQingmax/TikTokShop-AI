"""Isolated DB tests; external browser data are explicit TEST fixtures."""
import uuid
import pytest
from sqlalchemy import select, text
from tests.conftest import TestSessionLocal, test_engine
from app.models.fastmoss import FastmossTask
from app.services.fastmoss.worker import Worker
from app.services.fastmoss.browser import BrowserError
from app.services.fastmoss.locking import browser_lock

ROOT = '/api/v1/sourcing/fastmoss'
CATS = [{'id': '1', 'name': '收纳', 'parent_id': None, 'path': ['收纳'], 'household': True},
        {'id': '2', 'name': '清洁', 'parent_id': None, 'path': ['清洁'], 'household': True}]
RAW = {'product_name': 'TEST 收纳盒', 'country': '马来西亚', 'price': 'RM 12.50', 'rank': '1',
       'sales_period': '1.2万', 'source_url': 'https://www.fastmoss.com/zh/e-commerce/sales',
       'product_url': 'https://www.fastmoss.com/zh/e-commerce/detail/123'}


@pytest.fixture
async def headers(client, monkeypatch):
    monkeypatch.setattr('app.api.v1.fastmoss.engine', test_engine)
    monkeypatch.setattr('app.api.v1.fastmoss.load_catalog', lambda m: CATS)
    monkeypatch.setattr('app.api.v1.fastmoss.Browser.status', lambda s: {'ready': True, 'message': 'TEST'})
    r = await client.post('/api/v1/auth/register', json={'username': 'fastmoss@example.com', 'password': 'securepass123', 'nickname': 'TEST'})
    headers = {'Authorization': 'Bearer ' + r.json()['access_token']}
    assert (await client.post(ROOT + '/categories/refresh', headers=headers)).status_code == 200
    return headers


async def create(client, headers, **changes):
    payload = dict(request_key=str(uuid.uuid4()), category_ids=['1'], target_market='MY', pages=3)
    payload.update(changes)
    r = await client.post(ROOT + '/tasks', headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json(), payload


class FixtureBrowser:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def catalog(self, market): return CATS
    def scrape(self, market, cat, pages):
        if cat['id'] == '2': raise BrowserError('TEST permission denied')
        return [RAW, RAW]


async def test_end_to_end_partial_report_csv_and_discovery(client, headers):
    job, _ = await create(client, headers, category_ids=['1', '2'])
    worker = Worker(TestSessionLocal, test_engine, FixtureBrowser)
    assert await worker.process_one()
    task = (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()
    assert task['status'] == 'partial' and task['row_count'] == 1
    report = (await client.get('/api/v1/sourcing/market-reports/' + task['report_id'], headers=headers)).json()
    assert report['rows'][0]['observed_on'] is None and report['rows'][0]['sales'] == 12000
    csv = await client.get(ROOT + '/tasks/' + job['id'] + '/csv', headers=headers)
    assert csv.status_code == 200 and 'TEST 收纳盒' in csv.text and csv.content.startswith(b'\xef\xbb\xbf')
    discovery = await client.post('/api/v1/sourcing/discovery/tasks', headers=headers, json={
        'request_key': str(uuid.uuid4()), 'category': '收纳', 'report_id': task['report_id'], 'report_rows': [2]})
    assert discovery.status_code == 202, discovery.text
    assert not await worker.process_one()


async def test_idempotency_validation_and_isolation(client, headers):
    job, payload = await create(client, headers)
    again = await client.post(ROOT + '/tasks', headers=headers, json=payload)
    assert again.json()['id'] == job['id']
    conflict = await client.post(ROOT + '/tasks', headers=headers, json={**payload, 'pages': 4})
    assert conflict.status_code == 409
    stale = await client.post(ROOT + '/tasks', headers=headers, json={**payload, 'request_key': str(uuid.uuid4()), 'category_ids': ['missing']})
    assert stale.status_code == 422
    other = await client.post('/api/v1/auth/register', json={'username': 'otherfm@example.com', 'password': 'securepass123', 'nickname': 'TEST'})
    other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get(ROOT + '/tasks/' + job['id'], headers=other_headers)).status_code == 404
    assert (await client.get(ROOT + '/tasks/' + job['id'] + '/csv', headers=other_headers)).status_code == 404
    assert (await client.get(ROOT + '/tasks', headers=other_headers)).json()['total'] == 0


async def test_browser_serialization_and_interruption(client, headers):
    job, _ = await create(client, headers)
    worker = Worker(TestSessionLocal, test_engine, FixtureBrowser)
    async with browser_lock(test_engine) as connection:
        assert connection is not None
        assert not await worker.process_one()
        assert (await client.post(ROOT + '/categories/refresh', headers=headers)).status_code == 409
    async with TestSessionLocal() as db, db.begin():
        task = await db.get(FastmossTask, uuid.UUID(job['id']))
        task.status = 'running'
    assert not await worker.process_one()
    task = (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()
    assert task['status'] == 'failed' and '中断' in task['error']


async def test_changed_catalog_and_timeout_never_publish_report(client, headers):
    class Changed(FixtureBrowser):
        def catalog(self, market): return [{**CATS[0], 'path': ['已变化分类']}]
        def scrape(self, *a): raise AssertionError('stale categories must not be scraped')
    job, _ = await create(client, headers)
    await Worker(TestSessionLocal, test_engine, Changed).process_one()
    failed = (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()
    assert failed['status'] == 'failed' and failed['report_id'] is None
    assert '分类已变化' in failed['category_results'][0]['error']
    class Timeout(FixtureBrowser):
        def scrape(self, *a): raise BrowserError('BrowserSkill 操作超时')
    job, _ = await create(client, headers)
    await Worker(TestSessionLocal, test_engine, Timeout).process_one()
    failed = (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()
    assert failed['status'] == 'failed' and failed['report_id'] is None


async def test_limit_preserves_raw_rows_and_warns(client, headers):
    class Large(FixtureBrowser):
        def scrape(self, *a):
            return [{**RAW, 'product_url': f'https://www.fastmoss.com/zh/e-commerce/detail/{i}',
                     'product_name': f'TEST 收纳盒 {i}'} for i in range(501)]
    job, _ = await create(client, headers)
    await Worker(TestSessionLocal, test_engine, Large).process_one()
    result = (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()
    assert result['row_count'] == 500 and result['truncated']
    assert result['status'] == 'succeeded'
