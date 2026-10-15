"""System settings: password change, roles, per-scenario models and the model usage ledger.

Usage numbers below are labelled fixtures standing in for provider responses.
"""
import uuid

import httpx
import pytest
from sqlalchemy import select, update

from app.models.system_settings import ModelUsageLog
from app.models.user import User
from app.models.workbench import WorkbenchTask as Task
from app.services.sourcing_providers import AnalysisError, CompatibleProvider
from app.schemas.sourcing import TextOutput
from app.services.workbench_worker import WorkbenchWorker
from tests.conftest import TestSessionLocal
from tests.test_workbench import ROOT, Provider, create_draft, headers, settings, task, upstream  # noqa: F401

SYSTEM = '/api/v1/system'
PASSWORD = 'securepass123'


async def register(client, username, role='operator'):
    r = await client.post('/api/v1/auth/register', json={'username': username, 'password': PASSWORD, 'nickname': 'UNIT_ONLY'})
    assert r.status_code == 201, r.text
    tokens = r.json()
    async with TestSessionLocal() as db:
        await db.execute(update(User).where(User.username == username).values(role=role))
        await db.commit()
    return tokens, {'Authorization': 'Bearer ' + tokens['access_token']}


async def user_id(username):
    async with TestSessionLocal() as db:
        return str(await db.scalar(select(User.id).where(User.username == username)))


async def promote(username, role='admin'):
    async with TestSessionLocal() as db:
        await db.execute(update(User).where(User.username == username).values(role=role))
        await db.commit()


async def test_change_password_invalidates_old_tokens(client):
    tokens, auth = await register(client, 'pw@example.com')
    wrong = await client.post('/api/v1/auth/change-password', headers=auth,
                              json={'current_password': 'not-the-password', 'new_password': 'newsecure456'})
    assert wrong.status_code == 400
    same = await client.post('/api/v1/auth/change-password', headers=auth,
                             json={'current_password': PASSWORD, 'new_password': PASSWORD})
    assert same.status_code == 400
    short = await client.post('/api/v1/auth/change-password', headers=auth,
                              json={'current_password': PASSWORD, 'new_password': 'short'})
    assert short.status_code == 422
    assert (await client.post('/api/v1/auth/change-password', json={'current_password': PASSWORD,
                                                                     'new_password': 'newsecure456'})).status_code in (401, 403)

    ok = await client.post('/api/v1/auth/change-password', headers=auth,
                           json={'current_password': PASSWORD, 'new_password': 'newsecure456'})
    assert ok.status_code == 204
    # Every token issued before the change stops working, including "remember me" refresh tokens.
    assert (await client.get('/api/v1/auth/me', headers=auth)).status_code == 401
    assert (await client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})).status_code == 401
    old = await client.post('/api/v1/auth/login', json={'username': 'pw@example.com', 'password': PASSWORD})
    assert old.status_code == 401
    new = await client.post('/api/v1/auth/login', json={'username': 'pw@example.com', 'password': 'newsecure456'})
    assert new.status_code == 200
    fresh = {'Authorization': 'Bearer ' + new.json()['access_token']}
    assert (await client.get('/api/v1/auth/me', headers=fresh)).status_code == 200
    assert (await client.post('/api/v1/auth/refresh', json={'refresh_token': new.json()['refresh_token']})).status_code == 200


async def test_roles_and_role_changes_are_admin_only(client):
    _, admin = await register(client, 'admin@example.com', 'admin')
    _, operator = await register(client, 'op@example.com')
    assert (await client.get(SYSTEM + '/roles')).status_code in (401, 403)

    roles = (await client.get(SYSTEM + '/roles', headers=operator)).json()
    assert roles['can_manage'] is False and roles['current_role'] == 'operator'
    by_name = {r['name']: r for r in roles['roles']}
    assert {'admin', 'operator', 'cs_agent'} <= set(by_name)
    assert by_name['admin']['user_count'] == 1 and by_name['operator']['user_count'] == 1
    assert by_name['operator']['permissions'] and by_name['cs_agent']['restrictions']

    op_id = await user_id('op@example.com')
    assert (await client.get(SYSTEM + '/users', headers=operator)).status_code == 403
    assert (await client.patch(f'{SYSTEM}/users/{op_id}/role', headers=operator, json={'role': 'admin'})).status_code == 403

    listed = (await client.get(SYSTEM + '/users', headers=admin)).json()
    assert [u['username'] for u in listed] == ['admin@example.com', 'op@example.com']
    assert listed[0]['is_self'] and 'hashed_password' not in listed[0]
    unknown = await client.patch(f'{SYSTEM}/users/{op_id}/role', headers=admin, json={'role': 'superuser'})
    assert unknown.status_code == 422
    self_change = await client.patch(f"{SYSTEM}/users/{await user_id('admin@example.com')}/role", headers=admin, json={'role': 'operator'})
    assert self_change.status_code == 400
    missing = await client.patch(f'{SYSTEM}/users/{uuid.uuid4()}/role', headers=admin, json={'role': 'operator'})
    assert missing.status_code == 404
    changed = await client.patch(f'{SYSTEM}/users/{op_id}/role', headers=admin, json={'role': 'cs_agent'})
    assert changed.status_code == 200 and changed.json()['role'] == 'cs_agent'
    # The new role applies to the user's very next request.
    assert (await client.get(SYSTEM + '/roles', headers=operator)).json()['current_role'] == 'cs_agent'


