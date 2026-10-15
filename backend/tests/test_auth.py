"""Authentication flow unit tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Test successful user registration."""
    response = await client.post("/api/v1/auth/register", json={
        "username": "testuser@example.com",
        "password": "securepass123",
        "nickname": "Test User",
    })
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate(client: AsyncClient):
    """Test duplicate registration."""
    payload = {"username": "dup@example.com", "password": "securepass123", "nickname": "Dup"}
    await client.post("/api/v1/auth/register", json=payload)

    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Test successful login."""
    # Register first
    await client.post("/api/v1/auth/register", json={
        "username": "login@example.com",
        "password": "securepass123",
        "nickname": "Login User",
    })

    # Login
    response = await client.post("/api/v1/auth/login", json={
        "username": "login@example.com",
        "password": "securepass123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    """Test login with wrong password."""
    await client.post("/api/v1/auth/register", json={
        "username": "wrong@example.com",
        "password": "securepass123",
        "nickname": "Wrong Pass",
    })

    response = await client.post("/api/v1/auth/login", json={
        "username": "wrong@example.com",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_authenticated(client: AsyncClient):
    """Test getting current user info with valid token."""
    # Register
    reg = await client.post("/api/v1/auth/register", json={
        "username": "me@example.com",
        "password": "securepass123",
        "nickname": "Me User",
    })
    token = reg.json()["access_token"]

    # Get me
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "me@example.com"


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient):
    """Existing HTTPBearer rejects missing credentials with 403."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    """Test getting current user with invalid token returns 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_accepts_long_email_username(client: AsyncClient):
    """Usernames are often e-mails longer than 20 characters (front-end once limited this)."""
    payload = {"username": "operations.manager@example-company.com", "password": "securepass123", "nickname": "Ops"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    response = await client.post("/api/v1/auth/login", json={"username": payload["username"], "password": payload["password"]})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_token_remember_me(client: AsyncClient):
    """“记住我”：refresh_token 换取可用的新访问令牌，并滚动签发新的 refresh_token。"""
    reg = await client.post("/api/v1/auth/register", json={
        "username": "remember@example.com", "password": "securepass123", "nickname": "Remember"})
    tokens = reg.json()
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"] and data["refresh_token"] and data["expires_in"] > 0
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "remember@example.com"
    # 新的 refresh_token 也能继续使用
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rejects_access_token_garbage_and_disabled_user(client: AsyncClient):
    from sqlalchemy import update
    from app.models.user import User
    from tests.conftest import TestSessionLocal

    reg = await client.post("/api/v1/auth/register", json={
        "username": "disabled@example.com", "password": "securepass123", "nickname": "Disabled"})
    tokens = reg.json()
    # 访问令牌不能当作 refresh_token 使用；伪造或空令牌被拒绝
    for value in (tokens["access_token"], "not-a-jwt"):
        assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": value})).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": ""})).status_code == 422
    # 账号停用后，已记住的会话不能再续期
    async with TestSessionLocal() as db:
        await db.execute(update(User).where(User.username == "disabled@example.com").values(is_active=False))
        await db.commit()
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
