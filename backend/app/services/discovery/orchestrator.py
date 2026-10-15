"""DiscoveryOrchestrator: persistent, resumable agent workflow driven by the existing worker process.

queued → planning → searching → filtering (candidate pool) → analyzing (text evidence only)
       → completed | partial_failed | failed        (cancelled only before execution / while awaiting confirmation)

Safety properties
* State, plan, search progress, budget usage and per-stage errors live in PostgreSQL; every stage is idempotent,
  so a restarted worker resumes from `resume_stage` without redoing finished work.
* Budget is reserved and COMMITTED before each external call (search / model). A crash can waste at most the
  reserved call, never exceed the budget.
* Collection is delegated to the existing Miaoshou task (deterministic request_key → submitted at most once;
  existing common-box items are synced, not resubmitted; timeouts only query platform state).
* Analysis reuses the existing AI queue (same candidate/version/config reuses an existing task, no double cost).
"""
import asyncio
import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, text, update

from app.core.database import async_session_factory, engine
from app.models.discovery import DiscoveryResult as Result, DiscoveryTask as Task
from app.models.sourcing import MiaoshouSyncTask, SourcingCandidate as Candidate, SourcingEvaluation as Evaluation, SourcingTask as AnalysisTask
from app.schemas.miaoshou import CollectInput
from app.services import sourcing_service
from app.services.discovery.adapters import default_adapter
from app.services.discovery.base import DiscoveryError
from app.services.discovery.config import DiscoverySettings
from app.services.discovery.dedupe import DiscoveryDeduplicator
from app.services.discovery.normalizer import DiscoveryResultNormalizer, NormalizedResult
from app.services.discovery.planner import SearchQueryPlanner
from app.services.miaoshou_tasks import create_task as create_miaoshou_task
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError

logger = logging.getLogger(__name__)
RUNNABLE = ('queued', 'planning', 'searching', 'filtering', 'collecting', 'analyzing')
LOCK_ID = 861280
COLLECT_NS = uuid.UUID('6f1d1e0e-4c55-4a52-9f6b-3d0a8f1c2b10')


def now():
    return datetime.now(timezone.utc)


class LeaseLost(Exception):
    pass


class Wait(Exception):
    """Release the lease and run again later (polling sub-tasks, rate limits)."""
    def __init__(self, seconds, message):
        super().__init__(message)
        self.seconds, self.message = seconds, message


