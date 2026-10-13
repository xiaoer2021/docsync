"""账号管理（仅管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.security import hash_password
from app.models.rbac import ROLES, SysUser
from app.schemas.auth import UserCreate, UserOut, UserResetPassword, UserUpdate
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])


async def _count_active_admins(session: DbSession, *, exclude_id: int | None = None) -> int:
    stmt = (
        select(func.count()).select_from(SysUser).where(SysUser.role == "admin", SysUser.status == "enabled")
    )
    if exclude_id is not None:
        stmt = stmt.where(SysUser.id != exclude_id)
    return int(await session.scalar(stmt) or 0)


async def _get_user(session: DbSession, user_id: int) -> SysUser:
    user = await session.get(SysUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    return user


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"角色只能是 {' 或 '.join(ROLES)}")
    return role


@router.get("", response_model=list[UserOut])
async def list_users(session: DbSession, _: CurrentUser) -> list[UserOut]:
    """所有登录用户都能看到账号清单 —— 界面上要显示「这条是谁改的」。"""
    rows = (await session.scalars(select(SysUser).order_by(SysUser.id))).all()
    return [UserOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, request: Request, session: DbSession, admin: AdminUser) -> UserOut:
    _validate_role(payload.role)
    exists = await session.scalar(select(SysUser.id).where(SysUser.username == payload.username))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")

    user = SysUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        role=payload.role,
        remark=payload.remark,
    )
    session.add(user)
    await session.flush()

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="user",
        target_id=user.id,
        summary=f"新建账号 {user.username}（{user.role}）",
        request=request,
    )
    return UserOut.model_validate(user, from_attributes=True)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: UserUpdate, request: Request, session: DbSession, admin: AdminUser
) -> UserOut:
    user = await _get_user(session, user_id)

    if payload.role is not None:
        _validate_role(payload.role)

        if (
            user.role == "admin"
            and payload.role != "admin"
            and await _count_active_admins(session, exclude_id=user.id) == 0
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少要保留一个管理员")

    if payload.status is not None:
        if payload.status not in ("enabled", "disabled"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是 enabled 或 disabled")
        if (
            payload.status == "disabled"
            and user.role == "admin"
            and await _count_active_admins(session, exclude_id=user.id) == 0
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少要保留一个启用的管理员")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
    if payload.remark is not None:
        user.remark = payload.remark

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="user",
        target_id=user.id,
        summary=f"修改账号 {user.username}",
        detail=payload.model_dump(exclude_unset=True, exclude={"new_password"}),
        request=request,
    )
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/{user_id}/password")
async def reset_password(
    user_id: int, payload: UserResetPassword, request: Request, session: DbSession, admin: AdminUser
) -> dict[str, str]:
    user = await _get_user(session, user_id)
    user.password_hash = hash_password(payload.new_password)
    audit.record(
        session,
        user=admin,
        action="update",
        target_type="user",
        target_id=user.id,
        summary=f"重置 {user.username} 的口令",
        request=request,
    )
    return {"status": "ok"}


@router.delete("/{user_id}")
async def delete_user(user_id: int, request: Request, session: DbSession, admin: AdminUser) -> dict[str, str]:
    user = await _get_user(session, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    if user.role == "admin" and await _count_active_admins(session, exclude_id=user.id) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少要保留一个管理员")

    username = user.username
    await session.delete(user)
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="user",
        target_id=user_id,
        summary=f"删除账号 {username}",
        request=request,
    )
    return {"status": "ok"}
