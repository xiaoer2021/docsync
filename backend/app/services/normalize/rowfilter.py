"丢掉不该写进库的行：小计、合计、说明、签字行。"

from __future__ import annotations

from typing import Any

__all__ = [
    "DEFAULT_SKIP_WORDS",
    "drop_skipped_rows",
    "row_should_skip",
    "skip_config",
]


def skip_config(source_config: dict | None) -> tuple[set[int], list[str]]:
    "从 ``source_config`` 里取「丢哪些行」的配置，返回 ``(行号集合, 关键词)``。"
    cfg = source_config or {}
    rows: set[int] = set()
    for raw in cfg.get("skip_rows") or []:
        try:
            rows.add(int(raw))
        except (TypeError, ValueError):
            continue
    words = [str(word).strip() for word in (cfg.get("skip_words") or []) if str(word).strip()]
    return rows, words


DEFAULT_SKIP_WORDS: tuple[str, ...] = ("总计", "合计", "小计", "汇总", "平均", "备注")

_TEXTY = (str,)


def row_should_skip(
    values: list[Any],
    row_no: int | None,
    *,
    skip_rows: set[int] | None = None,
    skip_words: tuple[str, ...] | list[str] | None = None,
) -> bool:
    "这一行要不要丢掉。"
    if skip_rows and row_no is not None and row_no in skip_rows:
        return True
    if skip_words:
        for value in values:
            if not isinstance(value, _TEXTY):
                continue
            text = value
            for word in skip_words:
                if word and word in text:
                    return True
    return False


def drop_skipped_rows(
    rows: list[tuple],
    *,
    skip_rows: set[int] | None = None,
    skip_words: tuple[str, ...] | list[str] | None = None,
) -> tuple[list[tuple], list[str]]:
    "把要丢掉的行筛掉，返回 ``(留下的行, 丢掉的原因说明)``。"
    if not skip_rows and not skip_words:
        return rows, []

    kept: list[tuple] = []
    dropped: list[str] = []
    for row in rows:
        row_no = row[0] if row else None
        values = list(row[1]) if len(row) > 1 else []
        if row_with_reason := _reason(values, row_no, skip_rows=skip_rows, skip_words=skip_words):
            dropped.append(f"第 {row_no} 行（{row_with_reason}）" if row_no else f"一行（{row_with_reason}）")
            continue
        kept.append(row)
    return kept, dropped


def _reason(
    values: list[Any],
    row_no: int | None,
    *,
    skip_rows: set[int] | None,
    skip_words: tuple[str, ...] | list[str] | None,
) -> str:
    if skip_rows and row_no is not None and row_no in skip_rows:
        return "你标了不写"
    if skip_words:
        for value in values:
            if not isinstance(value, _TEXTY):
                continue
            for word in skip_words:
                if word and word in value:
                    return f"含「{word}」"
    return ""