class DiscoveryOrchestrator:
    def __init__(self, sessions=async_session_factory, settings=None, sourcing_settings=None, adapter=None,
                 planner=None, scorer=None):
        self.sessions = sessions
        self.settings = settings or DiscoverySettings()
        self.sourcing_settings = sourcing_settings or SourcingSettings()
        self.adapter = adapter or default_adapter()
        self.planner = planner or SearchQueryPlanner(self.sourcing_settings)
        self.normalizer = DiscoveryResultNormalizer()
        self.dedupe = DiscoveryDeduplicator()

    # ---------------- lease infrastructure (same pattern as existing workers) ----------------
    async def recover_expired(self):
        async with self.sessions() as db, db.begin():
            rows = (await db.scalars(select(Task).where(Task.lease_token.is_not(None), Task.lease_until < now())
                                     .with_for_update(skip_locked=True))).all()
            for task in rows:
                task.lease_token = task.lease_until = None
                task.next_run_at = now()
                task.stage_errors = [*task.stage_errors, {'stage': task.resume_stage, 'code': 'worker_interrupted', 'at': now().isoformat(),
                                     'message': 'Worker 中断或租约到期；从已持久化的阶段继续，已完成的外部调用不重复'}]

    async def claim(self):
        async with self.sessions() as db, db.begin():
            task = await db.scalar(select(Task).where(Task.status.in_(RUNNABLE), Task.lease_token.is_(None),
                                                      Task.next_run_at.is_not(None), Task.next_run_at <= now())
                                   .order_by(Task.next_run_at).with_for_update(skip_locked=True).limit(1))
            if not task:
                return None
            task.lease_token, task.lease_until = uuid.uuid4(), now() + timedelta(seconds=90)
            task.attempts += 1
            if task.status == 'queued':
                task.status = task.resume_stage
            return task

    async def locked(self, db, task):
        current = await db.scalar(select(Task).where(Task.id == task.id).with_for_update())
        if current.lease_token != task.lease_token:
            raise LeaseLost()
        return current

    async def heartbeat(self, task):
        while True:
            await asyncio.sleep(20)
            async with self.sessions() as db, db.begin():
                r = await db.execute(update(Task).where(Task.id == task.id, Task.lease_token == task.lease_token)
                                     .values(lease_until=now() + timedelta(seconds=90)))
                if not r.rowcount:
                    return

    async def save(self, task, **values):
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, task)
            for k, v in values.items():
                setattr(current, k, v)
                setattr(task, k, v)

    async def add_error(self, task, stage, code, message):
        entry = {'stage': stage, 'code': code, 'message': message, 'at': now().isoformat()}
        await self.save(task, stage_errors=[*task.stage_errors, entry])

    async def reserve(self, task, kind, amount=1):
        """Commit the reservation before the external call."""
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, task)
            usage = dict(current.usage)
            if usage.get(kind, 0) + amount > current.budget[kind]:
                return False
            usage[kind] = usage.get(kind, 0) + amount
            current.usage = task.usage = usage
            return True

    async def advance(self, task, stage, message):
        await self.save(task, status=stage, resume_stage=stage, progress_message=message)

    async def finish(self, task, status, message):
        await self.save(task, status=status, progress_message=message, finished_at=now(), next_run_at=None)

    # ---------------- stages ----------------
    async def stage_planning(self, task):
        if task.plan is None:
            if not await self.reserve(task, 'model_calls'):
                raise DiscoveryError('budget_exhausted', '模型调用预算不足，无法规划关键词', 'budget')
            try:
                plan = await self.planner.plan(task.goal, task.budget['keywords'])
            except AnalysisError as error:
                await self.add_error(task, 'planning', error.code, error.message)
                await self.finish(task, 'failed', f'关键词规划失败：{error.message}')
                return False
            if plan.get('planner_error'):
                await self.add_error(task, 'planning', plan['planner_error']['code'],
                                     'DeepSeek 规划失败，仅使用用户输入的关键词：' + plan['planner_error']['message'])
            await self.save(task, plan=plan)
        await self.advance(task, 'searching', f"已生成 {len(task.plan['keywords'])} 个搜索关键词，开始搜索真实货源")
        return True

    async def stage_searching(self, task):
        log = copy.deepcopy(task.search_log or [])
        done = {e['key'] for e in log if e.get('state') in ('done', 'error', 'skipped_budget')}
        exclude = task.goal.get('exclude_words', [])
        limit = task.goal['max_candidates']
        fatal = None
        for kw in task.plan['keywords']:
            for page in range(task.budget['pages_per_keyword']):
                key = f"{kw['keyword']}#{page}"
                if key in done:
                    continue
                async with self.sessions() as db:
                    found = await db.scalar(select(func.count(Result.id)).where(Result.task_id == task.id))
                if found >= limit:
                    break
                if page > 0 and any(e['key'] == f"{kw['keyword']}#{page - 1}" and not e.get('more_available') for e in log):
                    break
                query = self.adapter.build_query(kw['keyword'], exclude)
                entry = {'key': key, 'keyword': kw['keyword'], 'query': query, 'page': page, 'provider': self.adapter.provider.name,
                         'source_platform': self.adapter.source_platform}
                if not await self.reserve(task, 'search_calls'):
                    log.append({**entry, 'state': 'skipped_budget', 'at': now().isoformat()})
                    await self.save(task, search_log=log, progress_message='搜索调用预算已用完')
                    fatal = fatal or 'budget'
                    break
                try:
                    result = await self.adapter.search(query, page)
                except DiscoveryError as error:
                    log.append({**entry, 'state': 'error', 'error_code': error.code, 'error': error.message, 'at': now().isoformat()})
                    await self.save(task, search_log=log)
                    await self.add_error(task, 'searching', error.code, f"{kw['keyword']}: {error.message}")
                    if error.category in ('configuration', 'auth', 'permission'):
                        fatal = error.category
                        break
                    if error.category == 'rate_limit':
                        log.pop()  # allow this query again after cooldown (budget already counted)
                        await self.save(task, search_log=log)
                        raise Wait(60, '1688 CLI 正忙，60 秒后继续搜索')
                    continue
                accepted, rejected, inserted = 0, {}, 0
                discovered_at = now()
                expires = discovered_at + timedelta(hours=self.settings.discovery_snippet_retention_hours)
                async with self.sessions() as db, db.begin():
                    await self.locked(db, task)
                    for hit in result.hits:
                        item = self.normalizer.normalize(hit, kw['keyword'], query, self.adapter.provider.name, exclude)
                        if isinstance(item, NormalizedResult):
                            accepted += 1
                            count = await db.scalar(select(func.count(Result.id)).where(Result.task_id == task.id))
                            if count >= limit:
                                rejected['over_limit'] = rejected.get('over_limit', 0) + 1
                                continue
                            inserted += await self.dedupe.insert_unique(db, task, item, discovered_at, expires)
                        else:
                            reason = item.reason.split(':')[0]
                            rejected[reason] = rejected.get(reason, 0) + 1
                log.append({**entry, 'state': 'done', 'at': discovered_at.isoformat(), 'result_count': len(result.hits),
                            'offer_hits': accepted, 'new_unique': inserted, 'duplicates_in_task': accepted - inserted - rejected.get('over_limit', 0),
                            'rejected': rejected, 'more_available': result.more_available,
                            'http_status': result.meta.get('http_status')})
                await self.save(task, search_log=log, progress_message=f"“{kw['keyword']}”第 {page + 1} 页：{len(result.hits)} 条结果，{accepted} 条 1688 商品链接，新增 {inserted}")
            if fatal:
                break
        async with self.sessions() as db:
            total = await db.scalar(select(func.count(Result.id)).where(Result.task_id == task.id))
        if total == 0:
            reason = {'configuration': '搜索数据源未配置', 'auth': '搜索数据源鉴权失败', 'permission': '搜索数据源无权限',
                      'budget': '搜索预算用完'}.get(fatal, '搜索数据源没有返回任何 1688 商品链接')
            await self.finish(task, 'failed', f'{reason}；未伪造商品，任务结束（阻塞已记录）')
            return False
        await self.advance(task, 'filtering', f'共发现 {total} 件真实 1688 商品，开始去重筛选')
        return True

    async def stage_filtering(self, task):
        from app.services.alibaba1688.candidates import to_candidate_input
        from app.services.market_evidence import MarketRow
        low = Decimal(str(task.goal['price_min'])) if task.goal.get('price_min') is not None else None
        high = Decimal(str(task.goal['price_max'])) if task.goal.get('price_max') is not None else None
        async with self.sessions() as db, db.begin():
            current = await self.locked(db, task)
            rows = (await db.scalars(select(Result).where(Result.task_id == task.id,
                Result.status == 'discovered').order_by(Result.search_position, Result.id))).all()
            await self.dedupe.annotate_existing(db, task, rows)
            for row in rows:
                record = row.source_snapshot or {'offer_id': row.source_item_id,
                    'product_url': row.canonical_url, 'title': row.snippet_title}
                data = to_candidate_input(record, False, task.goal['target_market'])
                price = data.purchase_price
                if (low is not None or high is not None) and (price is None or
                        (low is not None and price < low) or (high is not None and price > high)):
                    row.status, row.status_reason = 'price_filtered', '采购价未知或不在设定区间，未入库'
                    continue
                result = await sourcing_service.import_one(db, data, task.owner_id, '1688_cli',
                    {'provider': '1688_cli', 'detail_fetched': False, 'discovery_task_id': str(task.id)})
                candidate = await sourcing_service.owned(db, uuid.UUID(result['id']), task.owner_id, lock=True)
                evidence = {e['evidence_id']: e for e in candidate.market_evidence or []}
                before = list(evidence.values())
                evidence.update({e['evidence_id']: e for e in task.goal.get('market_evidence', [])})
                candidate.market_evidence = list(evidence.values())
                if before != candidate.market_evidence and result['status'] == 'duplicate':
                    candidate.version += 1
                    await db.execute(update(Evaluation).where(Evaluation.candidate_id == candidate.id).values(stale=True))
                if result['status'] == 'imported':
                    price_info = record.get('price') or {}
                    candidate.source_price_min = price_info.get('min')
                    candidate.source_price_max = price_info.get('max')
                    candidate.min_order_quantity = record.get('min_order_quantity')
                    candidate.trust_status = 'platform_session'
                row.candidate_id = candidate.id
                if candidate.review_status == 'rejected':
                    row.status, row.status_reason = 'filtered_out', '候选已被人工排除，保留原决定并关联新依据'
                    continue
                if not candidate.name:
                    row.status, row.status_reason = 'incomplete', '资料待补充；已保存有效来源链接'
                    continue
                if current.usage['model_calls'] >= current.budget['model_calls']:
                    row.status, row.status_reason = 'skipped_budget', '已入库待分析；模型预算用完'
                    continue
                analysis, reused = await sourcing_service.enqueue(db, candidate, task.owner_id, task.id)
                if not reused:
                    current.usage = {**current.usage, 'model_calls': current.usage['model_calls'] + 1}
                row.status, row.analysis_task_id = 'analyzing', analysis.id
            current.wait_started_at = task.wait_started_at = now()
        await self.advance(task, 'analyzing', '货源已去重入库，进行文字证据分析；未调用妙手采集')
        return True

    async def stage_analyzing(self, task):
        async with self.sessions() as db, db.begin():
            await self.locked(db, task)
            rows = (await db.scalars(select(Result).where(Result.task_id == task.id))).all()
            waiting = 0
            for row in rows:
                if row.status != 'analyzing':
                    continue
                analysis = await db.get(AnalysisTask, row.analysis_task_id)
                if analysis.status == 'succeeded':
                    evaluation = await db.scalar(select(Evaluation).where(Evaluation.task_id == analysis.id))
                    if evaluation:
                        row.status, row.evaluation_id, row.assessment = 'analyzed', evaluation.id, evaluation.text_analysis
                    else:
                        row.status, row.status_reason = 'analysis_failed', '未找到分析记录'
                elif analysis.status == 'failed':
                    row.status, row.status_reason = 'analysis_failed', analysis.error_message
                elif task.wait_started_at and now() - task.wait_started_at > timedelta(minutes=self.settings.discovery_wait_timeout_minutes):
                    row.status, row.status_reason = 'analysis_failed', '等待分析超时，可从候选库查询分析任务'
                else:
                    waiting += 1
            saved = sum(r.candidate_id is not None for r in rows)
            failed = sum(r.status in ('analysis_failed', 'skipped_budget') for r in rows)
        if waiting:
            await self.save(task, progress_message=f'文字证据分析中：{waiting} 件待完成')
            raise Wait(self.settings.discovery_poll_interval, '等待证据分析')
        status = 'partial_failed' if failed or task.stage_errors else 'completed'
        await self.finish(task, status, f'完成：{saved} 件已关联候选库，{failed} 件分析未完成；请人工勾选后采集到妙手')
        return False

    # ---------------- driver ----------------
    STAGES = {'planning': 'stage_planning', 'searching': 'stage_searching', 'filtering': 'stage_filtering',
              'analyzing': 'stage_analyzing'}

    async def perform(self, task):
        if task.goal.get('workflow_version') != 2:
            await self.finish(task, 'cancelled', '旧流程已停用，请重新创建选品任务')
            return
        while task.status in self.STAGES:
            proceed = await getattr(self, self.STAGES[task.status])(task)
            if not proceed:
                return

    async def release(self, task, next_run_at=None):
        async with self.sessions() as db, db.begin():
            await db.execute(update(Task).where(Task.id == task.id, Task.lease_token == task.lease_token)
                             .values(lease_token=None, lease_until=None, next_run_at=next_run_at))

    async def process_one(self):
        task = await self.claim()
        if not task:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(task))
        next_run = None
        try:
            await self.perform(task)
        except Wait as wait:
            next_run = now() + timedelta(seconds=wait.seconds)
        except LeaseLost:
            return True
        except DiscoveryError as error:
            await self.add_error(task, task.status, error.code, error.message)
            await self.finish(task, 'failed', f'{error.message}')
        except Exception as error:  # never log upstream content or secrets
            logger.error('Discovery task %s failed: %s', task.id, type(error).__name__)
            try:
                await self.add_error(task, task.status, 'worker_error', f'后台执行异常（{type(error).__name__}），可查看服务端日志')
                if task.attempts >= 5:
                    await self.finish(task, 'failed', '多次执行异常，任务终止；已完成的数据保留')
                else:
                    next_run = now() + timedelta(seconds=30)
            except LeaseLost:
                return True
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        await self.release(task, next_run)
        return True

    async def purge_snippets(self):
        async with self.sessions() as db, db.begin():
            await db.execute(update(Result).where(Result.snippet_expires_at < now(), Result.snippet_title.is_not(None))
                             .values(snippet_title=None))

    async def run(self):
        last_purge = 0.0
        while True:
            processed = False
            async with engine.connect() as connection:
                acquired = await connection.scalar(text(f'SELECT pg_try_advisory_lock({LOCK_ID})'))
                await connection.commit()
                if acquired:
                    try:
                        await self.recover_expired()
                        if asyncio.get_running_loop().time() - last_purge > 600:
                            await self.purge_snippets()
                            last_purge = asyncio.get_running_loop().time()
                        processed = await self.process_one()
                    finally:
                        await connection.execute(text(f'SELECT pg_advisory_unlock({LOCK_ID})'))
                        await connection.commit()
            if not processed:
                await asyncio.sleep(2)
