"""Runs listing tasks: check every item, submit each shop's passing items once, then only query results."""
import asyncio
import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select, text, update
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from app.core.database import async_session_factory, engine
from app.models.listing import ListingTask as Job
from app.services.listing_publish_service import PENDING, Checker, find_record, record_failure
from app.services.sourcing_config import SourcingSettings

logger = logging.getLogger(__name__)
POLL_SECONDS = 15
MAX_POLLS = 40  # about 10 minutes of waiting for Miaoshou to report results
FATAL = ('auth', 'permission', 'rate_limit', 'configuration')


def now():
    return datetime.now(timezone.utc)


class LeaseLost(Exception):
    pass


class ListingWorker:
    def __init__(self, sessions=async_session_factory, settings=None, client=None):
        self.sessions = sessions
        self.settings = settings or SourcingSettings()
        self.client = client or MiaoshouClient(self.settings)

    async def recover_expired(self):
        async with self.sessions() as db, db.begin():
            jobs = (await db.scalars(select(Job).where(Job.status == 'running', Job.lease_until < now()).with_for_update(skip_locked=True))).all()
            for job in jobs:
                # An interrupted submit may have reached Miaoshou: those items are only queried from now on.
                items = copy.deepcopy(job.items)
                for item in items:
                    if item['state'] == 'submitting':
                        item['state'], item['error'] = 'uncertain', 'Worker 中断时发布请求可能已到达妙手，只查询结果，不重发'
                job.items, job.status, job.lease_token, job.lease_until, job.next_poll_at = items, 'waiting', None, None, now()

    async def claim(self):
        async with self.sessions() as db, db.begin():
            job = await db.scalar(select(Job).where(Job.status.in_(['queued', 'waiting']), or_(Job.next_poll_at.is_(None), Job.next_poll_at <= now()))
                                  .order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            job.status, job.lease_token, job.lease_until = 'running', uuid.uuid4(), now() + timedelta(seconds=120)
            return job

    async def heartbeat(self, job):
        while True:
            await asyncio.sleep(30)
            async with self.sessions() as db, db.begin():
                r = await db.execute(update(Job).where(Job.id == job.id, Job.status == 'running', Job.lease_token == job.lease_token)
                                     .values(lease_until=now() + timedelta(seconds=120)))
                if not r.rowcount:
                    return

    async def save(self, job, items, stage, **values):
        async with self.sessions() as db, db.begin():
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current.status != 'running' or current.lease_token != job.lease_token:
                raise LeaseLost()
            current.items, current.stage = copy.deepcopy(items), stage
            for key, value in values.items():
                setattr(current, key, value)

    async def check(self, job, items):
        checker = Checker(self.client, job.market)
        for item in items:
            if item['state'] != 'pending':
                continue
            try:
                title, errors, warnings = await checker.check(item['detail_id'], item['shop_id'])
            except MiaoshouError as error:
                if error.category in FATAL:
                    raise
                title, errors, warnings = None, [{'field': 'platform', 'message': error.message}], []
            if title:
                item['title'] = title
            item['errors'], item['warnings'] = errors, warnings
            item['state'] = 'blocked' if errors else 'ready'
            await self.save(job, items, 'checking')

    async def submit(self, job, items):
        shops = sorted({x['shop_id'] for x in items if x['state'] == 'ready'})
        for shop_id in shops:
            group = [x for x in items if x['state'] == 'ready' and x['shop_id'] == shop_id]
            for item in group:
                item['state'] = 'submitting'
            # Persist before the call: a crash after this point never resubmits these items.
            await self.save(job, items, 'submitting')
            try:
                await self.client.publish([x['detail_id'] for x in group], [shop_id])
                state, message = 'submitted', None
            except MiaoshouError as error:
                state = 'uncertain' if error.uncertain else 'failed'
                message = error.message
                if error.category in FATAL:
                    for item in group:
                        item['state'], item['error'] = state, message
                    await self.save(job, items, 'submitting')
                    raise
            for item in group:
                item['state'] = state
                if message:
                    item['error'] = message
            await self.save(job, items, 'submitting')

    async def resolve(self, items):
        waiting = [x for x in items if x['state'] in PENDING]
        if not waiting:
            return
        published = await Checker(self.client, None).published_ids()
        records = []
        for page in range(1, 4):
            rows = (await self.client.get_publish_records(page, 100)).data.get('moveCollectDetailList') or []
            records += rows
            if len(rows) < 100:
                break
        for item in waiting:
            record = find_record(records, item['detail_id'])
            if record:
                item['record'] = record
            if item['detail_id'] in published:
                item['state'] = 'published'
                item.pop('error', None)
            elif failure := record_failure(record):
                item['state'], item['error'] = 'failed', failure

    async def perform(self, job):
        items = copy.deepcopy(job.items)
        await self.check(job, items)
        if job.kind == 'publish':
            await self.submit(job, items)
            await self.resolve(items)
        pending = any(x['state'] in PENDING for x in items)
        poll_count = job.poll_count + (1 if job.kind == 'publish' and job.stage in ('submitting', 'waiting_result') else 0)
        if pending and poll_count < MAX_POLLS:
            await self.save(job, items, 'waiting_result', status='waiting', poll_count=poll_count,
                            next_poll_at=now() + timedelta(seconds=POLL_SECONDS), lease_token=None, lease_until=None)
            return
        good = 'ready' if job.kind == 'check' else 'published'
        if pending:
            status, code, message = 'uncertain', 'result_not_confirmed', '妙手尚未返回部分商品的发布结果，请稍后查询；不会自动重发'
        elif all(x['state'] == good for x in items):
            status, code, message = 'succeeded', None, None
        elif any(x['state'] == good for x in items):
            status, code, message = 'partial', None, None
        else:
            status, code, message = 'failed', None, None
        await self.save(job, items, 'complete', status=status, poll_count=poll_count, error_code=code, error_message=message,
                        finished_at=now(), lease_token=None, lease_until=None)

    async def fail(self, job, error):
        async with self.sessions() as db, db.begin():
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current.status != 'running' or current.lease_token != job.lease_token:
                return
            unresolved = any(x['state'] in PENDING for x in current.items)
            current.status = 'uncertain' if unresolved else 'failed'
            current.error_code = getattr(error, 'code', 'worker_error')
            current.error_message = getattr(error, 'message', '上架任务执行失败；已提交的商品只查询结果，不重发')
            current.lease_token = current.lease_until = None
            current.finished_at = now()

    async def process_one(self):
        job = await self.claim()
        if not job:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(job))
        try:
            await self.perform(job)
        except LeaseLost:
            pass
        except MiaoshouError as error:
            await self.fail(job, error)
        except Exception as error:
            logger.error('Listing task %s failed: %s', job.id, type(error).__name__)
            await self.fail(job, error)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def run(self):
        while True:
            processed = False
            async with engine.connect() as connection:
                acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(861271)'))
                await connection.commit()
                if acquired:
                    try:
                        await self.recover_expired()
                        processed = await self.process_one()
                    finally:
                        await connection.execute(text('SELECT pg_advisory_unlock(861271)'))
                        await connection.commit()
            if not processed:
                await asyncio.sleep(2)
