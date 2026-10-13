"""落库层：连接、方言、建表补列、批量写入。"""

from app.services.loader.ddl import TablePlan, ensure_table, existing_columns, plan_table
from app.services.loader.dialects import Dialect, dialect_for
from app.services.loader.dsn import (
    DB_TYPE_LABELS,
    DB_TYPE_MYSQL,
    DB_TYPE_SQLSERVER,
    DEFAULT_PORTS,
    build_url,
    connect_args,
    describe,
    make_engine,
)
from app.services.loader.writer import (
    WRITE_APPEND,
    WRITE_FULL_REPLACE,
    WRITE_REPLACE_PARTITION,
    WRITE_UPSERT,
    WriteStats,
    write,
)

__all__ = [
    "DB_TYPE_LABELS",
    "DB_TYPE_MYSQL",
    "DB_TYPE_SQLSERVER",
    "DEFAULT_PORTS",
    "Dialect",
    "TablePlan",
    "WRITE_APPEND",
    "WRITE_FULL_REPLACE",
    "WRITE_REPLACE_PARTITION",
    "WRITE_UPSERT",
    "WriteStats",
    "build_url",
    "connect_args",
    "describe",
    "dialect_for",
    "ensure_table",
    "existing_columns",
    "make_engine",
    "plan_table",
    "write",
]
