"对账（删除同步 / 差异预览）与增量窗口。"

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, text

from app.services.loader import reconcile
from app.services.loader.dialects import Dialect
from app.services.runner.orchestrator import _apply_incremental


class FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str) -> None:
        self.lines.append(message)

    def warn(self, message: str) -> None:
        self.lines.append("WARN " + message)

    def error(self, message: str) -> None:
        self.lines.append("ERR " + message)


@pytest.fixture
def engine(monkeypatch):
    """SQLite 替身：方言固定成 MySQL，SQL 语句就通用。"""
    eng = create_engine("sqlite://")
    monkeypatch.setattr("app.services.loader.reconcile.dialect_from_engine", lambda _e: Dialect("mysql"))
    with eng.begin() as conn:
        conn.execute(
            text("CREATE TABLE t (" "`产品编码` TEXT, `金额` REAL, `来源工作表ID` TEXT, `数据指纹` TEXT)")
        )
    yield eng
    eng.dispose()


def seed(engine, rows: list[tuple]) -> None:
    with engine.begin() as conn:
        for code, amount, sheet, fp in rows:
            conn.execute(
                text(
                    "INSERT INTO t (`产品编码`, `金额`, `来源工作表ID`, `数据指纹`) "
                    "VALUES (:a, :b, :c, :d)"
                ),
                {"a": code, "b": amount, "c": sheet, "d": fp},
            )


class TestPreviewDiff:
    def test_counts_insert_update_unchanged(self, engine):
        seed(engine, [("A001", 100, "st1", "fp-old"), ("A002", 200, "st1", "fp-same")])
        diff = reconcile.preview_diff(
            engine,
            table="t",
            key_columns=["产品编码"],
            fingerprint_column="数据指纹",
            scope_column="来源工作表ID",
            scope_value="st1",
            rows=[
                {"产品编码": "A001", "数据指纹": "fp-new"},
                {"产品编码": "A002", "数据指纹": "fp-same"},
                {"产品编码": "A003", "数据指纹": "fp-x"},
            ],
        )
        assert diff.to_insert == 1
        assert diff.to_update == 1
        assert diff.unchanged == 1
        assert diff.missing == 0

    def test_reports_rows_gone_from_source(self, engine):
        seed(
            engine,
            [("A001", 1, "st1", "f1"), ("A002", 2, "st1", "f2"), ("A003", 3, "st1", "f3")],
        )
        diff = reconcile.preview_diff(
            engine,
            table="t",
            key_columns=["产品编码"],
            fingerprint_column="数据指纹",
            scope_column="来源工作表ID",
            scope_value="st1",
            rows=[{"产品编码": "A001", "数据指纹": "f1"}],
        )
        assert diff.missing == 2

    def test_scoped_by_source_column(self, engine):
        """别的子表写进去的行不能被算进来 —— 否则会互相删数据。"""
        seed(engine, [("A001", 1, "st1", "f1"), ("B001", 1, "st2", "f1")])
        diff = reconcile.preview_diff(
            engine,
            table="t",
            key_columns=["产品编码"],
            fingerprint_column="数据指纹",
            scope_column="来源工作表ID",
            scope_value="st1",
            rows=[{"产品编码": "A001", "数据指纹": "f1"}],
        )
        assert diff.existing == 1
        assert diff.missing == 0

    def test_no_keys_returns_zeros(self, engine):
        diff = reconcile.preview_diff(engine, table="t", key_columns=[], rows=[{"a": 1}])
        assert diff.to_insert == 0 and diff.missing == 0


