"""Audit existing ORM baseline before stamping 002; never modify legacy tables.

Default is read-only. Use --adopt only after independent test-db validation.
Empty databases use alembic upgrade head instead. Never reset or drop data.
"""
import argparse
import asyncio
import json
from pathlib import Path
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import get_settings
from app.models import Base


def audit(connection, adopt):
    baseline = MetaData()
    for table in Base.metadata.sorted_tables:
        if not table.name.startswith('sourcing_'):
            table.to_metadata(baseline)
    inspector = inspect(connection)
    actual = set(inspector.get_table_names())
    expected = set(baseline.tables)
    if 'alembic_version' in actual:
        revisions = list(connection.scalars(text('SELECT version_num FROM alembic_version')))
        if revisions:
            raise RuntimeError('Database already versioned; inspect revisions instead of stamping again')
    context = MigrationContext.configure(connection, opts={'compare_type': True,
             'include_object': lambda obj, name, type_, reflected, compare_to: name != 'alembic_version' if type_ == 'table' else True})
    diffs = compare_metadata(context, baseline)
    primary_key_errors = [name for name, table in baseline.tables.items() if name in actual and
                          set(inspector.get_pk_constraint(name)['constrained_columns']) != {c.name for c in table.primary_key.columns}]
    report = {'expected_tables': len(expected), 'actual_tables': len(actual - {'alembic_version'}),
              'missing_tables': sorted(expected - actual), 'schema_differences': [str(d) for d in diffs],
              'primary_key_errors': primary_key_errors, 'matches': not diffs and not primary_key_errors and expected == actual - {'alembic_version'}}
    Path('../.runtime').mkdir(exist_ok=True)
    Path('../.runtime/sourcing-baseline-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if not report['matches']:
        raise RuntimeError('Schema mismatch; refusing stamp. Resolve differences on an independent copy first.')
    if adopt:
        config = Config('alembic.ini')
        config.attributes['connection'] = connection
        command.stamp(config, '002')
        print('Validated existing baseline adopted at 002; no legacy data changed.')


async def main(adopt=False):
    engine = create_async_engine(get_settings().database_url, echo=False)
    async with engine.begin() as connection:
        await connection.execute(text('SELECT pg_advisory_xact_lock(861261)'))
        await connection.run_sync(lambda c: audit(c, adopt))
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--adopt', action='store_true')
    asyncio.run(main(parser.parse_args().adopt))
