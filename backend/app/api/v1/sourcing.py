"""Authenticated sourcing API with owner-scoped queries."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sourcing import SourcingCandidate as Candidate, SourcingTask as Task, SourcingEvaluation as Evaluation, SourcingReview as Review
from app.schemas.sourcing import BatchInput, CandidateInput, ImportInput, Market, ReviewInput
from app.services import sourcing_service as service
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError
from app.services.sourcing_sources import MiaoshouSourceAdapter, UnavailableSourceAdapter, ManualSourceAdapter, FileSourceAdapter

router = APIRouter(prefix='/v1/sourcing', tags=['Sourcing'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)


@router.get('/providers/status')
async def providers_status(user: User = AUTH):
    s = SourcingSettings()
    return {'vision': {'provider': 'bailian', 'model': s.bailian_vision_model, 'configured': False, 'enabled': False},
            'text': {'provider': 'deepseek', 'model': s.deepseek_model, 'configured': bool(s.deepseek_api_key.get_secret_value())},
            'sources': [MiaoshouSourceAdapter(s).status(), ManualSourceAdapter().status(), FileSourceAdapter().status(), UnavailableSourceAdapter().status()],
            'fetch_item': {'available': MiaoshouSourceAdapter(s).client.configured, 'path': '/open/v1/product/common_collect_box/common_collect_box/fetch_item',
                           'max_links': 50, 'reason': '已按完整文档实现；持久化任务仅发送一次，异常只查询平台状态'},
            'market_metrics_available': False}


@router.post('/candidates', status_code=201)
async def create_candidate(data: CandidateInput, db: AsyncSession = DB, user: User = AUTH):
    return await service.import_one(db, ManualSourceAdapter().normalize(data.model_dump()), user.id)


@router.post('/candidates/import')
async def import_candidates(data: ImportInput, db: AsyncSession = DB, user: User = AUTH):
    return await service.import_records(db, data, user.id)


@router.get('/candidates')
async def candidates(keyword: str = Query('', max_length=200), target_market: Market | None = None,
                     category: str = Query('', max_length=200), currency: str = Query('CNY', pattern='^[A-Z]{3}$'),
                     min_price: Decimal | None = Query(None, ge=0), max_price: Decimal | None = Query(None, ge=0),
                     review_status: Literal['pending', 'approved', 'rejected'] | None = None, favorite: bool | None = None,
                     completeness: Literal['ready', 'needs_details'] | None = None,
                     data_source: str | None = Query(None, max_length=30),
                     sourcing_status: Literal['saved', 'to_analyze', 'to_review'] | None = None,
                     sort: Literal['newest', 'price_asc'] = 'newest',
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     db: AsyncSession = DB, user: User = AUTH):
    latest = select(Evaluation.id).where(Evaluation.candidate_id == Candidate.id).order_by(Evaluation.created_at.desc(), Evaluation.id.desc()).limit(1).correlate(Candidate).scalar_subquery()
    query = select(Candidate, Evaluation).outerjoin(Evaluation, Evaluation.id == latest).where(Candidate.owner_id == user.id)
    if keyword:
        query = query.where(or_(Candidate.name.ilike(f'%{keyword}%'), Candidate.source_product_id.ilike(f'%{keyword}%')))
    for field, value in [('target_market', target_market), ('review_status', review_status), ('favorite', favorite), ('completeness', completeness),
                         ('data_source', data_source), ('sourcing_status', sourcing_status)]:
        if value is not None:
            query = query.where(getattr(Candidate, field) == value)
    if category:
        query = query.where(Candidate.category.ilike(f'%{category}%'))
    if min_price is not None or max_price is not None or sort == 'price_asc':
        query = query.where(Candidate.currency == currency)
    if min_price is not None:
        query = query.where(Candidate.purchase_price >= min_price)
    if max_price is not None:
        query = query.where(Candidate.purchase_price <= max_price)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    if sort == 'price_asc':
        query = query.order_by(Candidate.purchase_price.asc().nulls_last())
    rows = (await db.execute(query.order_by(Candidate.created_at.desc(), Candidate.id).offset((page - 1) * page_size).limit(page_size))).all()
    from app.models.sourcing import MiaoshouSyncTask
    from app.services.miaoshou_tasks import task_dto
    job_ids = [c.collection_task_id for c, _ in rows if c.collection_task_id]
    jobs = {j.id: task_dto(j) for j in (await db.scalars(select(MiaoshouSyncTask).where(
        MiaoshouSyncTask.id.in_(job_ids), MiaoshouSyncTask.owner_id == user.id))).all()} if job_ids else {}
    from app.models.collect_box import CollectBoxItem
    boxed = set((await db.scalars(select(CollectBoxItem.candidate_id).where(
        CollectBoxItem.owner_id == user.id, CollectBoxItem.candidate_id.in_([c.id for c, _ in rows])))).all()) if rows else set()
    return {'items': [{**service.candidate_dto(c, e), 'collection': jobs.get(c.collection_task_id), 'in_collect_box': c.id in boxed}
                      for c, e in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/candidates/{candidate_id}')
async def candidate_detail(candidate_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    candidate = await service.owned(db, candidate_id, user.id)
    evaluation = await db.scalar(select(Evaluation).where(Evaluation.candidate_id == candidate.id).order_by(Evaluation.created_at.desc()).limit(1))
    return service.candidate_dto(candidate, evaluation)


@router.patch('/candidates/{candidate_id}')
async def edit(candidate_id: UUID, data: CandidateInput, db: AsyncSession = DB, user: User = AUTH):
    candidate = await service.owned(db, candidate_id, user.id, lock=True)
    try:
        await service.edit_candidate(db, candidate, data)
        return service.candidate_dto(candidate)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, '此来源商品已存在') from None


class Operations(BaseModel):
    """运营人员维护的信息：不改变商品资料版本，不影响已有 AI 评估。"""
    favorite: bool | None = None
    operator_note: str | None = Field(default=None, max_length=2000)
    sourcing_status: Literal['saved', 'to_analyze', 'to_review'] | None = None
    review_status: Literal['pending', 'rejected'] | None = None
    input_version: int | None = Field(default=None, ge=1)


@router.patch('/candidates/{candidate_id}/operations')
async def operations(candidate_id: UUID, data: Operations, db: AsyncSession = DB, user: User = AUTH):
    candidate = await service.owned(db, candidate_id, user.id, lock=True)
    if data.review_status is not None:
        if data.input_version != candidate.version:
            raise HTTPException(409, '商品资料已变化，请刷新后操作')
        db.add(Review(candidate_id=candidate.id, input_version=candidate.version, reviewer_id=user.id,
                      action='reject' if data.review_status == 'rejected' else 'restore',
                      note='', input_snapshot=service.analysis_snapshot(candidate)))
    for k, v in data.model_dump(exclude_none=True, exclude={'input_version'}).items():
        setattr(candidate, k, v)
    await db.flush()
    await db.refresh(candidate)
    return service.candidate_dto(candidate)


@router.post('/analyses', status_code=202)
async def analyze(data: BatchInput, db: AsyncSession = DB, user: User = AUTH):
    ids = sorted(set(data.candidate_ids))  # Deterministic lock order prevents batch deadlocks.
    candidates = [await service.owned(db, x, user.id, lock=True) for x in ids]
    if any(not x.name for x in candidates):
        raise HTTPException(422, '请先补充所选商品的名称')
    batch_id = uuid.uuid4()
    results = []
    for candidate in candidates:
        task, reused = await service.enqueue(db, candidate, user.id, batch_id)
        results.append({**service.task_dto(task), 'reused': reused})
    return {'batch_id': batch_id, 'tasks': results}


@router.get('/tasks')
async def tasks(batch_id: UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                db: AsyncSession = DB, user: User = AUTH):
    query = select(Task).where(Task.owner_id == user.id)
    if batch_id:
        query = query.where(Task.batch_id == batch_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    # Show active tasks first so page refresh always recovers ongoing progress.
    rows = (await db.scalars(query.order_by(Task.status.in_(['queued', 'running']).desc(), Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [service.task_dto(t) for t in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/tasks/{task_id}')
async def task_detail(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    task = await db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id))
    if not task:
        raise HTTPException(404, '任务不存在')
    candidate = await service.owned(db, task.candidate_id, user.id)
    evaluation = await db.scalar(select(Evaluation).where(Evaluation.task_id == task.id))
    return {**service.task_dto(task), 'evaluation': service.evaluation_dto(evaluation, candidate),
            'partial_vision': task.vision_checkpoint['output'] if task.vision_checkpoint else None}


@router.post('/tasks/{task_id}/retry', status_code=202)
async def retry(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    parent = await db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id))
    if not parent:
        raise HTTPException(404, '任务不存在')
    if parent.status != 'failed':
        raise HTTPException(409, '只能重试失败任务')
    candidate = await service.owned(db, parent.candidate_id, user.id, lock=True)
    if parent.input_version != candidate.version:
        raise HTTPException(409, '商品资料已改变，请提交新版本分析')
    task, reused = await service.enqueue(db, candidate, user.id, uuid.uuid4(), parent)
    return {**service.task_dto(task), 'reused': reused}


@router.post('/candidates/{candidate_id}/review')
async def review(candidate_id: UUID, data: ReviewInput, db: AsyncSession = DB, user: User = AUTH):
    candidate = await service.owned(db, candidate_id, user.id, lock=True)
    return await service.decide(db, candidate, data, user.id)


@router.get('/reviews')
async def review_history(candidate_id: UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         db: AsyncSession = DB, user: User = AUTH):
    query = select(Review, Candidate.name, User.nickname).join(Candidate, Candidate.id == Review.candidate_id).join(User, User.id == Review.reviewer_id).where(Candidate.owner_id == user.id)
    if candidate_id:
        query = query.where(Review.candidate_id == candidate_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(Review.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [{**{k: getattr(r, k) for k in ('id', 'candidate_id', 'evaluation_id', 'input_version', 'reviewer_id', 'action', 'note', 'created_at')},
                       'candidate_name': name, 'reviewer_name': nickname} for r, name, nickname in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/sources/miaoshou/products')
async def source_products(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=500),
                          source_id: str | None = Query(None, max_length=255),
                          tab: Literal['all', 'noClaimed', 'claimed', 'collectFail', 'collectSuccess'] = 'all', user: User = AUTH):
    try:
        return await MiaoshouSourceAdapter().search(page, page_size, source_id, tab)
    except AnalysisError as e:
        raise HTTPException(424, e.message) from None


class SourceImport(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=20)
    target_market: Market
    currency: str = Field(pattern='^[A-Z]{3}$')


@router.post('/sources/miaoshou/import')
async def source_import(data: SourceImport, db: AsyncSession = DB, user: User = AUTH):
    adapter = MiaoshouSourceAdapter()
    results = []
    for product_id in dict.fromkeys(data.product_ids):
        try:
            record = await adapter.detail(product_id)
            details = record['editCommonCollectBoxDetail']
            sources = details.get('sourceList') or []
            source = next((x for x in sources if '.1688.com/' in (x.get('sourceItemUrl') or '') or '//1688.com/' in (x.get('sourceItemUrl') or '')), None)
            if not source:
                raise AnalysisError('source_details_missing', '详情未提供明确 1688 货源链接，不能伪装为完整商品')
            from app.services.miaoshou_mapping import store_detail
            result = await store_detail(db, adapter, record, product_id, user.id, data.target_market, data.currency)
        except AnalysisError as e:
            result = {'status': 'invalid', 'error': e.message, 'error_code': e.code}
        except (ValidationError, ValueError, KeyError, TypeError):
            result = {'status': 'invalid', 'error': '妙手商品字段未通过输入校验', 'error_code': 'source_invalid_data'}
        results.append({'source_id': product_id, **result})
    return {'results': results}


class CandidateVersion(BaseModel):
    id: UUID
    version: int = Field(ge=1)


class CandidateCollect(BaseModel):
    request_key: UUID
    candidates: list[CandidateVersion] = Field(min_length=1, max_length=50)


@router.post('/candidates/collect', status_code=202)
async def collect_candidates(data: CandidateCollect, db: AsyncSession = DB, user: User = AUTH):
    from app.api.v1.miaoshou import operator
    from app.clients.miaoshou_client import MiaoshouClient
    from app.models.sourcing import MiaoshouSyncTask
    from app.schemas.miaoshou import CollectInput, normalized_link
    from app.services.miaoshou_tasks import create_task, task_dto
    operator(user)
    if not MiaoshouClient().configured:
        raise HTTPException(424, '妙手服务端凭证未配置')
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    versions = {x.id: x.version for x in data.candidates}
    if len(versions) != len(data.candidates):
        raise HTTPException(422, '选择中存在重复候选商品')
    existing = await db.scalar(select(MiaoshouSyncTask).where(MiaoshouSyncTask.owner_id == user.id,
                                                             MiaoshouSyncTask.request_key == data.request_key))
    if existing:
        recorded = {UUID(x['selected_candidate_id']): x['selected_version'] for x in existing.items
                    if x.get('selected_candidate_id')}
        if recorded != versions:
            raise HTTPException(409, '相同 request_key 不能用于不同选择')
        return {**task_dto(existing), 'reused': True}
    rows = [await service.owned(db, id, user.id, lock=True) for id in sorted(versions)]
    if len({r.target_market for r in rows}) != 1:
        raise HTTPException(422, '请按地区分别采集')
    for row in rows:
        if row.version != versions[row.id]:
            raise HTTPException(409, '商品资料已更新，请刷新后重新选择')
        if row.review_status == 'rejected':
            raise HTTPException(409, '所选商品已排除，请先恢复')
        try:
            normalized_link(row.product_url)
        except ValueError:
            raise HTTPException(422, '只能采集具有标准 1688 商品链接的候选') from None
    job, reused = await create_task(db, user.id, CollectInput(request_key=data.request_key,
        links=[r.product_url for r in rows], target_market=rows[0].target_market,
        currency='CNY', analyze_after_sync=False), 'collect')
    by_source = {r.source_product_id: r for r in rows}
    items = []
    for item in job.items:
        row = by_source[item['source_item_id']]
        items.append({**item, 'selected_candidate_id': str(row.id), 'selected_version': row.version})
        row.collection_task_id = job.id
        if not reused:
            row.review_status = 'approved'
            db.add(Review(candidate_id=row.id, evaluation_id=None, input_version=row.version,
                          reviewer_id=user.id, action='approve', note='人工勾选采集到妙手',
                          input_snapshot=service.analysis_snapshot(row)))
    job.items = items
    await db.flush()
    await db.refresh(job)
    return {**task_dto(job), 'reused': reused}


@router.get('/candidates/{candidate_id}/evaluations')
async def evaluations(candidate_id: UUID, page: int = Query(1, ge=1),
                      db: AsyncSession = DB, user: User = AUTH):
    candidate = await service.owned(db, candidate_id, user.id)
    query = select(Evaluation).where(Evaluation.candidate_id == candidate.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(Evaluation.created_at.desc()).offset((page - 1) * 20).limit(20))).all()
    return {'items': [service.evaluation_dto(r, candidate) for r in rows], 'total': total, 'page': page, 'page_size': 20}
