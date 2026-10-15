"""Export a safe projection of persisted acceptance evidence, without API calls.

Run from backend with the intended DATABASE_URL explicitly set. This script is
read-only toward PostgreSQL and never exports raw supplier data or credentials.
"""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_, select, text
from app.core.database import async_session_factory, engine
from app.models.sourcing import MiaoshouSyncTask, SourcingCandidate, SourcingEvaluation, SourcingReview
from app.services.miaoshou_tasks import task_dto


async def export(source_id, destination):
    engine.echo = False
    async with async_session_factory() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        counts = {}
        for table in ('users', 'products', 'orders', 'sourcing_candidates', 'sourcing_miaoshou_tasks',
                      'sourcing_analysis_tasks', 'sourcing_ai_evaluations', 'sourcing_reviews'):
            counts[table] = await db.scalar(text(f'SELECT count(*) FROM {table}'))
        candidates = (await db.scalars(select(SourcingCandidate).where(SourcingCandidate.source_product_id == source_id))).all()
        if not candidates:
            raise RuntimeError('No persisted candidate found for this source ID')
        query = [MiaoshouSyncTask.items.contains([{'source_item_id': source_id}])]
        query += [MiaoshouSyncTask.items.contains([{'common_detail_id': c.miaoshou_detail_id}]) for c in candidates if c.miaoshou_detail_id]
        jobs = (await db.scalars(select(MiaoshouSyncTask).where(or_(*query)).order_by(MiaoshouSyncTask.created_at))).all()
        safe_jobs = []
        for job in jobs:
            response = job.submitted_response or {}
            safe_jobs.append({**task_dto(job), 'response': {'result': response.get('result'), 'code': response.get('code'),
                             'sourceItemIdAndDetailIdMap': response.get('data', {}).get('sourceItemIdAndDetailIdMap')}
                             if response else None})
        safe_candidates, evaluations, reviews = [], [], []
        for candidate in candidates:
            raw = candidate.raw_data or {}
            envelope = raw.get('detail_response', {})
            detail = envelope.get('data', {}).get('editCommonCollectBoxDetail', {})
            raw_text = raw.get('raw_response_text') or ''
            safe_candidates.append({'id': candidate.id, 'input_version': candidate.version, 'source_product_id': candidate.source_product_id,
                                    'common_collect_box_detail_id': candidate.miaoshou_detail_id, 'product_url': candidate.product_url,
                                    'market': candidate.target_market, 'currency_confirmed_by_operator': candidate.currency,
                                    'title': candidate.name, 'spu_price': candidate.source_spu_price, 'stock': candidate.source_stock,
                                    'weight': candidate.source_weight, 'sku_count': len(detail.get('skuMap') or {}),
                                    'sku_price_fields': [{'key': k, **{f: v.get(f) for f in ('price', 'oriPrice', 'stock', 'weight', 'packageLength', 'packageWidth', 'packageHeight')}} for k, v in (detail.get('skuMap') or {}).items()],
                                    'image_count': len(detail.get('imgUrls') or []), 'units': raw.get('units'), 'price_meanings': raw.get('price_meanings'),
                                    'supplier_info_keys': sorted((candidate.source_supplier_info or {}).keys()),
                                    'meta_info_keys': sorted((candidate.source_meta_info or {}).keys()),
                                    'detail_response_result': envelope.get('result'), 'detail_response_code': envelope.get('code'),
                                    'raw_response_bytes': len(raw_text.encode()), 'raw_response_sha256': hashlib.sha256(raw_text.encode()).hexdigest(),
                                    'sync_status': candidate.sync_status, 'synced_at': candidate.synced_at,
                                    'review_status': candidate.review_status, 'favorite': candidate.favorite})
            for evaluation in (await db.scalars(select(SourcingEvaluation).where(SourcingEvaluation.candidate_id == candidate.id))).all():
                evidence = evaluation.evidence or {}
                evaluations.append({'id': evaluation.id, 'task_id': evaluation.task_id, 'candidate_id': candidate.id,
                                    'input_version': evaluation.input_version, 'stale': evaluation.stale,
                                    'visual_score': evaluation.visual_score, 'rule_score': evaluation.rule_score,
                                    'text_status': evaluation.text_status, 'vision': evidence.get('vision'), 'text': evidence.get('text'),
                                    'prompt_version': evidence.get('config', {}).get('prompt_version'),
                                    'schema_version': evidence.get('config', {}).get('schema_version')})
            for review in (await db.scalars(select(SourcingReview).where(SourcingReview.candidate_id == candidate.id).order_by(SourcingReview.created_at))).all():
                reviews.append({k: getattr(review, k) for k in ('id', 'candidate_id', 'evaluation_id', 'input_version', 'reviewer_id', 'action', 'note', 'created_at')})
        report = {'exported_at': datetime.now(timezone.utc).isoformat(), 'migration_version': await db.scalar(text('SELECT version_num FROM alembic_version')),
                  'counts': counts, 'source_jobs': safe_jobs, 'candidates': safe_candidates, 'evaluations': evaluations, 'reviews': reviews,
                  'notes': ['Persisted real responses; not unit-test fixtures', 'Raw response and supplier/meta values remain in PostgreSQL',
                            'Review decisions are functional acceptance only; no publishing authorization']}
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        print(json.dumps({'output': str(Path(destination).resolve()), 'counts': counts, 'source_jobs': len(jobs),
                          'matching_candidates': len(candidates), 'evaluations': len(evaluations), 'reviews': len(reviews)}, ensure_ascii=False))
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-item-id', required=True)
    parser.add_argument('--output', default='../docs/evidence/miaoshou-real-acceptance.json')
    args = parser.parse_args()
    asyncio.run(export(args.source_item_id, args.output))
