"日期交叉表（科目 × 日期）的读法。"

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from app.services.sources.base import SourceError
from app.services.tabular.geometry import a1_address, cell_is_empty, col_to_index, index_to_col

__all__ = ["GridReader", "MatrixData", "read_date_matrix"]

_is_blank = cell_is_empty

_PROBE_COLUMNS = 61

_FORMULA_ERRORS = ("#DIV/0!", "#VALUE!", "#REF!", "#N/A", "#NUM!", "#NAME?")

_ZERO_PERCENT = re.compile(r"[+-]?0+(?:\.0+)?[%％]{2,}")

_MONTH_ONLY = re.compile(r"^(\d{1,2})\s*月$")
_YEAR_MONTH = re.compile(r"^(\d{4})\s*[-/.年]\s*(\d{1,2})\s*月?$")


def _month_of(raw: Any) -> tuple[int, int, int | None] | None:
    "认出「月份」表头，返回 ``(年, 月, 原始年)``。"
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    found = _YEAR_MONTH.match(text)
    if found:
        year, month = int(found.group(1)), int(found.group(2))
        return (year, month, year) if 1 <= month <= 12 else None
    found = _MONTH_ONLY.match(text)
    if found:
        month = int(found.group(1))
        return (0, month, None) if 1 <= month <= 12 else None
    return None


def _axis_from_days(cells: list, to_date, convert_error, timedelta_) -> tuple[list[str], bool]:
    "按「连续日期」认表头。返回 ``(每天的标签, 是否月份模式)``。"
    labels: list[str] = []
    previous = None
    for raw in cells:
        if _is_blank(raw):
            break
        try:
            day = to_date(raw)
        except (convert_error, ValueError):
            break
        if day is None:
            break
        if previous is not None and day != previous + timedelta_(days=1):
            raise SourceError("交叉表日期表头不连续，请检查日期起始列和表头行。")
        labels.append(day.isoformat())
        previous = day
    return labels, False


def _axis_from_months(cells: list) -> tuple[list[str], bool]:
    "按「连续月份」认表头。返回 ``(每个月的标签, True)``。"
    labels: list[str] = []
    previous: tuple[int, int, int | None] | None = None
    for raw in cells:
        if _is_blank(raw):
            break
        found = _month_of(raw)
        if found is None:
            break
        year, month, original_year = found
        if previous is not None:
            last_year, last_month, last_year_written = previous
            if last_year_written is None or original_year is None:
                ok = month == last_month % 12 + 1
            else:
                expected = (last_year, last_month + 1) if last_month < 12 else (last_year + 1, 1)
                ok = (year, month) == expected
            if not ok:
                raise SourceError(
                    "交叉表月份表头不连续，请检查日期起始列和表头行。"
                    "（右边应该是 1月、2月、3月… 这样连着排的）"
                )
        labels.append(f"{year}-{month:02d}" if original_year else f"{month:02d}月")
        previous = found
    return labels, True


class GridReader(Protocol):
    "读网格的两个原语。各平台的适配器只要实现这两个方法。"

    async def read_range(self, sheet_id: str, address: str) -> list[list]:
        """读一块 A1 区域，返回二维数组。"""
        ...

    def iter_rows(
        self,
        sheet_id: str,
        *,
        start_row: int,
        col_start: str,
        col_end: str,
        limit: int | None = None,
    ) -> AsyncIterator[tuple[int, list]]:
        """从 start_row 往下逐批读，产出 ``(行号, 各列值)``。"""
        ...


@dataclass(slots=True)
class MatrixData:
    header: list[str] = field(default_factory=list)
    rows: list[tuple[int, list]] = field(default_factory=list)
    date_count: int = 0
    formula_errors: list[str] = field(default_factory=list)
    corrected_zero_percent: int = 0


async def read_date_matrix(
    reader: GridReader,
    sheet_id: str,
    *,
    header_row: int = 3,
    data_start_row: int = 4,
    field_col: str = "C",
    date_start_col: str = "E",
    limit: int | None = None,
) -> MatrixData:
    """把交叉表读成一条记录一个「科目 × 日期」。"""
    from app.services.normalize.coercions import ConvertError, to_date

    field_idx = col_to_index(field_col)
    date_idx = col_to_index(date_start_col)
    if header_row < 1 or data_start_row <= header_row or date_idx <= field_idx:
        raise SourceError("交叉表的表头行、数据起始行或日期起始列不正确。")

    last_probe = min(date_idx + _PROBE_COLUMNS, 16383)
    heading = await reader.read_range(
        sheet_id,
        a1_address(date_start_col, header_row, index_to_col(last_probe), header_row),
    )
    cells = heading[0] if heading else []

    dates, month_mode = _axis_from_days(cells, to_date, ConvertError, timedelta)
    if not dates:
        dates, month_mode = _axis_from_months(cells)

    if not dates:
        raise SourceError(
            "日期起始列没有读到日期或月份，请检查交叉表设置。"
            "表头可以是一串连续日期（10-01、10-02…），也可以是一串连续月份（1月、2月…）。"
        )

    axis_name = "月份" if month_mode else "日期"
    result = MatrixData([axis_name, "经营科目", "数值"], [], len(dates), [])
    end_col = index_to_col(date_idx + len(dates) - 1)

    async for row_no, values in reader.iter_rows(
        sheet_id,
        start_row=data_start_row,
        col_start=field_col,
        col_end=end_col,
        limit=limit,
    ):
        subject = values[0] if values else None
        if _is_blank(subject):
            continue

        for offset, _label in enumerate(dates):
            pos = date_idx - field_idx + offset
            raw = values[pos] if pos < len(values) else None
            if _is_blank(raw):
                continue

            if isinstance(raw, str) and raw.startswith(_FORMULA_ERRORS):
                result.formula_errors.append(f"{index_to_col(date_idx + offset)}{row_no}: {raw}")
                raw = 0.0

            if isinstance(raw, str) and _ZERO_PERCENT.fullmatch(raw.strip()):
                raw = 0.0
                result.corrected_zero_percent += 1

            result.rows.append((row_no, [dates[offset], str(subject).strip(), raw]))
            if limit is not None and len(result.rows) >= limit:
                return result

    return result
