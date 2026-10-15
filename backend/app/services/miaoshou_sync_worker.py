"""Collection submits once. All recovery and retries only query platform state."""
import asyncio
import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from sqlalchemy import or_, select, text, update
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.core.database import async_session_factory, engine
from app.models.sourcing import MiaoshouSyncTask as Job
from app.services.miaoshou_mapping import store_detail
from app.services.miaoshou_tasks import item_done
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError
from app.services.sourcing_sources import MiaoshouSourceAdapter
from app.services import sourcing_service

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


class MiaoshouSyncWorker:
    def __init__(self, sessions=async_session_factory, settings=None, client=None):
        self.sessions = sessions
        self.settings = settings or SourcingSettings()
        self.client = client or MiaoshouClient(self.settings)
        self.adapter = MiaoshouSourceAdapter(self.settings, self.client)

    async def recover_expired(self):
        async with self.sessions() as db, db.begin():
            jobs = (await db.scalars(select(Job).where(Job.status == 'running', Job.lease_until < now()).with_for_update(skip_locked=True))).all()
            for job in jobs:
                job.status, job.stage = 'waiting', 'reconcile'
                job.error_code, job.error_message = 'worker_interrupted', 'Worker 租约到期，接下来只查询平台状态，不重复采集'
                job.lease_token = job.lease_until = None
                job.next_poll_at = now()

    async def claim(self):
        async with self.sessions() as db, db.begin():
            job = await db.scalar(select(Job).where(Job.status.in_(['queued', 'waiting']), or_(Job.next_poll_at.is_(None), Job.next_poll_at <= now()))
                                  .order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            job.status, job.lease_token, job.lease_until = 'running', uuid.uuid4(), now() + timedelta(seconds=90)
            return job

    async def locked(self, db, job):
        current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
        if current.status != 'running' or current.lease_token != job.lease_token:
            raise AnalysisError('lease_lost', '采集任务租约失效，已停止写入')
        return current

    async def heartbeat(self, job):
        while True:
            await asyncio.sleep(20)
            async with self.sessions() as db, db.begin():
                r = await db.execute(update(Job).where(Job.id == job.id, Job.status == 'running', Job.lease_token == job.lease_token).values(lease_until=now() + timedelta(seconds=90)))
                if not r.rowcount:
                    return

    async def save_items(self, job, items, stage, response=None):
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, job)
            current.items, current.stage = copy.deepcopy(items), stage
            if response is not None:
                current.submitted_response = response

    async def find_existing(self, source_id):
        response = await self.client.get_common_list(page_size=500, source_id=source_id)
        # Actual platform responses contain skip records alongside the usable success record.
        for row in sorted(response.data['detailList'], key=lambda x: x.get('status') != 'success'):
            if any(str(s.get('sourceItemId')) == source_id and s.get('source') == '1688' for s in row.get('sourceList') or []):
                return str(row['commonCollectBoxDetailId'])
        return None

    async def find_claimed(self, item):
        """在 TikTok 采集箱中按货源 ID 查找由该公共采集箱商品认领出的记录。"""
        response = await self.client.get_tiktok_list(page_size=500, source_id=item['source_item_id'])
        for row in response.data['detailList']:
            if str(row.get('commonCollectBoxDetailId')) == str(item['common_detail_id']) and row.get('collectBoxDetailId'):
                return str(row['collectBoxDetailId'])
        return None

    async def claim_platform(self, job, items):
        """认领只提交一次：提交前持久化标记，之后只查询 TikTok 采集箱确认结果。"""
        waiting = [x for x in items if x.get('state') == 'saved' and x.get('claim_platform') and not x.get('platform_detail_id')]
        for item in waiting:
            found = await self.find_claimed(item)
            if found:
                item['platform_detail_id'] = found
                item.pop('error', None)
                item.pop('error_code', None)
        submit = [x for x in waiting if not x.get('platform_detail_id') and not x.get('claim_submitted')]
        if submit:
            for item in submit:
                item['claim_submitted'] = True
            await self.save_items(job, items, 'claiming_once')
            response = await self.client.claim_to_platform([x['common_detail_id'] for x in submit], 'tiktok')
            for item in submit:
                item['claim_response'] = response.data
                found = await self.find_claimed(item)
                if found:
                    item['platform_detail_id'] = found
                else:
                    item['error_code'], item['error'] = 'claim_not_confirmed', '已提交认领，TikTok 采集箱暂未查到记录，稍后自动复查'
            await self.save_items(job, items, 'awaiting_claim')
        for item in waiting:
            if not item.get('platform_detail_id') and item.get('claim_submitted') and item not in submit:
                item['error_code'], item['error'] = 'claim_not_confirmed', '已提交认领，TikTok 采集箱暂未查到记录，稍后自动复查'

    async def mark_external_started(self, job):
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, job)
            if current.external_started_at is not None:
                raise AnalysisError('already_submitted', '采集请求已发出，禁止重复提交')
            current.external_started_at, current.stage = now(), 'submitting_once'
            job.external_started_at = current.external_started_at

    async def perform(self, job):
        items = copy.deepcopy(job.items)
        may_submit = job.kind == 'collect' and job.external_started_at is None and job.stage in ('queued', 'preflight')
        for item in items:
            if item.get('state') == 'saved':
                continue
            if not item.get('common_detail_id') and item.get('source_item_id'):
                existing = await self.find_existing(item['source_item_id'])
                if existing:
                    item['common_detail_id'], item['reused_platform'] = existing, may_submit
        await self.save_items(job, items, 'preflight' if may_submit else 'reconcile')
        missing = [x for x in items if not x.get('common_detail_id')]
        if missing and may_submit:
            # Commit an irreversible submission marker BEFORE network I/O. Even process death cannot resend.
            await self.mark_external_started(job)
            response = await self.client.fetch_items([x['url'] for x in missing])
            mapping = response.data['sourceItemIdAndDetailIdMap']
            for item in missing:
                if item['source_item_id'] in mapping:
                    item['common_detail_id'] = str(mapping[item['source_item_id']])
                    item['state'] = 'awaiting_details'
            await self.save_items(job, items, 'awaiting_details', response.envelope)
        for item in items:
            if item.get('state') == 'saved' or not item.get('common_detail_id'):
                continue
            try:
                response = await self.client.get_common_detail(item['common_detail_id'])
                record = {**response.data, '_response_envelope': response.envelope, '_raw_response_text': response.raw_text}
                async with self.sessions() as db, db.begin():
                    current = await self.locked(db, job)
                    result = await store_detail(db, self.adapter, record, item['common_detail_id'], job.owner_id, job.target_market, job.currency)
                    item.update(candidate_id=result['id'], state='saved', sync_status=result['sync_status'], completeness=result['completeness'], updated=result.get('updated', False))
                    item.pop('error', None)
                    item.pop('error_code', None)
                    if item.get('analyze_after_sync') and result['completeness'] == 'ready':
                        candidate = await sourcing_service.owned(db, uuid.UUID(result['id']), job.owner_id, lock=True)
                        analysis, _ = await sourcing_service.enqueue(db, candidate, job.owner_id, job.id)
                        item['analysis_task_id'] = str(analysis.id)
                    current.items = copy.deepcopy(items)
            except (AnalysisError, ValidationError, ValueError, TypeError, KeyError) as error:
                item['state'], item['error_code'], item['error'] = 'awaiting_details', getattr(error, 'code', 'source_mapping'), getattr(error, 'message', '详情字段尚未完整或格式需核实，未填入模拟数据')
            except MiaoshouError as error:
                item['state'], item['error_code'], item['error'] = 'awaiting_details', error.code, error.message
                if error.category in ('auth', 'permission', 'rate_limit'):
                    await self.save_items(job, items, 'reconcile')
                    raise
        try:
            await self.claim_platform(job, items)
        except MiaoshouError as error:
            for item in items:
                if item.get('state') == 'saved' and item.get('claim_platform') and not item.get('platform_detail_id'):
                    item['error_code'], item['error'] = error.code, error.message
                    if not error.uncertain:
                        # 平台明确拒绝（鉴权/权限/限流）时请求未生效，允许下次重新提交认领
                        item.pop('claim_submitted', None)
            if error.category in ('auth', 'permission', 'rate_limit'):
                await self.save_items(job, items, 'reconcile')
                raise
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, job)
            current.items = copy.deepcopy(items)
            current.poll_count += 1
            done = all(item_done(x) for x in items)
            unknown = any(not x.get('common_detail_id') for x in items)
            if done:
                current.status, current.stage, current.finished_at = 'succeeded', 'complete', now()
                current.error_code = current.error_message = None
            elif current.poll_count >= self.settings.miaoshou_max_polls:
                current.status = 'uncertain' if unknown and current.external_started_at else 'failed'
                current.stage, current.finished_at = 'needs_platform_query', now()
                current.error_code, current.error_message = 'platform_not_confirmed', '平台结果尚未确认或详情暂不可用。请查询平台状态，不重复采集。'
            else:
                current.status, current.stage = 'waiting', 'awaiting_details'
                current.next_poll_at = now() + timedelta(seconds=self.settings.miaoshou_poll_interval)
            current.lease_token = current.lease_until = None

    async def handle_error(self, job, error):
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, job)
            uncertain = getattr(error, 'uncertain', False) or (current.external_started_at is not None and current.submitted_response is None and current.stage != 'submitting_once') or (current.external_started_at is not None and not isinstance(error, MiaoshouError))
            current.poll_count += 1
            current.status = ('uncertain' if current.poll_count >= self.settings.miaoshou_max_polls else 'waiting') if uncertain else 'failed'
            current.stage = 'reconcile'
            current.error_code, current.error_message = error.code, error.message
            current.next_poll_at = now() + timedelta(seconds=max(self.settings.miaoshou_poll_interval, getattr(error, 'retry_after', None) or 0))
            current.lease_token = current.lease_until = None
            if current.status in ('failed', 'uncertain'):
                current.finished_at = now()

    async def process_one(self):
        job = await self.claim()
        if not job:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(job))
        try:
            await self.perform(job)
        except (MiaoshouError, AnalysisError) as error:
            if error.code != 'lease_lost':
                await self.handle_error(job, error)
        except Exception as error:
            logger.error('Miaoshou task %s failed: %s', job.id, type(error).__name__)
            await self.handle_error(job, AnalysisError('worker_error', '货源任务执行失败，接下来只能查询或重新同步，不自动重发采集'))
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def run(self):
        while True:
            processed = False
            async with engine.connect() as connection:
                acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(861270)'))
                await connection.commit()
                if acquired:
                    try:
                        await self.recover_expired()
                        processed = await self.process_one()
                    finally:
                        await connection.execute(text('SELECT pg_advisory_unlock(861270)'))
                        await connection.commit()
            if not processed:
                await asyncio.sleep(2)
