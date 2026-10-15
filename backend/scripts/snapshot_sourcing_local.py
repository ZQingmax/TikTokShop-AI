"""Local data snapshot before additive sourcing migrations; never prints row contents."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from app.config import get_settings
from app.core.database import engine

TABLES = ['alembic_version', 'sourcing_candidates', 'sourcing_suppliers', 'sourcing_analysis_tasks',
          'sourcing_ai_evaluations', 'sourcing_reviews', 'sourcing_miaoshou_tasks', 'discovery_tasks', 'discovery_results']


async def main():
    url = urlsplit(get_settings().database_url)
    if url.hostname not in ('localhost', '127.0.0.1') or url.path != '/tiktok_ops_local':
        raise RuntimeError('Snapshot script only supports the named local development database')
    folder = Path(__file__).resolve().parents[2] / '.runtime' / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('sourcing-before-evidence-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    async with engine.connect() as connection:
        await connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        data = {table: [dict(row) for row in (await connection.execute(text(f'SELECT * FROM "{table}"'))).mappings()]
                for table in TABLES}
    target.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    await engine.dispose()
    print(f'Sourcing data snapshot saved: {target}')
    print(json.dumps({key: len(rows) for key, rows in data.items()}))


if __name__ == '__main__':
    asyncio.run(main())