class TestApplyMissing:
    @pytest.mark.parametrize("mode", [reconcile.ON_MISSING_DELETE, reconcile.ON_MISSING_MARK])
    def test_same_key_in_other_sheet_is_preserved(self, engine, mode):
        seed(engine, [("SAME", 1, "st1", "f1"), ("SAME", 2, "st2", "f2")])
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE t ADD COLUMN `__is_deleted__` INTEGER DEFAULT 0"))
        affected = reconcile.apply_missing(
            engine,
            table="t",
            key_columns=["产品编码"],
            scope_column="来源工作表ID",
            scope_value="st1",
            keep_keys=set(),
            mode=mode,
        )
        assert affected == 1
        with engine.connect() as conn:
            other = conn.execute(
                text("SELECT `金额`, `__is_deleted__` FROM t WHERE `来源工作表ID`='st2'")
            ).one()
        assert tuple(other) == (2, 0)

    def test_empty_scope_refuses_destructive_cleanup(self, engine):
        with pytest.raises(ValueError, match="来源"):
            reconcile.apply_missing(
                engine,
                table="t",
                key_columns=["产品编码"],
                scope_column="",
                scope_value="",
                keep_keys=set(),
                mode=reconcile.ON_MISSING_DELETE,
            )

    def test_delete_mode_removes_stale(self, engine):
        seed(engine, [("A001", 1, "st1", "f1"), ("A002", 2, "st1", "f2")])
        removed = reconcile.apply_missing(
            engine,
            table="t",
            key_columns=["产品编码"],
            scope_column="来源工作表ID",
            scope_value="st1",
            keep_keys={("A001",)},
            mode=reconcile.ON_MISSING_DELETE,
        )
        assert removed == 1
        with engine.connect() as conn:
            left = [r[0] for r in conn.execute(text("SELECT `产品编码` FROM t")).all()]
        assert left == ["A001"]

    def test_keep_mode_does_nothing(self, engine):
        seed(engine, [("A001", 1, "st1", "f1"), ("A002", 2, "st1", "f2")])
        removed = reconcile.apply_missing(
            engine,
            table="t",
            key_columns=["产品编码"],
            scope_column="来源工作表ID",
            scope_value="st1",
            keep_keys={("A001",)},
            mode=reconcile.ON_MISSING_KEEP,
        )
        assert removed == 0

    def test_mark_mode_flags_instead_of_deleting(self, engine):
        seed(engine, [("A001", 1, "st1", "f1"), ("A002", 2, "st1", "f2")])
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE t ADD COLUMN `__is_deleted__` INTEGER DEFAULT 0"))

        marked = reconcile.apply_missing(
            engine,
            table="t",
            key_columns=["产品编码"],
            scope_column="来源工作表ID",
            scope_value="st1",
            keep_keys={("A001",)},
            mode=reconcile.ON_MISSING_MARK,
            mark_column="__is_deleted__",
        )
        assert marked == 1
        with engine.connect() as conn:
            rows = dict(conn.execute(text("SELECT `产品编码`, `__is_deleted__` FROM t")).all())

        assert rows == {"A001": 0, "A002": 1}

    def test_other_sheets_untouched(self, engine):
        seed(engine, [("A001", 1, "st1", "f1"), ("B001", 1, "st2", "f1")])
        removed = reconcile.apply_missing(
            engine,
            table="t",
            key_columns=["产品编码"],
            scope_column="来源工作表ID",
            scope_value="st1",
            keep_keys=set(),
            mode=reconcile.ON_MISSING_DELETE,
        )
        assert removed == 1
        with engine.connect() as conn:
            left = [r[0] for r in conn.execute(text("SELECT `产品编码` FROM t")).all()]
        assert left == ["B001"], "别的子表的行不能被误删"


class TestIncrementalWindow:
    TODAY = dt.datetime.now()

    def rows(self):
        return [
            {"日期": self.TODAY - dt.timedelta(days=1), "值": 1},
            {"日期": self.TODAY - dt.timedelta(days=3), "值": 2},
            {"日期": self.TODAY - dt.timedelta(days=30), "值": 3},
        ]

    def test_filters_old_rows(self):
        logger = FakeLogger()
        kept = _apply_incremental(
            self.rows(), source_cfg={"incremental": {"column": "日期", "days": 7}}, logger=logger
        )
        assert [r["值"] for r in kept] == [1, 2]
        assert any("过滤掉 1 行" in line for line in logger.lines)

    def test_no_config_passthrough(self):
        logger = FakeLogger()
        rows = self.rows()
        assert _apply_incremental(rows, source_cfg={}, logger=logger) == rows

    def test_unknown_column_warns_and_keeps_all(self):
        """增量列写错了不该把数据全过滤没，只提示一下。"""
        logger = FakeLogger()
        rows = self.rows()
        kept = _apply_incremental(
            rows,
            source_cfg={"incremental": {"column": "不存在的列", "days": 7}},
            logger=logger,
        )
        assert kept == rows
        assert any("不做增量过滤" in line for line in logger.lines)

    def test_empty_value_kept(self):
        logger = FakeLogger()
        rows = [{"日期": None, "值": 9}]
        kept = _apply_incremental(
            rows, source_cfg={"incremental": {"column": "日期", "days": 7}}, logger=logger
        )
        assert kept == rows

    def test_string_dates_supported(self):
        logger = FakeLogger()
        old = (self.TODAY - dt.timedelta(days=60)).strftime("%Y-%m-%d")
        rows = [{"日期": old, "值": 1}]
        kept = _apply_incremental(
            rows, source_cfg={"incremental": {"column": "日期", "days": 7}}, logger=logger
        )
        assert kept == []
