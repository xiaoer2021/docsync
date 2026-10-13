"""Check migrated credentials and read-only target database connectivity."""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.core.crypto import decrypt_secret
from app.core.db import SessionLocal
from app.models.app import DdApp
from app.models.datasource import DdDatasource
from app.services.loader.dsn import make_engine


async def main() -> int:
    async with SessionLocal() as session:
        apps = list((await session.scalars(select(DdApp))).all())
        sources = list((await session.scalars(select(DdDatasource))).all())
    for app in apps:
        try:
            if app.platform == "wps":
                print(f"app {app.id}: browser authorization; no app secret required")
                continue
            value = decrypt_secret(app.app_secret_enc)
            if not value.get("app_secret"):
                raise ValueError("empty app secret")
            print(f"app {app.id}: credential ok")
        except Exception as exc:
            print(f"app {app.id}: credential failed ({type(exc).__name__})")
            return 1
    for source in sources:
        try:
            password = decrypt_secret(source.password_enc).get("password")

            def check(source=source, password=password) -> None:
                engine = make_engine(
                    db_type=source.db_type,
                    host=source.host,
                    port=source.port,
                    database=source.database,
                    username=source.username,
                    password=password or "",
                    extra=source.extra,
                )
                try:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                finally:
                    engine.dispose()

            await asyncio.to_thread(check)
            print(f"datasource {source.id}: credential and read-only connection ok")
        except Exception as exc:
            print(f"datasource {source.id}: validation failed ({type(exc).__name__})")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
