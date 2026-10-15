"""Run locally with: python -m app.services.fastmoss.worker."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update, text
from app.core.database import async_session_factory, engine
from app.models.fastmoss import FastmossTask
from app.models.sourcing import MarketReport
from .browser import Browser, BrowserError
from .locking import browser_lock
from .normalize import normalize_rows, merge_rows, encode_csv

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


class Worker:
    def __init__(self, sessions=async_session_factory, db_engine=engine, browser_factory=Browser):
        self.sessions, self.engine, self.browser_factory = sessions, db_engine, browser_factory

    async def save_progress(self, task_id, **values):
        async with self.sessions() as db, db.begin():
            await db.execute(update(FastmossTask).where(FastmossTask.id == task_id, FastmossTask.status == 'running').values(**values))

    def collect_category(self, market, category, pages):
        with self.browser_factory() as browser:
            # Refresh actual taxonomy before every category: stale IDs never silently map to new labels.
            live = {c['id']: c for c in browser.catalog(market)}
            if category['id'] not in live or live[category['id']]['path'] != category['path']:
                raise BrowserError('所选分类已变化，请刷新分类并重新选择')
            return browser.scrape(market, category, pages)

    async def execute(self, task, lock_connection):
        rows, raw_rows, outcomes = [], [], []
        truncated = False
        for index, category in enumerate(task.categories):
            if len(rows) >= 500:
                truncated = True
                outcomes.append({'category': category, 'status': 'skipped', 'error': '已达到 500 条上限'})
                continue
            await self.save_progress(task.id, progress=f'抓取 {index + 1}/{len(task.categories)}：' + ' / '.join(category['path']))
            try:
                raw = await asyncio.to_thread(self.collect_category, task.target_market, category, task.pages)
                if not raw:
                    raise BrowserError('该品类没有抓取到商品')
                converted = normalize_rows(raw, task.target_market, fetched_at=now().isoformat(), category=category)
                combined = merge_rows([*rows, *converted])
                truncated = truncated or len(combined) > 500 or len(raw) >= 500
                rows = combined[:500]
                raw_rows.extend(raw)
                outcomes.append({'category': category, 'status': 'succeeded', 'rows': len(converted)})
            except (BrowserError, ValueError) as exc:
                outcomes.append({'category': category, 'status': 'failed', 'error': str(exc)[:300]})
            # A lost advisory-lock connection invalidates this worker's right to publish.
            await lock_connection.execute(text('SELECT 1'))
            await lock_connection.commit()
            await self.save_progress(task.id, category_results=list(outcomes), row_count=len(rows), progress='转换并保存市场依据')
        async with self.sessions() as db, db.begin():
            current = await db.scalar(select(FastmossTask).where(FastmossTask.id == task.id).with_for_update())
            if current.status != 'running':
                return
            if rows:
                report = MarketReport(owner_id=task.owner_id, name=f'FastMoss {task.target_market} 家居选品 {now():%Y-%m-%d %H:%M}',
                    target_market=task.target_market, scope='market', rows=rows,
                    fingerprint=hashlib.sha256(json.dumps([str(task.id), rows], sort_keys=True).encode()).hexdigest())
                db.add(report)
                await db.flush()
                current.report_id = report.id
                current.raw_csv = encode_csv(raw_rows)
            failed = any(x['status'] == 'failed' for x in outcomes)
            current.status = ('partial' if failed else 'succeeded') if rows else 'failed'
            current.error = '部分分类失败，请查看明细并重新抓取' if failed and rows else ('没有可用商品，请查看分类错误' if not rows else None)
            current.progress = f'已保存 {len(rows)} 条商品' + ('；达到 500 条上限，结果已截断' if truncated else '')
            current.row_count, current.category_results = len(rows), outcomes
            current.truncated, current.finished_at = truncated, now()

    async def process_one(self):
        async with browser_lock(self.engine) as connection:
            if connection is None:
                return False
            async with self.sessions() as db, db.begin():
                # Holding the global browser lock proves no other healthy worker is collecting.
                await db.execute(update(FastmossTask).where(FastmossTask.status == 'running').values(
                    status='failed', error='本机 Worker 中断，请重新抓取', finished_at=now()))
                task = await db.scalar(select(FastmossTask).where(FastmossTask.status == 'queued')
                    .order_by(FastmossTask.created_at).with_for_update(skip_locked=True).limit(1))
                if task is None:
                    return False
                task.status, task.progress = 'running', '准备浏览器及分类'
            try:
                await self.execute(task, connection)
            except Exception as exc:
                logger.error('FastMoss task %s failed: %s', task.id, type(exc).__name__)
                await self.save_progress(task.id, status='failed', error='后台执行中断，请检查日志并重新抓取', finished_at=now())
            return True


async def main():
    worker = Worker()
    while True:
        try:
            if not await worker.process_one():
                await asyncio.sleep(2)
        except Exception as exc:
            logger.error('FastMoss worker unavailable: %s', type(exc).__name__)
            await asyncio.sleep(5)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
