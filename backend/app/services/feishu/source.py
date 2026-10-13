"飞书的读源实现。"

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.feishu import bitable_reader, sheet_reader
from app.services.feishu.client import FeishuClient
from app.services.feishu.merges import VerticalFill, combine_header_with_parent, parse_merges
from app.services.normalize.headers import compose_header, normalize_headers
from app.services.sheet_meta import is_blank_row, note_column_changes
from app.services.sheet_meta import sheet_ids as _sheet_ids
from app.services.sheet_meta import sheet_label as _label
from app.services.sources.base import RunAborted
from app.services.sources.data import MAX_ROWS, SourceData
from app.services.sources.merge_check import (
    column_types_from_samples,
    find_same_name_conflicts,
    sample_row,
)
from app.services.tabular import (
    a1_address,
    align_headers,
    col_to_index,
    expand_row,
    is_placeholder_header,
    missing_expected_headers,
)

__all__ = ["FeishuSource"]


class FeishuSource:
    "飞书读源。"

    platform = "feishu"

    def __init__(self, client: FeishuClient) -> None:
        self.client = client

    async def read(
        self,
        task: Any,
        doc: Any,
        logger: Any,
        *,
        names: dict[str, str],
        history: dict[str, list[str]] | None = None,
        limit: int | None = None,
    ) -> SourceData:
        if task.engine == "aitable":
            return await read_bitable(self.client, task, doc, logger, limit=limit)
        return await read_grid(self.client, task, doc, logger, names, limit=limit, history=history)


def _seg_row(segment: dict, default: int) -> int:
    """这一段取第几行。写错了退回 ``default`` —— 配置错误不该变成 500。"""
    try:
        row = int(segment.get("row") or default)
    except (TypeError, ValueError):
        return default
    return max(row, 1)


def _unsupported_orientation(orientation: str) -> RunAborted:
    label = {"horizontal": "横向表", "matrix": "交叉表"}.get(orientation, orientation)
    return RunAborted(
        f"飞书电子表格暂时还不支持「{label}」这种摆法。"
        "现在支持的是「表头在第一行、一行一条记录」的普通表和日期交叉表。"
        "要么把这张表改成普通表（推荐），要么先用钉钉那套跑 —— "
        "硬读会把列读错，比不做更糟。"
    )


async def read_matrix(
    client: FeishuClient,
    task: Any,
    doc: Any,
    logger: Any,
    names: dict[str, str],
    *,
    limit: int | None,
) -> SourceData:
    "日期交叉表（左侧科目、右侧按日期铺开）。"
    cfg = task.source_config or {}
    sheet_ids_ = await _sheet_ids(task)
    base = SourceData(header=["日期", "经营科目", "数值"])

    for sid in sheet_ids_:
        matrix = await sheet_reader.read_date_matrix(
            client,
            doc.node_id,
            sid,
            header_row=int(cfg.get("matrix_header_row") or 3),
            data_start_row=int(cfg.get("matrix_data_start_row") or 4),
            field_col=str(cfg.get("matrix_field_col") or "C"),
            date_start_col=str(cfg.get("matrix_date_start_col") or "E"),
            limit=None if limit is None else max(limit - len(base.rows), 1),
        )

        base.header = matrix.header
        if matrix.formula_errors:
            base.skipped_formula_cells += len(matrix.formula_errors)
            examples = "、".join(matrix.formula_errors[:5])
            if str((task.target or {}).get("write_mode") or "") == "full_replace":
                raise RunAborted(
                    f"{_label(names, sid)}有 {len(matrix.formula_errors)} 个公式错误"
                    f"（{examples}）；整表重写会丢失这些记录，已阻止写入。"
                )
            logger.warn(
                f"{_label(names, sid)}有 {len(matrix.formula_errors)} 个公式错误"
                "单元格，已按 0 写入（源表修好后重跑可覆盖）"
                f"（{examples}）；源表修复后重跑可补齐"
            )
        if matrix.corrected_zero_percent:
            logger.info(f"{_label(names, sid)}把 {matrix.corrected_zero_percent} 个重复百分号的零值按 0 读取")
        for row_no, values in matrix.rows:
            base.rows.append((row_no, values, sid) if len(sheet_ids_) > 1 else (row_no, values))
        logger.info(
            f"{_label(names, sid)}交叉表：{matrix.date_count} 个日期，"
            f"读到 {len(matrix.rows)} 条日数据；汇总列未作为日期读取"
        )
        if limit is not None and len(base.rows) >= limit:
            break
        if len(base.rows) >= MAX_ROWS:
            raise RunAborted(f"交叉表超过 {MAX_ROWS} 条记录，请缩小范围。")

    return base


