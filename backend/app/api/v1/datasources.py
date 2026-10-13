"""目标库（数据源）管理。"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select, text

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.mask import mask_value
from app.models.datasource import DdDatasource
from app.models.task import DdTask
from app.schemas.sync import (
    DatasourceCreate,
    DatasourceDraftTest,
    DatasourceOut,
    DatasourceTestResult,
    DatasourceUpdate,
    TableInfo,
)
from app.services import audit
from app.services.loader import dsn as dsn_mod

router = APIRouter(prefix="/datasources", tags=["datasources"])


def _secret_of(ds: DdDatasource) -> str:
    try:
        return str(decrypt_secret(ds.password_enc).get("password") or "")
    except Exception:  # noqa: BLE001
        return ""


def _to_out(ds: DdDatasource, *, task_count: int = 0) -> DatasourceOut:
    return DatasourceOut(
        id=ds.id,
        name=ds.name,
        db_type=ds.db_type,
        db_type_label=dsn_mod.DB_TYPE_LABELS.get(ds.db_type, ds.db_type),
        host=ds.host,
        port=ds.port,
        database=ds.database,
        username=ds.username,
        password_masked=mask_value(_secret_of(ds)),
        extra=ds.extra,
        is_default=ds.is_default,
        enabled=ds.enabled,
        remark=ds.remark,
        task_count=task_count,
        created_at=ds.created_at,
    )


async def _get(session: DbSession, ds_id: int) -> DdDatasource:
    ds = await session.get(DdDatasource, ds_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标库不存在")
    return ds


async def _task_counts(session: DbSession) -> dict[int, int]:
    rows = await session.execute(
        select(DdTask.target["datasource_id"].as_integer(), func.count()).group_by(
            DdTask.target["datasource_id"].as_integer()
        )
    )
    return {int(k): int(v) for k, v in rows.all() if k is not None}


def _ds_kwargs(ds: DdDatasource) -> dict:
    return {
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "database": ds.database,
        "username": ds.username,
        "password": _secret_of(ds),
        "extra": ds.extra,
    }


def _describe_args(ds: DdDatasource) -> dict:
    """describe() 只要这几个字段，而且**不含口令**。"""
    return {
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "database": ds.database,
        "username": ds.username,
    }


@router.get("", response_model=list[DatasourceOut])
async def list_datasources(session: DbSession, _: CurrentUser) -> list[DatasourceOut]:
    items = list((await session.scalars(select(DdDatasource).order_by(DdDatasource.id))).all())
    counts = await _task_counts(session)
    return [_to_out(ds, task_count=counts.get(ds.id, 0)) for ds in items]


@router.post("", response_model=DatasourceOut, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    payload: DatasourceCreate, request: Request, session: DbSession, admin: AdminUser
) -> DatasourceOut:
    if payload.db_type not in dsn_mod.SUPPORTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"只支持 {' 和 '.join(dsn_mod.SUPPORTED)}")
    exists = await session.scalar(select(DdDatasource.id).where(DdDatasource.name == payload.name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "已有同名的目标库")

    port = payload.port or dsn_mod.DEFAULT_PORTS.get(payload.db_type, 1433)
    ds = DdDatasource(
        name=payload.name,
        db_type=payload.db_type,
        host=payload.host.strip(),
        port=int(port),
        database=payload.database.strip(),
        username=payload.username.strip(),
        password_enc=encrypt_secret({"password": payload.password}),
        extra=payload.extra,
        is_default=payload.is_default,
        remark=payload.remark,
    )
    session.add(ds)
    await session.flush()

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_datasource",
        target_id=ds.id,
        summary=f"新建目标库 {ds.name}（{dsn_mod.describe(**_describe_args(ds))}）",
        request=request,
    )
    return _to_out(ds)


@router.get("/{ds_id}", response_model=DatasourceOut)
async def get_datasource(ds_id: int, session: DbSession, _: CurrentUser) -> DatasourceOut:
    ds = await _get(session, ds_id)
    counts = await _task_counts(session)
    return _to_out(ds, task_count=counts.get(ds.id, 0))


@router.patch("/{ds_id}", response_model=DatasourceOut)
async def update_datasource(
    ds_id: int, payload: DatasourceUpdate, request: Request, session: DbSession, admin: AdminUser
) -> DatasourceOut:
    ds = await _get(session, ds_id)

    if payload.name and payload.name != ds.name:
        exists = await session.scalar(
            select(DdDatasource.id).where(DdDatasource.name == payload.name, DdDatasource.id != ds.id)
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "已有同名的目标库")
        ds.name = payload.name
    if payload.host:
        ds.host = payload.host.strip()
    if payload.port is not None:
        ds.port = int(payload.port)
    if payload.database:
        ds.database = payload.database.strip()
    if payload.username:
        ds.username = payload.username.strip()
    if payload.password:
        ds.password_enc = encrypt_secret({"password": payload.password})
    if payload.extra is not None:
        ds.extra = payload.extra
    if payload.is_default is not None:
        ds.is_default = payload.is_default
    if payload.enabled is not None:
        ds.enabled = payload.enabled
    if payload.remark is not None:
        ds.remark = payload.remark

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_datasource",
        target_id=ds.id,
        summary=f"修改目标库 {ds.name}",
        request=request,
    )
    counts = await _task_counts(session)
    return _to_out(ds, task_count=counts.get(ds.id, 0))


@router.delete("/{ds_id}")
async def delete_datasource(
    ds_id: int, request: Request, session: DbSession, admin: AdminUser
) -> dict[str, str]:
    ds = await _get(session, ds_id)
    counts = await _task_counts(session)
    used = counts.get(ds.id, 0)
    if used:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"还有 {used} 个同步任务在用它，先把任务改到别的库或删掉"
        )

    name = ds.name
    await session.delete(ds)
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_datasource",
        target_id=ds_id,
        summary=f"删除目标库 {name}",
        request=request,
    )
    return {"status": "ok"}


async def _run_test(kwargs: dict) -> DatasourceTestResult:
    "真连一次库。连不上时把驱动原话带出来 —— 那通常直接指向问题。"

    def _run() -> DatasourceTestResult:
        started = time.monotonic()
        engine = None
        try:
            engine = dsn_mod.make_engine(**kwargs)
            with engine.connect() as conn:
                version = None
                try:
                    if kwargs["db_type"] == dsn_mod.DB_TYPE_SQLSERVER:
                        version = str(conn.execute(text("SELECT @@VERSION")).scalar() or "")
                        version = version.splitlines()[0][:80] if version else None
                    else:
                        version = str(conn.execute(text("SELECT VERSION()")).scalar() or "")
                except Exception:  # noqa: BLE001 — 版本只是附赠信息，读不到不影响连通判定
                    version = None
            latency = int((time.monotonic() - started) * 1000)
            return DatasourceTestResult(ok=True, message="连接成功", version=version, latency_ms=latency)
        except Exception as exc:  # noqa: BLE001
            return DatasourceTestResult(
                ok=False,
                message=f"{type(exc).__name__}: {exc}",
                hint=(
                    "检查主机/端口/库名/账号密码是否对，以及这台机器能不能连到目标库。"
                    "SQL Server 还要确认已开启 TCP/IP 和 SQL 登录认证。"
                ),
            )
        finally:
            if engine is not None:
                engine.dispose()

    return await asyncio.to_thread(_run)


@router.post("/test", response_model=DatasourceTestResult)
async def test_datasource_draft(
    payload: DatasourceDraftTest, session: DbSession, admin: AdminUser
) -> DatasourceTestResult:
    "用**表单里当前填的参数**测一次，不要求先保存。"
    password = payload.password
    if not password and payload.ds_id:
        password = _secret_of(await _get(session, payload.ds_id))

    return await _run_test(
        {
            "db_type": payload.db_type,
            "host": payload.host,
            "port": payload.port,
            "database": payload.database,
            "username": payload.username,
            "password": password,
            "extra": None,
        }
    )


@router.post("/{ds_id}/test", response_model=DatasourceTestResult)
async def test_datasource(ds_id: int, session: DbSession, admin: AdminUser) -> DatasourceTestResult:
    """测一个已经保存的账号。"""
    ds = await _get(session, ds_id)
    return await _run_test(_ds_kwargs(ds))


@router.get("/{ds_id}/tables", response_model=list[str])
async def list_tables(
    ds_id: int,
    session: DbSession,
    _: CurrentUser,
    keyword: str | None = Query(default=None),
) -> list[str]:
    """列出目标库里已有的表，方便挑一张作为写入目标。"""
    ds = await _get(session, ds_id)
    kwargs = _ds_kwargs(ds)

    def _run() -> list[str]:
        engine = dsn_mod.make_engine(**kwargs)
        try:
            with engine.connect() as conn:
                if kwargs["db_type"] == dsn_mod.DB_TYPE_SQLSERVER:
                    sql = text(
                        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
                    )
                else:
                    sql = text(
                        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME"
                    )
                return [str(row[0]) for row in conn.execute(sql).all()]
        finally:
            engine.dispose()

    try:
        tables = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"读表清单失败：{exc}") from exc

    if keyword:
        text_ = keyword.strip().lower()
        tables = [t for t in tables if text_ in t.lower()]
    return tables


@router.get("/{ds_id}/table", response_model=TableInfo)
async def inspect_table(
    ds_id: int, session: DbSession, _: CurrentUser, name: str = Query(min_length=1)
) -> TableInfo:
    ds = await _get(session, ds_id)
    kwargs = _ds_kwargs(ds)
    dialect = dsn_mod.DB_TYPE_SQLSERVER

    def _run() -> TableInfo:
        from app.services.loader.ddl import existing_columns
        from app.services.loader.dialects import dialect_for

        engine = dsn_mod.make_engine(**kwargs)
        try:
            with engine.connect() as conn:
                columns = existing_columns(conn, dialect_for(kwargs["db_type"]), name) or {}
                count = None
                if columns:
                    quoted = dialect_for(kwargs["db_type"]).quote(name)
                    try:
                        count = int(conn.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar() or 0)
                    except Exception:  # noqa: BLE001 — 行数只是参考
                        count = None
        finally:
            engine.dispose()
        return TableInfo(name=name, columns=list(columns), column_types=columns, row_count=count)

    try:
        info = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"读表结构失败：{exc}") from exc
    if not info.columns and dialect:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"目标库里没有表 {name}")
    return info


@router.get("/{ds_id}/table/rows")
async def table_rows(
    ds_id: int,
    session: DbSession,
    _: CurrentUser,
    name: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    order_by: str | None = Query(default=None),
    desc: bool = Query(default=True),
    filter_column: str | None = Query(default=None),
    filter_value: str | None = Query(default=None),
) -> dict:
    "翻一张表里的实际数据。"
    ds = await _get(session, ds_id)
    kwargs = _ds_kwargs(ds)

    def _run() -> dict:
        from sqlalchemy import inspect as sa_inspect

        from app.services.loader.dialects import dialect_for

        dialect = dialect_for(kwargs["db_type"])
        engine = dsn_mod.make_engine(**kwargs)
        try:
            with engine.connect() as conn:
                columns = [c["name"] for c in sa_inspect(conn).get_columns(name)]
                if not columns:
                    return {"columns": [], "rows": [], "total": 0}

                quoted = dialect.quote(name)

                where: str | None = None
                params: dict = {"off": offset, "lim": limit}
                if filter_column and filter_value and filter_column in columns:
                    where = f"{dialect.as_text(filter_column)} LIKE :flt"
                    params["flt"] = f"%{filter_value}%"

                count_sql = f"SELECT COUNT(*) FROM {quoted}"
                if where:
                    count_sql += f" WHERE {where}"
                total = int(conn.execute(text(count_sql), params).scalar() or 0)

                order_column = order_by if (order_by and order_by in columns) else columns[0]
                paged = conn.execute(
                    text(dialect.select_page_sql(name, order_column=order_column, desc=desc, where=where)),
                    params,
                )
                keys = list(paged.keys())
                rows = [[str(v) if v is not None else None for v in record] for record in paged.fetchall()]
            return {"columns": keys or columns, "rows": rows, "total": total}
        finally:
            engine.dispose()

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"读表数据失败：{exc}") from exc
