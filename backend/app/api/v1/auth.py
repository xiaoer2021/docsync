"""登录、当前用户、改口令。"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.rbac import SysUser
from app.schemas.auth import LoginRequest, LoginResponse, PasswordChange, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, session: DbSession) -> LoginResponse:
    user = await session.scalar(select(SysUser).where(SysUser.username == payload.username))

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或口令不正确")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用，请联系管理员")

    user.last_login_at = dt.datetime.now()
    audit.record(
        session,
        user=user,
        action="login",
        target_type="user",
        target_id=user.id,
        summary=f"{user.username} 登录",
        request=request,
    )

    return LoginResponse(
        token=create_access_token(user.id, username=user.username, role=user.role),
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserOut.model_validate(user, from_attributes=True),
    )


@router.post("/logout")
async def logout(request: Request, session: DbSession, user: CurrentUser) -> dict[str, str]:
    "登出。"
    audit.record(
        session,
        user=user,
        action="logout",
        target_type="user",
        target_id=user.id,
        summary=f"{user.username} 登出",
        request=request,
    )
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/password")
async def change_password(
    payload: PasswordChange, request: Request, session: DbSession, user: CurrentUser
) -> dict[str, str]:
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原口令不正确")
    if payload.old_password == payload.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新口令不能与原口令相同")

    user.password_hash = hash_password(payload.new_password)
    audit.record(
        session,
        user=user,
        action="update",
        target_type="user",
        target_id=user.id,
        summary=f"{user.username} 修改口令",
        request=request,
    )
    return {"status": "ok"}
