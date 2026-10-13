"建表与补列。"

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.loader.dialects import Dialect
from app.services.loader.dsn import DB_TYPE_SQLSERVER


@dataclass(slots=True)
class TablePlan:
    """将要执行的 DDL。界面上先把这份计划给用户过目，确认了才真跑。"""

    table: str
    will_create: bool = False
    will_add_columns: list[tuple[str, str]] = field(default_factory=list)
    existing_columns: list[str] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.will_create or bool(self.will_add_columns)


def existing_columns(conn: Connection, dialect: Dialect, table: str) -> dict[str, str] | None:
    """读目标表现有列。表不存在返回 None。"""
    if dialect.db_type == DB_TYPE_SQLSERVER:
        sql = text(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
        )
        params: dict[str, Any] = {"t": table}
    else:
        sql = text(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
        )
        params = {"t": table}

    rows = conn.execute(sql, params).all()
    if not rows:
        return None
    return {str(name): str(data_type) for name, data_type in rows}


def plan_table(
    dialect: Dialect,
    table: str,
    columns: dict[str, str],
    *,
    existing: dict[str, str] | None,
) -> TablePlan:
    """算出要执行的 DDL。纯函数，方便先给用户看再执行。"""
    plan = TablePlan(table=table)

    if not columns:
        raise ValueError("没有目标列，先做字段映射")

    if existing is None:
        plan.will_create = True
        cols = ", ".join(
            f"{dialect.quote(name)} {dialect.type_sql(col_type)} NULL" for name, col_type in columns.items()
        )
        plan.statements.append(f"CREATE TABLE {dialect.quote(table)} ({cols})")
        return plan

    plan.existing_columns = list(existing.keys())
    for name, col_type in columns.items():
        if name in existing:
            continue
        plan.will_add_columns.append((name, col_type))
        plan.statements.append(
            f"ALTER TABLE {dialect.quote(table)} ADD {dialect.quote(name)} "
            f"{dialect.type_sql(col_type)} NULL"
        )
    return plan


def ensure_table(conn: Connection, dialect: Dialect, table: str, columns: dict[str, str]) -> TablePlan:
    """把表结构补齐（建表 / 加列），返回实际执行了哪些 DDL。"""
    plan = plan_table(dialect, table, columns, existing=existing_columns(conn, dialect, table))
    for statement in plan.statements:
        conn.execute(text(statement))
    return plan


def plan_widen_columns(
    dialect: Dialect,
    table: str,
    wanted: dict[str, str],
    *,
    existing: dict[str, str] | None,
) -> list[str]:
    "算出「目标表哪几列需要放宽类型」的 DDL。"
    if not existing or dialect.db_type != DB_TYPE_SQLSERVER:
        return []
    statements: list[str] = []
    for name, col_type in wanted.items():
        db_type = (existing.get(name) or "").lower()
        if not db_type:
            continue
        current = abstract_type_for_db(db_type)
        if current is None or current not in _WIDEN_ORDER or col_type not in _WIDEN_ORDER:
            continue
        if _WIDEN_ORDER.index(col_type) <= _WIDEN_ORDER.index(current):
            continue
        statements.append(
            f"ALTER TABLE {dialect.quote(table)} ALTER COLUMN {dialect.quote(name)} "
            f"{dialect.type_sql(col_type)} NULL"
        )
    return statements


_NUMERIC_DB_TYPES = frozenset(
    {
        "bigint",
        "int",
        "smallint",
        "tinyint",
        "float",
        "real",
        "decimal",
        "numeric",
        "money",
        "smallmoney",
        "bit",
    }
)
_TEMPORAL_DB_TYPES = frozenset({"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"})

_TEXTY = frozenset({"text", "json"})

_WIDEN_ORDER = ("bool", "int", "float", "decimal", "text")

_DB_TYPE_WIDTH: dict[str, str] = {
    "bit": "bool",
    "tinyint": "int",
    "smallint": "int",
    "int": "int",
    "bigint": "int",
    "real": "float",
    "float": "float",
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    "smallmoney": "decimal",
    "nvarchar": "text",
    "varchar": "text",
    "nchar": "text",
    "char": "text",
    "ntext": "text",
    "text": "text",
}


def abstract_type_for_db(db_type: str | None) -> str | None:
    "目标库的列类型 → 平台内部的抽象类型。"
    if not db_type:
        return None
    name = str(db_type).lower()
    if name in _TEMPORAL_DB_TYPES:
        return name if name in ("date", "datetime") else "datetime"
    if name in _TEXTY:
        return "text"
    return _DB_TYPE_WIDTH.get(name)


def find_type_conflicts(
    column_types: dict[str, str], existing: dict[str, str] | None
) -> list[dict[str, str]]:
    "哪些列「要写文本、但目标库那一列是数字/日期」。"
    if not existing:
        return []
    conflicts: list[dict[str, str]] = []
    for name, col_type in column_types.items():
        db_type = (existing.get(name) or "").lower()
        if not db_type:
            continue
        if col_type in _TEXTY and (db_type in _NUMERIC_DB_TYPES or db_type in _TEMPORAL_DB_TYPES):
            conflicts.append({"column": name, "wanted": col_type, "existing": db_type})
    return conflicts


COUNT_CAP = 100_000


def count_rows(conn: Connection, dialect: Dialect, table: str) -> int | None:
    "目标表里现有多少行。数不动就返回 None，绝不因此把同步搞挂。"
    inner = f"SELECT TOP {COUNT_CAP + 1} 1 AS x FROM {dialect.quote(table)}"
    if dialect.db_type != DB_TYPE_SQLSERVER:
        inner = f"SELECT 1 AS x FROM {dialect.quote(table)} LIMIT {COUNT_CAP + 1}"
    try:
        rows = conn.execute(text(f"SELECT COUNT(*) FROM ({inner}) AS s")).scalar()
        return int(rows or 0)
    except Exception:  # noqa: BLE001 — 数不出来不影响写入
        return None
