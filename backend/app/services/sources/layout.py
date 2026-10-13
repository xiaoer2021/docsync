"表格摆法识别：拿一块探测区，判断这是纵向表还是交叉表，以及各个坐标在哪。"

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.services.tabular.geometry import cell_is_empty, col_to_index, index_to_col

__all__ = ["DetectedLayout", "detect_layout"]

_SCAN_ROWS = 20
_SCAN_COLS = 40

_MIN_AXIS = 3

_DAY = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")
_DAYLESS = re.compile(r"^(\d{1,2})[-/.](\d{1,2})$")
_MONTH_ONLY = re.compile(r"^(\d{1,2})\s*月$")
_YEAR_MONTH = re.compile(r"^(\d{4})\s*[-/.年]\s*(\d{1,2})\s*月?$")

_COMPARE_YEAR = 2000


@dataclass(slots=True)
class DetectedLayout:
    """识别出来的摆法。**是建议，不是事实** —— 界面要让用户能改。"""

    orientation: str
    header_row: int = 1
    data_start_row: int = 2

    field_col: str = "A"
    date_start_col: str = ""
    axis_kind: str = ""
    axis_count: int = 0

    reasons: list[str] = field(default_factory=list)
    confidence: str = "low"


def _month_number(raw: Any) -> int | None:
    """单元格是不是「几月」。返回月份号。"""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    found = _YEAR_MONTH.match(text) or _MONTH_ONLY.match(text)
    if not found:
        return None
    month = int(found.group(found.lastindex or 1))
    return month if 1 <= month <= 12 else None


def _day_value(raw: Any) -> date | None:
    "单元格是不是一个日期。"
    from app.services.normalize.coercions import ConvertError, to_date

    if isinstance(raw, str):
        text = raw.strip()
        if not _DAY.match(text):
            found = _DAYLESS.match(text)
            if not found:
                return None
            month, day = int(found.group(1)), int(found.group(2))
            try:
                return date(_COMPARE_YEAR, month, day)
            except ValueError:
                return None

    try:
        return to_date(raw)
    except (ConvertError, ValueError, TypeError):
        return None


def _longest_run(cells: list, parse, is_next) -> tuple[int, int]:
    "最长的「连续」段，返回 ``(起始列下标, 长度)``。"
    best_start, best_len = -1, 0
    start, previous = -1, None
    for index, raw in enumerate(cells):
        value = parse(raw)
        if value is None:
            start, previous = -1, None
            continue
        if previous is not None and is_next(previous, value):
            length = index - start + 1
        else:
            start, length = index, 1
        if length > best_len:
            best_start, best_len = start, length
        previous = value
    return best_start, best_len


def _find_axis(row: list[Any]) -> tuple[int, int, str]:
    "在这一行里找最长的「连续日期 / 连续月份」段。"
    cells = list(row)[:_SCAN_COLS]

    start, length = _longest_run(cells, _day_value, lambda a, b: b == a + timedelta(days=1))
    if length >= _MIN_AXIS:
        return start, length, "day"

    start, length = _longest_run(cells, _month_number, lambda a, b: b == a % 12 + 1)
    if length >= _MIN_AXIS:
        return start, length, "month"

    return -1, 0, ""


def _first_text_column(rows: list[list], *, below: int) -> int:
    "数据区里最左边那一列「有文字」的列 —— 交叉表的科目列。"
    width = max((len(r) for r in rows), default=0)
    for index in range(min(width, _SCAN_COLS)):
        texts = 0
        for row in rows[below:]:
            if index >= len(row) or cell_is_empty(row[index]):
                continue
            if isinstance(row[index], str):
                texts += 1
        if texts >= 2:
            return index
    return 0


def detect_layout(rows: list[list[Any]], *, start_row: int = 1) -> DetectedLayout:
    "识别这块探测区是什么摆法、各个坐标在哪。"
    from app.services.normalize.headers import infer_header_row

    if not rows:
        return DetectedLayout(
            orientation="vertical",
            reasons=["表格是空的，按默认的纵向表处理。"],
            confidence="low",
        )

    window = rows[:_SCAN_ROWS]

    for offset, row in enumerate(window):
        axis_start, axis_len, axis_kind = _find_axis(row)
        if axis_start < 0:
            continue

        axis_row = start_row + offset

        field_idx = _first_text_column(window, below=offset + 1)
        kind_label = "日期" if axis_kind == "day" else "月份"
        return DetectedLayout(
            orientation="matrix",
            header_row=axis_row,
            data_start_row=axis_row + 1,
            field_col=index_to_col(field_idx),
            date_start_col=index_to_col(axis_start),
            axis_kind=axis_kind,
            axis_count=axis_len,
            reasons=[
                f"第 {axis_row} 行有一串连续的{kind_label}（{axis_len} 个，"
                f"从 {index_to_col(axis_start)} 列开始）—— 这是交叉表的样子："
                f"左边是科目，右边按{kind_label}横向铺开。",
                f"科目列取 {index_to_col(field_idx)}：它下面几行是文字（科目名），" "比它更左的列没有文字。",
            ],
            confidence="high" if axis_len >= 5 else "medium",
        )

    header_row = infer_header_row(window, start_row=start_row)
    above = window[: header_row - start_row]
    reasons = [f"没找到连续的日期/月份轴，按纵向表处理：表头在第 {header_row} 行。"]
    if above:
        reasons.append(f"第 1~{header_row - 1} 行看着像标题/说明（格子少），已跳过。")
    return DetectedLayout(
        orientation="vertical",
        header_row=header_row,
        data_start_row=header_row + 1,
        field_col="A",
        date_start_col="",
        reasons=reasons,
        confidence="high" if header_row == 1 else "medium",
    )


def col_letter(index: int) -> str:
    """给界面用的小工具（避免各处再 import 一次）。"""
    return index_to_col(index)


def col_index(letter: str) -> int:
    return col_to_index(letter)
