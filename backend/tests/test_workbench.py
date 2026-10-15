"""Persistent workbench tests. All upstream values are labelled fixtures."""
import copy
import io
import uuid
from datetime import timedelta
import pytest
from PIL import Image
from sqlalchemy import select
from app.models.workbench import WorkbenchDraft as Draft, WorkbenchTask as Task, WorkbenchAsset as Asset
from app.models.user import User
from app.services.workbench_config import WorkbenchSettings
from app.services.workbench_worker import WorkbenchWorker
from app.services.sourcing_providers import AnalysisError, image_result
from app.clients.miaoshou_client import MiaoshouError
from app.services import workbench_service as service
from tests.conftest import TestSessionLocal
from tests.test_collect_box import TiktokFixtureClient, boxed_item
from tests.test_miaoshou_integration import response, worker as collector

ROOT = '/api/v1/product-workbench'
IMAGE = 'https://example.com/source.png'
TITLE = 'UNIT_ONLY Durable household storage rack'


class Upstream(TiktokFixtureClient):
    configured = True
    def __init__(self):
        super().__init__()
        self.remote, self.claimed_shops, self.saves, self.uploads, self.md5 = {}, [], 0, 0, 'fixture-v1'
        self.lose_save_response = False
        self.transfer_error = False
        self.wrong_readback = False
        self.reject_saves = 0

    async def get_shops(self, platform, site, page=1, page_size=100):
        return response({'shopList': [{'shopId': 99, 'site': 'MY', 'platform': 'tiktok', 'platformShopName': 'UNIT_ONLY'}]})

    async def get_categories(self, site):
        return response({'cateTree': {'7': {'cid': 7, 'name': 'UNIT_ONLY', 'isLastLevel': '1', 'disabled': False}}})

    async def get_category_metadata(self, site, cid, shop_id):
        return response({'categoryMetadata': {'categoryConfig': {}, 'categoryProductAttrList': [], 'categorySaleAttrList': []}})

    async def get_warehouses(self, shop_id):
        return response({'shopWarehouseList': [{'shopId': 99, 'warehouseList': [{'warehouseId': '8', 'warehouseName': 'UNIT_ONLY', 'warehouseEffectStatus': '1'}]}]})

    async def get_shop_detail(self, detail_id, shop_id):
        return response({'ossMd5': self.md5, 'shopCollectItemInfo': copy.deepcopy(self.remote), 'claimToShopIds': self.claimed_shops})

    async def claim_to_shop(self, detail_id, shop_id):
        self.claimed_shops = [shop_id]
        return response({})

    async def save_shop_detail(self, detail_id, shop_id, md5, content):
        assert md5 == self.md5
        if self.reject_saves:
            self.reject_saves -= 1
            raise MiaoshouError('fail', 'platform', '妙手拒绝了请求（fail）：UNIT_ONLY 规格值不合法')
        self.saves += 1
        self.remote = copy.deepcopy(content)
        self.md5 = 'fixture-v' + str(self.saves + 1)
        if self.wrong_readback:
            self.remote['title'] = 'UNIT_ONLY different platform title'
        if self.lose_save_response:
            raise MiaoshouError('timeout', 'timeout', 'UNIT_ONLY lost acknowledgement', uncertain=True)
        return response({'ossMd5': self.md5})

    async def upload_picture(self, url):
        self.uploads += 1
        if self.transfer_error:
            raise MiaoshouError('permissionDenied', 'permission', 'UNIT_ONLY upload denied')
        return response({'picturePath': 'https://example.com/stable-' + str(self.uploads) + '.png', 'width': 32, 'height': 32})


