"飞书的「预览一个子表」实现。"

from __future__ import annotations

from typing import Any

from app.services.feishu import bitable_reader, sheet_reader
from app.services.feishu.client import FeishuClient
from app.services.normalize.headers import compose_header, infer_header_row, normalize_headers
from app.services.normalize.splitter import expand_rows, separator_indexes
from app.services.sources.base import SourceError, SourcePreview
from app.services.sources.preview_util import display_rows, format_grid, profiles
from app.services.tabular import a1_address, col_to_index, index_to_col

__all__ = ["PREVIEW_ROWS", "preview_feishu"]

PREVIEW_ROWS = 50


async def preview_rows_feishu(
    client: FeishuClient,
    *,
    node_id: str,
    doc_type: str | None,
    sheet_id: str,
    cfg: dict[str, Any],
    rows_wanted: int,
    merge_ids: list[str] | None = None,
    sheet_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    "数据预览：给任务向导第 2 步看的样数据。"

    merge_ids = list(merge_ids or [])
    sheet_names = sheet_names or {}
    cfg = dict(cfg or {})

    suggested: dict[str, Any] | None = None
    if doc_type != "aitable" and not cfg.get("orientation"):
        from app.services.sources.layout import detect_layout

        probe = await sheet_reader.read_range(client, node_id, sheet_id, a1_address("A", 1, "T", 20))
        found = detect_layout(probe)
        suggested = {
            "orientation": found.orientation,
            "header_row": found.header_row,
            "data_start_row": found.data_start_row,
            "field_col": found.field_col,
            "date_start_col": found.date_start_col,
            "axis_kind": found.axis_kind,
            "axis_count": found.axis_count,
            "confidence": found.confidence,
            "reasons": found.reasons,
        }
        cfg.update(
            {
                "orientation": found.orientation,
                "header_row": found.header_row,
                "data_start_row": found.data_start_row,
            }
        )
        if found.orientation == "matrix":
            cfg.update(
                {
                    "matrix_header_row": found.header_row,
                    "matrix_data_start_row": found.data_start_row,
                    "matrix_field_col": found.field_col,
                    "matrix_date_start_col": found.date_start_col,
                }
            )

    envelope = await _preview_with_layout(
        client,
        node_id=node_id,
        doc_type=doc_type,
        sheet_id=sheet_id,
        cfg=cfg,
        rows_wanted=rows_wanted,
        merge_ids=merge_ids,
        sheet_names=sheet_names,
    )
    if suggested is not None:
        envelope["suggested"] = suggested
    return envelope


async def _preview_with_layout(
    client: FeishuClient,
    *,
    node_id: str,
    doc_type: str | None,
    sheet_id: str,
    cfg: dict[str, Any],
    rows_wanted: int,
    merge_ids: list[str],
    sheet_names: dict[str, str],
) -> dict[str, Any]:
    """按已经确定下来的摆法去读。跟识别分开，是为了各自能单独测。"""
    orientation = str(cfg.get("orientation") or "vertical")
    if orientation == "matrix":
        return await _envelope_for_matrix(
            client,
            node_id=node_id,
            sheet_id=sheet_id,
            cfg=cfg,
            rows_wanted=rows_wanted,
            sheet_names=sheet_names,
        )
    if orientation == "horizontal":
        return {
            "ok": False,
            "error": "飞书电子表格暂时还不支持「横向表」这种摆法。",
            "hint": "目前支持「纵向表」和「日期交叉表」。横向表要整列探测才知道哪块是数据，还没做。",
        }

    header_row = int(cfg.get("header_row") or 1)
    data_start_row = int(cfg.get("data_start_row") or header_row + 1)
    col_start = str(cfg.get("col_start") or "A")
    col_end = str(cfg.get("col_end") or "Z")

    segments = cfg.get("header_rows")
    col_offset = col_to_index(col_start)
    header_indexes: set[int] = set()

    if doc_type == "aitable":
        return await _envelope_for_records(
            client,
            node_id=node_id,
            sheet_id=sheet_id,
            cfg=cfg,
            rows_wanted=rows_wanted,
            sheet_names=sheet_names,
        )

    probe = await sheet_reader.read_range(client, node_id, sheet_id, a1_address(col_start, 1, col_end, 15))
    if not int(cfg.get("header_row") or 0):
        header_row = infer_header_row(probe, start_row=1)
    if not int(cfg.get("data_start_row") or 0):
        data_start_row = header_row + 1

    header_indexes = {header_row - 1}
    grid_view, marks = format_grid(probe, header_rows=header_indexes)

    if segments:
        values, max_row = compose_header(
            probe,
            segments,
            first_row=1,
            col_start_index=col_offset,
            width=max((len(row) for row in probe), default=0),
        )
        header = normalize_headers(values, width=len(values) or None)

        data_start_row = max(data_start_row, max_row + 1)

        header_indexes = {row - 1 for row in {_seg_row(seg) for seg in segments}}
        grid_view, marks = format_grid(probe, header_rows=header_indexes)
    else:
        head = await sheet_reader.read_range(
            client, node_id, sheet_id, a1_address(col_start, header_row, col_end, header_row)
        )
        header = normalize_headers(head[0] if head else [])

    all_ids = [sheet_id, *merge_ids]
    multi = len(all_ids) > 1
    collected: list[tuple] = []
    for sid in all_ids:
        if len(collected) >= rows_wanted:
            break
        remaining = max(rows_wanted - len(collected), 0)
        async for row_no, values in sheet_reader.iter_rows(
            client,
            node_id,
            sid,
            start_row=data_start_row,
            col_start=col_start,
            col_end=col_end,
            limit=remaining,
        ):
            collected.append((sid, row_no, list(values)))

    from app.services.normalize.rowfilter import row_should_skip, skip_config
    from app.services.normalize.rules import apply_rules, parse_rules

    _, skip_words_cfg = skip_config(cfg)

    active_rules = parse_rules(cfg.get("rules"))
    separators = separator_indexes(header, cfg.get("split_columns"))

    skipped_by_words: set[int] = set()
    rule_notes: list[str] = []
    expanded: list[dict] = []
    for _, row_no, values in collected:
        if skip_words_cfg and row_should_skip(values, row_no, skip_words=skip_words_cfg):
            skipped_by_words.add(row_no)
        if active_rules:
            cells = ["" if v is None else str(v) for v in values]
            hit = apply_rules([cells], header, active_rules, first_row=row_no)
            if not hit.rows:
                skipped_by_words.add(row_no)
            for one in hit.hits:
                if one.action == "replace" and 0 <= one.index < len(values):
                    values[one.index] = one.after
                    rule_notes.append(
                        f"第 {row_no} 行「{one.column}」把「{one.before}」换成了「{one.after}」"
                    )
        for piece in expand_rows([values], separators):
            expanded.append({"no": row_no, "values": piece})

    raw_rows = [item["values"] for item in expanded]
    row_numbers = [item["no"] for item in expanded]
    profs = profiles(header, raw_rows)
    from app.services.normalize.coercions import infer_transform, infer_type

    return {
        "ok": True,
        "header": header,
        "rows": display_rows(header, raw_rows, profs),
        "raw_rows": raw_rows,
        "total_preview": len(raw_rows),
        "inferred_header_row": header_row,
        "suggested_types": [infer_type(_column(raw_rows, i)) for i in range(len(header))],
        "suggested_transforms": [infer_transform(_column(raw_rows, i)) for i in range(len(header))],
        "column_stats": profs,
        "raw_grid": grid_view,
        "raw_grid_marks": marks,
        "raw_origin": {"row": 1, "col": col_start},
        "row_numbers": row_numbers,
        "skipped_row_numbers": sorted(skipped_by_words),
        "raw_markers": {},
        "row_sources": [sid for sid, _, _ in collected] if multi else [],
        "sheet_id": sheet_id,
        "sheet_name": sheet_names.get(sheet_id, ""),
        "merged_sheet_names": [sheet_names.get(s, s) for s in merge_ids],
        "message": "",
    }


def _seg_row(segment: dict, default: int = 1) -> int:
    """这一段取第几行。写错了退回 ``default`` —— 配置错误不该变成 500。"""
    try:
        row = int(segment.get("row") or default)
    except (TypeError, ValueError):
        return default
    return max(row, 1)


def _column(rows: list[list], index: int) -> list:
    return [r[index] for r in rows if index < len(r)]


async def _envelope_for_matrix(
    client: FeishuClient,
    *,
    node_id: str,
    sheet_id: str,
    cfg: dict[str, Any],
    rows_wanted: int,
    sheet_names: dict[str, str],
) -> dict[str, Any]:
    "日期交叉表的预览。"
    from app.services.normalize.coercions import infer_transform
    from app.services.sources.preview_util import display_rows, format_grid, profiles

    header_row = int(cfg.get("matrix_header_row") or 3)
    field_col = str(cfg.get("matrix_field_col") or "C")
    date_start_col = str(cfg.get("matrix_date_start_col") or "E")

    probe = await sheet_reader.read_range(
        client,
        node_id,
        sheet_id,
        a1_address(field_col, 1, index_to_col(col_to_index(field_col) + 8), 15),
    )
    grid_view, marks = format_grid(probe, header_rows={header_row - 1})

    try:
        matrix = await sheet_reader.read_date_matrix(
            client,
            node_id,
            sheet_id,
            header_row=header_row,
            data_start_row=int(cfg.get("matrix_data_start_row") or 4),
            field_col=field_col,
            date_start_col=date_start_col,
            limit=rows_wanted,
        )
    except SourceError as exc:
        return {"ok": False, "error": exc.message, "hint": exc.hint}

    raw_rows = [values for _, values in matrix.rows]
    profs = profiles(matrix.header, raw_rows)
    from app.services.normalize.coercions import infer_type

    width = len(matrix.header)
    out: dict[str, Any] = {
        "ok": True,
        "header": matrix.header,
        "rows": display_rows(matrix.header, raw_rows, profs),
        "raw_rows": raw_rows,
        "total_preview": len(raw_rows),
        "inferred_header_row": None,
        "suggested_types": [infer_type(_column(raw_rows, i)) for i in range(width)],
        "suggested_transforms": [infer_transform(_column(raw_rows, i)) for i in range(width)],
        "column_stats": profs,
        "raw_grid": grid_view,
        "raw_grid_marks": marks,
        "raw_origin": {"row": 1, "col": field_col},
        "row_numbers": [row_no for row_no, _ in matrix.rows],
        "skipped_row_numbers": [],
        "raw_markers": {},
        "row_sources": [],
        "sheet_id": sheet_id,
        "sheet_name": sheet_names.get(sheet_id, ""),
        "merged_sheet_names": [],
        "message": f"交叉表：{matrix.date_count} 个日期，转成 {len(raw_rows)} 条日数据",
    }
    if matrix.formula_errors:
        out["message"] += (
            f"；{len(matrix.formula_errors)} 个公式错误格已按 0 读取"
            f"（如 {'、'.join(matrix.formula_errors[:3])}）"
        )
    return out


async def _envelope_for_records(
    client: FeishuClient,
    *,
    node_id: str,
    sheet_id: str,
    cfg: dict[str, Any],
    rows_wanted: int,
    sheet_names: dict[str, str],
) -> dict[str, Any]:
    """记录型的预览：没有「网格」这个概念，raw_grid 留空。"""
    from app.services.normalize.coercions import infer_transform
    from app.services.sources.preview_util import display_rows, profiles

    picked = [str(f) for f in (cfg.get("fields") or []) if f]
    if not picked:
        picked = [f.name for f in await bitable_reader.list_fields(client, node_id, sheet_id)]

    raw_rows: list[list] = []
    async for record in bitable_reader.iter_records(
        client, node_id, sheet_id, fields=picked, limit=rows_wanted
    ):
        raw_rows.append([record.get(name) for name in picked])

    profs = profiles(picked, raw_rows)
    from app.services.normalize.coercions import infer_type

    return {
        "ok": True,
        "header": picked,
        "rows": display_rows(picked, raw_rows, profs),
        "raw_rows": raw_rows,
        "total_preview": len(raw_rows),
        "inferred_header_row": None,
        "suggested_types": [infer_type(_column(raw_rows, i)) for i in range(len(picked))],
        "suggested_transforms": [infer_transform(_column(raw_rows, i)) for i in range(len(picked))],
        "column_stats": profs,
        "raw_grid": [],
        "raw_grid_marks": [],
        "raw_origin": {"row": 1, "col": "A"},
        "row_numbers": [],
        "skipped_row_numbers": [],
        "raw_markers": {},
        "row_sources": [],
        "sheet_id": sheet_id,
        "sheet_name": sheet_names.get(sheet_id, ""),
        "merged_sheet_names": [],
        "message": "",
    }


async def preview_feishu(
    client: FeishuClient,
    *,
    doc_type: str | None,
    node_id: str,
    sheet_id: str,
    cfg: dict[str, Any],
    limit: int | None = None,
) -> SourcePreview:
    rows = limit or PREVIEW_ROWS

    if doc_type == "aitable":
        fields = await bitable_reader.list_fields(client, node_id, sheet_id)
        header = [f.name for f in fields]
        samples: list[list] = [[] for _ in header]
        async for record in bitable_reader.iter_records(
            client, node_id, sheet_id, fields=header or None, limit=rows
        ):
            for index, name in enumerate(header):
                if len(samples[index]) < rows:
                    samples[index].append(record.get(name))
        return SourcePreview(header=header, samples=samples, engine="aitable")

    header_row = int(cfg.get("header_row") or 1)
    col_start = str(cfg.get("col_start") or "A")
    col_end = str(cfg.get("col_end") or "Z")

    head = await sheet_reader.read_range(
        client, node_id, sheet_id, a1_address(col_start, header_row, col_end, header_row)
    )
    header = normalize_headers(head[0] if head else [])

    data_start = int(cfg.get("data_start_row") or header_row + 1)
    samples = [[] for _ in header]
    async for _, values in sheet_reader.iter_rows(
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
