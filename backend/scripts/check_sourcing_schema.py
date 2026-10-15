"""Read-only startup verification; no implicit migration or stamp."""
import asyncio
from sqlalchemy import text
from app.core.database import engine
from alembic.config import Config
from alembic.script import ScriptDirectory


async def main():
    async with engine.connect() as connection:
        versions = list((await connection.execute(text('SELECT version_num FROM alembic_version'))).scalars())
        expected = ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()
        if versions != [expected]:
            raise RuntimeError('Apply independently validated sourcing migrations first')
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
