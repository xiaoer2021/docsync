"操作审计。"

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mask import mask_text
from app.models.audit import SysAudit
from app.models.rbac import SysUser


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record(
    session: AsyncSession,
    *,
    user: SysUser | None,
    action: str,
    target_type: str,
    target_id: Any = None,
    summary: str | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> SysAudit:
    """写一条审计。不 commit —— 由请求级会话统一提交，和业务改动同生共死。"""
    entry = SysAudit(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
        ip=client_ip(request),
        summary=mask_text(summary) if summary else None,
    )
    session.add(entry)
    return entry
