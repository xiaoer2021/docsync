"""平台自身的设置（键值对）。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class DdSetting(BaseModel):
    "平台设置，一个 key 一行。"

    __tablename__ = "dd_setting"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
