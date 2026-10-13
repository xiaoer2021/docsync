"飞书文档链接解析。"

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

DOC_TYPE_SHEET = "sheet"

DOC_TYPE_AITABLE = "aitable"

DOC_TYPE_WIKI = "wiki"

DOC_TYPE_LABELS = {
    DOC_TYPE_SHEET: "飞书电子表格",
    DOC_TYPE_AITABLE: "多维表格",
}

_PATH_TYPES = {
    "sheets": DOC_TYPE_SHEET,
    "base": DOC_TYPE_AITABLE,
    "wiki": DOC_TYPE_WIKI,
    "docs": DOC_TYPE_SHEET,
    "file": DOC_TYPE_SHEET,
}

_PATH_RE = re.compile(r"/(sheets|base|wiki|docs|file)/([A-Za-z0-9_\-]+)")

_SUB_HINT = re.compile(r"(?:sheet|table|view)[=%]([A-Za-z0-9_\-]+)")

_BARE_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{8,80}$")


@dataclass(slots=True)
class DocRef:
    node_id: str

    doc_type: str
    source_url: str | None = None
    sub_id_hint: str | None = None

    @property
    def is_url(self) -> bool:
        return bool(self.source_url)

    @property
    def needs_resolve(self) -> bool:
        """要不要再去问一次接口才知道真实类型（知识库链接要）。"""
        return self.doc_type == DOC_TYPE_WIKI


class DocRefError(ValueError):
    """链接/ID 认不出来。"""


def parse_doc_ref(raw: str) -> DocRef:
    text = (raw or "").strip()
    if not text:
        raise DocRefError("请填写飞书文档链接或文档 token")

    if "http://" in text or "https://" in text:
        match = re.search(r"https?://\S+", text)
        if match:
            text = match.group(0)

    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        found = _PATH_RE.search(parsed.path)
        if not found:
            raise DocRefError(
                "认不出这是哪份文档。请用飞书文档里「复制链接」拿到的地址，"
                "形如 https://xxx.feishu.cn/sheets/xxxxxxxx 或 .../base/xxxxxxxx"
            )
        segment, token = found.group(1), found.group(2)
        hint = _SUB_HINT.search(unquote(parsed.query))
        return DocRef(
            node_id=token,
            doc_type=_PATH_TYPES[segment],
            source_url=text,
            sub_id_hint=hint.group(1) if hint else None,
        )

    if _BARE_TOKEN.match(text):
        return DocRef(node_id=text, doc_type=guess_type(text))

    raise DocRefError("文档 token 看起来不对，应该是一串字母数字，不含空格和斜杠")


def guess_type(token: str) -> str:
    "从 token 前缀猜类型。"
    lowered = token.lower()
    if lowered.startswith("bas"):
        return DOC_TYPE_AITABLE
    if lowered.startswith(("sht", "doc")):
        return DOC_TYPE_SHEET
    return DOC_TYPE_SHEET


def doc_url(node_id: str, doc_type: str) -> str:
    segment = "base" if doc_type == DOC_TYPE_AITABLE else "sheets"
    return f"https://feishu.cn/{segment}/{node_id}"
