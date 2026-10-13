"把源数据整理成可以直接写库的行。"

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field, replace
from typing import Any

from app.models.task import COL_TYPE_LABELS
from app.services.normalize.coercions import (
    ConvertError,
    convert,
    infer_type,
    is_empty,
    to_date,
    to_number,
)
from app.services.normalize.mapping import (
    ColumnSpec,
    dedupe_rows,
    map_row,
    resolve_columns,
    row_fingerprint,
)
from app.services.normalize.rowfilter import drop_skipped_rows

DEFAULT_SOURCE_TAG: dict[str, str] = {
    "doc": "",
    "sheet": "",
    "row": "来源行号",
    "fingerprint": "数据指纹",
    "last_synced": "最后同步时间",
}

DEFAULT_DIRTY_COLUMN = "原始值_未识别"

from app.services.sources.data import SourceData as SourceData  # noqa: E402


@dataclass(slots=True)
class PreparedRows:
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    dropped_rows: list[str] = field(default_factory=list)

    auto_split: dict[str, str] = field(default_factory=dict)

    rule_notes: list[str] = field(default_factory=list)

    insert_only: list[str] = field(default_factory=list)
    fingerprint_column: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)

    issue_summary: list[dict[str, Any]] = field(default_factory=list)

    auto_adjustments: list[dict[str, Any]] = field(default_factory=list)

    blocked_values: list[dict[str, Any]] = field(default_factory=list)

    retyped_columns: list[dict[str, Any]] = field(default_factory=list)

    dirty_column: str | None = None

    effective_types: dict[str, str] = field(default_factory=dict)
    missing_sources: list[str] = field(default_factory=list)
    bad_rows: int = 0
    invalid_cells: int = 0
    critical_cells: int = 0
    critical_issues: list[dict[str, Any]] = field(default_factory=list)
    skipped_required: int = 0
    deduped: int = 0
    repaired_dates: list[dict[str, Any]] = field(default_factory=list)
    amount_notes: int = 0

    @property
    def ok(self) -> bool:
        return not self.missing_sources


class MappingError(RuntimeError):
    """源列对不上，或压根没配映射。"""


_WIDEN_ORDER = ("bool", "int", "float", "decimal", "text")

_NOT_AUTO_WIDENED = {"date", "datetime", "json"}


def _fits(value: Any, col_type: str) -> bool:
    "这个值能不能被这种类型装下。"
    if is_empty(value):
        return True
    try:
        if col_type == "int":
            number = to_number(value)
            return number is not None and abs(number - round(number)) < 1e-9
        convert(value, col_type)
        return True
    except ConvertError:
        return False


_MISTYPE_RATIO = 0.5
_SHORT_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})$")


def _short_month_day(raw: Any) -> tuple[int, int] | None:
    if isinstance(raw, bool):
        return None
    match = _SHORT_DATE.fullmatch(str(raw).strip())
    if not match:
        return None
    month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None

    if isinstance(raw, float) and day in (1, 2, 3):
        return None
    return month, day


def _repair_context_dates(source: SourceData, resolved: list[Any]) -> tuple[SourceData, list[dict[str, Any]]]:
    rows = list(source.rows)
    repaired: list[dict[str, Any]] = []
    for item in resolved:
        if item.spec.type != "date" or item.index < 0:
            continue
        for index, entry in enumerate(rows):
            if item.index >= len(entry[1]):
                continue
            raw = entry[1][item.index]
            partial = _short_month_day(raw)
            if partial is None:
                continue
            sheet = entry[2] if len(entry) > 2 else None
            anchors: list[dt.date | None] = []
            for step in (-1, 1):
                anchor = None
                position = index + step
                while 0 <= position < len(rows):
                    nearby = rows[position]
                    if (nearby[2] if len(nearby) > 2 else None) != sheet:
                        break
                    value = nearby[1][item.index] if item.index < len(nearby[1]) else None
                    try:
                        anchor = to_date(value)
                    except ConvertError:
                        pass
                    if anchor is not None:
                        break
                    position += step
                anchors.append(anchor)
            before, after = anchors
            if before is None and after is None:
                continue
            years = {
                year
                for anchor in (before, after)
                if anchor
                for year in (anchor.year - 1, anchor.year, anchor.year + 1)
            }
            candidates: list[dt.date] = []
            for year in years:
                try:
                    candidate = dt.date(year, *partial)
                except ValueError:
                    continue
                if before and after:
                    if before <= candidate <= after and (after - before).days <= 90:
                        candidates.append(candidate)
                elif (before and 0 <= (candidate - before).days <= 14) or (
                    after and 0 <= (after - candidate).days <= 14
                ):
                    candidates.append(candidate)
            if len(candidates) != 1:
                continue
            values = list(entry[1])
            values[item.index] = candidates[0]
            rows[index] = (entry[0], values, *entry[2:])
            repaired.append(
                {
                    "row_no": entry[0],
                    "sheet_id": sheet,
                    "column": item.spec.target,
                    "from": str(raw),
                    "to": str(candidates[0]),
                }
            )
    return SourceData(header=source.header, rows=rows), repaired


