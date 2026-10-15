"""Read-only: print alembic version and row counts of business + sourcing + discovery tables."""
import asyncio
import json

from sqlalchemy import text

from app.core.database import engine

TABLES = ['users', 'products', 'orders', 'sourcing_candidates', 'sourcing_analysis_tasks', 'sourcing_ai_evaluations',
          'sourcing_reviews', 'sourcing_miaoshou_tasks', 'discovery_tasks', 'discovery_results', 'sourcing_suppliers']


async def main():
    out = {}
    async with engine.connect() as c:
        out['database'] = await c.scalar(text('select current_database()'))
        out['alembic_version'] = list((await c.execute(text('select version_num from alembic_version'))).scalars())
        for t in TABLES:
            exists = await c.scalar(text('select to_regclass(:t)'), {'t': 'public.' + t})
            out[t] = (await c.scalar(text(f'select count(*) from "{t}"'))) if exists else None
    await engine.dispose()
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
