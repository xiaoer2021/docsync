"合并多子表时，检查**同名但性质不同**的列。"

from __future__ import annotations

from typing import Any

__all__ = ["family_of", "find_same_name_conflicts", "sample_row"]

SAMPLE_LIMIT = 30

MIN_SAMPLES = 3


def column_types_from_samples(
    per_sheet: dict[str, dict[int, list[Any]]], header: list[str]
) -> dict[str, dict[str, str]]:
    "把采样转成「子表 → {列名: 性质家族}」。"
    out: dict[str, dict[str, str]] = {}
    for sid, columns in per_sheet.items():
        kinds: dict[str, str] = {}
        for index, values in columns.items():
            if index >= len(header):
                continue
            family = family_of(values)
            if family:
                kinds[header[index]] = family
        out[sid] = kinds
    return out


def sample_row(per_sheet: dict[str, dict[int, list[Any]]], sheet_id: str, cells: list[Any]) -> None:
    "把一行采进样本桶。每列最多留 ``SAMPLE_LIMIT`` 个。"
    bucket = per_sheet.setdefault(sheet_id, {})
    for index, value in enumerate(cells):
        if value is None or value == "":
            continue
        column = bucket.setdefault(index, [])
        if len(column) < SAMPLE_LIMIT:
            column.append(value)


def family_of(samples: list[Any]) -> str:
    "把一列样例归到一个「性质家族」。"
    from app.services.normalize.coercions import infer_type

    values = [v for v in samples if v is not None and v != ""]
    if len(values) < MIN_SAMPLES:
        return ""
    kind = infer_type(values)
    if kind in ("int", "float"):
        return "数值"
    if kind in ("date", "datetime"):
        return "日期"
    if kind == "bool":
        return "布尔"
    return "文本"


def find_same_name_conflicts(
    per_sheet_samples: dict[str, dict[int, list[Any]]],
    header: list[str],
    sheet_names: dict[str, str],
) -> list[str]:
    "找出「同一个列名，在不同子表里性质不同」的列。"
    if len(per_sheet_samples) < 2:
        return []

    width = len(header)
    notes: list[str] = []

    for index in range(width):
        by_sheet: dict[str, str] = {}
        for sid, columns in per_sheet_samples.items():
            family = family_of(columns.get(index) or [])
            if family:
                by_sheet[sid] = family

        if len(by_sheet) < 2:
            continue
        if len(set(by_sheet.values())) < 2:
            continue

        detail = "、".join(f"{sheet_names.get(sid, sid)} 是{fam}" for sid, fam in list(by_sheet.items())[:4])
        notes.append(
            f"「{header[index]}」这个列名在不同子表里**不是同一种东西**：{detail}。"
            "合并之后它们会被塞进同一列 —— 请确认这确实是同一列，"
            "不是的话在其中一个子表里把列名改掉。"
        )

    return notes
