"""钉钉接入相关的请求/响应模型。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class AppCreate(BaseModel):
    platform: str = Field(default="dingtalk", max_length=16)
    name: str = Field(min_length=1, max_length=64)

    app_key: str = Field(default="", max_length=128)
    app_secret: str = Field(default="", max_length=256)
    default_operator_union_id: str | None = Field(default=None, max_length=128)
    default_operator_name: str | None = Field(default=None, max_length=64)
    remark: str | None = None

    recipe: dict | None = None


class AppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)

    recipe: dict | None = None

    app_key: str | None = Field(default=None, max_length=128)

    app_secret: str | None = Field(default=None, max_length=256)
    default_operator_union_id: str | None = Field(default=None, max_length=128)
    default_operator_name: str | None = Field(default=None, max_length=64)
    status: str | None = None
    remark: str | None = None


class AppOut(BaseModel):
    id: int
    platform: str = "dingtalk"
    name: str

    app_key: str = ""
    app_key_masked: str = ""

    app_secret_masked: str = ""
    has_secret: bool = False
    default_operator_union_id: str | None = None
    default_operator_name: str | None = None
    token_expires_at: dt.datetime | None = None
    last_token_at: dt.datetime | None = None
    last_token_error: str | None = None
    status: str
    remark: str | None = None

    recipe: dict | None = None
    doc_count: int = 0
    created_at: dt.datetime | None = None


class TestStep(BaseModel):
    name: str
    ok: bool
    message: str = ""
    hint: str | None = None

    optional: bool = False


class AppTestResult(BaseModel):
    ok: bool
    steps: list[TestStep] = []


class ScopeInfo(BaseModel):
    scope: str
    name: str
    used_for: str
    when: str


class ScopeGuide(BaseModel):
    scopes: list[ScopeInfo]
    author_guide: str


class ContactOut(BaseModel):
    user_id: str | None = None
    union_id: str | None = None
    name: str | None = None
    mobile: str | None = None
    dept: str | None = None
    from_cache: bool = False


class ContactResolveRequest(BaseModel):
    app_id: int
    mobile: str = Field(min_length=5, max_length=32)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    sort_order: int = 0
    remark: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None
    remark: str | None = None


class GroupOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    remark: str | None = None
    doc_count: int = 0
    task_count: int = 0


class DocSearchHit(BaseModel):
    uuid: str
    name: str
    creator: str | None = None
    modifier: str | None = None

    registered_doc_id: int | None = None
    registered_name: str | None = None


class DocSearchResult(BaseModel):
    items: list[DocSearchHit] = []
    next_token: str | None = None
    keyword: str = ""


class DocResolveRequest(BaseModel):
    """只解析 + 探测，不落库。给新增向导的第一步用。"""

    ref: str = Field(min_length=1, max_length=1024)
    app_id: int
    operator_union_id: str | None = None

    doc_type: str | None = None


class SubItemOut(BaseModel):
    id: str
    name: str
    kind: str
    field_count: int | None = None

    task_id: int | None = None
    task_name: str | None = None
    task_status: str | None = None
    last_run_status: str | None = None
    last_run_at: dt.datetime | None = None
    configured: bool = False

    schedule_label: str | None = None
    post_actions_label: str | None = None

    auto_column_check: bool = False

    column_drift: str | None = None


class ColumnCheckSheet(BaseModel):
    """一个子表的列变化。"""

    sheet_id: str
    sheet_name: str

    first_check: bool = False
    column_count: int = 0
    added: list[str] = []
    removed: list[str] = []


class ColumnCheckResult(BaseModel):
    ok: bool
    checked: int = 0
    changed: int = 0
    sheets: list[ColumnCheckSheet] = []
    changed_sheets: list[ColumnCheckSheet] = []
    errors: list[str] = []
    error: str | None = None


class ProbeAttempt(BaseModel):
    doc_type: str
    label: str
    code: str = ""
    message: str = ""


class DocResolveResult(BaseModel):
    node_id: str
    source_url: str | None = None
    doc_type: str | None = None
    sub_items: list[SubItemOut] = []
    suggested_name: str | None = None
    sub_id_hint: str | None = None
    ok: bool = True
    error: str | None = None
    hint: str | None = None

    code: str | None = None
    http_status: int | None = None
    attempts: list[ProbeAttempt] = []

    used_node_id: str | None = None
    used_operator_union_id: str | None = None


class DocCreate(BaseModel):
    ref: str = Field(min_length=1, max_length=1024)
    app_id: int
    name: str | None = Field(default=None, max_length=128)
    doc_type: str | None = None
    operator_union_id: str | None = Field(default=None, max_length=128)
    group_id: int | None = None

    group_ids: list[int] | None = None
    remark: str | None = None


class DocUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    doc_type: str | None = None
    app_id: int | None = None
    operator_union_id: str | None = Field(default=None, max_length=128)
    group_id: int | None = None
    group_ids: list[int] | None = None
    status: str | None = None
    remark: str | None = None
    watch_enabled: bool | None = None
    watch_cron: str | None = Field(default=None, max_length=64)


class DocOut(BaseModel):
    id: int
    name: str
    doc_type: str
    doc_type_label: str = ""

    platform: str = "dingtalk"
    node_id: str
    source_url: str | None = None
    app_id: int
    app_name: str | None = None
    operator_union_id: str | None = None

    group_id: int | None = None
    group_name: str | None = None
    group_ids: list[int] = Field(default_factory=list)
    group_names: list[str] = Field(default_factory=list)
    status: str
    remark: str | None = None
    watch_enabled: bool = False
    watch_cron: str | None = None
    next_watch_at: dt.datetime | None = None
    last_probe_at: dt.datetime | None = None
    last_probe_ok: bool | None = None
    last_probe_error: str | None = None
    structure_drift: str | None = None
    sheet_count: int = 0
    task_count: int = 0
    unconfigured_count: int = 0
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class DocBatchRequest(BaseModel):
    app_id: int
    refs: list[str] = Field(min_length=1, max_length=100)
    group_id: int | None = None
    group_ids: list[int] | None = None
    operator_union_id: str | None = None


class DocBatchItem(BaseModel):
    ref: str
    ok: bool
    doc_id: int | None = None
    node_id: str | None = None
    name: str | None = None
    doc_type: str | None = None
    sub_item_count: int = 0
    error: str | None = None
    hint: str | None = None
    skipped: bool = False


class DocBatchResult(BaseModel):
    total: int
    ok_count: int
    failed_count: int
    skipped_count: int
    items: list[DocBatchItem] = []


class WatchUpdate(BaseModel):
    watch_enabled: bool
    watch_cron: str | None = Field(default=None, max_length=64)
