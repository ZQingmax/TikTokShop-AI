from contextlib import asynccontextmanager
from sqlalchemy import text
from .config import BROWSER_LOCK


@asynccontextmanager
async def browser_lock(engine):
    # Session-level lock is shared by catalog requests and every worker process.
    async with engine.connect() as conn:
        locked = await conn.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': BROWSER_LOCK})
        await conn.commit()
        try:
            yield conn if locked else None
        finally:
            if locked:
                try:
                    await conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': BROWSER_LOCK})
                    await conn.commit()
                except Exception:
                    await conn.invalidate()
