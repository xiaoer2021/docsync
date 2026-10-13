"平台来源接口 —— 多平台这件事的**唯一抽象**。"

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.services.sources.data import SourceData


class SourceError(RuntimeError):
    "读源失败。**平台无关** —— 各平台把自己的异常包成它。"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        errcode: int | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.errcode = errcode
        self.http_status = http_status
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "code": self.code,
            "errcode": self.errcode,
            "http_status": self.http_status,
            "hint": self.hint,
        }

    def __str__(self) -> str:
        text = self.message
        if self.code:
            text = f"{text}（{self.code}）"
        if self.hint:
            text = f"{text} → {self.hint}"
        return text


class RunAborted(RuntimeError):
    "这次执行不该继续了 —— 被用户取消，或遇到不该硬撑的错误。"


class DocLinkError(ValueError):
    "文档链接/ID 认不出来。"


@dataclass(slots=True)
class SourceDocRef:
    """从链接或 ID 里解出来的文档标识。"""

    node_id: str
    source_url: str | None = None

    doc_type: str | None = None

    sub_id_hint: str | None = None

    @property
    def is_url(self) -> bool:
        return bool(self.source_url)


@dataclass(slots=True)
class SourcePreview:
    "预览一个子表：列名 + 每列几个样例值。"

    header: list[str]

    samples: list[list] = field(default_factory=list)
    engine: str = "sheet"


@dataclass(slots=True)
class SubItem:
    "文档下的一个子表。"

    id: str
    name: str
    kind: str
    field_count: int | None = None


@dataclass(slots=True)
class ProbeResult:
    """探测一份文档的结果：是什么类型、有哪些子表、失败原因。"""

    ok: bool
    doc_type: str | None = None
    sub_items: list[SubItem] = field(default_factory=list)

    resolved_node_id: str | None = None
    error: str | None = None
    hint: str | None = None

    code: str | None = None
    http_status: int | None = None

    attempts: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class DocSource(Protocol):
    "一个平台的读源实现。"

    platform: str

    async def read(
        self,
        task: Any,
        doc: Any,
        logger: Any,
        *,
        names: dict[str, str],
        history: dict[str, list[str]] | None = None,
        limit: int | None = None,
    ) -> SourceData:
        "读一次源数据。"
        ...
