"批量写入：四种策略。"

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.services.loader.dialects import Dialect, dialect_from_engine
from app.services.loader.dsn import DB_TYPE_SQLSERVER

WRITE_UPSERT = "upsert"
WRITE_APPEND = "append"
WRITE_REPLACE_PARTITION = "replace_partition"
WRITE_FULL_REPLACE = "full_replace"

DEFAULT_BATCH = 2000


@dataclass(slots=True)
class WriteStats:
    read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    written: int = 0
    failed: int = 0
    batches: int = 0
    deleted: int = 0

    duplicates: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, other: WriteStats) -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.written += other.written
        self.failed += other.failed
        self.batches += other.batches
        self.deleted += other.deleted
        self.duplicates += other.duplicates
        self.issues.extend(other.issues)


def _key_text(value: Any) -> str:
    "主键值比成一串文本。"
    return "" if value is None else str(value).strip()


def dedupe_by_key(rows: list[dict[str, Any]], keys: list[str]) -> tuple[list[dict[str, Any]], int]:
    "按主键去重，**保留最后出现的那条**。"
    if not keys:
        return rows, 0
    seen: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        seen[tuple(_key_text(row.get(k)) for k in keys)] = row
    dropped = len(rows) - len(seen)
    return list(seen.values()), dropped


