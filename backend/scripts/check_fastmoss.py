import asyncio
import sys
from sqlalchemy import text
from app.core.database import engine
from app.services.fastmoss.browser import Browser, upstream


async def main():
    async with engine.connect() as conn:
        ready = await conn.scalar(text("SELECT to_regclass('public.fastmoss_tasks')"))
    await engine.dispose()
    if not ready:
        print('Missing FastMoss migration: run alembic upgrade head after backing up the database.')
        return 1
    browser = Browser()
    upstream(browser.settings)
    if not browser.binary:
        print('BrowserSkill binary not installed')
        return 1
    status = browser.status()
    print(status['message'])
    return 0  # The worker may start before the operator connects the extension.


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