class Provider:
    def __init__(self): self.calls, self.polls = 0, 0
    async def text(self, kind, snapshot, images=None):
        self.calls += 1
        output = {'title': TITLE, 'bullet_points': ['UNIT_ONLY observed feature'], 'notes': 'UNIT_ONLY source-grounded description'} if kind == 'copy' else {'blocks': [{'image_index': 0, 'text': 'UNIT_ONLY original text', 'image_url': IMAGE}]}
        return {'output': output, 'request_id': 'UNIT_REQUEST', 'model': 'UNIT_MODEL'}
    async def image(self, snapshot, images=None):
        self.calls += 1
        self.images = images
        return {'image_url': 'https://example.com/generated.png', 'request_id': 'UNIT_IMAGE', 'model': 'UNIT_MODEL'}
    async def translate_submit(self, snapshot, images=None):
        self.calls += 1
        return {'upstream_task_id': 'UNIT_TASK', 'request_id': 'UNIT_TRANSLATE', 'model': 'UNIT_MODEL'}
    async def translate_poll(self, snapshot, result):
        self.polls += 1
        return None if self.polls == 1 else {**result, 'image_url': 'https://example.com/translated.png'}
    async def fill(self, snapshot, context):
        self.calls += 1
        self.context = context
        return {'output': {'category': None, 'weight': {'value': .4, 'reason': 'UNIT_ONLY 估算'}, 'package': None,
                           'sku_weights': [], 'attributes': [], 'sale_specs': []}, 'model': 'UNIT_MODEL'}


@pytest.fixture
def upstream(monkeypatch):
    value = Upstream()
    monkeypatch.setattr('app.api.v1.workbench.MiaoshouClient', lambda: value)
    monkeypatch.setattr('app.clients.miaoshou_client.MiaoshouClient.configured', property(lambda self: True))
    return value


@pytest.fixture
async def headers(client, upstream):
    r = await client.post('/api/v1/auth/register', json={'username': 'workbench@example.com', 'password': 'securepass123', 'nickname': 'UNIT_ONLY'})
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    value = WorkbenchSettings(_env_file=None, BAILIAN_API_KEY='UNIT_KEY', workbench_asset_directory=str(tmp_path))
    monkeypatch.setattr('app.api.v1.workbench.WorkbenchSettings', lambda: value)
    return value


@pytest.fixture
def downloaded(monkeypatch):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buffer, format='PNG')
    def fetch(url, *_): return image_result(url, 'image/png', buffer.getvalue())
    monkeypatch.setattr('app.services.workbench_worker.fetch_image', fetch)


async def create_draft(client, headers, shop_id=None):
    item = await boxed_item(client, headers)
    r = await client.post(ROOT + '/drafts', headers=headers, json={'ids': [item['id']], 'shop_id': shop_id})
    assert r.status_code == 201, r.text
    return item, r.json()['items'][0]


async def save(client, headers, draft, **fields):
    content = {**draft['content'], **fields}
    r = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': draft['version'], 'shop_id': draft['shop_id'], 'language': draft['language'], 'content': content})
    assert r.status_code == 200, r.text
    return r.json()


async def ready(client, headers, draft):
    return await save(client, headers, draft, title=TITLE, notes='UNIT_ONLY factual description', imgUrls=[IMAGE], cid='7',
        weight=.2, packageLength=20, packageWidth=10, packageHeight=5,
        skuMap={';': {'itemNum': 'UNIT_SKU', 'price': 9.5, 'stock': 4, 'isDelete': '0', 'shopIdToWarehouseIdAndStockMap': {'99': {'8': 4}}}})


async def task(client, headers, draft, kind, **extra):
    r = await client.post(ROOT + '/drafts/' + draft['id'] + '/ai-tasks', headers=headers,
        json={'version': draft['version'], 'request_key': str(uuid.uuid4()), 'kind': kind, **extra})
    assert r.status_code == 202, r.text
    return r.json()


async def get_task(client, headers, job):
    return (await client.get(ROOT + '/tasks/' + job['id'], headers=headers)).json()


async def expedite(job):
    async with TestSessionLocal() as db:
        current = await db.get(Task, uuid.UUID(job['id']))
        current.next_poll_at = None
        await db.commit()


