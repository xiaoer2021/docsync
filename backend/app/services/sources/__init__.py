"平台来源层。"

from __future__ import annotations

from typing import Any

from app.services.sources.base import (
    DocLinkError,
    DocSource,
    ProbeResult,
    RunAborted,
    SourceDocRef,
    SourceError,
    SourcePreview,
    SubItem,
)
from app.services.sources.data import MAX_ROWS, SourceData

READY_PLATFORMS: frozenset[str] = frozenset({"dingtalk", "feishu", "wps"})

KNOWN_PLATFORMS: dict[str, str] = {
    "dingtalk": "钉钉",
    "feishu": "飞书",
    "wps_api": "WPS 开发者",
    "wps": "WPS 个人",
    "google": "Google Docs",
}

__all__ = [
    "KNOWN_PLATFORMS",
    "MAX_ROWS",
    "READY_PLATFORMS",
    "DocLinkError",
    "DocSource",
    "ProbeResult",
    "RunAborted",
    "SourceData",
    "SourceDocRef",
    "SourceError",
    "SourcePreview",
    "SubItem",
    "build_source",
    "doc_url_for",
    "parse_doc_link",
    "platform_label",
    "preview_source",
    "probe_source",
]


async def probe_source(
    app: object,
    doc: object,
    *,
    secret: str,
    doc_type_hint: str | None = None,
) -> ProbeResult:
    "按应用所属平台探测一份文档（是什么类型、有哪些子表）。"
    platform = getattr(app, "platform", None) or "dingtalk"
    node_id = str(getattr(doc, "node_id", "") or "")

    if platform == "dingtalk":
        from app.services.dingtalk.client import DingTalkClient
        from app.services.dingtalk.resolve import probe_doc

        operator = getattr(doc, "operator_union_id", None) or getattr(app, "default_operator_union_id", None)
        client = DingTalkClient(
            app_id=app.id,
            app_key=app.app_key,
            app_secret=secret,
            operator_id=operator,
        )
        return await probe_doc(client, node_id, preferred_type=doc_type_hint)

    if platform == "feishu":
        from app.services.feishu.client import FeishuClient
        from app.services.feishu.probe import probe_feishu

        client = FeishuClient(app_id=app.id, app_key=app.app_key, app_secret=secret)
        return await probe_feishu(client, node_id, doc_type_hint=doc_type_hint)

    if platform == "wps":
        from app.services.webflow.cdp import CdpError
        from app.services.webflow.source import list_sheets, recipe_for

        try:
            names = await list_sheets(recipe_for(app, node_id))
        except CdpError as exc:
            raise SourceError(
                f"浏览器起不来：{exc.message}",
                hint="服务器上要能跑 Chromium（或 Edge）。先看这台机器装没装，"
                "以及环境变量 DOCSYNC_BROWSER 指对没有。",
            ) from exc

        if not names:
            raise SourceError(
                "这份链接里没读到工作表。",
                hint="多半不是「在线表格」的分享链接（文档 / 幻灯片没有工作表），"
                "或者页面没加载出来。确认链接是表格、再试一次。",
            )

        return ProbeResult(
            ok=True,
            doc_type="sheet",
            sub_items=[SubItem(id=name, name=name, kind="worksheet") for name in names],
            resolved_node_id=None,
        )

    if platform in KNOWN_PLATFORMS:
        raise RunAborted(f"{platform_label(platform)} 的对接还在接入中，暂时不能登记文档。")
    raise RunAborted(f"不认识的平台：{platform}")


def _first_url(text: str) -> str:
    "从一段文本里抠出第一个网址。抠不到返回空串。"
    import re

    match = re.search(r"https?://\S+", str(text or ""))
    return match.group(0).rstrip("，。,.") if match else ""


def platform_label(key: str | None) -> str:
    """平台的中文名。认不出就原样返回 —— 至少能让报错里看到是什么值。"""
    return KNOWN_PLATFORMS.get(key or "", key or "")


def parse_doc_link(platform: str, raw: str) -> SourceDocRef:
    "按平台解析文档链接/ID。"
    if platform == "feishu":
        from app.services.feishu.urls import parse_doc_ref

        try:
            ref = parse_doc_ref(raw)
        except ValueError as exc:
            raise DocLinkError(str(exc)) from exc
        return SourceDocRef(
            node_id=ref.node_id,
            source_url=ref.source_url,
            doc_type=ref.doc_type,
            sub_id_hint=ref.sub_id_hint,
        )

    if platform == "wps":
        url = _first_url(raw)
        if not url:
            raise DocLinkError("这段里没找到网址。粘从金山文档「复制共享链接」出来的那一段即可。")
        return SourceDocRef(node_id=url, source_url=url, doc_type="webpage", sub_id_hint=None)

    from app.services.dingtalk.urls import parse_doc_ref as parse_dingtalk_ref

    try:
        ref = parse_dingtalk_ref(raw)
    except ValueError as exc:
        raise DocLinkError(str(exc)) from exc
    return SourceDocRef(
        node_id=ref.node_id,
        source_url=ref.source_url,
        doc_type=None,
        sub_id_hint=ref.sub_id_hint,
    )


