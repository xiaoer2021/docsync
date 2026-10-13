"""Import a consistent SQLite snapshot into an empty, Alembic-initialized MySQL database."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sqlite3
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Time, func, select, text

from app.core.db import engine
from app.models import Base


def convert(value, column):
    if value is None:
        return None
    if isinstance(column.type, JSON):
        return json.loads(value)
    if isinstance(column.type, DateTime):
        return dt.datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return dt.date.fromisoformat(value)
    if isinstance(column.type, Time):
        return dt.time.fromisoformat(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    return value


async def migrate(source: Path) -> None:
    if not source.is_file():
        raise SystemExit("SQLite snapshot missing")
    sqlite = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    sqlite.row_factory = sqlite3.Row
    try:
        if sqlite.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
        if sqlite.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("SQLite foreign key check failed")
        source_tables = {
            row[0]
            for row in sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected_tables = set(Base.metadata.tables)
        if source_tables - {"alembic_version"} != expected_tables:
            raise RuntimeError(
                f"Schema tables differ: missing={sorted(expected_tables - source_tables)}, "
                f"extra={sorted(source_tables - expected_tables - {'alembic_version'})}"
            )
        counts = {
            name: sqlite.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in expected_tables
        }
        async with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                existing = await conn.scalar(select(func.count()).select_from(table))
                if existing:
                    raise RuntimeError(f"Destination is not empty: {table.name}")
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            try:
                for table in Base.metadata.sorted_tables:
                    source_columns = {row[1] for row in sqlite.execute(f'PRAGMA table_info("{table.name}")')}
                    target_columns = set(table.columns.keys())
                    if source_columns != target_columns:
                        raise RuntimeError(
                            f"Columns differ in {table.name}: "
                            f"missing={sorted(target_columns - source_columns)}, "
                            f"extra={sorted(source_columns - target_columns)}"
                        )
                    cursor = sqlite.execute(f'SELECT * FROM "{table.name}" ORDER BY id')
                    total = 0
                    while batch := cursor.fetchmany(500):
                        records = [
                            {key: convert(row[key], table.c[key]) for key in row.keys()}  # noqa: SIM118
                            for row in batch
                        ]
                        await conn.execute(table.insert(), records)
                        total += len(records)
                    print(f"{table.name}: {total}")
                for table in Base.metadata.sorted_tables:
                    actual = await conn.scalar(select(func.count()).select_from(table))
                    if actual != counts[table.name]:
                        raise RuntimeError(
                            f"Count mismatch in {table.name}: {counts[table.name]} vs {actual}"
                        )
            finally:
                await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        print("Migration counts verified")
    finally:
        sqlite.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    asyncio.run(migrate(parser.parse_args().source))