async def test_snapshot_dedupe_scope_version_and_remove(client, headers, settings):
    item, draft = await create_draft(client, headers)
    again = await client.post(ROOT + '/drafts', headers=headers, json={'ids': [item['id'], item['id']]})
    assert again.json()['items'][0]['id'] == draft['id']
    changed = await save(client, headers, draft, title=TITLE)
    conflict = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': draft['version'], 'shop_id': None, 'language': 'en', 'content': draft['content']})
    assert conflict.status_code == 409
    other = await client.post('/api/v1/auth/register', json={'username': 'other-workbench@example.com', 'password': 'securepass123', 'nickname': 'UNIT'})
    oh = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.get(ROOT + '/drafts/' + draft['id'], headers=oh)).status_code == 404
    assert (await client.post('/api/v1/collect-box/items/remove', headers=headers, json={'ids': [item['id']]})).status_code == 200
    persisted = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    assert persisted['collect_item_id'] is None and persisted['content']['title'] == TITLE
    assert persisted['source_snapshot']['name'] != changed['content']['title']


async def test_one_draft_per_source_with_editable_shop(client, headers, settings):
    item, draft = await create_draft(client, headers)
    assigned = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': draft['version'], 'shop_id': 99, 'language': 'en', 'content': draft['content']})
    assert assigned.status_code == 200 and assigned.json()['version'] == 2
    # Reopening the product, with or without a shop, always returns its single draft.
    for shop_id in (None, 99, 666):
        again = await client.post(ROOT + '/drafts', headers=headers, json={'ids': [item['id']], 'shop_id': shop_id})
        assert again.status_code == 201 and again.json()['items'][0]['id'] == draft['id']
    listed = (await client.get(ROOT + '/drafts', headers=headers)).json()
    assert listed['total'] == 1
    bad = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': 2, 'shop_id': 666, 'language': 'en', 'content': draft['content']})
    assert bad.status_code == 422
    cleared = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': 2, 'shop_id': None, 'language': 'en', 'content': draft['content']})
    assert cleared.status_code == 200 and cleared.json()['shop_id'] is None
    async with TestSessionLocal() as db:
        row = await db.get(Draft, uuid.UUID(draft['id']))
        row.synced_version = row.version
        await db.commit()
    locked = await client.patch(ROOT + '/drafts/' + draft['id'], headers=headers,
        json={'version': cleared.json()['version'], 'shop_id': 99, 'language': 'en', 'content': draft['content']})
    assert locked.status_code == 409


async def test_ai_ocr_copy_stale_adoption(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers)
    provider = Provider()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, provider)
    job = await task(client, headers, draft, 'copy')
    assert await w.process_one()
    changed = await save(client, headers, draft, notes='UNIT_ONLY manual edit')
    denied = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers, json={'version': changed['version']})
    assert denied.status_code == 409
    adopted = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers, json={'version': changed['version'], 'confirm_stale': True})
    assert adopted.status_code == 200 and adopted.json()['content']['title'] == TITLE
    newdraft = adopted.json()
    ocr = await task(client, headers, newdraft, 'ocr', image_urls=[IMAGE])
    await w.process_one()
    adopted = await client.post(ROOT + '/tasks/' + ocr['id'] + '/adopt', headers=headers, json={'version': newdraft['version']})
    assert adopted.json()['content']['recognized_text'][0]['image_url'] == IMAGE
    assert provider.calls == 2


async def test_historical_mixed_language_copy_cannot_be_adopted(client, headers, settings, upstream):
    _, draft = await create_draft(client, headers)
    class MixedProvider(Provider):
        async def text(self, kind, snapshot, images=None):
            return {'output': {'title': TITLE, 'bullet_points': ['UNIT_ONLY small 杂物'], 'notes': 'UNIT_ONLY facts'}}
    job = await task(client, headers, draft, 'copy')
    await WorkbenchWorker(TestSessionLocal, settings, upstream, MixedProvider()).process_one()
    r = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers, json={'version': draft['version']})
    assert r.status_code == 409
    unchanged = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    assert unchanged['version'] == draft['version']


