"""落库层：方言、DDL 计划、批量切片。"""

from __future__ import annotations

import pytest

from app.services.loader.ddl import plan_table
from app.services.loader.dialects import Dialect, dialect_for
from app.services.loader.dsn import build_url, connect_args, normalize_db_type
from app.services.loader.writer import DEFAULT_BATCH, chunk_rows


class TestDsn:
    def test_builds_sqlserver_with_mssql_dialect(self):
        "回归：内部叫法是 sqlserver，但 SQLAlchemy 的方言名必须是 mssql。"
        url = build_url(
            db_type="sqlserver",
            host="192.0.2.10",
            port=11433,
            database="BI",
            username="example_user",
            password="Example!@#$%&*()+=NotARealSecret",
        )
        assert url.startswith("mssql+pymssql://")

        assert "Example!@#$%&*()+=NotARealSecret" not in url
        assert "192.0.2.10:11433" in url

    def test_builds_mysql(self):
        url = build_url(
            db_type="mysql",
            host="localhost",
            port=3306,
            database="bi",
            username="root",
            password="p@ss:word",
        )
        assert url.startswith("mysql+pymysql://")

    def test_accepts_sqlalchemy_name_too(self):
        assert build_url(
            db_type="mssql", host="h", port=1, database="d", username="u", password="p"
        ).startswith("mssql+pymssql://")

    def test_unknown_type(self):
        with pytest.raises(ValueError):
            build_url(db_type="oracle", host="h", port=1, database="d", username="u", password="p")

    def test_connect_args_sqlserver(self):
        args = connect_args("sqlserver")
        assert args["charset"] == "utf8"
        assert args["login_timeout"] == 30

    def test_connect_args_mysql(self):
        assert connect_args("mysql")["charset"] == "utf8mb4"


class TestNormalizeDbType:
    def test_internal_name_passthrough(self):
        assert normalize_db_type("sqlserver") == "sqlserver"
        assert normalize_db_type("MySQL") == "mysql"

    def test_sqlalchemy_name_mapped_back(self):
        "回归：engine.dialect.name 返回 mssql，必须能映射回 sqlserver。"
        assert normalize_db_type("mssql") == "sqlserver"

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_db_type("postgres")


class TestDialect:
    def test_quoting(self):
        assert Dialect("sqlserver").quote("订单号") == "[订单号]"
        assert Dialect("mysql").quote("订单号") == "`订单号`"

    def test_quoting_escapes_closing_bracket(self):
        assert Dialect("sqlserver").quote("a]b") == "[a]]b]"

    def test_type_map(self):
        sql = Dialect("sqlserver")
        assert sql.type_sql("text") == "NVARCHAR(MAX)"
        assert sql.type_sql("int") == "BIGINT"
        assert sql.type_sql("date") == "DATE"
        assert sql.type_sql("bool") == "BIT"
        assert sql.type_sql("text", length=100) == "NVARCHAR(100)"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            Dialect("sqlserver").type_sql("blob")

    def test_rows_per_insert_respects_param_limit(self):
        sql = Dialect("sqlserver")

        assert sql.rows_per_insert(30, ceiling=2000) == 70

        assert sql.rows_per_insert(6, ceiling=2000) == 350

    def test_rows_per_insert_capped_by_ceiling(self):
        sql = Dialect("sqlserver")
        assert sql.rows_per_insert(2, ceiling=500) == 500

    def test_dialect_for_rejects_unknown(self):
        with pytest.raises(ValueError):
            dialect_for("postgres")


class TestSelectPage:
    "翻页读表。"

    def test_sqlserver_always_has_order_by(self):
        sql = Dialect("sqlserver").select_page_sql("订单", order_column="订单号")
        assert "ORDER BY" in sql, "SQL Server 少了 ORDER BY 会直接语法报错"
        assert "OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY" in sql

    def test_sqlserver_order_direction(self):
        sql = Dialect("sqlserver")
        assert "DESC" in sql.select_page_sql("t", order_column="id", desc=True)
        assert "ASC" in sql.select_page_sql("t", order_column="id", desc=False)

    def test_sqlserver_quotes_identifiers(self):
        sql = Dialect("sqlserver").select_page_sql("订单", order_column="订单号")
        assert "[订单]" in sql
        assert "[订单号]" in sql

    def test_mysql_uses_limit_offset(self):
        sql = Dialect("mysql").select_page_sql("订单", order_column="订单号")
        assert "LIMIT :lim OFFSET :off" in sql
        assert "FETCH NEXT" not in sql


class TestPlanTable:
    COLUMNS = {"店铺": "text", "产品编码": "text", "数量": "int"}

    def test_create_when_missing(self):
        plan = plan_table(Dialect("sqlserver"), "t1", self.COLUMNS, existing=None)
        assert plan.will_create
        assert plan.has_changes
        assert plan.statements[0].startswith("CREATE TABLE [t1]")
        assert "[数量] BIGINT" in plan.statements[0]

    def test_no_change_when_all_present(self):
        existing = {k: "nvarchar" for k in self.COLUMNS}
        plan = plan_table(Dialect("sqlserver"), "t1", self.COLUMNS, existing=existing)
        assert not plan.has_changes
        assert plan.statements == []

    def test_adds_only_missing_columns(self):
        existing = {"店铺": "nvarchar", "产品编码": "nvarchar"}
        plan = plan_table(Dialect("sqlserver"), "t1", self.COLUMNS, existing=existing)
        assert plan.will_create is False
        assert [n for n, _ in plan.will_add_columns] == ["数量"]
        assert plan.statements == ["ALTER TABLE [t1] ADD [数量] BIGINT NULL"]

    def test_never_drops_extra_columns(self):
        """目标表多出来的列一律不动 —— 下游可能正引用着。"""
        existing = {**{k: "nvarchar" for k in self.COLUMNS}, "下游用的列": "nvarchar"}
        plan = plan_table(Dialect("sqlserver"), "t1", self.COLUMNS, existing=existing)
        assert plan.statements == []
        assert "下游用的列" in plan.existing_columns

    def test_empty_columns_rejected(self):
        with pytest.raises(ValueError):
            plan_table(Dialect("sqlserver"), "t1", {}, existing=None)


class TestChunking:
    def test_chunks(self):
        rows = [{"i": i} for i in range(5)]
        assert [len(c) for c in chunk_rows(rows, 2)] == [2, 2, 1]

    def test_empty(self):
        assert chunk_rows([], 10) == []

    def test_default_batch_is_2000(self):
        assert DEFAULT_BATCH == 2000
