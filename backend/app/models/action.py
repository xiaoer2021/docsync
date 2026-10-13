"""后置动作：落库完成后要触发什么。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

ACTION_WEBHOOK = "webhook"
ACTION_INTERFACE = "interface"
ACTION_DINGTALK_ROBOT = "dingtalk_robot"

ACTION_KINDS = (ACTION_WEBHOOK, ACTION_INTERFACE, ACTION_DINGTALK_ROBOT)

ACTION_KIND_LABELS = {
    ACTION_WEBHOOK: "Webhook 调度",
    ACTION_INTERFACE: "接口调度",
    ACTION_DINGTALK_ROBOT: "钉钉机器人",
}

ACTION_KIND_HELP = {
    ACTION_WEBHOOK: "往一个网址发一下，告诉对方「数据已经好了」。最常见的是 BI 的刷新地址。",
    ACTION_INTERFACE: "按你选的方法调一个接口，可以带请求体。适合需要传参数的场景。",
    ACTION_DINGTALK_ROBOT: "给钉钉群发消息。适合同步失败告警，或成功时通知一声。",
}

ON_SUCCESS = "success"
ON_PARTIAL = "partial"
ON_NOT_SUCCESS = "not_success"
ON_FAILURE = "failure"
ON_ALWAYS = "always"
ON_MODES = (ON_SUCCESS, ON_PARTIAL, ON_NOT_SUCCESS, ON_FAILURE, ON_ALWAYS)

ON_MODE_LABELS = {
    ON_SUCCESS: "成功时",
    ON_PARTIAL: "部分成功时",
    ON_NOT_SUCCESS: "没完全成功时",
    ON_FAILURE: "失败时",
    ON_ALWAYS: "每次都做",
}

ON_MODE_HINTS = {
    ON_SUCCESS: "只有完全成功才发 —— 部分成功不算成功。",
    ON_PARTIAL: "只有部分成功才发（有脏格子、有行被跳过、类型被自动改过）。",
    ON_NOT_SUCCESS: "部分成功和失败都发。想「不干净就通知我」用这个。",
    ON_FAILURE: "只有失败、超时、取消才发，部分成功不发。",
    ON_ALWAYS: "不管什么结果都发。",
}

ACT_PENDING = "pending"
ACT_RUNNING = "running"
ACT_SUCCESS = "success"
ACT_FAILED = "failed"
ACT_SKIPPED = "skipped"


def channels_of(action: DdAction) -> list[dict[str, Any]]:
    "取这个动作要做的事。"
    if action.channels:
        return [dict(c) for c in action.channels]
    if action.kind:
        return [{"kind": action.kind, "config": dict(action.config or {})}]
    return []


class DdAction(BaseModel):
    "一个后置动作的定义（不含它挂在哪个任务上）。"

    __tablename__ = "dd_action"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    channels: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