def _params(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    return {f"c{i}": row.get(name) for i, name in enumerate(columns)}


def _insert_sql(dialect: Dialect, table: str, columns: list[str], *, into: str | None = None) -> str:
    target = into or dialect.quote(table)
    names = ", ".join(dialect.quote(c) for c in columns)
    values = ", ".join(f":c{i}" for i in range(len(columns)))
    return f"INSERT INTO {target} ({names}) VALUES ({values})"


def _write_append(
    conn: Connection,
    dialect: Dialect,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    stats: WriteStats,
) -> None:
    sql = text(_insert_sql(dialect, table, columns))
    conn.execute(sql, [_params(row, columns) for row in rows])
    stats.inserted += len(rows)
    stats.written += len(rows)


def _write_upsert_sqlserver(
    conn: Connection,
    dialect: Dialect,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    keys: list[str],
    fingerprint_column: str | None,
    insert_only: list[str],
    stats: WriteStats,
) -> None:
    "临时表 + MERGE。"
    stage = "#docsync_stage"
    insert_cols = ", ".join(dialect.quote(c) for c in columns)

    joiner = " AND ".join(f"T.{dialect.quote(k)} = S.{dialect.quote(k)}" for k in keys)
    insert_vals = ", ".join(f"S.{dialect.quote(c)}" for c in columns)
    updatable = [c for c in columns if c not in keys and c not in insert_only]
    updates = ", ".join(f"T.{dialect.quote(c)} = S.{dialect.quote(c)}" for c in updatable)

    when_matched = "WHEN MATCHED"
    if fingerprint_column and fingerprint_column in columns:
        fp = dialect.quote(fingerprint_column)
        when_matched += f" AND ISNULL(T.{fp}, '') <> ISNULL(S.{fp}, '')"

    conn.execute(text(f"IF OBJECT_ID('tempdb..{stage}') IS NOT NULL DROP TABLE {stage}"))
    conn.execute(text(f"SELECT TOP 0 {insert_cols} INTO {stage} FROM {dialect.quote(table)}"))
    conn.execute(
        text(_insert_sql(dialect, table, columns, into=stage)),
        [_params(r, columns) for r in rows],
    )

    merge_action = f"{when_matched} THEN UPDATE SET {updates}\n" if updates else ""
    merge = f"""
        MERGE INTO {dialect.quote(table)} WITH (HOLDLOCK) AS T
        USING {stage} AS S ON {joiner}
        {merge_action}WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        OUTPUT $action AS act;
    """
    actions = [str(row[0]).upper() for row in conn.execute(text(merge)).all()]
    inserted = actions.count("INSERT")
    updated = actions.count("UPDATE")
    stats.inserted += inserted
    stats.updated += updated
    stats.unchanged += len(rows) - inserted - updated
    stats.written += inserted + updated


def _write_upsert_mysql(
    conn: Connection,
    dialect: Dialect,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    keys: list[str],
    fingerprint_column: str | None,
    insert_only: list[str],
    stats: WriteStats,
) -> None:
    "MySQL 的 ON DUPLICATE KEY UPDATE。"
    names = ", ".join(dialect.quote(c) for c in columns)
    values = ", ".join(f":c{i}" for i in range(len(columns)))
    updatable = [c for c in columns if c not in keys and c not in insert_only]
    updates = ", ".join(f"{dialect.quote(c)} = VALUES({dialect.quote(c)})" for c in updatable)
    if not updates:
        updates = f"{dialect.quote(columns[0])} = {dialect.quote(columns[0])}"

    sql = text(
        f"INSERT INTO {dialect.quote(table)} ({names}) VALUES ({values}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    result = conn.execute(sql, [_params(r, columns) for r in rows])
    affected = int(result.rowcount or 0)
    count = len(rows)

    inserted = max(min(2 * count - affected, count), 0)
    updated = max(affected - count, 0)
    stats.inserted += inserted
    stats.updated += updated
    stats.unchanged += max(count - inserted - updated, 0)
    stats.written += affected


def _write_upsert(
    conn: Connection,
    dialect: Dialect,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    keys: list[str],
    fingerprint_column: str | None,
    insert_only: list[str],
    stats: WriteStats,
) -> None:
    if dialect.db_type == DB_TYPE_SQLSERVER:
        _write_upsert_sqlserver(
            conn, dialect, table, columns, rows, keys, fingerprint_column, insert_only, stats
        )
    else:
        _write_upsert_mysql(conn, dialect, table, columns, rows, keys, fingerprint_column, insert_only, stats)


def _delete_partitions(
    conn: Connection,
    dialect: Dialect,
    table: str,
    rows: list[dict[str, Any]],
    partition_column: str,
    stats: WriteStats,
) -> None:
    values = sorted({row.get(partition_column) for row in rows}, key=lambda v: (v is None, v))
    if not values:
        return

    for offset in range(0, len(values), 1000):
        group = values[offset : offset + 1000]
        placeholders = ", ".join(f":p{i}" for i in range(len(group)))
        conn.execute(
            text(
                f"DELETE FROM {dialect.quote(table)} "
                f"WHERE {dialect.quote(partition_column)} IN ({placeholders})"
            ),
            {f"p{i}": v for i, v in enumerate(group)},
        )
    stats.deleted += len(values)


def _write_full_replace(
    conn: Connection,
    dialect: Dialect,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    stats: WriteStats,
) -> None:
    conn.execute(text(f"DELETE FROM {dialect.quote(table)}"))
    _write_append(conn, dialect, table, columns, rows, stats)


def chunk_rows(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def write(
    engine: Engine,
    *,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    mode: str = WRITE_UPSERT,
    key_columns: list[str] | None = None,
    partition_column: str | None = None,
    fingerprint_column: str | None = None,
    insert_only_columns: list[str] | None = None,
    batch_size: int = DEFAULT_BATCH,
    after_write: Callable[[Connection], None] | None = None,
) -> WriteStats:
    "按策略把行写进目标表。一次执行共用一个事务。"
    stats = WriteStats(read=len(rows))
    if not rows:
        return stats

    dialect = dialect_from_engine(engine)
    keys = [k for k in (key_columns or []) if k in columns]
    insert_only = [c for c in (insert_only_columns or []) if c in columns]

    if mode == WRITE_UPSERT and not keys:
        raise ValueError("按主键更新需要先指定主键列")
    if mode == WRITE_REPLACE_PARTITION and not partition_column:
        raise ValueError("按分区覆盖需要先指定分区列")

    if mode == WRITE_UPSERT and keys:
        rows, stats.duplicates = dedupe_by_key(rows, keys)

    size = max(batch_size, 1)
    if mode == WRITE_UPSERT:
        size = min(size, dialect.rows_per_insert(len(columns), ceiling=batch_size))

    if mode == WRITE_FULL_REPLACE:
        with engine.begin() as conn:
            _write_full_replace(conn, dialect, table, columns, rows, stats)
            if after_write:
                after_write(conn)
        stats.batches = 1
        return stats

    with engine.begin() as conn:
        if mode == WRITE_REPLACE_PARTITION:
            _delete_partitions(conn, dialect, table, rows, str(partition_column), stats)
        for chunk in chunk_rows(rows, size):
            if mode == WRITE_APPEND:
                _write_append(conn, dialect, table, columns, chunk, stats)
            elif mode == WRITE_UPSERT:
                _write_upsert(
                    conn,
                    dialect,
                    table,
                    columns,
                    chunk,
                    keys,
                    fingerprint_column,
                    insert_only,
                    stats,
                )
            elif mode == WRITE_REPLACE_PARTITION:
                _write_append(conn, dialect, table, columns, chunk, stats)
            else:
                raise ValueError(f"不认识的写入策略：{mode}")
            stats.batches += 1
        if after_write:
            after_write(conn)

    return stats