async def _merges_by_sheet(client: FeishuClient, token: str) -> dict[str, list]:
    "一次拿到所有子表的合并范围。"
    sheets = await sheet_reader.list_sheets(client, token)
    return {sheet.id: parse_merges(sheet.merges) for sheet in sheets}


async def read_grid(
    client: FeishuClient,
    task: Any,
    doc: Any,
    logger: Any,
    names: dict[str, str],
    *,
    limit: int | None,
    history: dict[str, list[str]] | None = None,
) -> SourceData:
    "电子表格（网格型）。逻辑跟钉钉那份**刻意保持同构** ——"
    cfg = task.source_config or {}

    orientation = str(cfg.get("orientation") or "vertical")
    if orientation == "matrix":
        return await read_matrix(client, task, doc, logger, names, limit=limit)
    if orientation == "horizontal":
        raise _unsupported_orientation(orientation)

    header_row = int(cfg.get("header_row") or 1)
    data_start_row = int(cfg.get("data_start_row") or header_row + 1)
    col_start = str(cfg.get("col_start") or "A")
    col_end = str(cfg.get("col_end") or "Z")

    segments = cfg.get("header_rows")

    sheet_ids_ = await _sheet_ids(task)
    multi = len(sheet_ids_) > 1

    merges_map = await _merges_by_sheet(client, doc.node_id)
    col_offset = col_to_index(col_start)

    raw_headers: list[list[str]] = []
    for sid in sheet_ids_:
        if segments:
            rows = [int(_seg_row(seg, header_row)) for seg in segments]
            top, bottom = min(rows), max(rows)
            block = await sheet_reader.read_range(
                client, doc.node_id, sid, a1_address(col_start, top, col_end, bottom)
            )
            width = max((len(row) for row in block), default=0)
            if not width:
                raw_headers.append([])
                continue
            values, max_row = compose_header(
                block,
                segments,
                first_row=top,
                col_start_index=col_offset,
                width=width,
            )
            raw_headers.append(normalize_headers(values, width=width))

            data_start_row = max(data_start_row, max_row + 1)
            continue

        top = max(header_row - 1, 1)
        block = await sheet_reader.read_range(
            client, doc.node_id, sid, a1_address(col_start, top, col_end, header_row)
        )
        own = list(block[-1]) if block else []
        parent = list(block[-2]) if len(block) >= 2 else []
        names = normalize_headers(own, width=len(own) or None)
        spans = merges_map.get(sid) or []
        if spans and header_row > 1:
            names = combine_header_with_parent(
                names,
                parent,
                spans,
                header_row=header_row,
                parent_row=header_row - 1,
                column_offset=col_offset,
            )
        raw_headers.append(names)

    header, slots = align_headers(raw_headers)

    if segments:
        used = "、".join(f"{seg.get('col_start') or 'A'}→第{_seg_row(seg, header_row)}行" for seg in segments)
        logger.info(
            f"表头分段取行（{used}），数据从第 {data_start_row} 行开始，"
            f"共 {len(header)} 列：" + "、".join(header[:10]) + ("…" if len(header) > 10 else "")
        )
    else:
        logger.info(
            f"表头取第 {header_row} 行，共 {len(header)} 列："
            + "、".join(header[:10])
            + ("…" if len(header) > 10 else "")
        )

    if multi:
        _log_merge_notes(logger, names, sheet_ids_, raw_headers, header)

    current_by_sheet = {
        sid: [c for c in (raw_headers[i] if i < len(raw_headers) else []) if not is_placeholder_header(c)]
        for i, sid in enumerate(sheet_ids_)
    }
    if history is not None:
        mapped_sources = {str(c.get("source") or "").strip() for c in (task.columns or [])}
        note_column_changes(logger, names, sheet_ids_, current_by_sheet, history, mapped_sources)

    check = bool(cfg.get("header_check"))
    expected = [str(c) for c in (cfg.get("expected_header") or []) if str(c).strip()]
    if check and expected:
        missing = missing_expected_headers(expected, header)
        if missing:
            raise RunAborted(
                "表头校验不通过，这几列没有找到："
                + "、".join(missing[:8])
                + ("…" if len(missing) > 8 else "")
                + " 实际表头："
                + "、".join(header[:8])
            )

    data = SourceData(header=header, sheet_columns=current_by_sheet)

    samples: dict[str, dict[int, list]] = {}
    for index, sid in enumerate(sheet_ids_):
        if limit is not None and len(data.rows) >= limit:
            break
        remaining = None if limit is None else max(limit - len(data.rows), 0)
        if remaining == 0:
            break

        slot = slots[index] if index < len(slots) else []
        landed = 0
        blank = 0

        fill = VerticalFill(merges_map.get(sid) or [], first_row=data_start_row, column_offset=col_offset)

        async for row_no, values in sheet_reader.iter_rows(
            client,
            doc.node_id,
            sid,
            start_row=data_start_row,
            col_start=col_start,
            col_end=col_end,
            batch_size=int(cfg.get("batch_size") or settings.default_batch_size),
            empty_batch_stop=int(cfg.get("empty_batch_stop") or settings.sheet_empty_batch_stop),
            limit=remaining,
        ):
            cells = expand_row(fill.apply(row_no, list(values)), slot, len(header))
            if is_blank_row(cells):
                blank += 1
                continue
            sample_row(samples, sid, cells)
            data.rows.append((row_no, cells, sid) if multi else (row_no, cells))
            landed += 1
            if landed % 1000 == 0:
                logger.info(f"{_label(names, sid)}已读取 {landed} 行")
            if len(data.rows) >= MAX_ROWS:
                logger.warn(f"超过 {MAX_ROWS} 行，只处理前 {MAX_ROWS} 行")
                break

        if blank:
            logger.info(f"{_label(names, sid) if multi else ''}跳过 {blank} 个空行（整行都没内容）")
        if fill.filled:
            logger.info(
                f"{_label(names, sid) if multi else ''}按合并单元格补了 {fill.filled} 个格子"
                "（表格里这些格是合并的，值取自合并区的第一行）"
            )
        if multi:
            logger.info(f"{_label(names, sid)}读到 {landed} 行")
        if len(data.rows) >= MAX_ROWS:
            break

    for note in find_same_name_conflicts(samples, header, names):
        logger.warn(note)

    data.sheet_column_types = column_types_from_samples(samples, header)

    return data


