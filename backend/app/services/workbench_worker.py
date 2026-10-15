"""Persistent workbench execution; mutations are marked before network I/O."""
import asyncio
import base64
import copy
import hashlib
import io
import logging
import uuid
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, update, or_, text
from app.core.database import async_session_factory, engine
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.models.workbench import WorkbenchTask as Task, WorkbenchDraft as Draft, WorkbenchAsset as Asset
from app.models.sourcing import MiaoshouSyncTask
from app.models.user import User
from app.schemas.miaoshou import CollectInput
from app.schemas.sourcing import public_url
from app.services.workbench_config import WorkbenchSettings
from app.services.workbench_providers import WorkbenchProvider, fetch_workbench_image as fetch_image
from app.services.sourcing_providers import AnalysisError, image_result
from app.services import workbench_service as service
from app.services import model_settings
from app.services.miaoshou_tasks import create_task, item_done

logger = logging.getLogger(__name__)


def cache_image(settings, asset_id, downloaded):
    from PIL import Image
    raw = base64.b64decode(downloaded['data_url'].split(',', 1)[1], validate=True)
    try:
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
            if width <= 0 or height <= 0 or width > 16000 or height > 16000 or width * height > 40000000:
                raise ValueError('dimensions')
            img.verify()
    except Exception:
        raise AnalysisError('image_dimensions', '图片内容无效或像素数量过大') from None
    mime = downloaded['data_url'].split(';', 1)[0].split(':')[1]
    suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[mime]
    root = Path(settings.workbench_asset_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = str(asset_id) + suffix
    tmp = root / (name + '.tmp')
    tmp.write_bytes(raw)
    tmp.replace(root / name)
    return {'local_name': name, 'width': width, 'height': height, 'mime': mime,
            'bytes': len(raw), 'sha256': downloaded['sha256']}


def read_cached(settings, asset, url):
    """Return a cached asset only if the file is inside the asset root and still matches its digest."""
    root = Path(settings.workbench_asset_directory).resolve()
    file = (root / asset.local_name).resolve()
    if file.parent != root or not file.is_file():
        return None
    data = file.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        return None
    return image_result(url, asset.mime, data)


class WorkbenchWorker:
    def __init__(self, sessions=async_session_factory, settings=None, client=None, provider=None):
        self.sessions = sessions
        self.settings = settings or WorkbenchSettings()
        self.client = client or MiaoshouClient(self.settings)
        self.provider = provider or WorkbenchProvider(self.settings)

    def fetch(self, url):
        return fetch_image(url, self.settings.trusted_image_hosts)

    async def input_images(self, job):
        # Adopted results and transferred images already have verified local copies; reuse them
        # instead of downloading again (picture-space hosts may be unverifiable behind Fake-IP DNS).
        images = []
        for url in job.snapshot['operation'].get('image_urls') or []:
            async with self.sessions() as db:
                asset = await db.scalar(select(Asset).where(Asset.owner_id == job.owner_id, Asset.local_name.is_not(None),
                    or_(Asset.public_url == url, Asset.source_url == url)).order_by(Asset.created_at).limit(1))
            cached = await asyncio.to_thread(read_cached, self.settings, asset, url) if asset else None
            images.append(cached or await asyncio.to_thread(self.fetch, url))
        return images

    async def fill_context(self, job):
        """Real platform data the model must choose from: leaf candidates, or the chosen category's rules."""
        snapshot, content = job.snapshot, job.snapshot['content']
        context = {'facts': service.source_hints(snapshot['source']), 'skus': service.sku_labels(content),
                   'categories': [], 'rules': {}, 'category_path': ''}
        if not getattr(self.client, 'configured', False):
            return context
        await self.checkpoint(job, 'loading_categories')
        tree = (await self.client.get_categories(snapshot['market'])).data.get('cateTree') or {}
        cid = content.get('cid')
        if cid and snapshot.get('shop_id'):
            context['category_path'] = next((c['path'] for c in service.category_leaves(tree) if c['cid'] == str(cid)), '')
            metadata = (await self.client.get_category_metadata(snapshot['market'], cid, snapshot['shop_id'])).data
            context['rules'] = service.fill_rules(metadata.get('categoryMetadata') or {})
        else:
            source = snapshot['source']
            text = ' '.join([source.get('name') or '', content.get('title') or '',
                             *(a['value'] for a in context['facts']['attributes'] if a['name'] in ('类型', '套装种类', '型号', '材质'))])
            context['categories'] = service.category_candidates(tree, text)
        return context

    async def locked(self, db, job):
        current = await db.scalar(select(Task).where(Task.id == job.id).with_for_update())
        if not current or current.status != 'running' or current.lease_token != job.lease_token:
            raise AnalysisError('lease_lost', '任务租约失效，执行已停止')
        return current

    async def checkpoint(self, job, stage=None, **values):
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, job)
            if stage:
                current.stage = job.stage = stage
            for key, value in values.items():
                setattr(current, key, copy.deepcopy(value))
                setattr(job, key, copy.deepcopy(value))

    async def mark(self, job, key, value=True, stage=None):
        steps = {**copy.deepcopy(job.steps), key: value}
        await self.checkpoint(job, stage, steps=steps)

    async def waiting(self, job, stage):
        polls = job.steps.get('polls', 0) + 1
        if polls > 120:
            raise AnalysisError('poll_limit', '平台结果长时间未确认，请稍后手动恢复查询')
        await self.checkpoint(job, stage, steps={**job.steps, 'polls': polls}, status='waiting',
                              next_poll_at=service.now() + timedelta(seconds=5), lease_token=None, lease_until=None)

    async def recover_expired(self):
        async with self.sessions() as db, db.begin():
            rows = (await db.scalars(select(Task).where(Task.status == 'running', Task.lease_until < service.now())
                                     .with_for_update(skip_locked=True))).all()
            for job in rows:
                ambiguous = job.steps.get('model_started') and not job.result
                ambiguous = ambiguous or bool(job.steps.get('transfer_started'))
                job.status = 'uncertain' if ambiguous else 'waiting'
                job.error_code, job.error_message = 'worker_interrupted', 'Worker 中断；已保存步骤保留，未确认的外部请求不会自动重复提交'
                job.next_poll_at, job.lease_token, job.lease_until = service.now(), None, None

    async def claim(self, task_id=None):
        async with self.sessions() as db, db.begin():
            query = select(Task).where(Task.status.in_(['queued', 'waiting']),
                or_(Task.next_poll_at.is_(None), Task.next_poll_at <= service.now()))
            if task_id:
                query = query.where(Task.id == task_id)
            job = await db.scalar(query.order_by(Task.created_at).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            job.status, job.lease_token = 'running', uuid.uuid4()
            job.lease_until = service.now() + timedelta(seconds=90)
            job.error_code = job.error_message = None
            return job

    async def heartbeat(self, job):
        while True:
            await asyncio.sleep(20)
            async with self.sessions() as db, db.begin():
                response = await db.execute(update(Task).where(Task.id == job.id, Task.status == 'running',
                    Task.lease_token == job.lease_token).values(lease_until=service.now() + timedelta(seconds=90)))
                if not response.rowcount:
                    return

    async def persist_asset(self, job, url, evidence=None):
        # Asset identity is persisted before downloading or uploading; retries reuse it.
        async with self.sessions() as db, db.begin():
            await self.locked(db, job)
            asset = await db.scalar(select(Asset).where(Asset.owner_id == job.owner_id, Asset.draft_id == job.draft_id,
                                                        or_(Asset.source_url == url, Asset.public_url == url)).order_by(Asset.created_at).limit(1))
            if not asset:
                asset = Asset(owner_id=job.owner_id, draft_id=job.draft_id, source_url=url, evidence=evidence or {})
                db.add(asset)
                await db.flush()
        if asset.status == 'ready':
            return asset
        if not asset.local_name:
            downloaded = await asyncio.to_thread(self.fetch, url)
            fields = await asyncio.to_thread(cache_image, self.settings, asset.id, downloaded)
            async with self.sessions() as db, db.begin():
                await self.locked(db, job)
                current = await db.get(Asset, asset.id)
                for key, value in fields.items():
                    setattr(current, key, value)
                    setattr(asset, key, value)
                current.status = 'cached'
        if job.steps.get('transfer_started'):
            raise AnalysisError('transfer_uncertain', '图片转存请求已发出但结果未确认，请人工确认重新转存')
        await self.mark(job, 'transfer_started', str(asset.id), 'transferring_image')
        response = await self.client.upload_picture(url)
        stable_url = public_url(response.data['picturePath'])
        async with self.sessions() as db, db.begin():
            current_job = await self.locked(db, job)
            current = await db.get(Asset, asset.id)
            current.public_url, current.status = stable_url, 'ready'
            current.evidence = {**current.evidence, 'picture_space': response.data}
            steps = copy.deepcopy(current_job.steps)
            steps.pop('transfer_started', None)
            current_job.steps = job.steps = steps
            asset.public_url, asset.status = stable_url, 'ready'
        return asset

    async def record_usage(self, job, result, status='succeeded'):
        config = job.snapshot.get('config') or {}
        await model_settings.record_usage(
            provider='bailian', scenario=config.get('scenario') or model_settings.KIND_SCENARIO[job.kind],
            model=result.get('model'), usage=result.get('usage'), status=status, request_id=result.get('request_id'),
            source_type='workbench_task', source_id=job.id, user_id=job.owner_id, sessions=self.sessions)

    async def ai(self, job):
        usable_result = any(key in job.result for key in ('output', 'image_url', 'upstream_task_id'))
        if not usable_result:
            if job.steps.get('model_started'):
                raise AnalysisError('model_uncertain', '模型请求已提交但结果未保存，需人工确认重新调用')
            # Inputs load before the billable call is marked, so image failures stay plainly retryable.
            if job.snapshot['operation'].get('image_urls'):
                await self.checkpoint(job, 'loading_images')
            images = await self.input_images(job)
            context = await self.fill_context(job) if job.kind == 'fill' else None
            await self.mark(job, 'model_started', True, 'calling_model')
            try:
                if job.kind == 'fill':
                    result = await self.provider.fill(job.snapshot, context)
                elif job.kind in ('ocr', 'copy'):
                    result = await self.provider.text(job.kind, job.snapshot, images)
                elif job.kind == 'translate':
                    result = await self.provider.translate_submit(job.snapshot, images)
                else:
                    result = await self.provider.image(job.snapshot, images)
            except AnalysisError as error:
                # The model answered but its output was rejected: the call was still billed.
                evidence = getattr(error, 'evidence', None)
                if isinstance(evidence, dict) and evidence.get('model'):
                    await self.record_usage(job, evidence, 'rejected')
                raise
            if job.kind != 'translate':
                # Image translation is billed per finished image; it is logged when the poll succeeds.
                await self.record_usage(job, result)
            await self.checkpoint(job, 'model_saved', result=result)
        if job.kind == 'translate' and not job.result.get('image_url'):
            result = await self.provider.translate_poll(job.snapshot, job.result)
            if result is None:
                await self.waiting(job, 'translation_poll')
                return
            await self.record_usage(job, {**result, 'request_id': result.get('upstream_task_id')})
            await self.checkpoint(job, 'model_saved', result=result)
        if job.kind in ('generate', 'edit', 'translate'):
            asset = await self.persist_asset(job, job.result['image_url'], {k: v for k, v in job.result.items() if k != 'image_url'})
            await self.checkpoint(job, 'image_saved', result={**job.result, 'asset_id': str(asset.id),
                 'public_url': asset.public_url, 'width': asset.width, 'height': asset.height,
                 'original_url': (job.snapshot['operation'].get('image_urls') or [None])[0]})
        await self.checkpoint(job, 'complete', status='succeeded', finished_at=service.now(), lease_token=None, lease_until=None)

    async def collect(self, job):
        child_id = job.steps.get('collection_task_id')
        if not child_id:
            async with self.sessions() as db, db.begin():
                await db.scalar(select(User.id).where(User.id == job.owner_id).with_for_update())
                await self.locked(db, job)
                source = job.snapshot['source']
                data = CollectInput(request_key=uuid.uuid5(job.id, 'collection'), links=[source['product_url']],
                    target_market=job.snapshot['market'], currency=source.get('currency') or 'CNY',
                    analyze_after_sync=False, claim_platform='tiktok')
                child, _ = await create_task(db, job.owner_id, data, 'collect')
                child_id = str(child.id)
                current = await self.locked(db, job)
                current.steps = job.steps = {**job.steps, 'collection_task_id': child_id}
                current.stage = 'collecting_source'
        async with self.sessions() as db:
            child = await db.get(MiaoshouSyncTask, uuid.UUID(child_id))
        if child.status in ('failed', 'uncertain'):
            raise AnalysisError('collection_unconfirmed', '底层采集任务尚未确认，请恢复查询；不会重复采集')
        if child.status != 'succeeded' or not child.items or not item_done(child.items[0]):
            await self.waiting(job, 'collecting_source')
            return None
        item = child.items[0]
        await self.mark(job, 'common_detail_id', item['common_detail_id'])
        await self.mark(job, 'platform_detail_id', item['platform_detail_id'])
        return item['platform_detail_id']

    async def sync(self, job):
        snapshot = job.snapshot
        platform_id = job.steps.get('platform_detail_id') or snapshot.get('platform_detail_id')
        if not platform_id:
            platform_id = await self.collect(job)
            if not platform_id:
                return
        shop_id = snapshot['shop_id']
        await service.shop_for(self.client, snapshot['market'], shop_id)
        remote = (await self.client.get_shop_detail(platform_id, shop_id)).data
        claimed = any(str(x) == str(shop_id) for x in remote.get('claimToShopIds') or [])
        if not claimed:
            if not job.steps.get('shop_claim_started'):
                await self.mark(job, 'shop_claim_started', True, 'claiming_shop')
                await self.client.claim_to_shop(platform_id, shop_id)
            await self.waiting(job, 'confirming_shop_claim')
            return
        if job.steps.get('save_started'):
            # Query-only reconciliation after a possibly successful save.
            if self.readback_matches(remote['shopCollectItemInfo'], job.steps['expected']):
                await self.finish_sync(job, remote, platform_id)
                return
            if service.normalize_remote(remote['shopCollectItemInfo']) == job.steps.get('before_save'):
                # Still unchanged: do not blindly resubmit an ambiguous request.
                await self.waiting(job, 'confirming_save')
                return
            raise AnalysisError('remote_conflict', '远端商品发生变化，未覆盖；请在妙手与本地草稿对比')
        previous = job.steps.get('previous_expected')
        if previous and self.readback_matches(remote['shopCollectItemInfo'], previous):
            await self.finish_sync(job, remote, platform_id)  # the unconfirmed save had landed after all
            return
        baseline = job.steps.get('resubmit_baseline') or snapshot.get('remote_snapshot')
        overwrite = (snapshot.get('operation') or {}).get('overwrite_remote')
        if baseline and not overwrite and service.normalize_remote(remote['shopCollectItemInfo']) != baseline:
            raise AnalysisError('remote_conflict', '妙手采集箱中的商品自上次同步后被修改，已停止覆盖；确认后可以草稿内容覆盖')
        expected = job.steps.get('expected')
        if not expected:
            # The collect box holds drafts: save every finished field now and leave unfinished ones
            # as they are in Miaoshou (reported back), instead of blocking the whole sync.
            check_draft = type('CheckDraft', (), {'shop_id': shop_id, 'market': snapshot['market'], 'content': snapshot['content']})()
            skipped = service.unsynced_fields(await service.preflight(self.client, check_draft))
            await self.mark(job, 'skipped', skipped)
            content = copy.deepcopy(snapshot['content'])
            uploads = dict(job.steps.get('uploaded_images') or {})
            sku_images = 'skuPropertyList' not in skipped
            urls = list(content['imgUrls']) if 'imgUrls' not in skipped else []
            for prop in (content.get('skuPropertyList') or []) if sku_images else []:
                for value in prop.get('attrValueList') or []:
                    if value.get('imgUrl'):
                        urls.append(value['imgUrl'])
            if content.get('sizeChart') and 'sizeChart' not in skipped:
                urls.append(content['sizeChart'])
            for url in dict.fromkeys(urls):
                if url not in uploads:
                    asset = await self.persist_asset(job, url)
                    uploads[url] = asset.public_url
                    await self.mark(job, 'uploaded_images', uploads)
            if 'imgUrls' not in skipped:
                content['imgUrls'] = [uploads[x] for x in content['imgUrls']]
            for prop in (content.get('skuPropertyList') or []) if sku_images else []:
                for value in prop.get('attrValueList') or []:
                    if value.get('imgUrl'):
                        value['imgUrl'] = uploads[value['imgUrl']]
            if content.get('sizeChart') and 'sizeChart' not in skipped:
                content['sizeChart'] = uploads[content['sizeChart']]
            expected = service.managed(service.platform_value_ids(content), exclude=skipped)
            await self.mark(job, 'expected', expected)
        # Re-read after slow image transfers and detect edits made while preparing the request.
        latest = (await self.client.get_shop_detail(platform_id, shop_id)).data
        if service.normalize_remote(latest['shopCollectItemInfo']) != service.normalize_remote(remote['shopCollectItemInfo']):
            raise AnalysisError('remote_conflict', '图片转存期间妙手商品被修改，已停止覆盖')
        merged = {**copy.deepcopy(latest['shopCollectItemInfo']), **expected,
                  'shopId': shop_id, 'detailId': int(platform_id), 'editModel': 'shop'}
        for key, sku in (expected.get('skuMap') or {}).items():  # only SKUs we send; skipped ones stay as-is
            # Same SKU shape as Miaoshou's own: blank identifiers, and a display price that follows the
            # new price unless Miaoshou keeps a different (VAT-inclusive) one.
            old = (latest['shopCollectItemInfo'].get('skuMap') or {}).get(key, {})
            merged['skuMap'][key] = {'identifierCode': '', 'identifierCodeType': '', **old, **sku}
            if sku.get('price') is not None and ('priceIncludeVat' not in old or old.get('priceIncludeVat') == old.get('price')):
                merged['skuMap'][key]['priceIncludeVat'] = sku['price']
        await self.mark(job, 'before_save', service.normalize_remote(latest['shopCollectItemInfo']))
        await self.mark(job, 'save_started', True, 'saving_shop_draft')
        response = await self.client.save_shop_detail(platform_id, shop_id, latest['ossMd5'], merged)
        await self.mark(job, 'saved_md5', response.data['ossMd5'], 'reading_back')
        remote = (await self.client.get_shop_detail(platform_id, shop_id)).data
        if not self.readback_matches(remote['shopCollectItemInfo'], expected):
            await self.waiting(job, 'confirming_save')
            return
        await self.finish_sync(job, remote, platform_id)

    @staticmethod
    def readback_matches(remote, expected):
        # The documented GET schema does not return this constant save-only option.
        expected = {k: v for k, v in expected.items() if k != 'deliveryOptionSetType'}
        if 'notes' in expected:
            # Generated description HTML may come back re-serialized; compare its normalized form.
            remote = {**remote, 'notes': service.normalize_notes(remote.get('notes'))}
            expected = {**expected, 'notes': service.normalize_notes(expected['notes'])}
        return service.matches_expected(remote, expected)

    async def finish_sync(self, job, remote, platform_id):
        async with self.sessions() as db, db.begin():
            # Same lock order as API mutations.
            draft = await db.scalar(select(Draft).where(Draft.id == job.draft_id).with_for_update())
            current = await self.locked(db, job)
            draft.common_detail_id = job.steps.get('common_detail_id') or job.snapshot.get('common_detail_id')
            draft.platform_detail_id = str(platform_id)
            draft.remote_snapshot = service.normalize_remote(remote['shopCollectItemInfo'])
            draft.remote_md5, draft.synced_version = remote['ossMd5'], job.input_version
            current.result = {'platform_detail_id': str(platform_id), 'shop_id': job.snapshot['shop_id'],
                              'synced_version': job.input_version, 'ossMd5': remote['ossMd5'], 'readback_confirmed': True,
                              'first_sync': not job.snapshot.get('remote_snapshot'), 'skipped': job.steps.get('skipped') or []}
            current.status, current.stage, current.finished_at = 'succeeded', 'complete', service.now()
            current.lease_token = current.lease_until = None

    async def fail(self, job, error):
        async with self.sessions() as db, db.begin():
            current = await db.scalar(select(Task).where(Task.id == job.id).with_for_update())
            if current.status != 'running' or current.lease_token != job.lease_token:
                return
            uncertain = bool(getattr(error, 'uncertain', False)) or error.code in ('model_uncertain', 'transfer_uncertain', 'task_timeout')
            steps = copy.deepcopy(current.steps)
            if isinstance(error, MiaoshouError) and not error.uncertain:
                if current.stage == 'transferring_image':
                    steps.pop('transfer_started', None)
                elif current.stage == 'saving_shop_draft':
                    steps.pop('save_started', None)
                elif current.stage == 'claiming_shop':
                    steps.pop('shop_claim_started', None)
            if current.kind != 'sync' and not any(key in current.result for key in ('output', 'image_url', 'upstream_task_id')) and not uncertain:
                steps.pop('model_started', None)
            if getattr(error, 'evidence', None):
                current.result = copy.deepcopy(error.evidence)
            # A submitted save must remain queryable and must block a fresh competing sync.
            if steps.get('save_started') and error.code != 'remote_conflict':
                uncertain = True
            current.steps, current.status = steps, 'uncertain' if uncertain else 'failed'
            current.error_code, current.error_message = error.code, error.message
            current.finished_at, current.lease_token, current.lease_until = service.now(), None, None

    async def process_one(self, task_id=None):
        job = await self.claim(task_id)
        if not job:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(job))
        try:
            await asyncio.wait_for(self.sync(job) if job.kind == 'sync' else self.ai(job), timeout=self.settings.workbench_timeout * 3 + 120)
        except (AnalysisError, MiaoshouError) as error:
            await self.fail(job, error)
        except asyncio.TimeoutError:
            await self.fail(job, AnalysisError('task_timeout', '任务执行超时，请查询已提交请求或人工恢复'))
        except Exception as error:
            logger.error('Workbench job %s failed: %s', job.id, type(error).__name__)
            # Unknown exceptions after submission must never implicitly permit another call.
            await self.fail(job, AnalysisError('task_timeout', '后台执行中断，已保存结果保留；请查询任务或人工恢复'))
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def run(self):
        while True:
            async with engine.connect() as connection:
                acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(861280)'))
                await connection.commit()
                processed = False
                if acquired:
                    try:
                        await self.recover_expired()
                        processed = await self.process_one()
                    finally:
                        await connection.execute(text('SELECT pg_advisory_unlock(861280)'))
                        await connection.commit()
            if not processed:
                await asyncio.sleep(2)
