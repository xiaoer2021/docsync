"""目标库连接串与引擎。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from app.core.config import settings

DB_TYPE_SQLSERVER = "sqlserver"
DB_TYPE_MYSQL = "mysql"
SUPPORTED = (DB_TYPE_SQLSERVER, DB_TYPE_MYSQL)

DB_TYPE_LABELS = {
    DB_TYPE_SQLSERVER: "SQL Server",
    DB_TYPE_MYSQL: "MySQL",
}

DEFAULT_PORTS = {
    DB_TYPE_SQLSERVER: 1433,
    DB_TYPE_MYSQL: 3306,
}

SA_DIALECT = {
    DB_TYPE_SQLSERVER: "mssql",
    DB_TYPE_MYSQL: "mysql",
}

SA_TO_DB_TYPE = {v: k for k, v in SA_DIALECT.items()}


def normalize_db_type(name: str | None) -> str:
    """把 ``sqlserver`` / ``mssql`` 这类叫法统一成内部类型名。"""
    text = (name or "").strip().lower()
    if text in SUPPORTED:
        return text
    if text in SA_TO_DB_TYPE:
        return SA_TO_DB_TYPE[text]
    raise ValueError(f"不支持的数据库类型：{name}（可选 {SUPPORTED}）")


def build_url(
    *,
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
) -> str:
    "拼连接串。"
    kind = normalize_db_type(db_type)
    driver = "pymssql" if kind == DB_TYPE_SQLSERVER else "pymysql"
    return URL.create(
        f"{SA_DIALECT[kind]}+{driver}",
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
    ).render_as_string(hide_password=False)


def connect_args(db_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """驱动级参数。单独传而不是塞进 URL，免得被当查询参数处理。"""
    extra = dict(extra or {})
    if (db_type or "").lower() == DB_TYPE_SQLSERVER:
        args: dict[str, Any] = {
            "charset": extra.pop("charset", "utf8"),
            "login_timeout": int(extra.pop("login_timeout", settings.target_login_timeout)),
            "timeout": int(extra.pop("timeout", settings.target_query_timeout)),
        }

        args.setdefault("tds_version", extra.pop("tds_version", "7.0"))
        args.update(extra)
        return args

    args = {"charset": extra.pop("charset", "utf8mb4")}
    args.update(extra)
    return args


def make_engine(
    *,
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    extra: dict[str, Any] | None = None,
) -> Engine:
    url = build_url(
        db_type=db_type,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
    return create_engine(
        url,
        connect_args=connect_args(db_type, extra),
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def describe(*, db_type: str, host: str, port: int, database: str, username: str) -> str:
    """用于日志与摘要的目标类型；不包含连接身份或地址。"""
    return db_type