def _log_merge_notes(
    logger: Any,
    names: dict[str, str],
    sheet_ids: list[str],
    raw_headers: list[list[str]],
    header: list[str],
) -> None:
    """合并多张表时说明各表列差异。按名字对齐之后这属于正常情况，只告知不报错。"""
    main = set(raw_headers[0]) if raw_headers else set()
    notes: list[str] = []
    for index, sid in enumerate(sheet_ids):
        if index == 0:
            continue
        mine = set(raw_headers[index]) if index < len(raw_headers) else set()
        missing = [c for c in header if c in main and c not in mine]
        extra = [c for c in header if c not in main and c in mine]
        label = _label(names, sid)
        if missing:
            notes.append(f"{label} 少 {len(missing)} 列（{'、'.join(missing[:4])}），那些列在它那边留空")
        if extra:
            notes.append(f"{label} 多 {len(extra)} 列（{'、'.join(extra[:4])}），已并入目标表")
    if notes:
        logger.warn("各子表的列不完全一样，已按列名对齐（不会错列）：" + "；".join(notes[:6]))
    logger.info(f"合并 {len(sheet_ids)} 个子表，按列名对齐，共 {len(header)} 列")


async def read_bitable(
    client: FeishuClient,
    task: Any,
    doc: Any,
    logger: Any,
    *,
    limit: int | None,
) -> SourceData:
    "多维表格（记录型）。"
    cfg = task.source_config or {}
    picked = [str(f) for f in (cfg.get("fields") or []) if f]

    if not picked:
        fields = await bitable_reader.list_fields(client, doc.node_id, task.sheet_id)
        picked = [f.name for f in fields]

    if not picked:
        raise RunAborted(
            "这个数据表里一个字段都没读到。检查应用是不是这张多维表格的协作者，"
            "以及「多维表格读权限」开了没有（开了还要发布版本）。"
        )

    header = list(picked)
    logger.info(f"多维表取 {len(header)} 个字段：" + "、".join(header[:10]))

    data = SourceData(header=header)
    async for record in bitable_reader.iter_records(
        client, doc.node_id, task.sheet_id, fields=picked, limit=limit
    ):
        data.rows.append((None, [record.get(name) for name in header]))
        if len(data.rows) % 1000 == 0:
            logger.info(f"多维表已读取 {len(data.rows)} 行")
        if len(data.rows) >= MAX_ROWS:
            logger.warn(f"超过 {MAX_ROWS} 行，只处理前 {MAX_ROWS} 行")
            break

    logger.info(f"读记录型表 {len(data.rows)} 行")
    return data
