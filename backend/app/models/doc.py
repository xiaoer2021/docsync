"""文档登记与子表缓存。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BigIntPK

SHEET_ACTIVE = "active"
SHEET_RENAMED = "renamed"
SHEET_MISSING = "missing"


class DdDoc(BaseModel):
    "一份登记进来的钉钉文档。"

    __tablename__ = "dd_doc"
    __table_args__ = (
        UniqueConstraint("app_id", "node_id", name="uq_dd_doc_app_node"),
        Index("ix_dd_doc_group", "group_id"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    app_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_app.id"), nullable=False)
    operator_union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("dd_doc_group.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="enabled", nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    watch_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    watch_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_watch_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    last_probe_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_probe_ok: Mapped[bool | None] = mapped_column(nullable=True)
    last_probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_column_check_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    structure_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    structure_drift: Mapped[str | None] = mapped_column(Text, nullable=True)


class DdDocSheet(BaseModel):
    "文档下的子表（钉钉表格的工作表 / 多维表的数据表）。"

    __tablename__ = "dd_doc_sheet"
    __table_args__ = (
        UniqueConstraint("doc_id", "sheet_id", name="uq_dd_doc_sheet"),
        Index("ix_dd_doc_sheet_doc", "doc_id"),
    )

    doc_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_doc.id"), nullable=False)
    sheet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="worksheet", nullable=False)

    field_count: Mapped[int | None] = mapped_column(nullable=True)

    column_names: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    column_types: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)

    auto_column_check: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_column_check_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    column_drift: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=SHEET_ACTIVE, nullable=False)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
