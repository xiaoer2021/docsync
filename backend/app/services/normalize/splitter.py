"把「一个格子里写了两个值」拆开。"

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "SEPARATOR_PRESETS",
    "detect_split_columns",
    "expand_rows",
    "looks_like_single_number",
    "separator_indexes",
    "split_into_rows",
    "split_multivalue",
]

SEPARATOR_PRESETS: dict[str, str] = {
    "comma": ",，",
    "dun": "、",
    "semicolon": ";；",
    "newline": "\r\n",
    "slash": "/",
    "pipe": "|",
}

_NUMERIC_WHOLE = re.compile(r"^[\s$¥￥€£₩]*-?\d+(?:[,，]\d{3})*(?:\.\d+)?\s*[%％]?\s*(?:元|人民币)?$")


def looks_like_single_number(text: str) -> bool:
    "这一串是不是**一个**数字（千分位逗号不算分隔符）。"
    stripped = (text or "").strip()
    if not stripped:
        return False
    if not _NUMERIC_WHOLE.match(stripped):
        return False

    from app.services.normalize.coercions import ConvertError, to_number

    try:
        return to_number(stripped) is not None
    except (ConvertError, ValueError):
        return False


def split_multivalue(value: Any, separators: str) -> list[str]:
    "按 ``separators`` 里的字符切开，返回**去空白、去空项**的片段。"
    if value is None or isinstance(value, bool | int | float):
        return [] if value is None else [str(value)]

    text = str(value)
    if not text.strip():
        return []

    if looks_like_single_number(text):
        return [text.strip()]

    charset = "".join(re.escape(ch) for ch in separators) if separators else ""
    if not charset:
        return [text.strip()]

    pieces = re.split(f"[{charset}]", text)
    return [piece.strip() for piece in pieces if piece.strip()]


def detect_split_columns(
    header: list[str],
    rows: list[list],
    *,
    max_columns: int = 5,
    max_parts: int = 10,
) -> dict[int, str]:
    "**自动**认出「一个格子里写了多个值」的列，返回 ``{列下标: 分隔符}``。"
    if not rows or not header:
        return {}

    width = len(header)
    candidates: list[tuple[int, str, int]] = []

    for index in range(width):
        values = [row[index] for row in rows if index < len(row)]
        values = [v for v in values if v is not None and v != ""]
        if len(values) < 3:
            continue

        for _preset, separator in SEPARATOR_PRESETS.items():
            counts = _part_counts(values, separator)
            if counts is None:
                continue
            parts = counts[0]
            if parts < 2 or parts > max_parts:
                continue
            candidates.append((index, separator, parts))
            break

    if len(candidates) > max_columns:
        return {}
    return {index: separator for index, separator, _ in candidates}


def _part_counts(values: list, separator: str) -> list[int] | None:
    "这一列按 ``separator`` 切，每行几份。有一条不成立就返回 None。"
    counts: list[int] = []

    pattern = "[" + re.escape(separator) + "]"
    for value in values:
        if looks_like_single_number(str(value)):
            return None

        raw = re.split(pattern, str(value))
        if any(re.search(r"\s", piece) for piece in raw):
            return None
        pieces = [p for p in (piece.strip() for piece in raw) if p]
        if len(pieces) < 2:
            return None
        if any(" " in piece or "\t" in piece for piece in pieces):
            return None
        counts.append(len(pieces))
    if not counts or len(set(counts)) != 1:
        return None
    return counts


def separator_indexes(header: list[str], split_by: dict[str, str] | None) -> dict[int, str]:
    "把「列名 → 预设」换算成「列下标 → 分隔符」。"
    if not split_by:
        return {}
    out: dict[int, str] = {}
    for index, name in enumerate(header):
        separator = SEPARATOR_PRESETS.get(split_by.get(name, ""), "")
        if separator:
            out[index] = separator
    return out


def expand_rows(rows: list[list], separators: dict[int, str]) -> list[list]:
    "按 ``{列下标: 分隔符}`` 把多值格子展开成多行。"
    if not separators:
        return rows

    current = rows
    for index, separator in separators.items():
        if not separator:
            continue
        expanded: list[list] = []
        for row in current:
            raw = row[index] if index < len(row) else None
            pieces = split_multivalue(raw, separator)
            if len(pieces) <= 1:
                expanded.append(row)
                continue
            for piece in pieces:
                clone = list(row)
                clone[index] = piece
                expanded.append(clone)
        current = expanded
    return current


def split_into_rows(values: list[Any], columns: list[int], separators: str) -> list[list[str]]:
    "把一行按「这几列的某个格子写了多个值」展开成多行。"
    if not columns or not values:
        return [values]

    parts: dict[int, list[str]] = {}
    for index in columns:
        if index >= len(values):
            continue
        pieces = split_multivalue(values[index], separators)
        if len(pieces) > 1:
            parts[index] = pieces

    if not parts:
        return [values]

    width = max(len(pieces) for pieces in parts.values())
    out: list[list[Any]] = []
    for offset in range(width):
        row = list(values)
        for index, pieces in parts.items():
            row[index] = pieces[offset] if offset < len(pieces) else pieces[-1]
        out.append(row)
    return out