async def test_task_idempotency_and_uncertain_model_requires_confirmation(client, headers, settings, upstream):
    _, draft = await create_draft(client, headers)
    payload = {'kind': 'copy', 'version': draft['version'], 'request_key': str(uuid.uuid4())}
    a = await client.post(ROOT + '/drafts/' + draft['id'] + '/ai-tasks', headers=headers, json=payload)
    b = await client.post(ROOT + '/drafts/' + draft['id'] + '/ai-tasks', headers=headers, json=payload)
    assert a.json()['id'] == b.json()['id'] and b.json()['reused']
    class LostProvider(Provider):
        async def text(self, kind, snapshot, images=None): raise AnalysisError('model_uncertain', 'UNIT_ONLY lost result')
    await WorkbenchWorker(TestSessionLocal, settings, upstream, LostProvider()).process_one()
    r = await client.post(ROOT + '/tasks/' + a.json()['id'] + '/retry', headers=headers, json={})
    assert r.status_code == 409
    r = await client.post(ROOT + '/tasks/' + a.json()['id'] + '/retry', headers=headers, json={'resubmit_model': True})
    assert r.status_code == 200
    await WorkbenchWorker(TestSessionLocal, settings, upstream, Provider()).process_one()
    assert (await get_task(client, headers, a.json()))['status'] == 'succeeded'


@pytest.mark.parametrize('kind', ['generate', 'edit', 'translate'])
async def test_images_are_cached_and_transferred_without_repeating_model(kind, client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers)
    provider = Provider()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, provider)
    job = await task(client, headers, draft, kind, prompt='UNIT_ONLY white backdrop', image_urls=[IMAGE] if kind != 'generate' else [])
    upstream.transfer_error = True
    await w.process_one()
    if kind == 'translate':
        await expedite(job)
        await w.process_one()
    failed = await get_task(client, headers, job)
    assert failed['status'] == 'failed'
    async with TestSessionLocal() as db:
        asset = await db.scalar(select(Asset))
        assert asset.local_name and asset.sha256 and asset.status == 'cached'
    upstream.transfer_error = False
    assert (await client.post(ROOT + '/tasks/' + job['id'] + '/retry', headers=headers, json={})).status_code == 200
    await w.process_one()
    completed = await get_task(client, headers, job)
    assert completed['status'] == 'succeeded' and provider.calls == 1
    assert completed['result']['width'] == 32
    file = await client.get(ROOT + '/assets/' + completed['result']['asset_id'] + '/file', headers=headers)
    assert file.status_code == 200 and file.headers['content-type'] == 'image/png'
    adopted = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers, json={'version': draft['version']})
    assert adopted.status_code == 200 and completed['result']['public_url'] in adopted.json()['content']['imgUrls']


async def test_edit_adopted_image_uses_local_copy_and_download_failures_skip_model(client, headers, settings, upstream, downloaded, monkeypatch):
    _, draft = await create_draft(client, headers)
    provider = Provider()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, provider)
    generated = await task(client, headers, draft, 'generate', prompt='UNIT_ONLY white backdrop')
    await w.process_one()
    stored = (await get_task(client, headers, generated))['result']['public_url']
    adopted = (await client.post(ROOT + '/tasks/' + generated['id'] + '/adopt', headers=headers, json={'version': draft['version']})).json()
    def offline(url, *_): raise AnalysisError('image_untrusted_host', 'UNIT_ONLY picture space unverifiable')
    monkeypatch.setattr('app.services.workbench_worker.fetch_image', offline)
    edit = await task(client, headers, adopted, 'edit', prompt='UNIT_ONLY softer light', image_urls=[stored])
    assert edit['operation'] == {'image_urls': [stored], 'prompt': 'UNIT_ONLY softer light', 'source_lang': 'auto'}
    await w.process_one()
    assert (await get_task(client, headers, edit))['status'] == 'succeeded'
    assert provider.images[0]['url'] == stored and provider.images[0]['data_url'].startswith('data:image/png;base64,')
    unknown = await task(client, headers, adopted, 'edit', prompt='UNIT_ONLY softer light', image_urls=['https://example.com/unknown.png'])
    calls = provider.calls
    await w.process_one()
    failed = await get_task(client, headers, unknown)
    assert failed['status'] == 'failed' and failed['error_code'] == 'image_untrusted_host'
    assert provider.calls == calls and 'model_started' not in failed['steps']


