"飞书**电子表格**（网格型）读取。"

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.feishu.cells import flatten
from app.services.feishu.client import FeishuClient, data_of
from app.services.feishu.errors import FeishuError
from app.services.sources.data import MAX_ROWS
from app.services.tabular import (
    RangeTooLarge,
    a1_address,
    assert_range_ok,
    cell_is_empty,
    column_count,
    index_to_col,
    row_has_data,
    rows_per_read,
)

__all__ = [
    "SheetInfo",
    "cell_is_empty",
    "column_count",
    "index_to_col",
    "iter_rows",
    "list_sheets",
    "read_date_matrix",
    "read_range",
    "read_rectangle",
    "row_has_data",
]


@dataclass(slots=True)
class SheetInfo:
    id: str
    name: str
    row_count: int | None = None
    col_count: int | None = None

    merges: list[Any] | None = None


def _range_path(sheet_id: str, address: str) -> str:
    "飞书的区域写法是 ``{sheetId}!{A1}``，整段要放进 URL 路径里。"
    return quote(f"{sheet_id}!{address}", safe="!:")


async def list_sheets(client: FeishuClient, spreadsheet_token: str) -> list[SheetInfo]:
    """列出电子表格里的所有工作表。"""
    body = await client.get(f"/sheets/v3/spreadsheets/{quote(spreadsheet_token, safe='')}/sheets/query")
    items = data_of(body).get("sheets") or []
    out: list[SheetInfo] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("sheet_id"):
            continue
        grid = item.get("grid_properties") or {}
        out.append(
            SheetInfo(
                id=str(item["sheet_id"]),
                name=str(item.get("title") or ""),
                row_count=grid.get("row_count") if isinstance(grid, dict) else None,
                col_count=grid.get("column_count") if isinstance(grid, dict) else None,
                merges=item.get("merges"),
            )
        )
    return out


async def read_range(client: FeishuClient, spreadsheet_token: str, sheet_id: str, address: str) -> list[list]:
    "读一块区域，返回二维数组。"
    path = (
        f"/sheets/v2/spreadsheets/{quote(spreadsheet_token, safe='')}"
        f"/values/{_range_path(sheet_id, address)}"
    )
    body = await client.get(path, params={"valueRenderOption": "UnformattedValue"})
    value_range = data_of(body).get("valueRange") or {}
    values = value_range.get("values") if isinstance(value_range, dict) else None
    if not values:
        return []

    return [[flatten(cell) for cell in (row if isinstance(row, list | tuple) else [row])] for row in values]


class _FeishuGrid:
    "把飞书的两个读原语包成 ``sources.matrix`` 要的形状。"

    def __init__(self, client: FeishuClient, spreadsheet_token: str) -> None:
        self._client = client
        self._token = spreadsheet_token

    async def read_range(self, sheet_id: str, address: str) -> list[list]:
        return await read_range(self._client, self._token, sheet_id, address)

    def iter_rows(self, sheet_id: str, **kwargs):
        return iter_rows(self._client, self._token, sheet_id, **kwargs)


async def read_date_matrix(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    *,
    header_row: int = 3,
    data_start_row: int = 4,
    field_col: str = "C",
    date_start_col: str = "E",
    limit: int | None = None,
):
    "日期交叉表（左侧科目、右侧按日期铺开）。"
    from app.services.sources.matrix import read_date_matrix as _read

    return await _read(
        _FeishuGrid(client, spreadsheet_token),
        sheet_id,
        header_row=header_row,
        data_start_row=data_start_row,
        field_col=field_col,
        date_start_col=date_start_col,
        limit=limit,
    )


async def read_rectangle(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    *,
    row_start: int,
    row_end: int,
    col_start_index: int,
    col_end_index: int,
    chunk_rows: int | None = None,
) -> list[list]:
    "按**行**分批读一个矩形，拼成一整块返回。"
    col_start = index_to_col(col_start_index)
    col_end = index_to_col(col_end_index)
    out: list[list] = []

    row = row_start
    while row <= row_end:
        step = rows_per_read(col_start, col_end, chunk_rows, max_cells=settings.feishu_sheet_max_cells)
        end = min(row + step - 1, row_end)
        address = a1_address(col_start, row, col_end, end)
        try:
            assert_range_ok(address, col_start, col_end, row, end, max_cells=settings.feishu_sheet_max_cells)
        except RangeTooLarge as exc:
            raise FeishuError(
                f"这次要读的范围太大：{exc.address} 一共 {exc.cells} 个单元格，"
                f"超过单次上限 {exc.max_cells} 个。",
                code="RANGE_TOO_LARGE",
                hint=(
                    f"窄一点就行：当前 {exc.columns} 列，"
                    f"一次最多读 {rows_per_read(col_start, col_end)} 行。"
                    "平台已经按这个规则自动分批了。"
                ),
            ) from exc
        out.extend(await read_range(client, spreadsheet_token, sheet_id, address))
        row = end + 1

    return out


async def iter_rows(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    *,
    start_row: int,
    col_start: str,
    col_end: str,
    batch_size: int | None = None,
    empty_batch_stop: int = 2,
    limit: int | None = None,
) -> AsyncIterator[tuple[int, list]]:
    "从 ``start_row`` 往下逐批读，产出 ``(行号, 各列值)``。"
    ceiling = batch_size or settings.default_batch_size
    step = rows_per_read(col_start, col_end, ceiling, max_cells=settings.feishu_sheet_max_cells)

    row = start_row
    emitted = 0
    empty_streak = 0

    while True:
        address = a1_address(col_start, row, col_end, row + step - 1)
        rows = await read_range(client, spreadsheet_token, sheet_id, address)
        if not rows:
            break

        batch_had_data = False
        for offset, values in enumerate(rows):
            values = list(values)
            if not row_has_data(values):
                continue
            batch_had_data = True
            yield row + offset, values
            emitted += 1
            if limit is not None and emitted >= limit:
                return
            if emitted >= MAX_ROWS:
                return

        if batch_had_data:
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak >= max(empty_batch_stop, 1):
                break

        row += len(rows) if len(rows) < step else step