async def test_demoted_admin_loses_rights_immediately(client):
    _, first = await register(client, 'a1@example.com', 'admin')
    _, second = await register(client, 'a2@example.com', 'admin')
    a1, a2 = await user_id('a1@example.com'), await user_id('a2@example.com')
    assert (await client.patch(f'{SYSTEM}/users/{a2}/role', headers=first, json={'role': 'operator'})).status_code == 200
    # a2 still holds a token from when it was admin, but is no longer one: it must not demote the only admin left.
    denied = await client.patch(f'{SYSTEM}/users/{a1}/role', headers=second, json={'role': 'operator'})
    assert denied.status_code == 403


async def test_model_settings_drive_workbench_tasks_and_usage(client, headers, settings, upstream):
    # `headers` registers the workbench operator; an admin chooses the models.
    _, admin = await register(client, 'models-admin@example.com', 'admin')
    initial = (await client.get(SYSTEM + '/models', headers=headers)).json()
    assert initial['can_edit'] is False
    scenarios = {s['key']: s for s in initial['scenarios']}
    assert set(scenarios) == {'workbench_ocr', 'workbench_copy', 'workbench_fill', 'workbench_image', 'workbench_translate'}
    copy_default = settings.workbench_text_model
    assert scenarios['workbench_copy']['effective_model'] == copy_default
    assert scenarios['workbench_copy']['selected_model'] is None
    assert all(c['id'] and c['note'] and c['price'] for s in scenarios.values() for c in s['candidates'])

    assert (await client.put(SYSTEM + '/models/workbench_copy', headers=headers, json={'model': 'qwen3.8-flash'})).status_code == 403
    assert (await client.put(SYSTEM + '/models/workbench_copy', headers=admin, json={'model': 'gpt-unknown'})).status_code == 422
    assert (await client.put(SYSTEM + '/models/nope', headers=admin, json={'model': 'qwen3.8-flash'})).status_code == 404
    saved = await client.put(SYSTEM + '/models/workbench_copy', headers=admin, json={'model': 'qwen3.8-flash'})
    assert saved.status_code == 200
    assert saved.json()['effective_model'] == 'qwen3.8-flash' and saved.json()['updated_by'] == 'UNIT_ONLY'
    assert (await client.put(SYSTEM + '/models/workbench_image', headers=admin, json={'model': 'qwen-image-3.0-pro'})).status_code == 200

    config = (await client.get(ROOT + '/config', headers=headers)).json()
    assert config['copy_model'] == 'qwen3.8-flash' and config['ocr_model'] == copy_default
    assert config['image_model'] == 'qwen-image-3.0-pro'

    _, draft = await create_draft(client, headers)

    class UsageProvider(Provider):
        async def text(self, kind, snapshot, images=None):
            self.model = snapshot['config']['text_model']
            result = await super().text(kind, snapshot, images)
            return {**result, 'model': self.model, 'request_id': 'UNIT_CHAT_1',
                    'usage': {'prompt_tokens': 120, 'completion_tokens': 30, 'total_tokens': 150}}

    provider = UsageProvider()
    job = await task(client, headers, draft, 'copy')
    assert await WorkbenchWorker(TestSessionLocal, settings, upstream, provider).process_one()
    assert provider.model == 'qwen3.8-flash'
    async with TestSessionLocal() as db:
        snapshot = (await db.get(Task, uuid.UUID(job['id']))).snapshot
        rows = (await db.scalars(select(ModelUsageLog))).all()
    assert snapshot['config']['text_model'] == 'qwen3.8-flash' and snapshot['config']['scenario'] == 'workbench_copy'
    assert [(r.scenario, r.model, r.input_tokens, r.output_tokens, r.total_tokens, r.status, r.source_id)
            for r in rows] == [('workbench_copy', 'qwen3.8-flash', 120, 30, 150, 'succeeded', job['id'])]

    # Back to the default: new tasks use the configured model again.
    reset = await client.put(SYSTEM + '/models/workbench_copy', headers=admin, json={'model': None})
    assert reset.json()['selected_model'] is None and reset.json()['effective_model'] == copy_default
    draft = (await client.get(ROOT + '/drafts/' + draft['id'], headers=headers)).json()
    await task(client, headers, draft, 'copy')

    class Rejected(Provider):
        async def text(self, kind, snapshot, images=None):
            error = AnalysisError('invalid_model_output', 'UNIT_ONLY rejected')
            error.evidence = {'model': snapshot['config']['text_model'], 'request_id': 'UNIT_CHAT_2', 'usage': None}
            raise error

    await WorkbenchWorker(TestSessionLocal, settings, upstream, Rejected()).process_one()
    async with TestSessionLocal() as db:
        rejected = await db.scalar(select(ModelUsageLog).where(ModelUsageLog.request_id == 'UNIT_CHAT_2'))
    # A billed call whose output was rejected is still logged; its counts stay empty because none were returned.
    assert rejected.model == copy_default and rejected.status == 'rejected'
    assert rejected.input_tokens is None and rejected.usage is None


