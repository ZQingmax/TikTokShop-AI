"""Authentication API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    token_claims,
    token_current,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest, LoginRequest, LoginResponse, RefreshRequest, RegisterRequest, UserResponse,
)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """User login with username and password."""
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token = create_access_token(data=token_claims(user))
    refresh_token = create_refresh_token(data=token_claims(user))

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800,
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    existing = await db.execute(select(User).where(User.username == request.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    user = User(
        username=request.username,
        hashed_password=hash_password(request.password),
        nickname=request.nickname,
        role="operator",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(data=token_claims(user))
    refresh_token = create_refresh_token(data=token_claims(user))

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access token (used by "remember me").

    The user must still exist and be active. A new refresh token is issued each time,
    so an actively used session stays signed in for the configured number of days.
    """
    from jose import JWTError, jwt
    from app.config import get_settings

    settings = get_settings()
    invalid = HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(
            request.refresh_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        raise invalid
    user_id = payload.get("sub")
    if payload.get("type") != "refresh" or not user_id:
        raise invalid
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or not token_current(payload, user):
        raise invalid

    return LoginResponse(
        access_token=create_access_token(data=token_claims(user)),
        refresh_token=create_refresh_token(data=token_claims(user)),
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info."""
    return UserResponse(
        id=str(current_user.id),
        username=current_user.username,
        nickname=current_user.nickname,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat(),
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the signed-in user's password.

    Bumping token_version invalidates every access and refresh token issued so far, on all devices,
    so the client must sign in again with the new password.
    """
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if request.new_password == request.current_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    user.hashed_password = hash_password(request.new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
