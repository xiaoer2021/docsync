"飞书文档探测：判定是电子表格还是多维表格，并列出子表。"

from __future__ import annotations

from app.models.app import DOC_TYPE_AITABLE, DOC_TYPE_SHEET
from app.services.feishu import bitable_reader, sheet_reader
from app.services.feishu.client import FeishuClient, data_of
from app.services.feishu.errors import FeishuError
from app.services.feishu.urls import DOC_TYPE_WIKI, parse_doc_ref
from app.services.sources.base import ProbeResult, SubItem

__all__ = ["probe_feishu", "resolve_wiki"]

_WIKI_OBJ_TYPES = {
    "sheet": DOC_TYPE_SHEET,
    "bitable": DOC_TYPE_AITABLE,
}


async def resolve_wiki(client: FeishuClient, node_token: str) -> tuple[str, str]:
    "把知识库节点换成 ``(doc_type, obj_token)``。"
    body = await client.get("/wiki/v2/spaces/get_node", params={"token": node_token})
    node = data_of(body).get("node") or {}
    if not isinstance(node, dict):
        raise FeishuError("知识库节点返回的内容看不懂，可能飞书改了接口。")

    obj_type = str(node.get("obj_type") or "")
    obj_token = str(node.get("obj_token") or "")
    if not obj_token:
        raise FeishuError("这个知识库节点里没有文档，可能它只是个目录。")

    mapped = _WIKI_OBJ_TYPES.get(obj_type)
    if not mapped:
        raise FeishuError(
            f"这个知识库节点是「{obj_type or '未知类型'}」，不是表格，取不了数。",
            hint="只支持知识库里的电子表格和多维表格；普通文档、幻灯片、思维笔记都读不了。",
        )
    return mapped, obj_token


async def probe_feishu(
    client: FeishuClient,
    node_id: str,
    *,
    doc_type_hint: str | None = None,
) -> ProbeResult:
    "探测一份飞书文档。"
    doc_type = doc_type_hint or ""
    token = node_id
    resolved: str | None = None

    try:
        if doc_type == DOC_TYPE_WIKI or not doc_type:
            ref = parse_doc_ref(token)
            if ref.needs_resolve:
                doc_type, token = await resolve_wiki(client, ref.node_id)

                resolved = token
            else:
                doc_type = ref.doc_type
                token = ref.node_id

        if doc_type == DOC_TYPE_AITABLE:
            items = await _probe_bitable(client, token)
        elif doc_type == DOC_TYPE_SHEET:
            items = await _probe_sheet(client, token)
        else:
            return ProbeResult(
                ok=False,
                error=f"这个文档类型（{doc_type}）取不了数。",
                hint="只支持飞书电子表格和多维表格两种。",
            )
    except FeishuError as exc:
        return ProbeResult(
            ok=False,
            doc_type=doc_type or None,
            error=exc.message,
            hint=exc.hint,
            code=exc.code,
            http_status=exc.http_status,
        )

    if not items:
        return ProbeResult(
            ok=False,
            doc_type=doc_type,
            resolved_node_id=resolved,
            error="这个文档里一个子表都没有。",
            hint=(
                "电子表格至少要有一个工作表；多维表格至少要有一个数据表。"
                "空文档登记了也没用 —— 先去飞书里建一个。"
            ),
        )

    return ProbeResult(ok=True, doc_type=doc_type, sub_items=items, resolved_node_id=resolved)


async def _probe_sheet(client: FeishuClient, token: str) -> list[SubItem]:
    sheets = await sheet_reader.list_sheets(client, token)
    return [SubItem(id=s.id, name=s.name, kind="worksheet") for s in sheets]


async def _probe_bitable(client: FeishuClient, token: str) -> list[SubItem]:
    tables = await bitable_reader.list_tables(client, token)
    out: list[SubItem] = []
    for table in tables:
        try:
            field_count: int | None = len(await bitable_reader.list_fields(client, token, table.id))
        except FeishuError:
            field_count = None
        out.append(SubItem(id=table.id, name=table.name, kind="aitable_table", field_count=field_count))
    return out
