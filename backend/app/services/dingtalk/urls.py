"钉钉文档链接解析。"

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

_NODE_PATTERNS = (
    re.compile(r"/i/nodes/([A-Za-z0-9_\-]+)"),
    re.compile(r"/i/p/([A-Za-z0-9_\-]+)"),
)

_BARE_ID = re.compile(r"^[A-Za-z0-9_\-]{6,80}$")

_SHEET_HINT = re.compile(r"(?:sheetId|tableId)[=%]([A-Za-z0-9_\-]+)")


@dataclass(slots=True)
class DocRef:
    node_id: str
    source_url: str | None = None
    sub_id_hint: str | None = None

    @property
    def is_url(self) -> bool:
        return bool(self.source_url)


class DocRefError(ValueError):
    """链接/ID 认不出来。"""


def parse_doc_ref(raw: str) -> DocRef:
    text = (raw or "").strip()
    if not text:
        raise DocRefError("请填写钉钉文档链接或文档 ID")

    if "http://" in text or "https://" in text:
        match = re.search(r"https?://\S+", text)
        if match:
            text = match.group(0)

    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        for pattern in _NODE_PATTERNS:
            found = pattern.search(parsed.path)
            if found:
                hint = _SHEET_HINT.search(unquote(parsed.query))
                return DocRef(
                    node_id=found.group(1),
                    source_url=text,
                    sub_id_hint=hint.group(1) if hint else None,
                )
        raise DocRefError(
            "认不出这是哪份文档。请用钉钉文档里「复制链接」拿到的地址，"
            "形如 https://alidocs.dingtalk.com/i/nodes/xxxxxxxx"
        )

    if _BARE_ID.match(text):
        return DocRef(node_id=text)

    raise DocRefError("文档 ID 看起来不对，应该是一串字母数字，不含空格和斜杠")


def doc_url(node_id: str) -> str:
    return f"https://alidocs.dingtalk.com/i/nodes/{node_id}"
