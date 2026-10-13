"WPS 个人版的「预览一个网页子表」实现。"

from __future__ import annotations

import logging
from typing import Any

from app.services.normalize.coercions import infer_transform, infer_type
from app.services.sources.base import SourceData
from app.services.sources.preview_util import display_rows, profiles
from app.services.webflow.actions import tsv_to_grid
from app.services.webflow.source import read_webflow, recipe_for

__all__ = ["preview_rows_webflow", "rows_envelope"]


async def preview_rows_webflow(
    app: object,
    doc: object,
    *,
    sheet_id: str = "",
    cfg: dict[str, Any] | None = None,
    limit: int | None = None,
    sheet_names: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    "读一次网页，把结果装成任务向导那套信封。"
    url = str(getattr(doc, "node_id", "") or "")
    source = await read_webflow(recipe_for(app, url), sheet=sheet_id, cfg=cfg, logger=logger)
    return rows_envelope(
        source,
        sheet_id=sheet_id or url,
        sheet_name=(sheet_names or {}).get(sheet_id, ""),
        cfg=cfg,
        limit=limit,
    )


def rows_envelope(
    source: SourceData,
    *,
    sheet_id: str = "",
    sheet_name: str = "",
    cfg: dict[str, Any] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    "``SourceData`` → 任务向导的预览信封。"
    cfg = dict(cfg or {})
    header = list(source.header)
    rows = [(row_no, list(values)) for row_no, values in source.rows]

    grid = tsv_to_grid(header, [values for _, values in rows])

    from app.services.normalize.rowfilter import row_should_skip, skip_config
    from app.services.normalize.rules import apply_rules, parse_rules
    from app.services.normalize.splitter import expand_rows, separator_indexes

    _, skip_words = skip_config(cfg)
    active_rules = parse_rules(cfg.get("rules"))
    separators = separator_indexes(header, cfg.get("split_columns"))

    skipped: set[int] = set()
    expanded: list[dict[str, Any]] = []
    for row_no, values in rows:
        if skip_words and row_should_skip(values, row_no, skip_words=skip_words):
            skipped.add(row_no)
        if active_rules:
            cells = ["" if v is None else str(v) for v in values]
            hit = apply_rules([cells], header, active_rules, first_row=row_no)
            if not hit.rows:
                skipped.add(row_no)
            for one in hit.hits:
                if one.action == "replace" and 0 <= one.index < len(values):
                    values[one.index] = one.after
        for piece in expand_rows([values], separators):
            expanded.append({"no": row_no, "values": piece})

    if limit is not None and limit > 0:
        expanded = expanded[:limit]

    raw_rows = [item["values"] for item in expanded]
    row_numbers = [item["no"] for item in expanded]
    profs = profiles(header, raw_rows)

    return {
        "ok": True,
        "header": header,
        "rows": display_rows(header, raw_rows, profs),
        "raw_rows": raw_rows,
        "total_preview": len(raw_rows),
        "inferred_header_row": None,
        "suggested_types": [infer_type(_column(raw_rows, i)) for i in range(len(header))],
        "suggested_transforms": [infer_transform(_column(raw_rows, i)) for i in range(len(header))],
        "column_stats": profs,
        "raw_grid": grid,
        "raw_grid_marks": [],
        "raw_origin": {"row": 1, "col": "A"},
        "row_numbers": row_numbers,
        "skipped_row_numbers": sorted(skipped),
        "raw_markers": {},
        "row_sources": [],
        "sheet_id": sheet_id,
        "sheet_name": sheet_name,
        "merged_sheet_names": [],
        "message": "",
    }


def _column(rows: list[list], index: int) -> list:
    return [r[index] for r in rows if index < len(r)]
