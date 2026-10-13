"""后置动作的请求/响应模型。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class Channel(BaseModel):
    """一个动作里的一个渠道。一个动作可以配几个渠道。"""

    kind: str = Field(min_length=1, max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


class ActionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    channels: list[Channel] = Field(default_factory=list)
    enabled: bool = True
    remark: str | None = None


class ActionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    channels: list[Channel] | None = None
    enabled: bool | None = None
    remark: str | None = None


class ActionOut(BaseModel):
    id: int
    name: str
    channels: list[dict[str, Any]] = Field(default_factory=list)

    kind_label: str = ""
    enabled: bool = True
    remark: str | None = None

    used_by: int = 0
    created_at: dt.datetime | None = None


class ActionKindOut(BaseModel):
    """给界面画表单用：每种类型要填什么、有哪些变量。"""

    kind: str
    label: str
    help: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)


class ChannelResult(BaseModel):
    kind: str
    label: str = ""
    ok: bool
    http_status: int | None = None
    detail: str = ""
    error: str | None = None
    elapsed_ms: int = 0


class ActionRecordOut(BaseModel):
    "这个动作**实际发生过**的一次执行。"

    id: int
    run_id: int
    task_name: str | None = None
    trigger_on: str | None = None
    status: str
    kind: str | None = None
    started_at: dt.datetime | None = None
    duration_ms: int | None = None
    http_status: int | None = None
    error_message: str | None = None


class ActionTestOut(BaseModel):
    ok: bool
    results: list[ChannelResult] = Field(default_factory=list)


class ActionPreviewOut(BaseModel):
    """「发出去大概长什么样」。不真发。"""

    rendered: str = ""
