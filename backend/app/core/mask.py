"日志与错误信息脱敏。"

from __future__ import annotations

import re

_KV_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|app_?secret|access_?token|refresh_?token|token|sign|authorization)"
    r"([\"']?\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;&}\)]+)"
)

_DB_DSN_PATTERN = re.compile(
    r"(?i)\b(?:sqlserver|mssql|mysql|postgres(?:ql)?|sqlite)" r"(?:\+[a-z0-9_]+)?://[^\s，。；）\]<>\"']+"
)

_WEBHOOK_PATTERN = re.compile(r"(?i)\b(access_token|sign)=([^&\s]+)")


def mask_text(text: str) -> str:
    """把文本里的敏感值替换成 ***。"""
    if not text:
        return text
    out = _KV_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    out = _DB_DSN_PATTERN.sub("[数据库连接已隐藏]", out)
    out = _WEBHOOK_PATTERN.sub(lambda m: f"{m.group(1)}=***", out)
    return out


def mask_value(value: str | None, *, keep: int = 4) -> str:
    "把一个敏感值打码成 ``abcd****`` 用于界面回显。"
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return f"{'*' * min(8, len(value) - keep)}{value[-keep:]}"
