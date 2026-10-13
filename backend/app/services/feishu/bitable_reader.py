"飞书**多维表格**（记录型）读取。"

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.feishu.cells import flatten as flatten
from app.services.feishu.client import FeishuClient, data_of
from app.services.sources.data import MAX_ROWS

__all__ = [
    "FieldInfo",
    "TableInfo",
    "flatten",
    "iter_records",
    "list_fields",
    "list_tables",
]


@dataclass(slots=True)
class TableInfo:
    """多维表格里的一个「数据表」。"""

    id: str
    name: str


@dataclass(slots=True)
class FieldInfo:
    id: str
    name: str

    type: int | None = None
    ui_type: str = ""


def _app_path(app_token: str) -> str:
    return f"/bitable/v1/apps/{quote(app_token, safe='')}"


async def list_tables(client: FeishuClient, app_token: str) -> list[TableInfo]:
    body = await client.get(f"{_app_path(app_token)}/tables", params={"page_size": 100})
    items = data_of(body).get("items") or []
    return [
        TableInfo(id=str(item["table_id"]), name=str(item.get("name") or ""))
        for item in items
        if isinstance(item, dict) and item.get("table_id")
    ]


async def list_fields(client: FeishuClient, app_token: str, table_id: str) -> list[FieldInfo]:
    body = await client.get(
        f"{_app_path(app_token)}/tables/{quote(table_id, safe='')}/fields",
        params={"page_size": 200},
    )
    items = data_of(body).get("items") or []
    out: list[FieldInfo] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("field_name"):
            continue
        out.append(
            FieldInfo(
                id=str(item.get("field_id") or ""),
                name=str(item["field_name"]),
                type=item.get("type") if isinstance(item.get("type"), int) else None,
                ui_type=str(item.get("ui_type") or ""),
            )
        )
    return out


async def iter_records(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    *,
    fields: list[str] | None = None,
    limit: int | None = None,
    page_size: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    "逐页读记录，产出**已经 flatten 过**的 ``{字段名: 值}``。"
    size = page_size or settings.feishu_bitable_page_size
    page_token: str | None = None
    seen = 0

    while True:
        params: dict[str, Any] = {"page_size": size, "page_token": page_token}

        wanted = set(fields) if fields else None

        body = await client.get(
            f"{_app_path(app_token)}/tables/{quote(table_id, safe='')}/records",
            params=params,
        )
        payload = data_of(body)
        items = payload.get("items") or []

        for item in items:
            if not isinstance(item, dict):
                continue
            raw = item.get("fields") or {}
            if not isinstance(raw, dict):
                continue

            if wanted is not None:
                raw = {k: v for k, v in raw.items() if k in wanted}
            yield {name: flatten(value) for name, value in raw.items()}
            seen += 1
            if limit is not None and seen >= limit:
                return
            if seen >= MAX_ROWS:
                return

        if not payload.get("has_more"):
            return
        page_token = payload.get("page_token")
        if not page_token:
            return
