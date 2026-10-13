"表格几何：列号换算、分批大小、范围自检。"

from __future__ import annotations

import re

_COL_RE = re.compile(r"^([A-Za-z]+)$")

MAX_CELLS = 30000

CELL_SAFETY = 28000


class RangeTooLarge(ValueError):
    "一次要读的区域超过了平台上限。"

    def __init__(self, *, address: str, cells: int, columns: int, rows: int, max_cells: int) -> None:
        super().__init__(f"{address} 一共 {cells} 个单元格，超过单次上限 {max_cells} 个")
        self.address = address
        self.cells = cells
        self.columns = columns
        self.rows = rows
        self.max_cells = max_cells


def col_to_index(letters: str) -> int:
    """``A`` → 0，``AA`` → 26。"""
    text = (letters or "").strip().upper()
    if not _COL_RE.match(text):
        raise ValueError(f"列号不合法：{letters!r}")
    index = 0
    for ch in text:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def index_to_col(index: int) -> str:
    """0 → ``A``，26 → ``AA``。"""
    if index < 0:
        raise ValueError("列序号不能为负")
    letters = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def a1_address(col_start: str, row_start: int, col_end: str, row_end: int) -> str:
    return f"{col_start.strip().upper()}{row_start}:{col_end.strip().upper()}{row_end}"


def column_count(col_start: str, col_end: str) -> int:
    return col_to_index(col_end) - col_to_index(col_start) + 1


def rows_per_read(
    col_start: str, col_end: str, ceiling: int | None = None, *, max_cells: int = CELL_SAFETY
) -> int:
    "按单元格上限算出一次最多能读几行。"
    width = max(column_count(col_start, col_end), 1)
    allowed = max(max_cells // width, 1)
    if ceiling is None:
        return allowed
    return max(min(allowed, ceiling), 1)


def cols_per_read(row_count: int, *, ceiling: int = 200, max_cells: int = CELL_SAFETY) -> int:
    "横向表按**列**分批时，一次能读几列。"
    rows = max(row_count, 1)
    return max(min(max_cells // rows, ceiling), 1)


def row_has_data(values: list) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
        else:
            return True
    return False


def cell_is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def assert_range_ok(
    address: str,
    col_start: str,
    col_end: str,
    row_start: int,
    row_end: int,
    *,
    max_cells: int = MAX_CELLS,
) -> None:
    columns = column_count(col_start, col_end)
    rows = row_end - row_start + 1
    cells = columns * rows
    if cells > max_cells:
        raise RangeTooLarge(address=address, cells=cells, columns=columns, rows=rows, max_cells=max_cells)
