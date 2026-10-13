"预览用的纯函数：列的体检报告、按类型转一遍再给界面看。"

from __future__ import annotations

__all__ = [
    "column_is_date",
    "column_samples",
    "display_rows",
    "format_grid",
    "profiles",
]


def column_samples(rows: list[list], index: int) -> list:
    return [r[index] for r in rows if index < len(r)]


def profiles(header: list[str], rows: list[list]) -> list[dict]:
    "每列的体检报告：推断类型、填充率、建议的转换方式。"
    from app.services.normalize.coercions import column_profile

    out: list[dict] = []
    for index, name in enumerate(header):
        try:
            out.append(column_profile(column_samples(rows, index), name=name))
        except Exception:  # noqa: BLE001 — 一列算不出来不该拖垮整张表的预览
            out.append(
                {
                    "name": name,
                    "inferred_type": "text",
                    "suggested_transform": None,
                    "filled": 0,
                    "empty": 0,
                }
            )
    return out


def display_rows(header: list[str], rows: list[list], profs: list[dict]) -> list[list]:
    "把样例值按推断出的类型转一遍再给界面看。"
    from app.services.normalize.coercions import ConvertError, convert, format_temporal

    out: list[list] = []
    for row in rows:
        line: list = []
        for index, value in enumerate(row):
            if index >= len(profs) or index >= len(header):
                line.append(format_temporal(value))
                continue
            prof = profs[index]
            try:
                converted = convert(value, prof["inferred_type"], transform=prof.get("suggested_transform"))
            except ConvertError:
                converted = value
            line.append(format_temporal(converted))
        out.append(line)
    return out


def column_is_date(values: list) -> bool:
    "这一列是不是日期列。"
    from app.services.normalize.coercions import (
        ConvertError,
        is_empty,
        looks_like_date_serial,
        to_date,
    )

    filled = [v for v in values if not is_empty(v)]
    if len(filled) < 2:
        return False

    serials = 0
    for value in filled:
        if looks_like_date_serial(value):
            serials += 1
            continue
        if isinstance(value, str):
            try:
                to_date(value)
                continue
            except (ConvertError, ValueError):
                return False
        return False
    return serials > 0


def format_grid(grid: list[list], *, header_rows: set[int] | None = None) -> tuple[list[list], list[str]]:
    "把「文档视图」里的日期序列号显示成日期。"
    from app.services.normalize.coercions import looks_like_date_serial, to_date

    if not grid:
        return grid, []

    width = max((len(r) for r in grid), default=0)
    marks = ["" for _ in range(width)]

    skip = header_rows or set()
    date_cols: set[int] = set()
    for index in range(width):
        column = [
            r[index] if index < len(r) else None for row_index, r in enumerate(grid) if row_index not in skip
        ]
        if column_is_date(column):
            date_cols.add(index)
            marks[index] = "date"

    header_cells: set[tuple[int, int]] = set()
    for row_index in header_rows or set():
        if row_index < 0 or row_index >= len(grid):
            continue
        raw_row = grid[row_index]
        for col_index in range(width):
            value = raw_row[col_index] if col_index < len(raw_row) else None
            if looks_like_date_serial(value):
                header_cells.add((row_index, col_index))
                if not marks[col_index]:
                    marks[col_index] = "date-header"

    out: list[list] = []
    for row_index, raw_row in enumerate(grid):
        line: list = []
        for col_index in range(width):
            value = raw_row[col_index] if col_index < len(raw_row) else None
            is_date = col_index in date_cols or (row_index, col_index) in header_cells
            if is_date and looks_like_date_serial(value):
                try:
                    line.append(str(to_date(value)))
                except Exception:  # noqa: BLE001 — 转不动就原样显示
                    line.append(value)
            else:
                line.append(value)
        out.append(line)

    return out, marks
