"""Create an isolated empty test database without touching operational data."""
import asyncio
import os
from urllib.parse import urlsplit
import asyncpg


async def main():
    url = os.environ["TEST_DATABASE_URL"]
    name = urlsplit(url).path.removeprefix("/")
    if not name.endswith("_test") or not name.replace('_', '').isalnum():
        raise RuntimeError("Only alphanumeric *_test databases are permitted")
    if url == os.environ.get("DATABASE_URL"):
        raise RuntimeError("Test and operational URLs must differ")
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn.rsplit('/', 1)[0] + '/postgres')
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
        print(f"Isolated database ready: {name}")
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
