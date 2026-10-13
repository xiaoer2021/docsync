"""用户与角色。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)


class SysUser(BaseModel):
    """平台自己的账号。不接外部身份，部署即用。"""

    __tablename__ = "sys_user"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="enabled", nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN and self.status == "enabled"

    @property
    def is_active(self) -> bool:
        return self.status == "enabled"