def forget_tokens(app: object) -> None:
    "清掉这个应用在**它所属平台**上缓存的访问凭证。"
    app_id = getattr(app, "id", None)
    if app_id is None:
        return
    platform = getattr(app, "platform", None) or "dingtalk"

    if platform == "feishu":
        from app.services.feishu.client import forget_token
    else:
        from app.services.dingtalk.client import forget_token

    forget_token(app_id)


def doc_url_for(platform: str, node_id: str, doc_type: str | None = None) -> str:
    """给一个 node_id 拼回可点击的地址。没存 source_url 时用它兜底。"""
    if platform == "feishu":
        from app.services.feishu.urls import doc_url

        return doc_url(node_id, doc_type or "sheet")
    if platform == "wps":
        return node_id
    from app.services.dingtalk.urls import doc_url

    return doc_url(node_id)


async def all_sheet_headers(
    app: object, doc: object, *, header_rows: dict[str, int], secret: str = ""
) -> dict[str, list[str]] | None:
    "一次把**所有子表的表头列名**读出来；做不到就返回 None（调用方退回逐表读）。"
    platform = getattr(app, "platform", None) or "dingtalk"
    if platform != "wps":
        return None

    from app.services.doc_registry import trim_header_cells
    from app.services.webflow.source import read_all_sheets_first_rows, recipe_for

    node_id = str(getattr(doc, "node_id", "") or "")
    grids = await read_all_sheets_first_rows(recipe_for(app, node_id))
    out: dict[str, list[str]] = {}
    for name, grid in grids.items():
        row = int(header_rows.get(name) or 1)
        cells = grid[row - 1] if 1 <= row <= len(grid) else []
        out[name] = trim_header_cells(cells)
    return out


async def preview_source(
    app: object,
    doc: object,
    *,
    secret: str,
    sheet_id: str,
    cfg: dict[str, Any] | None = None,
    limit: int | None = None,
) -> SourcePreview:
    "预览一个子表（列名 + 每列几个样例值）。"
    platform = getattr(app, "platform", None) or "dingtalk"
    node_id = str(getattr(doc, "node_id", "") or "")
    doc_type = getattr(doc, "doc_type", None)
    config = cfg or {}

    if platform == "dingtalk":
        from app.services.dingtalk.client import DingTalkClient
        from app.services.dingtalk.preview import preview_dingtalk

        operator = getattr(doc, "operator_union_id", None) or getattr(app, "default_operator_union_id", None)
        client = DingTalkClient(
            app_id=app.id,
            app_key=app.app_key,
            app_secret=secret,
            operator_id=operator,
        )
        return await preview_dingtalk(
            client,
            doc_type=doc_type,
            node_id=node_id,
            sheet_id=sheet_id,
            cfg=config,
            limit=limit,
        )

    if platform == "feishu":
        from app.services.feishu.client import FeishuClient
        from app.services.feishu.preview import preview_feishu

        feishu_client = FeishuClient(app_id=app.id, app_key=app.app_key, app_secret=secret)
        return await preview_feishu(
            feishu_client,
            doc_type=doc_type,
            node_id=node_id,
            sheet_id=sheet_id,
            cfg=config,
            limit=limit,
        )

    if platform == "wps":
        from app.services.webflow.source import read_webflow, recipe_for

        source = await read_webflow(recipe_for(app, node_id), sheet=sheet_id, cfg=config)
        return SourcePreview(
            header=list(source.header),
            samples=[
                [row[1][index] for row in source.rows[:8] if index < len(row[1])]
                for index in range(len(source.header))
            ],
            engine="sheet",
        )

    if platform in KNOWN_PLATFORMS:
        raise RunAborted(f"{platform_label(platform)} 的对接还在接入中，暂时不能预览。")
    raise RunAborted(f"不认识的平台：{platform}")


def build_source(app: object, doc: object, *, secret: str) -> DocSource:
    "按应用所属平台造一个读源。"
    platform = getattr(app, "platform", None) or "dingtalk"

    if platform == "dingtalk":
        from app.services.dingtalk.client import DingTalkClient
        from app.services.dingtalk.source import DingTalkSource

        operator = getattr(doc, "operator_union_id", None) or getattr(app, "default_operator_union_id", None)
        return DingTalkSource(
            DingTalkClient(
                app_id=app.id,
                app_key=app.app_key,
                app_secret=secret,
                operator_id=operator,
            )
        )

    if platform == "feishu":
        from app.services.feishu.client import FeishuClient
        from app.services.feishu.source import FeishuSource

        return FeishuSource(FeishuClient(app_id=app.id, app_key=app.app_key, app_secret=secret))

    if platform == "wps":
        from app.services.webflow.check import profile_name_for
        from app.services.webflow.source import WebflowSource

        recipe = getattr(app, "recipe", None)

        return WebflowSource(
            recipe=recipe if isinstance(recipe, dict) else None,
            profile_name=profile_name_for(getattr(app, "id", None)),
        )

    if platform in KNOWN_PLATFORMS:
        raise RunAborted(
            f"{platform_label(platform)} 的对接还在接入中，暂时不能同步。"
            "凭证已经存下了，接入完成后回来重跑即可。"
        )
    raise RunAborted(f"不认识的平台：{platform}")
