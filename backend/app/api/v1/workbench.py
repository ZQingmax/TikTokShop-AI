import copy
import re
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError
from app.core.database import get_db
from app.core.security import get_current_user
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.models.collect_box import CollectBoxItem
from app.models.sourcing import SourcingCandidate, MiaoshouSyncTask
from app.models.user import User
from app.models.workbench import WorkbenchDraft as Draft, WorkbenchTask as Task, WorkbenchAsset as Asset
from app.schemas.workbench import CreateDrafts, SaveDraft, VersionInput, AIInput, SyncInput, AdoptInput, StrictInput, CopyOutput
from app.schemas.sourcing import Market
from app.services.workbench_config import WorkbenchSettings
from app.services import workbench_service as service
from app.services import model_settings

router = APIRouter(prefix='/v1/product-workbench', tags=['Product Workbench'])
DB, AUTH = Depends(get_db), Depends(get_current_user)


def upstream(error):
    raise HTTPException(424, {'message': error.message, 'code': error.code})


@router.get('/config')
async def config(db: AsyncSession = DB, user: User = AUTH):
    settings = WorkbenchSettings()
    models = await model_settings.effective_models(db, settings)
    # Same per-scenario models that enqueue freezes into new tasks (system settings → model settings).
    return {**settings.public_config(), 'ocr_model': models['workbench_ocr'], 'copy_model': models['workbench_copy'],
            'fill_model': models['workbench_fill'], 'image_model': models['workbench_image'],
            'translation_model': models['workbench_translate'], 'miaoshou_configured': MiaoshouClient().configured}


