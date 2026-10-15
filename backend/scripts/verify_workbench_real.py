"""Explicit live AI smoke test using a real box item. Never fabricates missing listing fields.

Run from backend with DATABASE_URL set: python -m scripts.verify_workbench_real
  --box-id UUID --execute-ai --output ../docs/evidence/workbench-real-acceptance.json
Creates/reuses an unassigned draft and saves candidate results, without adopting or publishing.
Uses a short-lived in-memory token for the box's existing active operator; never writes a token to disk.
"""
import argparse
import asyncio
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path
import httpx
from app.main import app
from app.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.models.collect_box import CollectBoxItem
from app.models.user import User
from app.services.workbench_worker import WorkbenchWorker
from app.services.workbench_config import WorkbenchSettings


async def main(args):
    if not args.execute_ai:
        raise SystemExit('Explicit --execute-ai is required for live billable AI tasks')
    operations = args.operations.split(',')
    if len(operations) > args.max_model_calls:
        raise SystemExit('Operation count exceeds --max-model-calls; default live-test budget is one call')
    async with async_session_factory() as db:
        box = await db.get(CollectBoxItem, uuid.UUID(args.box_id))
        if not box:
            raise SystemExit('Box item does not exist')
        user = await db.get(User, box.owner_id)
        if not user or not user.is_active or user.role not in ('admin', 'operator'):
            raise SystemExit('Box item must belong to an active operator')
    token = create_access_token({'sub': str(user.id)}, expires_delta=timedelta(minutes=20))
    app.state.settings = get_settings()
    evidence = {'executed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'box_id': args.box_id,
                'config': WorkbenchSettings().public_config(), 'tasks': []}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local-verification',
                                 headers={'Authorization': 'Bearer ' + token}) as api:
        response = await api.post('/api/v1/product-workbench/drafts', json={'ids': [args.box_id]})
        if response.status_code != 201:
            raise SystemExit('Draft creation failed: ' + str(response.status_code))
        draft = response.json()['items'][0]
        evidence['draft_id'] = draft['id']
        evidence['source_product_id'] = draft['source_snapshot'].get('source_product_id')
        images = draft['content']['imgUrls']
        if not images:
            raise SystemExit('Source item has no real product images')
        w = WorkbenchWorker()
        for kind in operations:
            if kind not in ('ocr', 'copy', 'generate', 'edit', 'translate'):
                raise SystemExit('Unsupported operation')
            prompt = ('商品摄影：' + draft['source_snapshot'].get('name', '') + '。柔和光线，干净白色背景。只呈现商品，不添加文字或未经证实的功能。'
                      if kind == 'generate' else '保持原图商品主体的形状、颜色和编织细节，改为干净的白色背景与柔和光线。不添加文字或未经证实的功能。')
            data = {'request_key': str(uuid.uuid4()), 'version': draft['version'], 'kind': kind,
                    'image_urls': images[:1] if kind in ('ocr', 'edit', 'translate') else [],
                    'prompt': prompt if kind in ('generate', 'edit') else '', 'source_lang': 'auto'}
            created = await api.post(f'/api/v1/product-workbench/drafts/{draft["id"]}/ai-tasks', json=data)
            if created.status_code != 202:
                evidence['tasks'].append({'kind': kind, 'status': 'creation_failed', 'http_status': created.status_code})
                continue
            job = created.json()
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                await w.process_one(uuid.UUID(job['id']))
                r = await api.get('/api/v1/product-workbench/tasks/' + job['id'])
                job = r.json()
                if job['status'] in ('succeeded', 'failed', 'uncertain'):
                    break
                await asyncio.sleep(5)
            # Do not expose expiring signed URLs or source snapshots in the acceptance artifact.
            result = job.get('result') or {}
            evidence['tasks'].append({'id': job['id'], 'kind': kind, 'status': job['status'], 'stage': job['stage'],
                'error_code': job.get('error_code'), 'error_message': job.get('error_message'),
                'model': result.get('model'), 'request_id': result.get('request_id'), 'usage': result.get('usage'),
                'upstream_task_id': result.get('upstream_task_id'), 'asset_id': result.get('asset_id'),
                'width': result.get('width'), 'height': result.get('height'), 'public_url': result.get('public_url'),
                'output': result.get('output')})
            print(kind, job['status'], job.get('error_code') or '', flush=True)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        checked = await api.post(f'/api/v1/product-workbench/drafts/{draft["id"]}/check', json={'version': draft['version']})
        evidence['validation'] = checked.json().get('validation') if checked.status_code == 200 else {'http_status': checked.status_code}
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--box-id', required=True)
    parser.add_argument('--execute-ai', action='store_true')
    parser.add_argument('--operations', default='ocr')
    parser.add_argument('--max-model-calls', type=int, default=1)
    parser.add_argument('--output', default='../docs/evidence/workbench-real-acceptance.json')
    asyncio.run(main(parser.parse_args()))
