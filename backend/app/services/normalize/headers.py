"""表头推断与列名规整。"""

from __future__ import annotations

from typing import Any

from app.services.normalize.coercions import fullwidth_to_half_width, is_empty

SCAN_ROWS = 10


def non_empty_count(row: list[Any] | None) -> int:
    if not row:
        return 0
    return sum(0 if is_empty(v) else 1 for v in row)


def infer_header_row(rows: list[list[Any]], *, start_row: int = 1, scan: int = SCAN_ROWS) -> int:
    "猜表头在第几行（返回 Excel 原始行号，从 1 开始）。"
    if not rows:
        return start_row

    window = rows[:scan]
    filled = [non_empty_count(row) for row in window]
    widest = max(filled) if filled else 0
    if widest == 0:
        return start_row

    threshold = widest * 0.6
    candidates = [i for i, count in enumerate(filled) if count >= threshold]
    if not candidates:
        candidates = list(range(len(window)))

    best_offset = candidates[0]
    best_score: tuple[int, int] = (-1, -1)
    for offset in candidates:
        score = (text_count(window[offset]), filled[offset])
        if score > best_score:
            best_score = score
            best_offset = offset

    return start_row + best_offset


def text_count(row: list[Any] | None) -> int:
    "这一行有多少个「像名字」的格子。"
    if not row:
        return 0
    total = 0
    for value in row:
        if is_empty(value):
            continue
        if isinstance(value, str):
            total += 1
            continue
        if isinstance(value, bool):
            total += 1
    return total


def normalize_headers(values: list[Any] | None, *, width: int | None = None) -> list[str]:
    "把表头行规整成干净的列名。"
    raw = list(values or [])
    size = width if width is not None else len(raw)
    if len(raw) < size:
        raw.extend([None] * (size - len(raw)))

    names: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(raw[:size]):
        text = "" if is_empty(value) else str(value).strip()
        if not text:
            text = f"列{index_to_col(index)}"
        if text in seen:
            seen[text] += 1
            text = f"{text}_{seen[text]}"
        else:
            seen[text] = 0
        names.append(text)
    return names


def compose_header(
    grid: list[list[Any]],
    segments: list[dict[str, Any]] | None,
    *,
    first_row: int = 1,
    col_start_index: int = 0,
    width: int | None = None,
) -> tuple[list[Any], int]:
    "表头**分段取行**：拼出一行列名。返回 ``(拼出来的原始值, 用到的最大行号)``。"
    size = width if width is not None else max((len(row) for row in grid), default=0)
    if not segments or size <= 0:
        return [], 0

    fallback = _segment_row(segments[0])
    per_column: dict[int, int] = {}
    used_rows: list[int] = []
    for segment in segments:
        row = _segment_row(segment)

        start = _segment_col(segment.get("col_start"), default=0) - col_start_index
        end_raw = segment.get("col_end")
        end = (
            (size - 1)
            if end_raw in (None, "")
            else _segment_col(end_raw, default=size - 1 + col_start_index) - col_start_index
        )
        if end < start:
            start, end = end, start
        for index in range(max(start, 0), min(end, size - 1) + 1):
            per_column[index] = row
        used_rows.append(row)

    values: list[Any] = []
    for index in range(size):
        row = per_column.get(index, fallback)
        offset = row - first_row
        row_cells = grid[offset] if 0 <= offset < len(grid) else []
        values.append(row_cells[index] if index < len(row_cells) else None)

    return values, (max(used_rows) if used_rows else fallback)


def _segment_row(segment: dict[str, Any]) -> int:
    """这一段取第几行。数值不合法就当第 1 行 —— 不能让配置错误变成 500。"""
    try:
        row = int(segment.get("row") or 1)
    except (TypeError, ValueError):
        return 1
    return max(row, 1)


def _segment_col(value: Any, *, default: int) -> int:
    """``"A"`` / ``"E"`` 这种列号转下标。认不出就用 ``default``。"""
    if value in (None, ""):
        return default
    try:
        return col_to_index(str(value))
    except ValueError:
        return default


def index_to_col(index: int) -> str:
    letters = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def header_key(name: Any) -> str:
    "把表头名压成一个「宽松比较用」的键。"
    if is_empty(name):
        return ""
    text = fullwidth_to_half_width(str(name))

    for ch in " \t\r\n\u3000":
        text = text.replace(ch, "")

    text = text.strip("*:：、,，.。")
    return text.lower()


def col_to_index(letters: str) -> int:
    index = 0
    for ch in letters.strip().upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"列号不合法：{letters!r}")
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1
