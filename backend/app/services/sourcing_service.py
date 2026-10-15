"""Transactional imports, versioned tasks and review decisions."""
import csv
import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.models.sourcing import SourcingCandidate as Candidate, SourcingTask as Task, SourcingEvaluation as Evaluation, SourcingReview as Review
from app.schemas.sourcing import CandidateInput
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_sources import FileSourceAdapter


def identity(data):
    value = data.source_platform + ':' + (data.source_product_id or data.product_url)
    return hashlib.sha256(value.encode()).hexdigest()


def completeness(data):
    return 'ready' if data.name and data.main_image and data.purchase_price is not None else 'needs_details'


def snapshot(candidate):
    return CandidateInput.model_validate({k: getattr(candidate, k) for k in CandidateInput.model_fields}).model_dump(mode='json')


def analysis_snapshot(candidate):
    from app.services.miaoshou_mapping import source_details
    data = {**snapshot(candidate), 'market_evidence': candidate.market_evidence or []}
    details = source_details(candidate)
    return {**data, 'source_details': details} if details else data


async def owned(db, candidate_id, user_id, lock=False):
    stmt = select(Candidate).where(Candidate.id == candidate_id, Candidate.owner_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    value = await db.scalar(stmt)
    if not value:
        raise HTTPException(404, '候选商品不存在')
    return value


async def import_one(db, data, user_id, source='manual', source_record=None):
    values = data.model_dump(mode='json')
    values.update(id=uuid.uuid4(), owner_id=user_id, identity_key=identity(data), data_source=source,
                  trust_status='authorized_account' if source == 'miaoshou_api' else 'user_provided',
                  source_record=source_record, completeness=completeness(data), version=1, review_status='pending', favorite=False)
    values.update(miaoshou_detail_id=source_record.get('common_collect_box_id') if source_record else None,
                  original_source_id=(source_record.get('source', {}).get('sourceItemId') if source_record else data.source_product_id),
                  original_url=(source_record.get('source', {}).get('sourceItemUrl') if source_record else data.product_url))
    stmt = insert(Candidate).values(**values).on_conflict_do_nothing(
        constraint='uq_sourcing_identity').returning(Candidate.id)
    new_id = await db.scalar(stmt)
    if new_id:
        return {'id': str(new_id), 'status': 'imported'}
    existing = await db.scalar(select(Candidate.id).where(Candidate.owner_id == user_id,
                             Candidate.identity_key == identity(data), Candidate.target_market == data.target_market))
    return {'id': str(existing), 'status': 'duplicate'}


def parse_import(data):
    try:
        return FileSourceAdapter().records(data)
    except (ValueError, csv.Error) as e:
        raise HTTPException(422, str(e)) from None


async def import_records(db, data, user_id):
    results = []
    for index, record in enumerate(parse_import(data), 1):
        try:
            if not isinstance(record, dict):
                raise ValueError('每条商品必须为对象')
            record = {k: v for k, v in record.items() if v not in ('', None)}
            record.setdefault('target_market', data.target_market)
            if data.format == 'csv':
                for key in ('images', 'skus'):
                    if key in record:
                        record[key] = json.loads(record[key])
            parsed = FileSourceAdapter().normalize(record)
            result = await import_one(db, parsed, user_id, source=data.format + '_import')
        except ValidationError as e:
            result = {'status': 'invalid', 'error': '; '.join(str(x['loc']) + ': ' + x['msg'] for x in e.errors(include_input=False))}
        except (ValueError, TypeError):
            result = {'status': 'invalid', 'error': '商品或数组字段格式无效'}
        results.append({'row': index, **result})
    return {'results': results, 'imported': sum(x['status'] == 'imported' for x in results),
            'duplicates': sum(x['status'] == 'duplicate' for x in results),
            'invalid': sum(x['status'] == 'invalid' for x in results)}


async def edit_candidate(db, candidate, data):
    if data.model_dump(mode='json') == snapshot(candidate):
        return candidate
    key = identity(data)
    duplicate = await db.scalar(select(Candidate.id).where(Candidate.owner_id == candidate.owner_id,
                              Candidate.identity_key == key, Candidate.target_market == data.target_market, Candidate.id != candidate.id))
    if duplicate:
        raise HTTPException(409, '此来源商品和站点已存在')
    for k, v in data.model_dump(mode='json').items():
        setattr(candidate, k, v)
    candidate.identity_key = key
    candidate.version += 1
    candidate.completeness = completeness(data)
    # User changes turn API-sourced records into user-edited data, not platform verification.
    candidate.trust_status = 'user_modified'
    await db.execute(update(Evaluation).where(Evaluation.candidate_id == candidate.id).values(stale=True))
    await db.execute(update(Task).where(Task.candidate_id == candidate.id, Task.status == 'queued').values(
        status='failed', error_code='input_changed', error_message='商品资料已修改，请提交新版本分析', finished_at=datetime.now(timezone.utc)))
    await db.flush()
    await db.refresh(candidate)
    return candidate


async def enqueue(db, candidate, user_id, batch_id, parent=None):
    if not candidate.name:
        raise HTTPException(422, '请先补充商品名称后分析')
    config = SourcingSettings().analysis_config()
    signature = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    query = select(Task).where(Task.candidate_id == candidate.id, Task.input_version == candidate.version,
                               Task.signature == signature, Task.status.in_(['queued', 'running', 'succeeded']))
    existing = await db.scalar(query)
    if existing:
        return existing, True
    task = Task(candidate_id=candidate.id, owner_id=user_id, batch_id=batch_id,
                input_version=candidate.version, snapshot=analysis_snapshot(candidate), signature=signature,
                model_config=config, parent_task_id=parent.id if parent else None,
                vision_checkpoint=None)
    db.add(task)
    await db.flush()
    return task, False


def task_dto(task):
    return {k: getattr(task, k) for k in ('id', 'candidate_id', 'batch_id', 'parent_task_id', 'input_version',
            'status', 'stage', 'attempts', 'error_code', 'error_message', 'created_at', 'updated_at', 'finished_at')}


def evaluation_dto(value, candidate):
    if not value:
        return None
    return {**{k: getattr(value, k) for k in ('id', 'task_id', 'input_version', 'visual_score', 'vision',
            'text_analysis', 'text_status', 'rule_score', 'rule_basis', 'evidence', 'created_at')},
            'stale': value.stale or value.input_version != candidate.version, 'market_metrics': None}


def candidate_dto(candidate, evaluation=None):
    from app.services.miaoshou_mapping import public_raw
    return {**snapshot(candidate), **{k: getattr(candidate, k) for k in ('id', 'version', 'completeness',
            'data_source', 'trust_status', 'review_status', 'favorite', 'created_at', 'updated_at',
            'miaoshou_detail_id', 'original_source_id', 'original_url', 'sync_status', 'synced_at',
            'source_spu_price', 'source_stock', 'source_weight', 'source_price_min', 'source_price_max',
            'min_order_quantity', 'fetched_at', 'supplier_ref_id', 'sourcing_status', 'operator_note', 'market_evidence', 'collection_task_id')},
            'source_record': public_raw(candidate.source_record),
            'source_supplier_info': public_raw(candidate.source_supplier_info),
            'source_meta_info': public_raw(candidate.source_meta_info), 'raw_data': public_raw(candidate.raw_data),
            'evaluation': evaluation_dto(evaluation, candidate)}


async def decide(db, candidate, data, user_id):
    if data.input_version != candidate.version:
        raise HTTPException(409, '商品资料已变化，请刷新后操作')
    evaluation = None
    if data.evaluation_id:
        evaluation = await db.scalar(select(Evaluation).where(Evaluation.id == data.evaluation_id,
                                                               Evaluation.candidate_id == candidate.id))
        if not evaluation or evaluation.stale or evaluation.input_version != candidate.version:
            raise HTTPException(409, '评估已过期，请刷新后操作或不关联旧评估')
    desired = {'approve': 'approved', 'reject': 'rejected'}.get(data.action)
    if desired and candidate.review_status == desired:
        return {'status': desired, 'reused': True}
    if data.action in ('favorite', 'unfavorite'):
        flag = data.action == 'favorite'
        if candidate.favorite == flag:
            return {'status': candidate.review_status, 'reused': True}
        candidate.favorite = flag
    else:
        candidate.review_status = desired
    review = Review(candidate_id=candidate.id, evaluation_id=evaluation.id if evaluation else None, input_version=candidate.version,
                    reviewer_id=user_id, action=data.action, note=data.note, input_snapshot=analysis_snapshot(candidate))
    db.add(review)
    await db.flush()
    return {'id': review.id, 'status': candidate.review_status, 'favorite': candidate.favorite, 'reused': False}
