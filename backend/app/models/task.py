"""同步任务：一条 = 一个子表 → 一张目标表。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BigIntPK

WRITE_UPSERT = "upsert"
WRITE_APPEND = "append"
WRITE_REPLACE_PARTITION = "replace_partition"
WRITE_FULL_REPLACE = "full_replace"
WRITE_MODES = (WRITE_UPSERT, WRITE_APPEND, WRITE_REPLACE_PARTITION, WRITE_FULL_REPLACE)

WRITE_MODE_LABELS = {
    WRITE_UPSERT: "按主键更新",
    WRITE_APPEND: "只追加",
    WRITE_REPLACE_PARTITION: "按分区覆盖",
    WRITE_FULL_REPLACE: "整表重写",
}

COL_TYPES = ("text", "int", "float", "decimal", "date", "datetime", "bool", "json")

COL_TYPE_LABELS = {
    "text": "文本",
    "int": "整数",
    "float": "小数",
    "decimal": "金额",
    "date": "日期",
    "datetime": "日期时间",
    "bool": "是否",
    "json": "JSON",
}

TRANSFORMS = (
    "trim",
    "number",
    "date",
    "percent",
    "bool",
    "fullwidth_to_half",
    "json_stringify",
    "upper",
    "lower",
)

TRANSFORM_LABELS = {
    "trim": "去空格",
    "number": "去千分位/货币符号",
    "date": "日期解析",
    "percent": "百分比转小数",
    "bool": "是/否转真假",
    "fullwidth_to_half": "全角转半角",
    "json_stringify": "转 JSON 文本",
    "upper": "转大写",
    "lower": "转小写",
}

SCHEDULE_MANUAL = "manual"
SCHEDULE_CRON = "cron"
SCHEDULE_INTERVAL = "interval"
SCHEDULE_KINDS = (SCHEDULE_MANUAL, SCHEDULE_CRON, SCHEDULE_INTERVAL)

ON_ERROR_STOP = "stop"
ON_ERROR_SKIP = "skip"
ON_ERROR_MODES = (ON_ERROR_STOP, ON_ERROR_SKIP)

TASK_ENABLED = "enabled"
TASK_PAUSED = "paused"


class DdTask(BaseModel):
    "同步任务。"

    __tablename__ = "dd_task"
    __table_args__ = (
        UniqueConstraint("code", name="uq_dd_task_code"),
        UniqueConstraint("doc_id", "sheet_id", name="uq_dd_task_doc_sheet"),
        Index("ix_dd_task_next_run", "next_run_at", "status"),
        Index("ix_dd_task_doc", "doc_id"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)

    doc_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_doc.id"), nullable=False)
    sheet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    engine: Mapped[str] = mapped_column(String(16), default="sheet", nullable=False)
    template_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("dd_template.id"), nullable=True)
    group_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("dd_doc_group.id"), nullable=True)

    source_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    dedupe: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    target: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    post_actions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=TASK_ENABLED, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    @property
    def target_table(self) -> str:
        return str((self.target or {}).get("table_name") or "")

    @property
    def write_mode(self) -> str:
        return str((self.target or {}).get("write_mode") or WRITE_UPSERT)
