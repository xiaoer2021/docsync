"钉钉接口错误 → 人话 + 可执行的修复动作。"

from __future__ import annotations

from app.services.sources.base import SourceError

_PATH_SCOPES: tuple[tuple[str, str, str], ...] = (
    ("/v1.0/doc/workbooks", "Document.Workbook.Read", "钉钉表格读权限"),
    ("/v1.0/notable/bases", "Notable.Base.Read.All", "AI 表格应用读权限"),
    ("/v2.0/storage/dentries", "Storage.Dentry.Search", "文件搜索权限"),
    ("/topapi/", "通讯录查询用户（如 qyapi_get_member）", "通讯录读权限"),
)

_PERMISSION_HINT = (
    "应用没有调用这个接口的权限。去钉钉开放平台给应用加上对应权限点，" "加完必须**发布应用版本**才会生效。"
)


def scope_for_path(path: str) -> tuple[str, str] | None:
    """这个接口要哪个权限点。返回 (权限点, 中文名)。"""
    for prefix, scope, name in _PATH_SCOPES:
        if path.startswith(prefix):
            return scope, name
    return None


def permission_hint_for(path: str) -> str:
    found = scope_for_path(path)
    if not found:
        return _PERMISSION_HINT
    scope, name = found
    return (
        f"应用没有调用这个接口的权限。去钉钉开放平台给应用加上「{name}（{scope}）」，"
        "加完必须**发布应用版本**才会生效。"
    )


_MESSAGE_HINTS: tuple[tuple[str, str], ...] = (
    (
        "30000 cells",
        "要读的区域太大了：钉钉一次最多读 30000 个单元格（按格数算，不是按行数算）。"
        "列越多，一次能读的行就越少。平台会自动按列数分批，"
        "如果你是在别的工具里看到这条，把列范围缩小或让平台自己分批。",
    ),
    (
        "at most",
        "钉钉限制了这次请求的范围/数量。把范围缩小一点再试。",
    ),
)

HINTS: dict[str, str] = {
    "forbidden.accessDenied": (
        "应用或操作人不是这份文档的协作者。打开文档 → 右上角「分享」，"
        "把应用和操作人（unionId 对应的人）加为协作者。"
    ),
    "forbidden.acrossOrg": (
        "这份文档和当前 AppKey 不属于同一个组织。检查 AppKey 是不是目标组织的应用，"
        "或者操作人是不是这个组织的人。"
    ),
    "forbidden.operationIllegal": "当前操作人不允许做这个操作，检查文档协作者权限。",
    "invalidRequest.resource.notWorkbook": (
        "这个 ID 不是钉钉表格。如果它其实是多维表 / AI 表格，把文档类型改成「多维表」。"
    ),
    "invalidRequest.document.typeIllegal": (
        "这个 ID 不是多维表。如果它其实是钉钉表格，把文档类型改成「钉钉表格」。"
    ),
    "invalidRequest.document.notFound": "找不到这份文档，或者操作人没有访问权限。",
    "invalidRequest.inputArgs.workbookIdIllegal": "workbookId 格式不对，检查链接是不是复制完整了。",
    "invalidRequest.inputArgs.invalid": (
        "钉钉说请求参数不合法。常见原因：要读的区域超过 30000 个单元格、"
        "文档 ID 填错、或者操作人（operatorId）不是这个组织的人。"
    ),
    "invalidRequest.document.stillInitializing": "文档正在初始化，稍等一会儿再试。",
    "invalidRequest.document.broken": "文档已损坏，钉钉侧无法读取。",
    "invalidRequest.document.sizeOverLimit": "文档内容过大，钉钉侧拒绝读取。",
    "invalidRequest.dataNotReady": "钉钉侧数据还没准备好，稍等一会儿再试。",
    "invalidRequest.resource.notFound": "找不到目标资源，可能已被删除。",
    "serviceBusy": "钉钉侧繁忙，稍后重试。",
    "service.timeout": "钉钉侧请求超时，稍后重试。",
    "internalError": "钉钉侧内部错误，稍后重试。",
    "unknownError": "钉钉侧未知错误。",
    "Forbidden.AccessDenied.AccessTokenPermissionDenied": _PERMISSION_HINT,
    "Forbidden.AccessDenied.AccessTokenExpired": (
        "访问凭证已失效，平台会自动重新换取；持续失败检查 AppKey / AppSecret。"
    ),
    "InvalidParameter": "请求参数不合法，检查填的内容。",
    "invalidParameter": "请求参数不合法，检查填的内容。",
    "unauthorized": "凭证无效或已过期，检查 AppKey / AppSecret。",
    "invalid_client": "AppKey 或 AppSecret 不正确。",
    "invalid_grant": "认证失败，AppKey / AppSecret 可能已重置。",
}

_ERRCODE_HINTS: dict[int, str] = {
    40001: "AppSecret 不正确。",
    40014: "access_token 无效，平台会自动重新换取。",
    41001: "缺少 access_token，检查应用配置。",
    42001: "access_token 已过期，平台会自动重新换取。",
    60011: _PERMISSION_HINT,
    60020: "调用方 IP 不在应用的白名单里。去开放平台把服务器出口 IP 加进白名单。",
    90018: "这个应用没有该接口的调用权限。",
    -1: "钉钉侧系统繁忙，稍后重试。",
}


class DingTalkError(SourceError):
    "钉钉接口调用失败。带上错误码与修复建议，界面直接用。"

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


def lookup_hint(
    *, code: str | None = None, errcode: int | None = None, message: str | None = None
) -> str | None:
    text = (message or "").lower()
    if text:
        for needle, hint in _MESSAGE_HINTS:
            if needle in text:
                return hint

    if code and code in HINTS:
        return HINTS[code]

    if code and "PermissionDenied" in code:
        return _PERMISSION_HINT
    if errcode is not None and errcode in _ERRCODE_HINTS:
        return _ERRCODE_HINTS[errcode]
    return None


def is_permission_error(exc: DingTalkError) -> bool:
    "是不是「应用没开这个权限点」——"
    if exc.errcode in (60011, 90018):
        return True
    return (exc.code or "").endswith("AccessTokenPermissionDenied")


REQUIRED_SCOPES = [
    {
        "scope": "Document.Workbook.Read",
        "name": "钉钉表格读权限",
        "used_for": "读取钉钉表格的工作表清单和数据区域",
        "when": "登记了「钉钉表格」类型的文档时需要",
    },
    {
        "scope": "Notable.Base.Read.All",
        "name": "AI 表格应用读权限",
        "used_for": "读取多维表的数据表、字段和记录",
        "when": "登记了「多维表」类型的文档时需要",
    },
    {
        "scope": "Storage.Dentry.Search",
        "name": "文件搜索权限",
        "used_for": "在平台上按名字搜钉钉文档，点一下就登记，不用复制链接",
        "when": "想用「搜文档」这个入口时需要；只粘链接或文档 ID 的话可以不开",
    },
    {
        "scope": "通讯录查询用户（如 qyapi_get_member）",
        "name": "通讯录读权限",
        "used_for": "用手机号或姓名换 unionId（operatorId），也用于按姓名选人",
        "when": "想用「手机号解析 / 按姓名选人」快速拿 operatorId 时需要；不用的话可以手动粘贴 unionId",
    },
]

DOC_AUTHOR_GUIDE = (
    "应用和操作人必须是文档的协作者，否则接口会报 forbidden.accessDenied。"
    "做法：打开钉钉文档 → 右上角「分享」→ 搜索应用名（就是你在开放平台建的那个企业内部应用）"
    "和操作人，加为可阅读；多维表同理。"
)