async def test_image_and_translation_usage_counts_images(client, headers, settings, upstream, monkeypatch):
    import io
    from PIL import Image
    from app.services.sourcing_providers import image_result
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buffer, format='PNG')
    fetch = lambda url, *_: image_result(url, 'image/png', buffer.getvalue())  # noqa: E731
    monkeypatch.setattr('app.services.workbench_worker.fetch_image', fetch)
    _, draft = await create_draft(client, headers)

    class Images(Provider):
        async def image(self, snapshot, images=None):
            return {'image_url': 'https://example.com/generated.png', 'request_id': 'UNIT_IMG_1', 'model': snapshot['config']['image_model'],
                    'usage': {'input_image_count': 0, 'output_image_count': 1, 'output_width': 1024, 'output_height': 1024}}

        async def translate_poll(self, snapshot, result):
            return {**result, 'image_url': 'https://example.com/translated.png', 'usage': {'image_count': 1}}

    worker = WorkbenchWorker(TestSessionLocal, settings, upstream, Images())
    await task(client, headers, draft, 'generate', prompt='UNIT_ONLY studio photo')
    assert await worker.process_one()
    await task(client, headers, draft, 'translate', image_urls=['https://example.com/source.png'], source_lang='zh')
    assert await worker.process_one()
    async with TestSessionLocal() as db:
        rows = {r.scenario: r for r in (await db.scalars(select(ModelUsageLog))).all()}
    assert rows['workbench_image'].output_images == 1 and rows['workbench_image'].input_tokens is None
    assert rows['workbench_image'].model == settings.workbench_image_model
    # Translation is logged once, when the finished image arrives, keyed by the upstream task id.
    assert rows['workbench_translate'].output_images == 1 and rows['workbench_translate'].request_id == 'UNIT_TASK'
    assert len(rows) == 2

    summary = (await client.get(SYSTEM + '/model-usage', headers=headers)).json()
    assert summary['totals']['calls'] == 2 and summary['totals']['output_images'] == 2
    assert summary['totals']['input_tokens'] is None
    labels = {row['scenario']: row['label'] for row in summary['by_scenario']}
    assert labels['workbench_translate'] == '图片翻译'


async def test_compatible_provider_logs_usage_and_summary(client, monkeypatch):
    _, auth = await register(client, 'usage@example.com')
    replies = iter([
        {'id': 'UNIT_DS_1', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
         'usage': {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200}},
        {'id': 'UNIT_DS_2', 'choices': [{'finish_reason': 'length', 'message': {'content': ''}}]},
    ])

    async def post(self, url, **kwargs):
        return httpx.Response(200, json=next(replies), request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    provider = CompatibleProvider('UNIT_KEY', 'https://example.com/v1', 'deepseek-unit', 30, 'deepseek', 'market_evidence')
    with pytest.raises(AnalysisError):
        # '{}' fails the schema, but the provider answered, so the call is logged.
        await provider.request('UNIT_ONLY', TextOutput)
    with pytest.raises(AnalysisError):
        await provider.request('UNIT_ONLY', TextOutput)

    summary = (await client.get(SYSTEM + '/model-usage', headers=auth)).json()
    assert summary['totals']['calls'] == 2 and summary['totals']['missing_usage'] == 1
    assert summary['totals']['input_tokens'] == 1000 and summary['totals']['output_tokens'] == 200
    assert summary['by_model'][0]['model'] == 'deepseek-unit' and summary['by_model'][0]['provider'] == 'deepseek'
    assert summary['by_scenario'][0]['label'] == '市场证据分析（DeepSeek）'
    assert len(summary['by_date']) == 1 and summary['by_date'][0]['calls'] == 2
    assert {r['has_usage'] for r in summary['recent']} == {True, False}
    bad = await client.get(SYSTEM + '/model-usage?start=2026-10-10&end=2026-10-01', headers=auth)
    assert bad.status_code == 422
    empty = (await client.get(SYSTEM + '/model-usage?start=2020-01-01&end=2020-01-31', headers=auth)).json()
    assert empty['totals']['calls'] == 0 and empty['by_scenario'] == [] and empty['recent'] == []
