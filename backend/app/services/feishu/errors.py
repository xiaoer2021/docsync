"飞书接口错误 → 人话 + 可执行的修复动作。"

from __future__ import annotations

import re

from app.services.sources.base import SourceError


class FeishuError(SourceError):
    "飞书接口调用失败。跟 ``DingTalkError`` 一样继承 ``SourceError`` ——"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        errcode: int | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            errcode=errcode,
            http_status=http_status,
            hint=hint or lookup_hint(code=code, errcode=errcode, message=message),
        )


_PERMISSION_HINT = (
    "应用没有这个接口的权限。去飞书开放平台 → 开发者后台 → 你的应用 → "
    "「权限管理」里开上对应权限，**然后必须「创建版本并发布」才生效** —— "
    "只在页面上勾选、不发布版本，是不生效的（这点最容易漏）。"
)

_COLLABORATOR_HINT = (
    "应用或你本人不是这份文档的协作者。打开文档 → 右上角「分享」→ "
    "把应用（在飞书开放平台上建的那个）加为可阅读；"
    "如果文档在知识库里，还要把应用加进**知识库成员**，光有文件分享不够。"
)

_MESSAGE_HINTS: tuple[tuple[str, str], ...] = (
    ("collaborator", _COLLABORATOR_HINT),
    ("forbidden", _COLLABORATOR_HINT),
    ("not exist", "文档/数据表不存在，或者应用看不到它。先确认链接里的 token 没抄错，再确认应用是协作者。"),
    ("not found", "文档/数据表不存在，或者应用看不到它。先确认链接里的 token 没抄错，再确认应用是协作者。"),
    ("token", "文档标识（token）不对。用文档里「复制链接」拿到的完整地址重新登记一次。"),
)

HINTS: dict[int, str] = {
    99991661: "请求里没有带 tenant_access_token，平台的鉴权头没发出去，重试一次。",
    99991663: "tenant_access_token 无效，平台会自动重新换取；持续失败检查 App ID / App Secret。",
    99991664: "tenant_access_token 已过期，平台会自动重新换取。",
    99991672: _PERMISSION_HINT,
    1310213: _COLLABORATOR_HINT,
    1310214: "工作表不存在，可能已被删除或改名。回到「管理文档」重新读取一下子表清单。",
    1310203: "读取范围不合法，检查「列范围」填得对不对。",
    1254302: _COLLABORATOR_HINT,
    1254005: "数据表不存在，可能已被删除。回到「管理文档」重新读取一下子表清单。",
    1254006: "字段不存在，可能已被删除或改名。回到第 2 步重新配一下字段映射。",
    1770001: "请求参数不合法，检查填的内容。",
    1770002: "应用没有调用这个接口的权限。",
}


def missing_scopes(message: str | None) -> list[str]:
    "从飞书的错误文案里把「缺哪个权限点」抠出来。"
    text = str(message or "")
    found: list[str] = []
    for match in _SCOPE_RE.finditer(text):
        scope = match.group(0).strip()

        if ":" in scope and scope not in found:
            found.append(scope)
    return found


_SCOPE_RE = re.compile(r"[a-z][a-z0-9_]*(?::[a-z0-9_]+)+", re.I)


def scope_names(scopes: list[str]) -> str:
    "把 scope 翻成人话。认不出的原样列出 —— **不猜**，猜错比不说更糟。"
    known = {str(item["scope"]).lower(): str(item["name"]) for item in REQUIRED_SCOPES}
    parts = []
    for scope in scopes:
        key = scope.lower()
        name = known.get(key)
        if name is None:
            for full, label in known.items():
                if full.startswith(key + ":") or key.startswith(full + ":"):
                    name = label
                    break
        parts.append(f"{name}（{scope}）" if name else scope)
    return "、".join(parts)


def lookup_hint(
    *,
    code: str | None = None,
    errcode: int | None = None,
    message: str | None = None,
) -> str | None:
    "查修复建议。**先错误码，再文案**。"
    if errcode is not None and errcode in HINTS:
        return _with_scopes(HINTS[errcode], message)
    if code and code.isdigit() and int(code) in HINTS:
        return _with_scopes(HINTS[int(code)], message)

    text = (message or "").lower()
    if text:
        for needle, hint in _MESSAGE_HINTS:
            if needle in text:
                return hint
    return None


def _with_scopes(hint: str, message: str | None) -> str:
    "权限类的建议里**把缺的那个权限点补在最前面**。"
    scopes = missing_scopes(message)
    if not scopes:
        return hint
    return f"缺这个权限：**{scope_names(scopes)}**。\n\n{hint}"


def is_permission_error(exc: FeishuError) -> bool:
    "是不是「应用没开这个权限点」。"
    return exc.errcode in (99991672, 1770002)


REQUIRED_SCOPES = [
    {
        "scope": "sheets:spreadsheet:readonly",
        "name": "电子表格读权限",
        "used_for": "读取飞书电子表格的工作表清单和数据区域",
        "when": "登记了飞书「电子表格」类型的文档时需要",
    },
    {
        "scope": "bitable:app:readonly",
        "name": "多维表格读权限",
        "used_for": "读取多维表格的数据表、字段和记录",
        "when": "登记了飞书「多维表格」类型的文档时需要",
    },
    {
        "scope": "drive:drive:readonly",
        "name": "云空间文件读权限",
        "used_for": "在平台上按名字搜飞书文档，点一下就登记，不用复制链接",
        "when": "想用「搜文档」这个入口时需要；只粘链接的话可以不开",
    },
    {
        "scope": "wiki:wiki:readonly",
        "name": "知识库读权限",
        "used_for": "解析知识库（/wiki/）链接，换成真正的文档 token",
        "when": "文档放在飞书知识库里时需要；直接是 /sheets/ 或 /base/ 链接可以不开",
    },
]

DOC_AUTHOR_GUIDE = (
    "应用必须是文档的协作者，否则接口会报权限错误。"
    "做法：打开飞书文档 → 右上角「分享」→ 搜索应用名"
    "（你在开发者后台建的那个）→ 加为可阅读。"
    "文档在知识库里的话，还要去知识库设置里把应用加为成员。"
)
