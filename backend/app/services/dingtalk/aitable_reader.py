from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.dingtalk.client import DingTalkClient


def _q(value: object) -> str:
    return quote(str(value), safe="")


@dataclass(slots=True)
class TableInfo:
    id: str
    name: str


@dataclass(slots=True)
class FieldInfo:
    id: str
    name: str
    type: str = ""


@dataclass(slots=True)
class Record:
    id: str
    fields: dict[str, Any] = field(default_factory=dict)


_LABEL_KEYS = ("name", "text", "value", "title", "label", "displayValue")


def simplify(value: Any) -> Any:
    "把钉钉返回的复合字段值降级成能直接入库的标量。"
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, list):
        parts = [simplify(item) for item in value]
        flat = [p for p in parts if p not in (None, "")]
        if not flat:
            return None

        if all(isinstance(p, str | int | float | bool) for p in flat):
            return "、".join(str(p) for p in flat)
        return json.dumps(flat, ensure_ascii=False)

    if isinstance(value, dict):
        for key in _LABEL_KEYS:
            inner = value.get(key)
            if inner not in (None, "", []):
                return simplify(inner)
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def _unwrap(body: Any) -> list[dict]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        for key in ("value", "values", "data", "list"):
            inner = body.get(key)
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, dict)]
    return []


async def list_tables(client: DingTalkClient, base_id: str) -> list[TableInfo]:
    body = await client.get(f"/v1.0/notable/bases/{_q(base_id)}/sheets")
    return [
        TableInfo(id=str(item.get("id") or ""), name=str(item.get("name") or ""))
        for item in _unwrap(body)
        if item.get("id")
    ]


async def list_fields(client: DingTalkClient, base_id: str, table_ref: str) -> list[FieldInfo]:
    body = await client.get(f"/v1.0/notable/bases/{_q(base_id)}/sheets/{_q(table_ref)}/fields")
    out: list[FieldInfo] = []
    for item in _unwrap(body):
        name = str(item.get("name") or "")
        if not name:
            continue
        out.append(
            FieldInfo(
                id=str(item.get("id") or name),
                name=name,
                type=str(item.get("type") or ""),
            )
        )
    return out


async def iter_records(
    client: DingTalkClient,
    base_id: str,
    table_ref: str,
    *,
    fields: list[str] | None = None,
    filter_spec: dict[str, Any] | None = None,
    page_size: int | None = None,
    limit: int | None = None,
) -> AsyncIterator[Record]:
    "游标分页拉记录。"
    size = min(page_size or settings.aitable_page_size, 100)
    next_token: str | None = None
    produced = 0

    while True:
        payload: dict[str, Any] = {"maxResults": size}
        if next_token:
            payload["nextToken"] = next_token
        if fields:
            payload["fieldIdOrNames"] = fields[:100]
        if filter_spec:
            payload["filter"] = filter_spec

        body = await client.post(
            f"/v1.0/notable/bases/{_q(base_id)}/sheets/{_q(table_ref)}/records/list",
            json=payload,
        )
        body = body or {}
        for item in body.get("records") or []:
            raw_fields = item.get("fields") or {}
            if not isinstance(raw_fields, dict):
                raw_fields = {}
            yield Record(
                id=str(item.get("id") or ""),
                fields={str(k): simplify(v) for k, v in raw_fields.items()},
            )
            produced += 1
            if limit is not None and produced >= limit:
                return

        if not body.get("hasMore"):
            return
        next_token = body.get("nextToken")
        if not next_token:
            return
