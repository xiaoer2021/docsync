"飞书的合并单元格：解析、表头拼名、数据区按范围补值。"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "MergedRange",
    "VerticalFill",
    "combine_header_with_parent",
    "parse_merges",
]


@dataclass(slots=True, frozen=True)
class MergedRange:
    """一块合并区域。**行号列号都是 1 起、含起含止**（跟表格显示一致）。"""

    start_row: int
    end_row: int
    start_col: int
    end_col: int

    @property
    def is_vertical(self) -> bool:
        """纵向合并（跨行）—— 数据区补值看的就是它。"""
        return self.end_row > self.start_row

    @property
    def is_horizontal(self) -> bool:
        """横向合并（跨列）—— 表头拼名看的就是它。"""
        return self.end_col > self.start_col


def parse_merges(raw: Any) -> list[MergedRange]:
    "把接口给的 ``merges`` 解成 ``MergedRange``。"
    if not isinstance(raw, list):
        return []
    out: list[MergedRange] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                MergedRange(
                    start_row=int(item["start_row_index"]) + 1,
                    end_row=int(item["end_row_index"]) + 1,
                    start_col=int(item["start_column_index"]),
                    end_col=int(item["end_column_index"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def combine_header_with_parent(
    own: list[str],
    parent_row_values: list[Any],
    merges: list[MergedRange],
    *,
    header_row: int,
    parent_row: int,
    column_offset: int = 0,
) -> list[str]:
    "把表头行和它上面那一行拼起来。"
    width = len(own)
    expanded = [""] * width

    for span in merges:
        if not (span.start_row <= parent_row <= span.end_row):
            continue
        source = ""
        start = span.start_col - column_offset
        end = span.end_col - column_offset
        if 0 <= start < len(parent_row_values):
            value = parent_row_values[start]
            source = "" if value is None else str(value).strip()
        if not source:
            continue
        for index in range(max(start, 0), min(end, width - 1) + 1):
            expanded[index] = source

    vertically_merged: set[int] = set()
    for span in merges:
        if span.is_vertical and span.start_row <= parent_row and span.end_row >= header_row:
            vertically_merged.update(range(span.start_col - column_offset, span.end_col - column_offset + 1))

    out: list[str] = []
    for index, name in enumerate(own):
        parent = "" if index in vertically_merged else expanded[index]
        text = name if name else ""

        if parent and text and parent != text:
            out.append(f"{parent}/{text}")
        else:
            out.append(text or parent or "")
    return out


class VerticalFill:
    "数据区的纵向合并：按范围把值补到下面几行。"

    def __init__(self, merges: list[MergedRange], *, first_row: int, column_offset: int = 0) -> None:
        self._spans = [
            MergedRange(
                start_row=m.start_row,
                end_row=m.end_row,
                start_col=m.start_col - column_offset,
                end_col=m.end_col - column_offset,
            )
            for m in merges
            if m.is_vertical and m.start_row >= first_row and m.end_col - column_offset >= 0
        ]
        self._kept: dict[tuple[int, int], Any] = {}
        self.filled = 0

    def apply(self, row_no: int, values: list[Any]) -> list[Any]:
        """把这一行按合并范围补一遍，返回补好的值。"""
        if not self._spans:
            return values
        out = list(values)
        for span in self._spans:
            if not (span.start_row <= row_no <= span.end_row):
                continue
            if row_no == span.start_row:
                for index in range(span.start_col, span.end_col + 1):
                    if index < len(out) and out[index] is not None and out[index] != "":
                        self._kept[(span.start_row, index)] = out[index]
                continue
            for index in range(span.start_col, span.end_col + 1):
                if index >= len(out):
                    continue
                if out[index] is not None and out[index] != "":
                    continue
                source = self._kept.get((span.start_row, index))
                if source is not None:
                    out[index] = source
                    self.filled += 1
        return out
