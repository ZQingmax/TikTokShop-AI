"""Periodically pulls orders (packages) and purchase orders from Miaoshou. Read-only towards Miaoshou."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from app.clients.miaoshou_client import MiaoshouClient
from app.core.database import async_session_factory, engine
from app.services import order_sync_service
from app.services.sourcing_config import SourcingSettings

logger = logging.getLogger(__name__)
INTERVAL = timedelta(minutes=10)


class OrderSyncWorker:
    def __init__(self, sessions=async_session_factory, client=None):
        self.sessions = sessions
        self.client = client or MiaoshouClient(SourcingSettings())

    async def due(self):
        async with self.sessions() as db:
            last = await db.scalar(text('SELECT min(coalesce(finished_at, started_at)) FROM miaoshou_sync_state'))
            kinds = await db.scalar(text('SELECT count(*) FROM miaoshou_sync_state'))
        return kinds < 2 or last is None or datetime.now(timezone.utc) - last >= INTERVAL

    async def run(self):
        while True:
            try:
                if self.client.configured and await self.due():
                    async with engine.connect() as connection:
                        acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(861272)'))
                        await connection.commit()
                        if acquired:
                            try:
                                await order_sync_service.run(self.sessions, self.client)
                            finally:
                                await connection.execute(text('SELECT pg_advisory_unlock(861272)'))
                                await connection.commit()
            except Exception as error:  # keep the loop alive; the state row records Miaoshou errors
                logger.error('Order sync loop failed: %s', type(error).__name__)
            await asyncio.sleep(60)
