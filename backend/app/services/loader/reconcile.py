"跟目标表对账：删除同步 + 差异预览。"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.services.loader.dialects import dialect_from_engine

ON_MISSING_KEEP = "keep"
ON_MISSING_DELETE = "delete"
ON_MISSING_MARK = "mark"
ON_MISSING_MODES = (ON_MISSING_KEEP, ON_MISSING_DELETE, ON_MISSING_MARK)

ON_MISSING_LABELS = {
    ON_MISSING_KEEP: "不动",
    ON_MISSING_DELETE: "删掉",
    ON_MISSING_MARK: "标记为已删除",
}


@dataclass(slots=True)
class ReconcileResult:
    existing: int = 0
    to_insert: int = 0
    to_update: int = 0
    unchanged: int = 0
    missing: int = 0
    deleted: int = 0
    marked: int = 0


def _scope_clause(dialect, scope_column: str | None, scope_value: Any) -> tuple[str, dict[str, Any]]:
    if not scope_column or scope_value in (None, ""):
        return "", {}
    return (
        f" AND {dialect.quote(scope_column)} = :scope_value",
        {"scope_value": scope_value},
    )


def existing_keys(
    engine: Engine,
    *,
    table: str,
    key_columns: list[str],
    scope_column: str | None = None,
    scope_value: Any = None,
    connection: Connection | None = None,
) -> set[tuple]:
    "把目标表里已有的主键捞出来。"
    if not key_columns:
        return set()

    dialect = dialect_from_engine(engine)
    cols = ", ".join(dialect.quote(c) for c in key_columns)
    where, params = _scope_clause(dialect, scope_column, scope_value)
    sql = text(f"SELECT {cols} FROM {dialect.quote(table)} WHERE 1 = 1{where}")

    if connection is not None:
        return {tuple(row) for row in connection.execute(sql, params).all()}
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).all()
    except Exception:  # noqa: BLE001
        return set()
    return {tuple(row) for row in rows}


def apply_missing(
    engine: Engine,
    *,
    table: str,
    key_columns: list[str],
    scope_column: str,
    scope_value: Any,
    keep_keys: set[tuple],
    mode: str = ON_MISSING_DELETE,
    mark_column: str | None = None,
    batch: int = 500,
    connection: Connection | None = None,
) -> int:
    "把「源里已经没有」的行删掉或标记掉。"
    if mode == ON_MISSING_KEEP or not key_columns:
        return 0
    if not scope_column or scope_value in (None, ""):
        raise ValueError("删除对账必须指定来源列与来源值，不能清理整个目标表")

    dialect = dialect_from_engine(engine)
    found = existing_keys(
        engine,
        table=table,
        key_columns=key_columns,
        scope_column=scope_column,
        scope_value=scope_value,
        connection=connection,
    )
    stale = [k for k in found if k not in keep_keys]
    if not stale:
        return 0

    key_where = " AND ".join(f"{dialect.quote(c)} = :k{i}" for i, c in enumerate(key_columns))
    scope_where, scope_params = _scope_clause(dialect, scope_column, scope_value)
    key_where += scope_where
    if mode == ON_MISSING_MARK:
        column = mark_column or "__is_deleted__"
        statement = f"UPDATE {dialect.quote(table)} SET {dialect.quote(column)} = :flag " f"WHERE {key_where}"
    else:
        statement = f"DELETE FROM {dialect.quote(table)} WHERE {key_where}"

    def apply(conn: Connection) -> int:
        affected = 0
        for index in range(0, len(stale), batch):
            chunk = stale[index : index + batch]
            for key in chunk:
                params = {f"k{i}": value for i, value in enumerate(key)}
                params.update(scope_params)
                if mode == ON_MISSING_MARK:
                    params["flag"] = 1
                result = conn.execute(text(statement), params)
                affected += int(result.rowcount or 0)
        return affected

    if connection is not None:
        return apply(connection)
    with engine.begin() as conn:
        return apply(conn)


def preview_diff(
    engine: Engine,
    *,
    table: str,
    key_columns: list[str],
    rows: list[dict[str, Any]],
    fingerprint_column: str | None = None,
    scope_column: str | None = None,
    scope_value: Any = None,
) -> ReconcileResult:
    "只读对比：这次要写的行里，哪些是新增、哪些会变、哪些没变、哪些源里删了。"
    result = ReconcileResult()
    if not key_columns:
        return result

    dialect = dialect_from_engine(engine)
    cols = list(dict.fromkeys([*key_columns, *([fingerprint_column] if fingerprint_column else [])]))
    select_cols = ", ".join(dialect.quote(c) for c in cols)
    where, params = _scope_clause(dialect, scope_column, scope_value)

    with engine.connect() as conn:
        existing = conn.execute(
            text(f"SELECT {select_cols} FROM {dialect.quote(table)} WHERE 1 = 1{where}"),
            params,
        ).all()

    result.existing = len(existing)
    old_by_key: dict[tuple, Any] = {}
    width = len(key_columns)
    for row in existing:
        old_by_key[tuple(row[:width])] = row[width] if fingerprint_column else None

    seen: set[tuple] = set()
    for row in rows:
        key = tuple(row.get(c) for c in key_columns)
        seen.add(key)
        if key not in old_by_key:
            result.to_insert += 1
            continue
        if (
            fingerprint_column
            and old_by_key[key] not in (None, "")
            and old_by_key[key] == row.get(fingerprint_column)
        ):
            result.unchanged += 1
            continue
        result.to_update += 1

    result.missing = len([k for k in old_by_key if k not in seen])
    return result
