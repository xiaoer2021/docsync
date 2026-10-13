"""目标库、同步任务、执行记录的请求/响应模型。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class DatasourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    db_type: str = "sqlserver"
    host: str = Field(min_length=1, max_length=255)
    port: int | None = None
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    extra: dict[str, Any] | None = None
    is_default: bool = False
    remark: str | None = None


class DatasourceDraftTest(BaseModel):
    "「还没保存，先测一下」用的连接参数。"

    db_type: str = "sqlserver"
    host: str = Field(min_length=1, max_length=255)
    port: int | None = None
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = None
    ds_id: int | None = None


class DatasourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None

    password: str | None = None
    extra: dict[str, Any] | None = None
    is_default: bool | None = None
    enabled: bool | None = None
    remark: str | None = None


class DatasourceOut(BaseModel):
    id: int
    name: str
    db_type: str
    db_type_label: str = ""
    host: str
    port: int
    database: str
    username: str
    password_masked: str = ""
    extra: dict[str, Any] | None = None
    is_default: bool = False
    enabled: bool = True
    remark: str | None = None
    task_count: int = 0
    created_at: dt.datetime | None = None


class DatasourceTestResult(BaseModel):
    ok: bool
    message: str = ""
    hint: str | None = None
    version: str | None = None
    latency_ms: int | None = None


class TableInfo(BaseModel):
    name: str
    columns: list[str] = []
    column_types: dict[str, str] = {}
    row_count: int | None = None


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    doc_id: int
    sheet_id: str = Field(min_length=1, max_length=128)
    sheet_name: str | None = None
    engine: str | None = None
    source_config: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    dedupe: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    post_actions: list[dict[str, Any]] | None = None
    schedule: dict[str, Any] | None = None
    remark: str | None = None


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    source_config: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    dedupe: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    post_actions: list[dict[str, Any]] | None = None
    schedule: dict[str, Any] | None = None
    status: str | None = None
    remark: str | None = None


class TaskOut(BaseModel):
    id: int
    code: str
    name: str
    doc_id: int
    doc_name: str | None = None
    doc_type: str | None = None
    sheet_id: str
    sheet_name: str | None = None
    engine: str
    group_id: int | None = None
    group_name: str | None = None
    source_config: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    dedupe: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    target_table: str = ""
    write_mode: str = ""
    datasource_name: str | None = None
    post_actions: list[dict[str, Any]] | None = None
    schedule: dict[str, Any] | None = None

    schedule_label: str = "手动"

    merge_sheet_names: list[str] = []
    status: str = "enabled"
    remark: str | None = None
    last_run_at: dt.datetime | None = None
    last_run_status: str | None = None
    last_success_at: dt.datetime | None = None
    next_run_at: dt.datetime | None = None
    last_summary: dict[str, Any] | None = None
    running: bool = False
    created_at: dt.datetime | None = None


class TaskClone(BaseModel):
    """把一份任务的配置复制到同一文档的另一个子表。"""

    sheet_id: str = Field(min_length=1, max_length=128)
    sheet_name: str | None = None
    name: str | None = None
    table_name: str | None = None


class PlanResult(BaseModel):
    ok: bool = True
    table: str = ""
    datasource: str = ""
    will_create: bool = False
    will_add_columns: list[dict[str, str]] = []
    existing_columns: list[str] = []
    statements: list[str] = []
    mapped_columns: list[dict[str, str]] = []
    message: str = ""


class CheckStep(BaseModel):
    name: str
    ok: bool
    message: str = ""
    hint: str | None = None


class CheckResult(BaseModel):
    ok: bool
    steps: list[CheckStep] = []


class PreviewRequest(BaseModel):
    doc_id: int
    sheet_id: str
    engine: str | None = None
    source_config: dict[str, Any] | None = None
    rows: int = 20


class PreviewResult(BaseModel):
    header: list[str] = []
    rows: list[list[Any]] = []
    total_preview: int = 0
    inferred_header_row: int | None = None
    suggested_types: list[str] = []
    message: str = ""
    ok: bool = True
    error: str | None = None
    hint: str | None = None


class RunOut(BaseModel):
    id: int
    task_id: int
    task_name: str | None = None
    trigger_type: str
    trigger_label: str = ""
    status: str
    status_label: str = ""
    queued_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    duration_ms: int | None = None
    rows_read: int = 0
    rows_written: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_failed: int = 0
    batches: int = 0
    dry_run: bool = False
    row_limit: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    stats: dict[str, Any] | None = None


class RunDetail(RunOut):
    logs: list[str] = []
    issues: list[dict[str, Any]] = []
