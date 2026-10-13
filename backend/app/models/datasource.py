"""目标库（数据源）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

DB_TYPE_SQLSERVER = "sqlserver"
DB_TYPE_MYSQL = "mysql"
DB_TYPES = (DB_TYPE_SQLSERVER, DB_TYPE_MYSQL)


class DdDatasource(BaseModel):
    "要写进去的目标库。"

    __tablename__ = "dd_datasource"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    db_type: Mapped[str] = mapped_column(String(16), default=DB_TYPE_SQLSERVER, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=1433, nullable=False)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)

    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
