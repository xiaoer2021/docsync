"钉钉的读源实现。"

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.dingtalk import aitable_reader
from app.services.dingtalk.client import DingTalkClient
from app.services.normalize.headers import normalize_headers
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
    expand_row,
    is_placeholder_header,
    missing_expected_headers,
)


class DingTalkSource:
    "钉钉读源。"

    platform = "dingtalk"

    def __init__(self, client: DingTalkClient) -> None:
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
        "按任务配置选一种读法。"
        if task.engine == "aitable":
            return await read_aitable(self.client, task, doc, logger, limit=limit)
        return await read_sheet(self.client, task, doc, logger, names, limit=limit, history=history)


async def read_sheet_horizontal(
    client: DingTalkClient,
    task: Any,
    doc: Any,
    logger: Any,
    names: dict[str, str],
    cfg: dict,
    *,
    limit: int | None,
) -> SourceData:
    "横向表：字段名在一列里，**一列一条记录**。"
    from app.services.dingtalk.sheet_reader import read_transposed

    sheet_ids = await _sheet_ids(task)
    kwargs = {
        "field_col": str(cfg.get("field_col") or "A"),
        "field_start_row": int(cfg.get("field_start_row") or 0),
        "field_end_row": int(cfg.get("field_end_row") or 0),
        "data_start_col": str(cfg.get("data_start_col") or "B"),
        "data_end_col": str(cfg.get("data_end_col") or ""),
        "record_name_row": int(cfg.get("record_name_row") or 0),
        "record_column_name": str(cfg.get("record_column_name") or "记录"),
    }

    base: SourceData | None = None
    multi = len(sheet_ids) > 1

    for sid in sheet_ids:
        pivot = await read_transposed(client, doc.node_id, sid, **kwargs)
        if not pivot.header:
            logger.warn(f"{_label(names, sid)}没读到字段名，跳过")
            continue
        if base is None:
            base = SourceData(header=pivot.header)
            logger.info(
                f"横向表：字段名取自 {kwargs['field_col']} 列，"
                f"共 {len(pivot.field_names)} 个字段，"
                f"数据列 {pivot.first_data_col + 1}~{pivot.last_data_col + 1}（一列一条记录）"
            )
            logger.info("字段：" + "、".join(pivot.field_names[:12]))
        elif pivot.header != base.header:
            raise RunAborted(
                f"{_label(names, sid)}的字段名跟主表不一致，合并会错位。"
                f"主表：{'、'.join(base.header[:6])}…；它：{'、'.join(pivot.header[:6])}…"
            )

        added = 0
        for row_no, values in pivot.rows:
            if limit is not None and len(base.rows) >= limit:
                break
            base.rows.append((row_no, list(values), sid) if multi else (row_no, list(values)))
            added += 1
            if len(base.rows) >= MAX_ROWS:
                logger.warn(f"超过 {MAX_ROWS} 行，只处理前 {MAX_ROWS} 行")
                break
        if multi:
            logger.info(f"{_label(names, sid)}读到 {added} 条记录")
        if len(base.rows) >= MAX_ROWS:
            break

    if base is None:
        raise RunAborted("没读到任何字段名。检查「字段名在哪一列 / 从第几行开始」填得对不对。")
    return base


