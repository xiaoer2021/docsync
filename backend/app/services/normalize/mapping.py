"""列映射：源列 → 目标列，以及行指纹。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.services.normalize.coercions import ConvertError, convert, is_empty
from app.services.normalize.headers import col_to_index, header_key


@dataclass(slots=True)
class ColumnSpec:
    """一条字段映射。``source`` 可以是表头名，也可以是列号（A / B / AA）。"""

    source: str
    target: str
    type: str = "text"
    transform: str | None = None
    required: bool = False
    default: Any = None
    length: int | None = None


@dataclass(slots=True)
class ResolvedColumn:
    """一条映射落到具体列上。index 为 NO_SOURCE 表示这一列没有源（手动加的常量列）。"""

    spec: ColumnSpec
    index: int


@dataclass(slots=True)
class RowResult:
    values: dict[str, Any] = field(default_factory=dict)
    issues: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    dirty: list[tuple[str, Any]] = field(default_factory=list)


NO_SOURCE = -1


def resolve_columns(header: list[str], specs: list[ColumnSpec]) -> tuple[list[ResolvedColumn], list[str]]:
    "把映射落到具体的列下标。返回 (解析成功的, 找不到源的列名列表)。"
    lookup = {name.strip(): index for index, name in enumerate(header)}

    loose: dict[str, int] = {}
    ambiguous: set[str] = set()
    for index, name in enumerate(header):
        key = header_key(name)
        if not key:
            continue
        if key in loose:
            ambiguous.add(key)
        else:
            loose[key] = index

    resolved: list[ResolvedColumn] = []
    missing: list[str] = []

    for spec in specs:
        source = (spec.source or "").strip()
        if not source:
            if spec.default is not None:
                resolved.append(ResolvedColumn(spec=spec, index=NO_SOURCE))
                continue
            missing.append(spec.target or "(没填源列)")
            continue

        index = lookup.get(source)
        if index is None:
            key = header_key(source)
            if key and key not in ambiguous and key in loose:
                index = loose[key]
        if index is None:
            try:
                candidate = col_to_index(source)
            except ValueError:
                candidate = -1
            if 0 <= candidate < len(header):
                index = candidate

        if index is None:
            missing.append(source)
            continue

        resolved.append(ResolvedColumn(spec=spec, index=index))

    return resolved, missing


def map_row(
    values: list[Any],
    resolved: list[ResolvedColumn],
    *,
    numeric_note_columns: set[str] | None = None,
    note_column: str = "备注",
) -> RowResult:
    """按映射把一行原始值转成目标列的值。单格失败只记问题，不炸整行。"""
    result = RowResult()

    for item in resolved:
        spec = item.spec

        raw = values[item.index] if 0 <= item.index < len(values) else None
        try:
            converted = convert(raw, spec.type, transform=spec.transform, max_length=spec.length)
        except ConvertError as exc:
            if spec.target in (numeric_note_columns or set()) and spec.type == "float" and not is_empty(raw):
                converted = 0.0
                result.notes.append(f"{spec.target}：{str(raw).strip()}")
            else:
                result.issues.append((spec.target, str(exc)))
                converted = None

                if not is_empty(raw):
                    result.dirty.append((spec.target, raw))

        if converted is None:
            if spec.default is not None and str(spec.default).strip() != "":
                try:
                    converted = convert(spec.default, spec.type)
                except ConvertError:
                    result.issues.append((spec.target, f"「空值填」的值转不成这一列的类型：{spec.default}"))
                    converted = None
                    if spec.required:
                        result.issues.append((spec.target, "必填但为空"))
            elif spec.required:
                result.issues.append((spec.target, "必填但为空"))

        result.values[spec.target] = converted

    if result.notes:
        existing = result.values.get(note_column)
        parts = [str(existing).strip()] if existing else []
        result.values[note_column] = "；".join(parts + result.notes)[:4000]

    return result


def row_fingerprint(values: dict[str, Any]) -> str:
    "按目标列算行指纹。"
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedupe_rows(
    rows: list[dict[str, Any]], keys: list[str], *, keep: str = "last"
) -> tuple[list[dict[str, Any]], int]:
    """按业务键去重。返回 (去重后的行, 丢掉的条数)。"""
    if not keys:
        return rows, 0

    picked: dict[tuple, dict[str, Any]] = {}
    dropped = 0
    for row in rows:
        key = tuple((row.get(k) if row.get(k) is not None else "") for k in keys)
        if key in picked:
            dropped += 1
            if keep == "first":
                continue
        picked[key] = row

    return list(picked.values()), dropped