async def test_fill_suggestions_use_real_categories_and_are_never_adopted_wholesale(client, headers, settings, upstream):
    _, draft = await create_draft(client, headers, 99)
    before = (await client.get(ROOT + '/drafts/' + draft['id'] + '/suggestions', headers=headers)).json()
    assert before['ai'] is None and 'fields' in before['source'] and 'skus' in before['source']
    provider = Provider()
    job = await task(client, headers, draft, 'fill')
    await WorkbenchWorker(TestSessionLocal, settings, upstream, provider).process_one()
    assert (await get_task(client, headers, job))['status'] == 'succeeded' and provider.calls == 1
    # Without a chosen category the model only sees real leaf candidates from the platform tree.
    assert provider.context['rules'] == {} and all(c['cid'] == '7' for c in provider.context['categories'])
    after = (await client.get(ROOT + '/drafts/' + draft['id'] + '/suggestions', headers=headers)).json()
    assert after['ai']['task_id'] == job['id'] and after['ai']['weight']['value'] == .4 and after['ai']['cid'] == ''
    adopted = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers, json={'version': draft['version']})
    assert adopted.status_code == 409
    unchanged = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    assert unchanged['version'] == draft['version'] and unchanged['content']['weight'] == draft['content']['weight']


async def test_delete_task_record_rules(client, headers, settings, upstream):
    _, draft = await create_draft(client, headers)
    job = await task(client, headers, draft, 'copy')
    assert (await client.delete(ROOT + '/tasks/' + job['id'], headers=headers)).status_code == 409
    await WorkbenchWorker(TestSessionLocal, settings, upstream, Provider()).process_one()
    other = await client.post('/api/v1/auth/register', json={'username': 'delete-workbench@example.com', 'password': 'securepass123', 'nickname': 'UNIT'})
    oh = {'Authorization': 'Bearer ' + other.json()['access_token']}
    assert (await client.delete(ROOT + '/tasks/' + job['id'], headers=oh)).status_code == 404
    assert (await client.delete(ROOT + '/tasks/' + job['id'], headers=headers)).status_code == 200
    assert (await client.get(ROOT + '/drafts/' + draft['id'] + '/tasks', headers=headers)).json()['items'] == []
    unconfirmed = await task(client, headers, draft, 'copy')
    async with TestSessionLocal() as db:
        row = await db.get(Task, uuid.UUID(unconfirmed['id']))
        row.kind, row.status = 'sync', 'uncertain'
        await db.commit()
    assert (await client.delete(ROOT + '/tasks/' + unconfirmed['id'], headers=headers)).status_code == 409


