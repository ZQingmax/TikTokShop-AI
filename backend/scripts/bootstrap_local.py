"""Initialize only the dedicated local database; never reset existing data."""

import asyncio
import os

import asyncpg


async def main():
    url = os.environ["DATABASE_URL"]
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    if not dsn.endswith("/tiktok_ops_local"):
        raise RuntimeError("Local bootstrap only supports the tiktok_ops_local database")
    connection = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", "tiktok_ops_local"
        )
        if exists:
            print("Local database already exists; preserving all data.")
            return
        await connection.execute('CREATE DATABASE "tiktok_ops_local"')
    finally:
        await connection.close()

    from scripts.seed_data import seed_data

    await seed_data()


if __name__ == "__main__":
    asyncio.run(main())
