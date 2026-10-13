"钉钉的「预览一个子表」实现。"

from __future__ import annotations

from typing import Any

from app.services.dingtalk import aitable_reader
from app.services.dingtalk.client import DingTalkClient
from app.services.normalize.headers import normalize_headers
from app.services.sources.base import SourcePreview
from app.services.tabular import a1_address

__all__ = ["preview_dingtalk"]

PREVIEW_ROWS = 50


async def preview_dingtalk(
    client: DingTalkClient,
    *,
    doc_type: str | None,
    node_id: str,
    sheet_id: str,
    cfg: dict[str, Any],
    limit: int | None = None,
) -> SourcePreview:
    rows = limit or PREVIEW_ROWS

    if doc_type == "aitable":
        fields = await aitable_reader.list_fields(client, node_id, sheet_id)
        header = [f.name for f in fields]
        samples: list[list] = [[] for _ in header]
        async for record in aitable_reader.iter_records(client, node_id, sheet_id, limit=rows):
            for index, name in enumerate(header):
                if len(samples[index]) < rows:
                    samples[index].append(record.fields.get(name))
        return SourcePreview(header=header, samples=samples, engine="aitable")

    from app.services.dingtalk.sheet_reader import iter_rows, read_range

    header_row = int(cfg.get("header_row") or 1)
    col_start = str(cfg.get("col_start") or "A")
    col_end = str(cfg.get("col_end") or "Z")

    head = await read_range(client, node_id, sheet_id, a1_address(col_start, header_row, col_end, header_row))
    header = normalize_headers(head[0] if head else [])

    data_start = int(cfg.get("data_start_row") or header_row + 1)
    samples = [[] for _ in header]
    async for _, values in iter_rows(
        client,
        node_id,
        sheet_id,
        start_row=data_start,
        col_start=col_start,
        col_end=col_end,
        limit=rows,
    ):
        for index in range(len(header)):
            if index < len(values) and len(samples[index]) < rows:
                samples[index].append(values[index])

    return SourcePreview(header=header, samples=samples, engine="sheet")