async def test_translated_detail_image_replaces_in_place_and_description_syncs_as_html(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers)
    detail = 'https://example.com/detail-1.png'
    draft = await save(client, headers, draft, descImgUrls=[detail, 'https://example.com/detail-2.png'], notes='UNIT_ONLY text',
                       sourceAttributes=[{'name': '材质', 'value': 'PP'}])
    assert draft['content']['sourceAttributes'] == [{'name': '材质', 'value': 'PP'}]
    job = await task(client, headers, draft, 'translate', image_urls=[detail], source_lang='zh')
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    await w.process_one()
    await expedite(job)
    await w.process_one()
    done = await get_task(client, headers, job)
    assert done['status'] == 'succeeded' and done['result']['original_url'] == detail
    r = await client.post(ROOT + '/tasks/' + job['id'] + '/adopt', headers=headers,
                          json={'version': draft['version'], 'image_action': 'replace', 'replace_url': detail})
    assert r.status_code == 200, r.text
    content = r.json()['content']
    assert content['descImgUrls'] == [done['result']['public_url'], 'https://example.com/detail-2.png']
    assert detail not in content['imgUrls']
    html = service.description(content)
    assert html.startswith('<p>UNIT_ONLY text</p>') and html.count('<img src=') == 2


async def test_validation_and_source_to_shop_sync(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers, 99)
    missing = await client.post(ROOT + '/drafts/' + draft['id'] + '/check', headers=headers, json={'version': draft['version']})
    assert missing.status_code == 200 and not missing.json()['validation']['valid']
    draft = await ready(client, headers, draft)
    checked = await client.post(ROOT + '/drafts/' + draft['id'] + '/check', headers=headers, json={'version': draft['version']})
    assert checked.status_code == 200 and checked.json()['validation']['valid'], checked.text
    payload = {'version': draft['version'], 'request_key': str(uuid.uuid4())}
    r = await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json=payload)
    assert r.status_code == 202, r.text
    job = r.json()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    await w.process_one()  # creates a child collection task
    await collector(upstream).process_one()  # real collector state machine, fixture platform
    await expedite(job)
    await w.process_one()  # claims shop, then polls
    await expedite(job)
    await w.process_one()
    completed = await get_task(client, headers, job)
    assert completed['status'] == 'succeeded', completed
    assert completed['result']['readback_confirmed'] and upstream.saves == 1
    assert upstream.writes == 1 and upstream.claims == 1
    assert upstream.remote['imgUrls'] != [IMAGE]
    persisted = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    assert persisted['state'] == 'synced' and persisted['platform_detail_id'] == '77'
    replay = await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json=payload)
    assert replay.status_code == 202 and replay.json()['id'] == job['id']
    assert completed['result']['first_sync'] and completed['result']['skipped'] == []
    # Later edits update the same collect-box item; an edit made directly in Miaoshou blocks it
    # until the operator explicitly chooses to overwrite.
    changed = await save(client, headers, persisted, title=TITLE + ' updated')
    upstream.remote['title'] = 'UNIT_ONLY independent remote edit'
    second = await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json={'version': changed['version'], 'request_key': str(uuid.uuid4())})
    await w.process_one()
    assert (await get_task(client, headers, second.json()))['error_code'] == 'remote_conflict'
    assert upstream.saves == 1
    third = await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers,
                              json={'version': changed['version'], 'request_key': str(uuid.uuid4()), 'overwrite_remote': True})
    await w.process_one()
    updated = await get_task(client, headers, third.json())
    assert updated['status'] == 'succeeded' and not updated['result']['first_sync']
    assert upstream.saves == 2 and upstream.remote['title'] == TITLE + ' updated' and upstream.writes == 1


