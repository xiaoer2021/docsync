"""方言差异：标识符引用、类型映射、单条语句的参数上限。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.loader.dsn import DB_TYPE_MYSQL, DB_TYPE_SQLSERVER, normalize_db_type

_TYPE_MAP: dict[str, dict[str, str]] = {
    DB_TYPE_SQLSERVER: {
        "text": "NVARCHAR(MAX)",
        "int": "BIGINT",
        "float": "FLOAT(53)",
        "decimal": "DECIMAL(18,6)",
        "date": "DATE",
        "datetime": "DATETIME2",
        "bool": "BIT",
        "json": "NVARCHAR(MAX)",
    },
    DB_TYPE_MYSQL: {
        "text": "VARCHAR(500)",
        "int": "BIGINT",
        "float": "DOUBLE",
        "decimal": "DECIMAL(18,6)",
        "date": "DATE",
        "datetime": "DATETIME(3)",
        "bool": "TINYINT(1)",
        "json": "JSON",
    },
}

_TEXT_WITH_LENGTH = {
    DB_TYPE_SQLSERVER: "NVARCHAR({length})",
    DB_TYPE_MYSQL: "VARCHAR({length})",
}


@dataclass(frozen=True, slots=True)
class Dialect:
    db_type: str

    def quote(self, ident: str) -> str:
        if self.db_type == DB_TYPE_SQLSERVER:
            return "[" + str(ident).replace("]", "]]") + "]"
        return "`" + str(ident).replace("`", "``") + "`"

    def type_sql(self, col_type: str, length: int | None = None) -> str:
        mapping = _TYPE_MAP.get(self.db_type)
        if mapping is None:
            raise ValueError(f"不支持的数据库类型：{self.db_type}")
        if col_type == "text" and length:
            return _TEXT_WITH_LENGTH[self.db_type].format(length=int(length))
        if col_type not in mapping:
            raise ValueError(f"不认识的列类型：{col_type}")
        return mapping[col_type]

    @property
    def max_params(self) -> int:
        "一条语句里最多多少个绑定参数。"
        return 2100 if self.db_type == DB_TYPE_SQLSERVER else 60000

    def rows_per_insert(self, column_count: int, *, ceiling: int) -> int:
        if column_count <= 0:
            return 1
        allowed = max(self.max_params // column_count, 1)
        return max(min(allowed, ceiling), 1)

    def select_page_sql(
        self, table: str, *, order_column: str, desc: bool = True, where: str | None = None
    ) -> str:
        "翻页读一张表。"
        clause = f"WHERE {where} " if where else ""
        order = f"ORDER BY {self.quote(order_column)} {'DESC' if desc else 'ASC'}"
        if self.db_type == DB_TYPE_SQLSERVER:
            return (
                f"SELECT * FROM {self.quote(table)} {clause}{order} "
                "OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY"
            )
        return f"SELECT * FROM {self.quote(table)} {clause}{order} LIMIT :lim OFFSET :off"

    def as_text(self, column: str) -> str:
        "把一列按文本来用（给 LIKE 模糊筛选）。"
        quoted = self.quote(column)
        if self.db_type == DB_TYPE_SQLSERVER:
            return f"CAST({quoted} AS NVARCHAR(MAX))"
        return f"CAST({quoted} AS CHAR)"

    @property
    def supports_merge(self) -> bool:
        return self.db_type == DB_TYPE_SQLSERVER

    @property
    def max_identifier_length(self) -> int:
        return 128 if self.db_type == DB_TYPE_SQLSERVER else 64


def dialect_for(db_type: str) -> Dialect:
    """按类型名造方言对象。``sqlserver`` 和 SQLAlchemy 的 ``mssql`` 都认。"""
    return Dialect(normalize_db_type(db_type))


def dialect_from_engine(engine: Any) -> Dialect:
    "从 SQLAlchemy 引擎反推方言。"
    return Dialect(normalize_db_type(getattr(engine.dialect, "name", "")))
