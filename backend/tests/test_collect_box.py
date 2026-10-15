"""我的采集箱与妙手同步；上游数据为标注的测试样本。"""
import uuid

import pytest
from app.clients.miaoshou_client import TK_LIST, CLAIM
from app.models.sourcing import MiaoshouSyncTask
from app.models.collect_box import CollectBoxItem
from tests.conftest import TestSessionLocal
from tests.test_miaoshou_integration import DETAIL_DATA, FixtureClient, response, worker

ROOT = '/api/v1/collect-box'
LINK = 'https://detail.1688.com/offer/635021027818.html'


class TiktokFixtureClient(FixtureClient):
    """认领后 TikTok 采集箱是否立即可查由 visible 控制，用于验证不重复认领。"""
    def __init__(self, visible=True):
        super().__init__()
        self.claims, self.claimed, self.visible = 0, False, visible

    async def claim_to_platform(self, detail_ids, platform='tiktok'):
        self.claims += 1
        self.claimed = True
        return response({'platformCollectBoxDetailIdMap': {'tiktok': {'9001': 77}}}, CLAIM)

    async def get_tiktok_list(self, **kwargs):
        rows = [{'collectBoxDetailId': 77, 'commonCollectBoxDetailId': 42, 'title': 'UNIT_ONLY'}] if self.claimed and self.visible else []
        return response({'detailList': rows}, TK_LIST)


@pytest.fixture
async def headers(client, monkeypatch):
    monkeypatch.setattr('app.clients.miaoshou_client.MiaoshouClient.configured', property(lambda self: True))
    r = await client.post('/api/v1/auth/register', json={'username': 'box@example.com', 'password': 'securepass123', 'nickname': 'TEST'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


async def boxed_item(client, headers):
    r = await client.post('/api/v1/sourcing/candidates', headers=headers,
                          json={'product_url': LINK, 'name': 'TEST 衣架', 'target_market': 'MY'})
    assert r.status_code == 201, r.text
    candidate_id = r.json()['id']
    added = await client.post(ROOT + '/items', headers=headers, json={'candidate_ids': [candidate_id, candidate_id]})
    assert added.status_code == 201 and added.json()['added'] == 1
    again = await client.post(ROOT + '/items', headers=headers, json={'candidate_ids': [candidate_id]})
    assert again.json() == {'added': 0, 'skipped': 1, 'items': []}
    listed = (await client.get('/api/v1/sourcing/candidates', headers=headers)).json()['items'][0]
    assert listed['in_collect_box'] and listed['review_status'] == 'approved'
    return (await client.get(ROOT + '/items', headers=headers, params={'target_market': 'MY'})).json()['items'][0]


async def sync(client, headers, item, box):
    # Historical task linkage remains readable after retiring the direct-sync entrypoint.
    r = await client.post('/api/v1/sourcing/miaoshou/collect', headers=headers,
                         json={'request_key': str(uuid.uuid4()), 'links': [item['product_url']],
                               'target_market': item['target_market'], 'currency': 'CNY',
                               'claim_platform': 'tiktok' if box == 'tiktok' else None})
    assert r.status_code == 202, r.text
    async with TestSessionLocal() as db:
        row = await db.get(CollectBoxItem, uuid.UUID(item['id']))
        row.sync_task_id, row.sync_status, row.miaoshou_box = uuid.UUID(r.json()['id']), 'syncing', box
        await db.commit()
    return r.json()


async def test_direct_sync_now_requires_workbench(client, headers):
    item = await boxed_item(client, headers)
    r = await client.post(ROOT + '/sync', headers=headers,
                          json={'request_key': str(uuid.uuid4()), 'ids': [item['id']], 'box': 'tiktok'})
    assert r.status_code == 409 and '工作台' in r.json()['detail']['message']


async def test_sync_common_box_marks_synced_after_platform_confirms(client, headers):
    item = await boxed_item(client, headers)
    assert item['sync_status'] == 'not_synced'
    upstream = FixtureClient()
    await sync(client, headers, item, 'common')
    syncing = (await client.get(ROOT + '/items', headers=headers)).json()['items'][0]
    assert syncing['sync_status'] == 'syncing'
    assert await worker(upstream).process_one()
    done = (await client.get(ROOT + '/items', headers=headers)).json()
    assert done['items'][0]['sync_status'] == 'synced' and done['items'][0]['miaoshou_detail_id'] == '42'
    assert done['items'][0]['miaoshou_box'] == 'common' and done['counts'] == {'synced': 1}
    assert upstream.writes == 1


async def test_sync_tiktok_box_claims_once_and_requires_list_confirmation(client, headers):
    item = await boxed_item(client, headers)
    upstream = TiktokFixtureClient(visible=False)
    w = worker(upstream)
    job = await sync(client, headers, item, 'tiktok')
    await w.process_one()
    pending = (await client.get(ROOT + '/items', headers=headers)).json()['items'][0]
    assert pending['sync_status'] == 'syncing' and upstream.claims == 1
    # 认领已提交但列表未确认：下一轮只查询，不重复认领
    upstream.visible = True
    async with TestSessionLocal() as db:
        task = await db.get(MiaoshouSyncTask, uuid.UUID(job['id']))
        assert task.status == 'waiting'
        task.next_poll_at = None
        await db.commit()
    await w.process_one()
    done = (await client.get(ROOT + '/items', headers=headers)).json()['items'][0]
    assert done['sync_status'] == 'synced' and done['miaoshou_detail_id'] == '77' and done['miaoshou_box'] == 'tiktok'
    assert upstream.claims == 1 and upstream.writes == 1


async def test_remove_only_local_and_blocks_syncing(client, headers):
    item = await boxed_item(client, headers)
    await sync(client, headers, item, 'common')
    blocked = await client.post(ROOT + '/items/remove', headers=headers, json={'ids': [item['id']]})
    assert blocked.status_code == 409
    await worker(FixtureClient()).process_one()
    removed = await client.post(ROOT + '/items/remove', headers=headers, json={'ids': [item['id']]})
    assert removed.json() == {'removed': 1}
    assert (await client.get(ROOT + '/items', headers=headers)).json()['total'] == 0
    assert DETAIL_DATA['commonCollectBoxDetailId'] == 42