async def test_incomplete_draft_syncs_finished_fields_and_keeps_the_rest_in_miaoshou(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers, 99)
    draft = await save(client, headers, draft, title=TITLE, notes='UNIT_ONLY factual description', imgUrls=[IMAGE], weight=.2,
                       skuMap={';': {'itemNum': 'UNIT_SKU', 'price': None, 'stock': None, 'isDelete': '0', 'shopIdToWarehouseIdAndStockMap': {}}})
    async with TestSessionLocal() as db:
        row = await db.get(Draft, uuid.UUID(draft['id']))
        row.platform_detail_id, row.common_detail_id = '77', '42'
        await db.commit()
    upstream.claimed_shops = [99]
    upstream.remote = {'title': 'UNIT_ONLY miaoshou title', 'skuMap': {';': {'price': 12, 'stock': 3}}, 'cid': '5'}
    job = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers,
                             json={'version': draft['version'], 'request_key': str(uuid.uuid4())})).json()
    await WorkbenchWorker(TestSessionLocal, settings, upstream, Provider()).process_one()
    done = await get_task(client, headers, job)
    assert done['status'] == 'succeeded', done
    assert {'skuMap', 'skuPropertyList', 'cid', 'productAttributes', 'packageLength'} <= set(done['result']['skipped'])
    assert upstream.remote['title'] == TITLE and upstream.remote['weight'] == .2
    assert upstream.remote['skuMap'] == {';': {'price': 12, 'stock': 3}} and upstream.remote['cid'] == '5'


async def test_delete_draft_archives_it_and_reopening_the_product_starts_fresh(client, headers, settings, upstream):
    item, draft = await create_draft(client, headers)
    job = await task(client, headers, draft, 'copy')
    assert (await client.delete(ROOT + '/drafts/' + draft['id'], headers=headers)).status_code == 409
    await WorkbenchWorker(TestSessionLocal, settings, upstream, Provider()).process_one()
    assert (await client.delete(ROOT + '/drafts/' + draft['id'], headers=headers)).status_code == 200
    assert (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).status_code == 404
    assert (await client.get(ROOT + '/drafts', headers=headers)).json()['total'] == 0
    fresh = (await client.post(ROOT + '/drafts', headers=headers, json={'ids': [item['id']]})).json()['items'][0]
    assert fresh['id'] != draft['id']
    async with TestSessionLocal() as db:
        assert (await db.get(Draft, uuid.UUID(draft['id']))).archived_at is not None and await db.get(Task, uuid.UUID(job['id']))


async def test_lost_save_response_queries_without_repeating_write(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers, 99)
    draft = await ready(client, headers, draft)
    async with TestSessionLocal() as db:
        row = await db.get(Draft, uuid.UUID(draft['id']))
        row.platform_detail_id, row.common_detail_id = '77', '42'
        await db.commit()
    upstream.claimed_shops = [99]
    upstream.lose_save_response = True
    await client.post(ROOT + '/drafts/' + draft['id'] + '/check', headers=headers, json={'version': draft['version']})
    job = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json={'version': draft['version'], 'request_key': str(uuid.uuid4())})).json()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    await w.process_one()
    assert (await get_task(client, headers, job))['status'] == 'uncertain'
    assert (await client.post(ROOT + '/tasks/' + job['id'] + '/retry', headers=headers, json={})).status_code == 200
    await w.process_one()
    assert (await get_task(client, headers, job))['status'] == 'succeeded'
    assert upstream.saves == 1


