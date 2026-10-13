"整表重写只能清一次表。"

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.services.loader import writer
from app.services.loader.dialects import Dialect
from app.services.loader.writer import WRITE_APPEND, WRITE_FULL_REPLACE, WRITE_REPLACE_PARTITION, write


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Engine:
    """只记录 begin() 被调用了几次 —— 每次 begin 就是一个独立事务。"""

    def __init__(self):
        self.transactions = 0

    def begin(self):
        self.transactions += 1
        return _Conn()


@pytest.fixture
def spy(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(writer, "dialect_from_engine", lambda engine: object())
    monkeypatch.setattr(
        writer,
        "_write_full_replace",
        lambda conn, dialect, table, columns, rows, stats: calls.append(len(rows)),
    )
    return calls


def rows(n: int) -> list[dict]:
    return [{"id": i} for i in range(n)]


class TestFullReplaceIsOneTransaction:
    def test_rows_beyond_batch_size_not_wiped(self, spy):
        """300 行、批 100 —— 只准一次 TRUNCATE，一次全写。"""
        engine = _Engine()
        stats = write(
            engine,
            table="t",
            columns=["id"],
            rows=rows(300),
            mode=WRITE_FULL_REPLACE,
            batch_size=100,
        )
        assert spy == [300], "被切成多批了 —— 第二批会清掉第一批"
        assert engine.transactions == 1
        assert stats.batches == 1

    def test_one_past_the_boundary(self, spy):
        """101 行、批 100 —— 最容易被吃掉一行/被清一次的位置。"""
        engine = _Engine()
        write(
            engine,
            table="t",
            columns=["id"],
            rows=rows(101),
            mode=WRITE_FULL_REPLACE,
            batch_size=100,
        )
        assert spy == [101]
        assert engine.transactions == 1

    def test_exactly_the_batch_size(self, spy):
        engine = _Engine()
        write(
            engine,
            table="t",
            columns=["id"],
            rows=rows(100),
            mode=WRITE_FULL_REPLACE,
            batch_size=100,
        )
        assert spy == [100]

    def test_small_input(self, spy):
        engine = _Engine()
        write(
            engine,
            table="t",
            columns=["id"],
            rows=rows(5),
            mode=WRITE_FULL_REPLACE,
            batch_size=100,
        )
        assert spy == [5]

    def test_empty_input_writes_nothing(self, spy):
        engine = _Engine()
        write(engine, table="t", columns=["id"], rows=[], mode=WRITE_FULL_REPLACE)
        assert spy == []


def test_append_batches_share_one_transaction(monkeypatch):
    monkeypatch.setattr(writer, "dialect_from_engine", lambda engine: object())
    calls = []
    monkeypatch.setattr(
        writer,
        "_write_append",
        lambda conn, dialect, table, columns, chunk, stats: calls.append(len(chunk)),
    )
    engine = _Engine()
    result = write(engine, table="t", columns=["id"], rows=rows(5), mode=WRITE_APPEND, batch_size=2)
    assert engine.transactions == 1
    assert calls == [2, 2, 1]
    assert result.batches == 3


def test_partition_is_deleted_once_before_all_insert_batches(monkeypatch):
    monkeypatch.setattr(writer, "dialect_from_engine", lambda engine: object())
    calls = []
    monkeypatch.setattr(writer, "_delete_partitions", lambda *args: calls.append("delete"))
    monkeypatch.setattr(writer, "_write_append", lambda *args: calls.append("insert"))
    engine = _Engine()
    write(
        engine,
        table="t",
        columns=["id", "day"],
        rows=[{"id": i, "day": "2026-10-08"} for i in range(5)],
        mode=WRITE_REPLACE_PARTITION,
        partition_column="day",
        batch_size=2,
    )
    assert engine.transactions == 1
    assert calls == ["delete", "insert", "insert", "insert"]


def test_cleanup_runs_inside_the_same_transaction(monkeypatch):
    monkeypatch.setattr(writer, "dialect_from_engine", lambda engine: object())
    calls = []
    monkeypatch.setattr(writer, "_write_append", lambda *args: calls.append("insert"))
    engine = _Engine()
    write(
        engine,
        table="t",
        columns=["id"],
        rows=rows(3),
        mode=WRITE_APPEND,
        batch_size=2,
        after_write=lambda conn: calls.append("cleanup"),
    )
    assert engine.transactions == 1
    assert calls == ["insert", "insert", "cleanup"]


def test_full_replace_insert_failure_restores_original_rows(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(writer, "dialect_from_engine", lambda _: Dialect("mysql"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE target (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO target VALUES (1, 'original')"))
    with pytest.raises(IntegrityError):
        write(
            engine,
            table="target",
            columns=["id", "value"],
            rows=[{"id": 2, "value": "new"}, {"id": 3, "value": None}],
            mode=WRITE_FULL_REPLACE,
        )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM target")).all() == [(1, "original")]
    engine.dispose()