def _abstract_type(db_type: str | None) -> str | None:
    """目标库的列类型 → 平台的抽象类型。延迟导入以免 loader 依赖 runner。"""
    if not db_type:
        return None
    from app.services.loader.ddl import abstract_type_for_db

    return abstract_type_for_db(db_type)


def _offenders(values: list[Any], col_type: str) -> list[str]:
    """哪些值装不进这个类型（会逐格留空的那些）。"""
    return [str(v)[:80] for v in values if not is_empty(v) and not _fits(v, col_type)]


def negotiate_type(configured: str, values: list[Any], *, ceiling: str | None = None) -> tuple[str, bool]:
    "配置的类型装不下这些值时，自动放宽到装得下的那个。"
    if configured in _NOT_AUTO_WIDENED or configured not in _WIDEN_ORDER:
        return configured, False

    start = _WIDEN_ORDER.index(configured)
    stop = _WIDEN_ORDER.index(ceiling) + 1 if ceiling in _WIDEN_ORDER else len(_WIDEN_ORDER)
    top = max(stop, start + 1)

    saturated = [v for v in values if not is_empty(v)]
    if not saturated:
        return configured, False

    for candidate in _WIDEN_ORDER[start:top]:
        if all(_fits(v, candidate) for v in saturated):
            return candidate, candidate != configured
    last = _WIDEN_ORDER[top - 1]
    return last, last != configured


def build_specs(raw: list[dict[str, Any]] | None) -> list[ColumnSpec]:
    return [
        ColumnSpec(
            source=str(item.get("source") or ""),
            target=str(item.get("target") or ""),
            type=str(item.get("type") or "text"),
            transform=item.get("transform") or None,
            required=bool(item.get("required")),
            default=item.get("default"),
            length=item.get("length"),
        )
        for item in (raw or [])
        if item.get("target")
    ]


def _expand_multivalue(
    source: SourceData,
    resolved: list[Any],
    split_by: dict[str, str] | None,
) -> tuple[SourceData, dict[int, str]]:
    "把「一个格子里写了多个值」的列展开成多行。返回 ``(数据, 用了哪些列)``。"
    from app.services.normalize.splitter import (
        detect_split_columns,
        expand_rows,
        separator_indexes,
    )

    separators = separator_indexes(source.header, split_by)
    if not separators:
        separators = detect_split_columns(source.header, [list(row[1]) for row in source.rows])
    if not separators:
        return source, {}

    rows: list[tuple] = []
    for row in source.rows:
        for values in expand_rows([list(row[1])], separators):
            rows.append((row[0], values, *row[2:]))
    source.rows = rows
    return source, separators


