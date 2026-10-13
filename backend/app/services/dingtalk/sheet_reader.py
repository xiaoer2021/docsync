"""钉钉表格读取。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import quote

from app.core.config import settings
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.sources.base import SourceError
from app.services.tabular.align import align_headers as align_headers
from app.services.tabular.align import expand_row as expand_row
from app.services.tabular.align import is_placeholder_header as is_placeholder_header
from app.services.tabular.geometry import CELL_SAFETY as CELL_SAFETY
from app.services.tabular.geometry import MAX_CELLS as MAX_CELLS
from app.services.tabular.geometry import a1_address as a1_address
from app.services.tabular.geometry import cell_is_empty as cell_is_empty
from app.services.tabular.geometry import col_to_index as col_to_index
from app.services.tabular.geometry import cols_per_read as cols_per_read
from app.services.tabular.geometry import column_count as column_count
from app.services.tabular.geometry import index_to_col as index_to_col
from app.services.tabular.geometry import row_has_data as row_has_data
from app.services.tabular.geometry import rows_per_read as rows_per_read


def _q(value: object) -> str:
    return quote(str(value), safe="")


@dataclass(slots=True)
class SheetInfo:
    id: str
    name: str


async def list_sheets(client: DingTalkClient, workbook_id: str) -> list[SheetInfo]:
    body = await client.get(f"/v1.0/doc/workbooks/{_q(workbook_id)}/sheets")
    items = (body or {}).get("value") or []
    return [
        SheetInfo(id=str(item["id"]), name=str(item.get("name") or "")) for item in items if item.get("id")
    ]


async def read_range(client: DingTalkClient, workbook_id: str, sheet_id: str, address: str) -> list[list]:
    body = await client.get(
        f"/v1.0/doc/workbooks/{_q(workbook_id)}/sheets/{_q(sheet_id)}/ranges/{_q(address)}",
        params={"select": "values"},
    )
    values = (body or {}).get("values") or []
    return [list(row) if isinstance(row, list | tuple) else [row] for row in values]


def assert_range_ok(address: str, col_start: str, col_end: str, row_start: int, row_end: int) -> None:
    from app.services.tabular.geometry import RangeTooLarge

    try:
        from app.services.tabular.geometry import assert_range_ok as _assert

        _assert(address, col_start, col_end, row_start, row_end)
    except RangeTooLarge as exc:
        raise DingTalkError(
            f"这次要读的范围太大：{exc.address} 一共 {exc.cells} 个单元格，"
            f"超过钉钉单次上限 {exc.max_cells} 个。",
            code="RANGE_TOO_LARGE",
            hint=(
                f"窄一点就行：当前 {exc.columns} 列，"
                f"一次最多读 {rows_per_read(col_start, col_end)} 行。"
                "平台已经按这个规则自动分批了 —— 如果你是在别处看到这条，"
                "把列范围缩小，或者让平台自己分批读。"
            ),
        ) from exc


async def read_rectangle(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    *,
    row_start: int,
    row_end: int,
    col_start_index: int,
    col_end_index: int,
    chunk_cols: int | None = None,
) -> list[list]:
    "读一个矩形区域，自动按列切块避开 30000 格的限制。"
    rows_total = row_end - row_start + 1
    step = chunk_cols or cols_per_read(rows_total)
    merged: list[list] = []
    col = col_start_index

    while col <= col_end_index:
        last = min(col + step - 1, col_end_index)
        width = last - col + 1
        address = a1_address(index_to_col(col), row_start, index_to_col(last), row_end)
        assert_range_ok(address, index_to_col(col), index_to_col(last), row_start, row_end)
        block = await read_range(client, workbook_id, sheet_id, address)

        while len(merged) < len(block):
            merged.append([])
        for index, row in enumerate(block):
            padded = list(row[:width])
            padded.extend([None] * (width - len(padded)))
            merged[index].extend(padded)

        col = last + 1

    return merged


_is_blank = cell_is_empty

from app.services.sources.matrix import MatrixData as MatrixData  # noqa: E402


class _DingTalkGrid:
    "把钉钉的两个读原语包成 matrix 模块要的形状。"

    def __init__(self, client: DingTalkClient, workbook_id: str) -> None:
        self._client = client
        self._workbook_id = workbook_id

    async def read_range(self, sheet_id: str, address: str) -> list[list]:
        from app.services.dingtalk import sheet_reader as mod

        return await mod.read_range(self._client, self._workbook_id, sheet_id, address)

    def iter_rows(self, sheet_id: str, **kwargs):
        from app.services.dingtalk import sheet_reader as mod

        return mod.iter_rows(self._client, self._workbook_id, sheet_id, **kwargs)


async def read_date_matrix(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    *,
    header_row: int = 3,
    data_start_row: int = 4,
    field_col: str = "C",
    date_start_col: str = "E",
    limit: int | None = None,
) -> MatrixData:
    "日期交叉表。算法在 ``sources/matrix.py``，这里只做适配 + 异常翻译。"
    from app.services.sources.matrix import read_date_matrix as _read

    try:
        return await _read(
            _DingTalkGrid(client, workbook_id),
            sheet_id,
            header_row=header_row,
            data_start_row=data_start_row,
            field_col=field_col,
            date_start_col=date_start_col,
            limit=limit,
        )
    except SourceError as exc:
        raise DingTalkError(exc.message, code=exc.code, hint=exc.hint) from exc


_PROBE_WIDTH = 20


def _has_value_to_the_right(values: list, start: int = 1) -> bool:
    return any(not _is_blank(v) for v in values[start:])


async def _find_first_field_row(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    field_col: str,
    *,
    max_scan: int = 500,
) -> int | None:
    "找第一行「既是字段名、右边又有数据」的行。"
    field_idx = col_to_index(field_col)
    right_edge = index_to_col(field_idx + _PROBE_WIDTH)
    scan = 1

    while scan < 1 + max_scan:
        block = await read_range(
            client, workbook_id, sheet_id, a1_address(field_col, scan, right_edge, scan + 99)
        )
        if not block:
            return None
        for offset, values in enumerate(block):
            if not values or _is_blank(values[0]):
                continue
            if _has_value_to_the_right(values):
                return scan + offset
        scan += 100
    return None


async def _scan_row_extent(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    row: int,
    start_idx: int,
    *,
    max_cols: int = 3000,
    blank_stop: int = 10,
) -> int | None:
    """从某一行的 start_idx 往右扫，返回最后一个有值的列下标。"""
    end_idx: int | None = None
    blanks = 0
    probe_col = start_idx

    while probe_col < start_idx + max_cols:
        last = min(probe_col + 39, start_idx + max_cols - 1)
        block = await read_range(
            client,
            workbook_id,
            sheet_id,
            a1_address(index_to_col(probe_col), row, index_to_col(last), row),
        )
        values = block[0] if block else []
        if not values:
            return end_idx
        for offset, value in enumerate(values):
            if _is_blank(value):
                blanks += 1
                if blanks >= blank_stop:
                    return end_idx
            else:
                blanks = 0
                end_idx = probe_col + offset
        probe_col = last + 1

    return end_idx


@dataclass(slots=True)
class TransposedData:
    "横向表读出来的结果。"

    header: list[str]
    rows: list[tuple]
    field_names: list[str]
    record_names: list[str]
    first_data_col: int
    last_data_col: int

    first_field_row: int = 0
    extent_row: int | None = None


async def read_transposed(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    *,
    field_col: str = "A",
    field_start_row: int = 0,
    field_end_row: int = 0,
    data_start_col: str = "B",
    data_end_col: str = "",
    record_name_row: int = 0,
    record_column_name: str = "记录",
    max_fields: int = 500,
    max_records: int = 3000,
    blank_stop: int = 10,
) -> TransposedData:
    "读横向表并转置成「一行一条记录」。"
    start_idx = col_to_index(data_start_col)

    first_row = field_start_row
    if not first_row:
        first_row = await _find_first_field_row(client, workbook_id, sheet_id, field_col, max_scan=max_fields)
        if not first_row:
            raise DingTalkError(
                f"在 {field_col} 列里没找到「有名字、右边又有数据」的行。",
                code="NO_FIELD_COLUMN",
                hint=(
                    f"横向表要求字段名写在 {field_col} 列。找不到通常是这几种情况："
                    "① 字段名其实在别的列；② 这一列全是合并单元格；"
                    "③ 表格开头是图片或图表。可以手填「从第几行开始」直接指定。"
                ),
            )

    if field_end_row:
        end_row = field_end_row
    else:
        end_row = first_row
        blanks = 0
        probe_row = first_row
        while probe_row < first_row + max_fields:
            block = await read_range(
                client,
                workbook_id,
                sheet_id,
                a1_address(field_col, probe_row, field_col, probe_row + 199),
            )
            if not block:
                break
            for offset, values in enumerate(block):
                value = values[0] if values else None
                if _is_blank(value):
                    blanks += 1
                    if blanks >= blank_stop:
                        end_row = probe_row + offset - blanks
                        break
                else:
                    blanks = 0
                    end_row = probe_row + offset
            else:
                probe_row += 200
                continue
            break

    if end_row < first_row:
        raise DingTalkError(
            f"{field_col} 列第 {first_row} 行往后读不到任何字段名。",
            code="NO_FIELD_COLUMN",
            hint="检查「字段名从第几行开始」，或者换个列。",
        )

    field_block = await read_range(
        client,
        workbook_id,
        sheet_id,
        a1_address(field_col, first_row, field_col, end_row),
    )
    field_names: list[str] = []
    for values in field_block:
        raw = values[0] if values else None
        field_names.append("" if _is_blank(raw) else str(raw).strip())

    used_row: int | None = None
    if data_end_col:
        end_idx = col_to_index(data_end_col)
    else:
        candidates = list(dict.fromkeys(r for r in (record_name_row, first_row) if r))
        end_idx = None
        for row in candidates:
            found = await _scan_row_extent(
                client, workbook_id, sheet_id, row, start_idx, max_cols=max_records
            )
            if found is not None:
                end_idx = found
                used_row = row
                break

        if end_idx is None:
            raise DingTalkError(
                f"从 {data_start_col} 列往右没读到任何数据。",
                code="NO_DATA_COLUMN",
                hint=(
                    f"试过第 {'、'.join(str(r) for r in candidates)} 行都是空的。"
                    "要么数据其实不在这些列，要么这几行正好是合并标题。"
                    "建议直接把「数据到哪一列」手填死。"
                ),
            )

    record_names: list[str] = []
    if record_name_row:
        row_block = await read_rectangle(
            client,
            workbook_id,
            sheet_id,
            row_start=record_name_row,
            row_end=record_name_row,
            col_start_index=start_idx,
            col_end_index=end_idx,
        )
        values = row_block[0] if row_block else []
        record_names = ["" if _is_blank(v) else str(v).strip() for v in values]

    data = await read_rectangle(
        client,
        workbook_id,
        sheet_id,
        row_start=first_row,
        row_end=end_row,
        col_start_index=start_idx,
        col_end_index=end_idx,
    )

    header = [record_column_name, *field_names]
    rows: list[tuple] = []
    width = end_idx - start_idx + 1
    for offset in range(width):
        values: list = []
        for block_row in data:
            values.append(block_row[offset] if offset < len(block_row) else None)
        name = record_names[offset] if offset < len(record_names) else ""
        if not name:
            name = index_to_col(start_idx + offset)

        if all(_is_blank(v) for v in values):
            continue
        rows.append((start_idx + offset, [name, *values]))

    return TransposedData(
        header=header,
        rows=rows,
        field_names=field_names,
        record_names=record_names,
        first_data_col=start_idx,
        last_data_col=end_idx,
        first_field_row=first_row,
        extent_row=used_row,
    )


async def iter_rows(
    client: DingTalkClient,
    workbook_id: str,
    sheet_id: str,
    *,
    start_row: int,
    col_start: str,
    col_end: str,
    batch_size: int | None = None,
    empty_batch_stop: int | None = None,
    limit: int | None = None,
) -> AsyncIterator[tuple[int, list]]:
    "分块读取，产出 ``(Excel 行号, 该行各列的值)``。"
    ceiling = batch_size or settings.default_batch_size

    size = rows_per_read(col_start, col_end, ceiling)
    stop_after = empty_batch_stop if empty_batch_stop is not None else settings.sheet_empty_batch_stop

    row = max(int(start_row), 1)
    yielded = 0
    empty_batches = 0

    while True:
        end = row + size - 1
        address = a1_address(col_start, row, col_end, end)
        assert_range_ok(address, col_start, col_end, row, end)
        batch = await read_range(client, workbook_id, sheet_id, address)
        if not batch:
            return

        valid = 0
        for offset, values in enumerate(batch):
            if not row_has_data(values):
                continue
            yield row + offset, values
            valid += 1
            yielded += 1
            if limit is not None and yielded >= limit:
                return

        empty_batches = 0 if valid else empty_batches + 1
        if len(batch) < size or empty_batches >= stop_after:
            return
        row = end + 1
