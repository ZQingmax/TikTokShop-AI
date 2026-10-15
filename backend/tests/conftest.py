"""Integration tests use only explicitly isolated PostgreSQL databases."""
import os
from urllib.parse import urlsplit
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise RuntimeError("Set TEST_DATABASE_URL to an independent PostgreSQL *_test database")
if not urlsplit(TEST_DATABASE_URL).path.removeprefix("/").endswith("_test"):
    raise RuntimeError("Refusing test cleanup outside a *_test database")
if TEST_DATABASE_URL == os.environ.get("DATABASE_URL"):
    raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")

from app.models import Base
from app.core.database import get_db
from app.main import app
from app.config import get_settings
app.state.settings = get_settings()

test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

# Model usage rows written by providers outside a request must land in the test database too.
from app.services import model_settings  # noqa: E402
model_settings.session_factory = TestSessionLocal


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        if not await conn.scalar(text("SELECT to_regclass('public.alembic_version')")):
            raise RuntimeError("Run alembic upgrade head against the test database first")
        tables = ', '.join('"' + t.name + '"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
