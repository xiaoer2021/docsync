"""任务模板：把一套配置复用到多个子表 / 多份文档。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class DdTemplate(BaseModel):
    "一份可复用的同步配置。"

    __tablename__ = "dd_template"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
