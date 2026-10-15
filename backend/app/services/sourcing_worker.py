"""Run separately: python -m app.services.sourcing_worker.

PostgreSQL advisory slots bound concurrency across worker processes. Row locks
claim tasks, leases fence writes; ambiguous interrupted calls need manual retry.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from app.core.database import async_session_factory, engine
from app.models.sourcing import SourcingCandidate as Candidate, SourcingTask as Task, SourcingEvaluation as Evaluation
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


class SourcingWorker:
    def __init__(self, sessions=async_session_factory, settings=None, vision_factory=None, text_factory=None, evidence_factory=None):
        self.sessions = sessions
        self.settings = settings or SourcingSettings()
        self.evidence_factory = evidence_factory

    async def recover_expired(self):
        async with self.sessions() as db, db.begin():
            await db.execute(update(Task).where(Task.status == 'running', Task.lease_until < now()).values(
                status='failed', stage='interrupted', error_code='worker_interrupted',
                error_message='Worker 中断或租约到期；上游可能已计费，需人工重试；已保存资料不会丢失',
                finished_at=now(), lease_token=None, lease_until=None))

    async def claim(self):
        async with self.sessions() as db, db.begin():
            task = await db.scalar(select(Task).where(Task.status == 'queued',
                      or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now()))
                      .order_by(Task.created_at).with_for_update(skip_locked=True).limit(1))
            if not task:
                return None
            task.status, task.stage = 'running', 'evidence'
            task.attempts += 1
            task.lease_token, task.lease_until = uuid.uuid4(), now() + timedelta(seconds=90)
            return task

    async def heartbeat(self, task):
        while True:
            await asyncio.sleep(20)
            async with self.sessions() as db, db.begin():
                result = await db.execute(update(Task).where(Task.id == task.id, Task.status == 'running',
                                           Task.lease_token == task.lease_token).values(lease_until=now() + timedelta(seconds=90)))
                if not result.rowcount:
                    return

    async def execute(self, task):
        async with self.sessions() as db:
            candidate = await db.get(Candidate, task.candidate_id)
            if candidate.version != task.input_version:
                raise AnalysisError('input_changed', '商品资料已修改，请提交当前版本分析')
        from app.services.market_evidence import EvidenceProvider
        text_result = await (self.evidence_factory or EvidenceProvider)(self.settings, task.model_config).analyze(task.snapshot)
        async with self.sessions() as db, db.begin():
            candidate = await db.scalar(select(Candidate).where(Candidate.id == task.candidate_id).with_for_update())
            current = await db.scalar(select(Task).where(Task.id == task.id).with_for_update())
            if current.status != 'running' or current.lease_token != task.lease_token:
                raise AnalysisError('lease_lost', '任务租约失效，结果未写入')
            if candidate.version != task.input_version:
                raise AnalysisError('input_changed', '分析期间商品资料已改变；旧输入结果不进入审核')
            db.add(Evaluation(candidate_id=task.candidate_id, task_id=task.id, input_version=task.input_version,
                   visual_score=None, vision=None, text_analysis=text_result['output'], text_status='succeeded',
                   rule_score=0, rule_basis=[],
                   evidence={'kind': 'market_evidence_v2', 'config': task.model_config,
                             'input_snapshot': task.snapshot,
                             'text': {k: v for k, v in text_result.items() if k != 'output'}}))
            current.status, current.stage, current.finished_at = 'succeeded', 'complete', now()
            current.lease_token = current.lease_until = None
            current.error_code = current.error_message = None

    async def fail(self, task, error):
        async with self.sessions() as db, db.begin():
            current = await db.scalar(select(Task).where(Task.id == task.id).with_for_update())
            if current.status != 'running' or current.lease_token != task.lease_token:
                return
            retry = error.retryable and current.attempts < self.settings.sourcing_max_attempts
            current.status = 'queued' if retry else 'failed'
            current.error_code, current.error_message = error.code, error.message
            current.next_attempt_at = now() + timedelta(seconds=10 * 2 ** (current.attempts - 1)) if retry else None
            current.finished_at = None if retry else now()
            current.lease_token = current.lease_until = None

    async def process_one(self):
        task = await self.claim()
        if not task:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(task))
        try:
            await asyncio.wait_for(self.execute(task), timeout=2 * self.settings.sourcing_model_timeout + 75)
        except AnalysisError as error:
            await self.fail(task, error)
        except asyncio.TimeoutError:
            await self.fail(task, AnalysisError('task_timeout', '任务总执行时间超限；上游可能已计费，请人工重试'))
        except Exception as error:
            # Never log credentials, upstream content or exception text.
            logger.error('Sourcing task %s failed: %s', task.id, type(error).__name__)
            await self.fail(task, AnalysisError('worker_error', '后台执行失败，请检查服务端日志中的错误类型后重试'))
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def slot(self, slot_id):
        while True:
            async with engine.connect() as connection:
                acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(861260, :slot)'), {'slot': slot_id})
                await connection.commit()
                if acquired:
                    try:
                        await self.recover_expired()
                        processed = await self.process_one()
                    finally:
                        await connection.execute(text('SELECT pg_advisory_unlock(861260, :slot)'), {'slot': slot_id})
                        await connection.commit()
                else:
                    processed = False
            if not processed:
                await asyncio.sleep(2)

    async def run(self):
        await asyncio.gather(*(self.slot(i) for i in range(self.settings.sourcing_worker_concurrency)))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    async def run_workers():
        from app.services.miaoshou_sync_worker import MiaoshouSyncWorker
        from app.services.discovery.orchestrator import DiscoveryOrchestrator
        from app.services.workbench_worker import WorkbenchWorker
        from app.services.listing_worker import ListingWorker
        from app.services.order_sync_worker import OrderSyncWorker
        await asyncio.gather(SourcingWorker().run(), MiaoshouSyncWorker().run(), DiscoveryOrchestrator().run(), WorkbenchWorker().run(),
                             ListingWorker().run(), OrderSyncWorker().run())
    asyncio.run(run_workers())