async def test_rejected_save_fails_with_reason_and_unconfirmed_save_can_be_resubmitted(client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers, 99)
    draft = await ready(client, headers, draft)
    async with TestSessionLocal() as db:
        row = await db.get(Draft, uuid.UUID(draft['id']))
        row.platform_detail_id, row.common_detail_id = '77', '42'
        await db.commit()
    upstream.claimed_shops, upstream.reject_saves = [99], 1
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    job = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json={'version': draft['version'], 'request_key': str(uuid.uuid4())})).json()
    await w.process_one()
    rejected = await get_task(client, headers, job)
    # An explicit rejection is definite: failed with Miaoshou's reason, and a plain retry saves again.
    assert rejected['status'] == 'failed' and '规格值不合法' in rejected['error_message'] and 'save_started' not in rejected['steps']
    assert (await client.post(ROOT + '/tasks/' + job['id'] + '/retry', headers=headers, json={})).status_code == 200
    await w.process_one()
    assert (await get_task(client, headers, job))['status'] == 'succeeded' and upstream.saves == 1
    # An unconfirmed save (e.g. lost response, as in the original incident) can be re-sent on request.
    changed = await save(client, headers, (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json(), title=TITLE + ' again')
    upstream.lose_save_response = True
    second = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json={'version': changed['version'], 'request_key': str(uuid.uuid4())})).json()
    await w.process_one()
    assert (await get_task(client, headers, second))['status'] == 'uncertain'
    upstream.lose_save_response = False
    assert (await client.post(ROOT + '/tasks/' + second['id'] + '/retry', headers=headers, json={'resubmit_save': True})).status_code == 200
    await w.process_one()
    # The lost save had landed: recognised by readback, so nothing is written twice.
    assert (await get_task(client, headers, second))['status'] == 'succeeded' and upstream.saves == 2
    # A save that never landed (Miaoshou unchanged) is rebuilt and sent again on request.
    third_draft = await save(client, headers, (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json(), title=TITLE + ' third')
    upstream.reject_saves = 1
    third = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers, json={'version': third_draft['version'], 'request_key': str(uuid.uuid4())})).json()
    async with TestSessionLocal() as db:  # simulate the original incident: a rejection recorded as unconfirmed
        await w.process_one()
        row = await db.get(Task, uuid.UUID(third['id']))
        row.status, row.steps = 'uncertain', {**row.steps, 'save_started': True,
                                               'before_save': service.normalize_remote(upstream.remote), 'expected': {'title': 'UNIT_ONLY never applied'}}
        await db.commit()
    assert (await client.post(ROOT + '/tasks/' + third['id'] + '/retry', headers=headers, json={'resubmit_save': True})).status_code == 200
    await w.process_one()
    assert (await get_task(client, headers, third))['status'] == 'succeeded' and upstream.saves == 3 and upstream.remote['title'] == TITLE + ' third'


async def test_lease_recovery_preserves_model_result(client, headers, settings, upstream):
    _, draft = await create_draft(client, headers)
    job = await task(client, headers, draft, 'copy')
    async with TestSessionLocal() as db:
        row = await db.get(Task, uuid.UUID(job['id']))
        row.status, row.steps = 'running', {'model_started': True}
        row.lease_until, row.lease_token = service.now() - timedelta(seconds=1), uuid.uuid4()
        await db.commit()
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    await w.recover_expired()
    assert (await get_task(client, headers, job))['status'] == 'uncertain'
    assert not await w.process_one()


@pytest.mark.parametrize('wrong_readback', [False, True])
async def test_fixed_sync_version_and_mismatched_readback(wrong_readback, client, headers, settings, upstream, downloaded):
    _, draft = await create_draft(client, headers, 99)
    draft = await ready(client, headers, draft)
    async with TestSessionLocal() as db:
        row = await db.get(Draft, uuid.UUID(draft['id']))
        row.platform_detail_id, row.common_detail_id = '77', '42'
        await db.commit()
    upstream.claimed_shops, upstream.wrong_readback = [99], wrong_readback
    await client.post(ROOT + '/drafts/' + draft['id'] + '/check', headers=headers, json={'version': draft['version']})
    job = (await client.post(ROOT + '/drafts/' + draft['id'] + '/sync', headers=headers,
                           json={'version': draft['version'], 'request_key': str(uuid.uuid4())})).json()
    changed = await save(client, headers, draft, title=TITLE + ' later local edit')
    w = WorkbenchWorker(TestSessionLocal, settings, upstream, Provider())
    await w.process_one()
    if wrong_readback:
        await expedite(job)
        await w.process_one()
        assert (await get_task(client, headers, job))['status'] == 'failed'
    else:
        assert (await get_task(client, headers, job))['status'] == 'succeeded'
        assert upstream.remote['title'] == TITLE
    persisted = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    assert persisted['content']['title'] == changed['content']['title']
    assert persisted['state'] != 'synced'
    assert upstream.saves == 1
