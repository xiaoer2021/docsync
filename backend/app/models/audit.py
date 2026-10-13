"""操作审计。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BigIntPK


class SysAudit(BaseModel):
    """谁在什么时候改了什么。写操作一律留痕。"""

    __tablename__ = "sys_audit"
    __table_args__ = (Index("ix_sys_audit_created", "created_at"),)

    user_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