async def read_sheet(
    client: DingTalkClient,
    task: Any,
    doc: Any,
    logger: Any,
    names: dict[str, str],
    *,
    limit: int | None,
    history: dict[str, list[str]] | None = None,
) -> SourceData:
    cfg = task.source_config or {}

    if str(cfg.get("orientation") or "vertical") == "matrix":
        from app.services.dingtalk.sheet_reader import read_date_matrix

        sheet_ids = await _sheet_ids(task)
        base = SourceData(header=["日期", "经营科目", "数值"])
        for sid in sheet_ids:
            matrix = await read_date_matrix(
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
                logger.info(
                    f"{_label(names, sid)}把 {matrix.corrected_zero_percent} 个重复百分号的零值按 0 读取"
                )
            for row_no, values in matrix.rows:
                base.rows.append((row_no, values, sid) if len(sheet_ids) > 1 else (row_no, values))
            logger.info(
                f"{_label(names, sid)}交叉表：{matrix.date_count} 个日期，"
                f"读到 {len(matrix.rows)} 条日数据；汇总列未作为日期读取"
            )
            if limit is not None and len(base.rows) >= limit:
                break
            if len(base.rows) >= MAX_ROWS:
                raise RunAborted(f"交叉表超过 {MAX_ROWS} 条记录，请缩小范围。")
        return base

    if str(cfg.get("orientation") or "vertical") == "horizontal":
        return await read_sheet_horizontal(client, task, doc, logger, names, cfg, limit=limit)

    header_row = int(cfg.get("header_row") or 1)
    data_start_row = int(cfg.get("data_start_row") or header_row + 1)
    col_start = str(cfg.get("col_start") or "A")
    col_end = str(cfg.get("col_end") or "Z")

    from app.services.dingtalk.sheet_reader import iter_rows, read_range

    sheet_ids = await _sheet_ids(task)
    multi = len(sheet_ids) > 1

    header_address = a1_address(col_start, header_row, col_end, header_row)

    raw_headers: list[list[str]] = []
    for sid in sheet_ids:
        head = await read_range(client, doc.node_id, sid, header_address)
        raw = head[0] if head else []
        raw_headers.append(normalize_headers(raw, width=len(raw) or None))

    header, slots = align_headers(raw_headers)

    logger.info(
        f"表头取第 {header_row} 行，共 {len(header)} 列："
        + "、".join(header[:10])
        + ("…" if len(header) > 10 else "")
    )

    if multi:
        log_merge_notes(logger, names, sheet_ids, raw_headers, header, slots)

    current_by_sheet = {
        sid: [c for c in (raw_headers[i] if i < len(raw_headers) else []) if not is_placeholder_header(c)]
        for i, sid in enumerate(sheet_ids)
    }
    if history is not None:
        mapped_sources = {str(c.get("source") or "").strip() for c in (task.columns or [])}
        note_column_changes(logger, names, sheet_ids, current_by_sheet, history, mapped_sources)

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
    for index, sid in enumerate(sheet_ids):
        if limit is not None and len(data.rows) >= limit:
            break
        remaining = None if limit is None else max(limit - len(data.rows), 0)
        if remaining == 0:
            break

        slot = slots[index] if index < len(slots) else []

        landed = 0
        blank = 0
        async for row_no, values in iter_rows(
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
            cells = expand_row(list(values), slot, len(header))

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
        if multi:
            logger.info(f"{_label(names, sid)}读到 {landed} 行")
        if len(data.rows) >= MAX_ROWS:
            break

    for note in find_same_name_conflicts(samples, header, names):
        logger.warn(note)

    data.sheet_column_types = column_types_from_samples(samples, header)

    return data


def log_merge_notes(
    logger: Any,
    names: dict[str, str],
    sheet_ids: list[str],
    raw_headers: list[list[str]],
    header: list[str],
    slots: list[list[int]],
) -> None:
    "合并多张表时，把「各表列不一样」说清楚。"
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


async def read_aitable(
    client: DingTalkClient,
    task: Any,
    doc: Any,
    logger: Any,
    *,
    limit: int | None,
) -> SourceData:
    cfg = task.source_config or {}
    picked = [str(f) for f in (cfg.get("fields") or []) if f]

    if not picked:
        fields = await aitable_reader.list_fields(client, doc.node_id, task.sheet_id)
        picked = [f.name for f in fields]
    header = list(picked)
    logger.info(f"多维表取 {len(header)} 个字段：" + "、".join(header[:10]))

    data = SourceData(header=header)
    async for record in aitable_reader.iter_records(
        client,
        doc.node_id,
        task.sheet_id,
        fields=picked or None,
        filter_spec=cfg.get("filter") or None,
        limit=limit,
    ):
        data.rows.append((None, [record.fields.get(name) for name in header]))
        if len(data.rows) % 1000 == 0:
            logger.info(f"多维表已读取 {len(data.rows)} 行")
        if len(data.rows) >= MAX_ROWS:
            logger.warn(f"超过 {MAX_ROWS} 行，只处理前 {MAX_ROWS} 行")
            break
    return data