def prepare_rows(
    source: SourceData,
    specs: list[ColumnSpec],
    *,
    dedupe_cfg: dict[str, Any] | None = None,
    tag_cfg: dict[str, Any] | None = None,
    doc_node_id: str = "",
    sheet_id: str = "",
    now: dt.datetime | None = None,
    max_issues: int = 200,
    target_types: dict[str, str] | None = None,
    dirty_column: str | None = DEFAULT_DIRTY_COLUMN,
    quality_block_columns: list[str] | None = None,
    numeric_note_columns: list[str] | None = None,
    note_column: str = "备注",
    split_by: dict[str, str] | None = None,
    skip_rows: set[int] | list[int] | None = None,
    skip_words: list[str] | None = None,
    rules_cfg: list[dict[str, Any]] | None = None,
) -> PreparedRows:
    "一行行转、按需去重、补来源列和指纹。"
    if not specs:
        raise MappingError("任务还没配字段映射")

    resolved, missing = resolve_columns(source.header, specs)
    if missing:
        raise MappingError("这些源列在文档里找不到：" + "、".join(missing))
    source, repaired_dates = _repair_context_dates(source, resolved)

    dropped_rows: list[str] = []
    rule_notes: list[str] = []

    if skip_rows or skip_words:
        source.rows, skipped = drop_skipped_rows(
            source.rows,
            skip_rows=set(skip_rows or []),
            skip_words=list(skip_words or []),
        )
        dropped_rows = skipped

    if rules_cfg:
        from app.services.normalize.rules import apply_rules, parse_rules

        active = parse_rules(rules_cfg)
        if active:
            kept: list[tuple] = []
            for row in source.rows:
                row_no = row[0]
                values = list(row[1])
                cells = ["" if v is None else str(v) for v in values]
                hit = apply_rules([cells], source.header, active, first_row=row_no)
                if not hit.rows:
                    skipped_hit = hit.hits[0] if hit.hits else None
                    where = f"（{skipped_hit.column} 含「{skipped_hit.match}」）" if skipped_hit else ""
                    dropped_rows.append(f"第 {row_no} 行{where}")
                    continue
                for one in hit.hits:
                    if one.action == "replace" and 0 <= one.index < len(values):
                        values[one.index] = one.after

                        rule_notes.append(
                            f"第 {row_no} 行「{one.column}」把「{one.before}」换成了「{one.after}」"
                        )
                kept.append((row[0], values, *row[2:]))
            source.rows = kept

    note_targets = set(numeric_note_columns or [])

    dirty_column = (dirty_column or "").strip() or None

    stamp = now or dt.datetime.now()
    user_columns = [c.target for c in specs]

    out = PreparedRows(missing_sources=missing)
    out.repaired_dates = repaired_dates
    source, auto_split = _expand_multivalue(source, resolved, split_by)
    out.auto_split = {
        source.header[index]: sep for index, sep in auto_split.items() if index < len(source.header)
    }

    adjusted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    retyped: list[dict[str, Any]] = []
    effective: dict[str, str] = {}
    critical_columns = {spec.target for spec in specs if spec.required}
    critical_columns.update(quality_block_columns or [])
    critical_seen: set[tuple[int, str]] = set()
    for item in resolved:
        spec = item.spec
        column_values = [row[1][item.index] if 0 <= item.index < len(row[1]) else None for row in source.rows]
        fixed = _abstract_type((target_types or {}).get(spec.target))
        if spec.target in note_targets and spec.type == "float":
            used, widened = "float", False
        else:
            if fixed is None:
                ceiling = None
            else:
                ceiling = spec.type
                if fixed in _WIDEN_ORDER and (
                    ceiling not in _WIDEN_ORDER or _WIDEN_ORDER.index(fixed) > _WIDEN_ORDER.index(ceiling)
                ):
                    ceiling = fixed
            used, widened = negotiate_type(spec.type, column_values, ceiling=ceiling)

        filled = [v for v in column_values if not is_empty(v)]
        offenders = [] if spec.target in note_targets and used == "float" else _offenders(column_values, used)

        retypeable = spec.type in _WIDEN_ORDER and spec.target not in note_targets
        if retypeable and offenders and len(offenders) > len(filled) * _MISTYPE_RATIO:
            used = infer_type(column_values)
            offenders = _offenders(column_values, used)
            widened = used != spec.type
            retyped.append(
                {
                    "column": spec.target,
                    "configured": spec.type,
                    "used": used,
                    "label": COL_TYPE_LABELS.get(used, used),
                    "from_label": COL_TYPE_LABELS.get(spec.type, spec.type),
                    "count": len(column_values)
                    - len([v for v in column_values if is_empty(v) or _fits(v, used)]),
                }
            )

        if spec.target in critical_columns and used != spec.type and spec.target not in note_targets:
            for entry_index, entry in enumerate(source.rows):
                raw = entry[1][item.index] if 0 <= item.index < len(entry[1]) else None
                if is_empty(raw):
                    continue
                try:
                    convert(raw, spec.type, transform=spec.transform, max_length=spec.length)
                except ConvertError:
                    critical_seen.add((entry_index, spec.target))
                    out.critical_cells += 1
                    issue = {
                        "row_no": entry[0],
                        "sheet_id": entry[2] if len(entry) > 2 else None,
                        "column": spec.target,
                        "reason": f"关键列的配置类型 {spec.type} 装不下原值",
                    }
                    if len(out.critical_issues) < max_issues:
                        out.critical_issues.append(issue)
                    if len(out.issues) < max_issues:
                        out.issues.append({**issue, "raw": {spec.source: str(raw)[:100]}})

        effective[spec.target] = used
        detail = {
            "column": spec.target,
            "configured": spec.type,
            "used": used,
            "count": len(offenders),
            "samples": list(dict.fromkeys(offenders))[:3],
        }
        if widened:
            adjusted.append(detail)
        if offenders:
            blocked.append(detail)
        if used != spec.type:
            item.spec = replace(spec, type=used)

    out.auto_adjustments = adjusted
    out.blocked_values = blocked
    out.retyped_columns = retyped
    out.dirty_column = dirty_column
    out.effective_types = effective
    specs = [item.spec for item in resolved]

    mapped: list[dict[str, Any]] = []

    per_reason: dict[tuple[str, str], dict[str, Any]] = {}
    samples_per_reason = 3
    invalid_seen = set(critical_seen)
    bad_row_indexes = {index for index, _ in critical_seen}
    out.invalid_cells = len(invalid_seen)
    out.bad_rows = len(bad_row_indexes)
    for entry_index, entry in enumerate(source.rows):
        row_no = entry[0]
        values = entry[1]

        origin_sheet = entry[2] if len(entry) > 2 else None

        result = map_row(values, resolved, numeric_note_columns=note_targets, note_column=note_column)
        out.amount_notes += len(result.notes)
        if result.issues:
            bad_row_indexes.add(entry_index)
            out.bad_rows = len(bad_row_indexes)
            for column, reason in result.issues:
                cell_key = (entry_index, column)
                if cell_key not in invalid_seen:
                    invalid_seen.add(cell_key)
                    out.invalid_cells += 1
                if column in critical_columns and (entry_index, column) not in critical_seen:
                    out.critical_cells += 1
                    if len(out.critical_issues) < max_issues:
                        out.critical_issues.append(
                            {"row_no": row_no, "sheet_id": origin_sheet, "column": column, "reason": reason}
                        )
                kind = reason.split("：", 1)[0]
                bucket = per_reason.setdefault(
                    (column, kind),
                    {"column": column, "reason": kind, "rows": 0, "samples": []},
                )
                bucket["rows"] += 1
                if len(bucket["samples"]) < samples_per_reason:
                    raw_value = ""
                    for name, cell in zip(source.header, values, strict=False):
                        if name == column:
                            raw_value = str(cell)[:120]
                            break
                    if raw_value and raw_value not in bucket["samples"]:
                        bucket["samples"].append(raw_value)

                if bucket["rows"] <= samples_per_reason and len(out.issues) < max_issues:
                    out.issues.append(
                        {
                            "row_no": row_no,
                            "column": column,
                            "reason": reason,
                            "raw": dict(zip(source.header, [str(v)[:100] for v in values], strict=False)),
                        }
                    )

            if any("必填" in reason for _, reason in result.issues):
                out.skipped_required += 1
                continue
        if result.dirty and dirty_column:
            result.values[dirty_column] = "；".join(f"{col}={val}" for col, val in result.dirty)[:4000]
        mapped.append({"__row_no__": row_no, "__sheet__": origin_sheet, **result.values})

    out.issue_summary = sorted(per_reason.values(), key=lambda item: -int(item["rows"]))
    if out.amount_notes and note_column not in user_columns:
        user_columns.append(note_column)
        effective[note_column] = "text"

    dedupe_keys = [k for k in ((dedupe_cfg or {}).get("keys") or []) if k in user_columns]
    if dedupe_keys:
        mapped, out.deduped = dedupe_rows(
            mapped, dedupe_keys, keep=str((dedupe_cfg or {}).get("keep") or "last")
        )

    tag = {**DEFAULT_SOURCE_TAG, **(tag_cfg or {})}
    fingerprint_column = (tag.get("fingerprint") or "").strip() or None
    out.fingerprint_column = fingerprint_column

    for row in mapped:
        row_no = row.pop("__row_no__", None)
        row_sheet = row.pop("__sheet__", None)

        if fingerprint_column:
            row[fingerprint_column] = row_fingerprint({name: row.get(name) for name in user_columns})
        if tag.get("row"):
            row[tag["row"]] = row_no
        if tag.get("doc"):
            row[tag["doc"]] = doc_node_id
        if tag.get("sheet"):
            row[tag["sheet"]] = row_sheet or sheet_id
        if tag.get("first_synced"):
            row[tag["first_synced"]] = stamp
        if tag.get("last_synced"):
            row[tag["last_synced"]] = stamp

    has_dirty = any(row.get(dirty_column) for row in mapped) if dirty_column else False
    if dirty_column and not has_dirty:
        for row in mapped:
            row.pop(dirty_column, None)
    extra = [dirty_column] if (dirty_column and has_dirty) else []
    out.columns = list(dict.fromkeys(user_columns + extra + [v for v in tag.values() if v]))
    for row in mapped:
        for name in out.columns:
            row.setdefault(name, None)

    out.rows = mapped

    out.insert_only = [tag["first_synced"]] if tag.get("first_synced") else []
    out.dropped_rows = dropped_rows
    out.rule_notes = rule_notes
    return out