@router.post('/drafts', status_code=201)
async def create(data: CreateDrafts, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    ids = list(dict.fromkeys(data.ids))
    items = (await db.scalars(select(CollectBoxItem).where(CollectBoxItem.id.in_(ids), CollectBoxItem.owner_id == user.id))).all()
    if len(items) != len(ids):
        raise HTTPException(404, '部分采集箱商品不存在')
    result = []
    for item in items:
        key = str(data.shop_id) if data.shop_id else 'unassigned'
        # One draft per source product: reopening a product returns its draft; the shop is chosen inside it.
        draft = await db.scalar(select(Draft).where(Draft.owner_id == user.id, Draft.source_key == str(item.candidate_id),
                                                    Draft.archived_at.is_(None)))
        if not draft:
            if data.shop_id:
                try:
                    await service.shop_for(MiaoshouClient(), item.target_market, data.shop_id)
                except MiaoshouError as error:
                    upstream(error)
            candidate = await service.owned(db, SourcingCandidate, item.candidate_id, user.id)
            snapshot = service.initial_snapshot(item, candidate)
            draft = Draft(owner_id=user.id, collect_item_id=item.id, source_key=str(item.candidate_id), shop_key=key,
                          shop_id=data.shop_id, market=item.target_market, currency=service.CURRENCIES[item.target_market],
                          language=WorkbenchSettings().workbench_language, source_snapshot=snapshot,
                          content=service.initial_content(snapshot), common_detail_id=candidate.miaoshou_detail_id)
            db.add(draft)
            await db.flush()
        result.append(service.draft_dto(draft))
    return {'items': result}


@router.get('/drafts')
async def drafts(market: Market | None = None, state: str | None = None, keyword: str = Query('', max_length=100),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: AsyncSession = DB, user: User = AUTH):
    q = select(Draft).where(Draft.owner_id == user.id, Draft.archived_at.is_(None))
    if market:
        q = q.where(Draft.market == market)
    if keyword:
        q = q.where(Draft.content['title'].astext.ilike(f'%{keyword}%'))
    if state == 'synced':
        q = q.where(Draft.synced_version == Draft.version)
    elif state == 'ready':
        q = q.where(Draft.checked_version == Draft.version, (Draft.synced_version.is_(None) | (Draft.synced_version != Draft.version)))
    elif state == 'modified':
        q = q.where(Draft.synced_version.is_not(None), Draft.synced_version != Draft.version,
                    Draft.checked_version.is_(None) | (Draft.checked_version != Draft.version))
    elif state == 'editing':
        q = q.where(Draft.synced_version.is_(None), Draft.checked_version.is_(None) | (Draft.checked_version != Draft.version))
    elif state:
        raise HTTPException(422, '未知草稿状态')
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.scalars(q.order_by(Draft.updated_at.desc(), Draft.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [service.draft_dto(x) for x in rows], 'total': total}


@router.get('/drafts/{draft_id}')
async def detail(draft_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    return service.draft_dto(await service.owned(db, Draft, draft_id, user.id))


@router.patch('/drafts/{draft_id}')
async def save(draft_id: UUID, data: SaveDraft, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    draft = await service.owned(db, Draft, draft_id, user.id, True)
    service.require_version(draft, data.version)
    shop_changed = draft.shop_id != data.shop_id
    if shop_changed:
        # The shop stays editable until the draft is linked to that shop's Miaoshou product.
        if draft.synced_version is not None:
            raise HTTPException(409, '草稿已同步到当前店铺，不能更换目标店铺')
        if await db.scalar(select(Task.id).where(Task.draft_id == draft.id, Task.kind == 'sync', Task.status.in_(service.ACTIVE))):
            raise HTTPException(409, '同步任务进行中，请先查询或恢复该任务再更换店铺')
        if data.shop_id:
            try:
                await service.shop_for(MiaoshouClient(), draft.market, data.shop_id)
            except MiaoshouError as error:
                upstream(error)
        draft.shop_id, draft.shop_key = data.shop_id, str(data.shop_id) if data.shop_id else 'unassigned'
    content = data.content.model_dump(mode='json')
    if draft.content != content or draft.language != data.language or shop_changed:
        # Every successful save is a new editable version, including first-time shop binding.
        draft.content, draft.language = content, data.language
        draft.version += 1
        draft.checked_version, draft.validation = None, None
    await db.flush()
    return service.draft_dto(draft)


@router.get('/shops')
async def shops(market: Market = 'MY', page: int = Query(1, ge=1), user: User = AUTH):
    try:
        response = await MiaoshouClient().get_shops('tiktok', market, page, 100)
        return {'items': response.data['shopList'], 'has_more': len(response.data['shopList']) == 100,
                'currency': service.CURRENCIES[market]}
    except MiaoshouError as error:
        upstream(error)


@router.get('/drafts/{draft_id}/options')
async def options(draft_id: UUID, cid: str = Query('', max_length=20), db: AsyncSession = DB, user: User = AUTH):
    draft = await service.owned(db, Draft, draft_id, user.id)
    if not draft.shop_id:
        raise HTTPException(422, '先选择并保存目标店铺')
    client = MiaoshouClient()
    try:
        await service.shop_for(client, draft.market, draft.shop_id)
        categories = (await client.get_categories(draft.market)).data
        warehouses = (await client.get_warehouses(draft.shop_id)).data
        metadata = {}
        if cid:
            if not service.find_category(categories.get('cateTree'), cid):
                raise HTTPException(422, '当前站点不存在该类目')
            metadata = (await client.get_category_metadata(draft.market, cid, draft.shop_id)).data.get('categoryMetadata') or {}
        return {'categories': categories.get('cateTree') or {}, 'metadata': metadata, 'warehouses': warehouses}
    except MiaoshouError as error:
        upstream(error)


@router.post('/drafts/{draft_id}/check')
async def check(draft_id: UUID, data: VersionInput, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    draft = await service.owned(db, Draft, draft_id, user.id, True)
    service.require_version(draft, data.version)
    try:
        draft.validation = await service.preflight(MiaoshouClient(), draft)
    except MiaoshouError as error:
        upstream(error)
    draft.checked_version = draft.version if draft.validation['valid'] else None
    await db.flush()
    return service.draft_dto(draft)


@router.post('/drafts/{draft_id}/ai-tasks', status_code=202)
async def ai_task(draft_id: UUID, data: AIInput, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    draft = await service.owned(db, Draft, draft_id, user.id, True)
    settings = WorkbenchSettings()
    if not settings.public_config()['configured']:
        raise HTTPException(424, '百炼服务端凭证未配置')
    if data.kind in ('generate', 'edit', 'translate') and not MiaoshouClient().configured:
        raise HTTPException(424, '妙手图片空间凭证未配置')
    if data.kind == 'translate' and data.source_lang == draft.language:
        raise HTTPException(422, '源语言与目标语言相同')
    task, reused = await service.enqueue(db, draft, user, data, data.kind, settings)
    return {**service.task_dto(task), 'reused': reused}


@router.post('/drafts/{draft_id}/sync', status_code=202)
async def sync(draft_id: UUID, data: SyncInput, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    draft = await service.owned(db, Draft, draft_id, user.id, True)
    previous = await db.scalar(select(Task).where(Task.owner_id == user.id, Task.request_key == data.request_key))
    # Syncing saves the draft into the shop's Miaoshou collect box (added the first time, edited after);
    # unfinished fields are left out by the worker, so a full publishing check is not required here.
    if not previous and not draft.shop_id:
        raise HTTPException(422, '先选择并保存目标店铺')
    task, reused = await service.enqueue(db, draft, user, data, 'sync', WorkbenchSettings())
    return {**service.task_dto(task), 'reused': reused}


@router.delete('/drafts/{draft_id}')
async def delete_draft(draft_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    """Remove a draft from the workbench. It is archived (recoverable); Miaoshou items are untouched."""
    service.operator(user)
    draft = await service.owned(db, Draft, draft_id, user.id, True)
    busy = await db.scalar(select(Task.id).where(Task.draft_id == draft.id, or_(
        Task.status.in_(('queued', 'running', 'waiting')), and_(Task.kind == 'sync', Task.status == 'uncertain'))).limit(1))
    if busy:
        raise HTTPException(409, '草稿有进行中或结果未确认的任务，请等待完成或先恢复确认后再删除')
    draft.archived_at = service.now()
    await db.flush()
    return {'id': str(draft_id), 'deleted': True}


@router.get('/drafts/{draft_id}/suggestions')
async def suggestions(draft_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    """Field suggestions: saved source data, plus the latest successful AI fill task (never auto-applied)."""
    draft = await service.owned(db, Draft, draft_id, user.id)
    latest = await db.scalar(select(Task).where(Task.draft_id == draft_id, Task.owner_id == user.id, Task.kind == 'fill',
                                                Task.status == 'succeeded').order_by(Task.created_at.desc()).limit(1))
    ai = latest and {'task_id': str(latest.id), 'input_version': latest.input_version,
                     'cid': latest.snapshot['content'].get('cid') or '', **latest.result['output']}
    return {'source': service.source_hints(draft.source_snapshot), 'ai': ai or None}


@router.get('/drafts/{draft_id}/tasks')
async def tasks(draft_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    await service.owned(db, Draft, draft_id, user.id)
    rows = (await db.scalars(select(Task).where(Task.draft_id == draft_id, Task.owner_id == user.id).order_by(Task.created_at.desc()).limit(100))).all()
    return {'items': [service.task_dto(x) for x in rows]}


@router.get('/tasks/{task_id}')
async def task_detail(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    return service.task_dto(await service.owned(db, Task, task_id, user.id))


@router.post('/tasks/{task_id}/adopt')
async def adopt(task_id: UUID, data: AdoptInput, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    # Keep the same draft -> task lock order as workers.
    task = await service.owned(db, Task, task_id, user.id)
    draft = await service.owned(db, Draft, task.draft_id, user.id, True)
    task = await service.owned(db, Task, task_id, user.id, True)
    service.require_version(draft, data.version)
    if task.status != 'succeeded' or task.kind == 'sync':
        raise HTTPException(409, '该任务没有可采纳的 AI 结果')
    if task.kind == 'fill':
        raise HTTPException(409, '填充建议请在对应字段中按 Tab 逐项采纳')
    if task.adopted_version:
        raise HTTPException(409, '该结果已采纳')
    if task.input_version != draft.version and not data.confirm_stale:
        raise HTTPException(409, '生成期间草稿已修改，请对比并确认采纳旧输入结果')
    content = copy.deepcopy(draft.content)
    if task.kind == 'ocr':
        content['recognized_text'] = task.result['output']['blocks']
    elif task.kind == 'copy':
        try:
            output = CopyOutput.model_validate(task.result['output']).model_dump(mode='json')
        except ValidationError:
            raise HTTPException(409, '历史文案未通过当前输出校验，请手动整理或重新生成') from None
        if draft.language == 'en' and any(re.search(r'[\u3400-\u9fff]', x) for x in [output['title'], output['notes'], *output['bullet_points']]):
            raise HTTPException(409, '该文案夹杂中文，不可直接采纳为英文草稿，请手动翻译或重新生成')
        content.update(output)
    else:
        asset = await service.owned(db, Asset, UUID(task.result['asset_id']), user.id)
        if asset.status != 'ready' or asset.draft_id != draft.id:
            raise HTTPException(409, '图片尚未完成持久化')
        if data.image_action == 'replace':
            # Replace in place, in product images or 详细描述 images (e.g. a translated detail image).
            field = next((f for f in ('imgUrls', 'descImgUrls') if data.replace_url in (content.get(f) or [])), None)
            if not field:
                raise HTTPException(409, '要替换的图片已不存在')
            content[field] = [asset.public_url if x == data.replace_url else x for x in content[field]]
        elif asset.public_url not in content['imgUrls']:
            content['imgUrls'].append(asset.public_url)
    from app.schemas.workbench import EditorialContent
    draft.content = EditorialContent.model_validate(content).model_dump(mode='json')
    draft.version += 1
    draft.checked_version, draft.validation = None, None
    task.adopted_version = draft.version
    await db.flush()
    return service.draft_dto(draft)


class RetryInput(StrictInput):
    resubmit_model: bool = False
    resubmit_transfer: bool = False
    # Without it an unconfirmed save is only read back; with it the save is prepared and sent again.
    resubmit_save: bool = False


@router.post('/tasks/{task_id}/retry')
async def retry(task_id: UUID, data: RetryInput, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    task = await service.owned(db, Task, task_id, user.id)
    await service.owned(db, Draft, task.draft_id, user.id, True)
    task = await service.owned(db, Task, task_id, user.id, True)
    if task.status not in ('failed', 'uncertain'):
        raise HTTPException(409, '只有失败或结果不确定的任务可以恢复')
    steps = copy.deepcopy(task.steps)
    steps['polls'] = 0
    if steps.get('model_started') and not task.result and not data.resubmit_model:
        raise HTTPException(409, '模型请求结果不确定；明确确认可能再次计费后才能重新提交')
    if data.resubmit_model and not task.result:
        steps.pop('model_started', None)
    if steps.get('transfer_started') and not data.resubmit_transfer:
        raise HTTPException(409, '图片转存结果不确定；确认重新转存后继续')
    if data.resubmit_transfer:
        steps.pop('transfer_started', None)
    if data.resubmit_save and task.kind == 'sync' and steps.get('save_started'):
        # The worker first checks whether the unconfirmed save did land (then it just finishes);
        # otherwise the remote must still equal its state right before that save, and the payload is
        # rebuilt under current rules and sent again.
        steps['previous_expected'], steps['resubmit_baseline'] = steps.get('expected'), steps.get('before_save')
        for key in ('save_started', 'expected', 'before_save', 'saved_md5', 'skipped'):
            steps.pop(key, None)
    child_id = steps.get('collection_task_id')
    if child_id:
        child = await db.scalar(select(MiaoshouSyncTask).where(MiaoshouSyncTask.id == UUID(child_id),
                                                             MiaoshouSyncTask.owner_id == user.id).with_for_update())
        if child and child.status in ('uncertain', 'failed'):
            # Existing collector recovery queries platform state, never blindly recollects.
            child.status, child.next_poll_at = 'waiting', None
            child.poll_count = 0
    task.steps, task.status, task.next_poll_at = steps, 'queued', None
    task.error_code = task.error_message = task.finished_at = None
    await db.flush()
    return service.task_dto(task)


@router.delete('/tasks/{task_id}')
async def delete_task(task_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    service.operator(user)
    # Same draft -> task lock order as adopt/retry, so a worker claim or adoption cannot interleave.
    task = await service.owned(db, Task, task_id, user.id)
    await service.owned(db, Draft, task.draft_id, user.id, True)
    task = await service.owned(db, Task, task_id, user.id, True)
    if task.status in ('queued', 'running', 'waiting'):
        raise HTTPException(409, '任务仍在执行，完成或失败后才能删除记录')
    if task.kind == 'sync' and task.status == 'uncertain':
        # An unconfirmed save must stay queryable and keep blocking a competing sync.
        raise HTTPException(409, '同步结果尚未确认，请先恢复任务查询妙手结果，避免重复保存')
    await db.delete(task)
    await db.flush()
    return {'id': str(task_id), 'deleted': True}


@router.get('/drafts/{draft_id}/assets')
async def assets(draft_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    await service.owned(db, Draft, draft_id, user.id)
    rows = (await db.scalars(select(Asset).where(Asset.draft_id == draft_id, Asset.owner_id == user.id).order_by(Asset.created_at))).all()
    return {'items': [{k: getattr(x, k) for k in ('id', 'source_url', 'public_url', 'width', 'height', 'sha256', 'status')} for x in rows]}


@router.get('/assets/{asset_id}/file')
async def asset_file(asset_id: UUID, db: AsyncSession = DB, user: User = AUTH):
    asset = await service.owned(db, Asset, asset_id, user.id)
    if not asset.local_name:
        raise HTTPException(404, '本地图片副本尚未保存')
    root = Path(WorkbenchSettings().workbench_asset_directory).resolve()
    file = (root / asset.local_name).resolve()
    if file.parent != root or not file.is_file():
        raise HTTPException(404, '图片副本不存在')
    return FileResponse(file, media_type=asset.mime, headers={'Cache-Control': 'private, no-store'})
