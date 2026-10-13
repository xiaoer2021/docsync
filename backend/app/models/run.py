"""执行记账：一次同步的所有痕迹。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BigIntPK

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"
RUN_TIMEOUT = "timeout"
RUN_CANCELED = "canceled"
RUN_PARTIAL = "partial"

RUN_STATUS_LABELS = {
    RUN_QUEUED: "排队中",
    RUN_RUNNING: "运行中",
    RUN_SUCCESS: "成功",
    RUN_FAILED: "失败",
    RUN_TIMEOUT: "超时",
    RUN_CANCELED: "已取消",
    RUN_PARTIAL: "部分成功",
}

TRIGGER_SCHEDULE = "schedule"
TRIGGER_MANUAL = "manual"
TRIGGER_RETRY = "retry"
TRIGGER_CHECK = "check"

TRIGGER_LABELS = {
    TRIGGER_SCHEDULE: "定时任务",
    TRIGGER_MANUAL: "手动运行",
    TRIGGER_RETRY: "重试",
    TRIGGER_CHECK: "测试运行",
}

LOG_STDOUT = "stdout"
LOG_STDERR = "stderr"


class DdRun(BaseModel):
    """一次执行实例。"""

    __tablename__ = "dd_run"
    __table_args__ = (
        Index("ix_dd_run_task_started", "task_id", "started_at"),
        Index("ix_dd_run_status", "status"),
    )

    task_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_task.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), default=TRIGGER_MANUAL, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RUN_QUEUED, nullable=False)

    queued_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    rows_read: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_inserted: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_unchanged: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(default=0, nullable=False)
    batches: Mapped[int] = mapped_column(default=0, nullable=False)

    dry_run: Mapped[bool] = mapped_column(default=False, nullable=False)
    row_limit: Mapped[int | None] = mapped_column(nullable=True)

    log_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    log_bytes: Mapped[int] = mapped_column(default=0, nullable=False)

    triggered_by: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)


class DdRunLog(BaseModel):
    """入库的日志片段。大日志只落盘，不进来。"""

    __tablename__ = "dd_run_log"
    __table_args__ = (Index("ix_dd_run_log_run_seq", "run_id", "seq"),)

    run_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_run.id"), nullable=False)
    seq: Mapped[int] = mapped_column(default=0, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, nullable=False)
    stream: Mapped[str] = mapped_column(String(8), default=LOG_STDOUT, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class DdRunAction(BaseModel):
    "每个后置动作的执行结果。"

    __tablename__ = "dd_run_action"
    __table_args__ = (Index("ix_dd_run_action_run", "run_id"),)

    run_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_run.id"), nullable=False)
    action_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    action_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trigger_on: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)

    request_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DdRunIssue(BaseModel):
    __tablename__ = "dd_run_issue"
    __table_args__ = (Index("ix_dd_run_issue_run", "run_id"),)

    run_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("dd_run.id"), nullable=False)
    row_no: Mapped[int | None] = mapped_column(nullable=True)
    column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
