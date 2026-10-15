"""Verify ORM-created baseline adoption only on an independent *_test database."""
import asyncio
import os
from urllib.parse import urlsplit
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, func, inspect, select
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base, User
from scripts.adopt_sourcing_baseline import audit


def verify(connection):
    if inspect(connection).get_table_names():
        raise RuntimeError('This verification requires a freshly created empty *_test database; no reset is performed')
    baseline = MetaData()
    for table in Base.metadata.sorted_tables:
        if not table.name.startswith('sourcing_'):
            table.to_metadata(baseline)
    baseline.create_all(connection)
    import uuid
    sentinel_id = uuid.uuid4()
    connection.execute(User.__table__.insert().values(id=sentinel_id, username='migration-sentinel', nickname='test sentinel', hashed_password='TEST_ONLY', role='operator', is_active=True))
    audit(connection, True)
    config = Config('alembic.ini')
    config.attributes['connection'] = connection
    command.upgrade(config, 'head')
    assert connection.scalar(select(func.count()).select_from(User).where(User.id == sentinel_id)) == 1
    diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    if diffs:
        raise RuntimeError('Migrated schema differs from current metadata')
    print('PASS: ORM baseline audited + adopted + upgraded; sentinel data preserved; metadata matches')


async def main():
    url = os.environ['TEST_DATABASE_URL']
    if not urlsplit(url).path.endswith('_test') or url == os.environ.get('DATABASE_URL'):
        raise RuntimeError('Independent *_test URL required')
    os.environ['DATABASE_URL'] = url
    from app.config import get_settings
    get_settings.cache_clear()
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(verify)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
