"""同步任务：配置、试跑、自检、克隆。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.crypto import decrypt_secret
from app.models.app import DOC_TYPE_LABELS, DdApp
from app.models.datasource import DdDatasource
from app.models.doc import DdDoc, DdDocSheet
from app.models.docgroup import DdDocGroup
from app.models.run import (
    TRIGGER_LABELS,
    TRIGGER_MANUAL,
    DdRun,
)
from app.models.task import (
    SCHEDULE_MANUAL,
    TASK_ENABLED,
    TASK_PAUSED,
    WRITE_MODE_LABELS,
    WRITE_UPSERT,
    DdTask,
)
from app.schemas.sync import (
    CheckResult,
    CheckStep,
    PlanResult,
    TaskClone,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.services import audit
from app.services.dingtalk.aitable_reader import iter_records, list_fields
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.dingtalk.sheet_reader import a1_address, iter_rows, read_range
from app.services.loader import dsn as dsn_mod
from app.services.loader.ddl import existing_columns, plan_table
from app.services.loader.dialects import dialect_for
from app.services.normalize.coercions import infer_transform, infer_type
from app.services.normalize.headers import normalize_headers
from app.services.runner.manager import manager
from app.services.runner.safety import validate_quality_policy
from app.services.schedule_rules import schedule_label, validate_schedule
from app.services.scheduler import apply_schedule
from app.services.sources import SourceError
from app.services.sources import preview_source as source_preview

router = APIRouter(prefix="/tasks", tags=["tasks"])

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TAG = {
    "doc": "",
    "sheet": "",
    "row": "来源行号",
    "fingerprint": "数据指纹",
    "last_synced": "最后同步时间",
}


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "_", text).strip("_")
    return cleaned[:48] or "task"


async def _unique_code(session: DbSession, base: str) -> str:
    stem = _slug(base)
    code = stem
    index = 1
    while await session.scalar(select(DdTask.id).where(DdTask.code == code)):
        index += 1
        code = f"{stem}_{index}"
    return code


async def _assert_sheet_free(session: DbSession, doc_id: int, sheet_id: str) -> None:
    "这个子表还没被占。主表被别人建过、或已经被合并进别的任务，都要拦。"
    owner = await session.scalar(select(DdTask).where(DdTask.doc_id == doc_id, DdTask.sheet_id == sheet_id))
    if owner is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"这个子表已经配过同步任务（{owner.name}）")

    others = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc_id))).all())
    for task in others:
        merged = [str(s) for s in ((task.source_config or {}).get("merge_sheet_ids") or [])]
        if sheet_id in merged:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"这个子表已经被「{task.name}」合并进去了，不要再单独建任务",
            )


async def _get_task(session: DbSession, task_id: int) -> DdTask:
    task = await session.get(DdTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return task


PREVIEW_SAMPLE_ROWS = 50


async def _app_and_secret(session: DbSession, doc: DdDoc) -> tuple[DdApp, str]:
    "文档归属的应用 + 明文 AppSecret，给 ``preview_source`` 用。"
    app = await session.get(DdApp, doc.app_id)
    if app is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这份文档关联的应用已被删除")
    from app.core.crypto import app_secret_of

    try:
        return app, app_secret_of(app.app_secret_enc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "应用的 AppSecret 解不开，去应用页重填一次") from exc


async def _client_for_doc(session: DbSession, doc: DdDoc) -> DingTalkClient:
    "造一个钉钉客户端。"
    app = await session.get(DdApp, doc.app_id)
    if app is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这份文档关联的应用已被删除")
    platform = app.platform or "dingtalk"
    if platform != "dingtalk":
        from app.services.sources import platform_label

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"这个功能暂时只支持钉钉，{platform_label(platform)}的还没做。",
        )
    try:
        secret = str(decrypt_secret(app.app_secret_enc).get("app_secret") or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "应用的 AppSecret 解不开，去应用页重填一次") from exc
    if not secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "应用没有 AppSecret")
    return DingTalkClient(
        app_id=app.id,
        app_key=app.app_key,
        app_secret=secret,
        operator_id=doc.operator_union_id or app.default_operator_union_id,
    )


async def _to_out(session: DbSession, task: DdTask) -> TaskOut:
    doc = await session.get(DdDoc, task.doc_id)
    ds_name = None
    ds_id = (task.target or {}).get("datasource_id")
    if ds_id:
        ds = await session.get(DdDatasource, int(ds_id))
        ds_name = ds.name if ds else None
    group_name = None
    if task.group_id:
        group = await session.get(DdDocGroup, task.group_id)
        group_name = group.name if group else None

    merged_ids = [str(s) for s in ((task.source_config or {}).get("merge_sheet_ids") or []) if s]
    merge_sheet_names: list[str] = []
    if merged_ids:
        rows = (
            await session.execute(
                select(DdDocSheet.sheet_id, DdDocSheet.sheet_name).where(
                    DdDocSheet.doc_id == task.doc_id, DdDocSheet.sheet_id.in_(merged_ids)
                )
            )
        ).all()
        names = {r[0]: r[1] for r in rows}

        merge_sheet_names = [names.get(sid, sid) for sid in merged_ids]

    return TaskOut(
        id=task.id,
        code=task.code,
        name=task.name,
        doc_id=task.doc_id,
        doc_name=doc.name if doc else None,
        doc_type=DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type) if doc else None,
        sheet_id=task.sheet_id,
        sheet_name=task.sheet_name,
        engine=task.engine,
        group_id=task.group_id,
        group_name=group_name,
        source_config=task.source_config,
        columns=task.columns,
        dedupe=task.dedupe,
        target=task.target,
        target_table=task.target_table,
        write_mode=WRITE_MODE_LABELS.get(task.write_mode, task.write_mode),
        datasource_name=ds_name,
        post_actions=task.post_actions,
        schedule=task.schedule,
        schedule_label=schedule_label(task.schedule),
        merge_sheet_names=merge_sheet_names,
        status=task.status,
        remark=task.remark,
        last_run_at=task.last_run_at,
        last_run_status=task.last_run_status,
        last_success_at=task.last_success_at,
        next_run_at=task.next_run_at,
        last_summary=task.last_summary,
        running=manager.is_task_running(task.id),
        created_at=task.created_at,
    )


def _default_schedule() -> dict:
    return {
        "kind": SCHEDULE_MANUAL,
        "cron_expr": "",
        "interval_sec": None,
        "timezone": "Asia/Shanghai",
        "timeout_sec": 3600,
        "max_retries": 0,
    }


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    session: DbSession,
    _: CurrentUser,
    doc_id: int | None = Query(default=None),
    datasource_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> list[TaskOut]:
    stmt = select(DdTask).order_by(DdTask.id.desc())
    if doc_id is not None:
        stmt = stmt.where(DdTask.doc_id == doc_id)
    if keyword:
        stmt = stmt.where(DdTask.name.contains(keyword.strip()))
    if datasource_id is not None:
        stmt = stmt.where(DdTask.target["datasource_id"].as_integer() == datasource_id)
    tasks = list((await session.scalars(stmt)).all())
    return [await _to_out(session, t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, session: DbSession, _: CurrentUser) -> TaskOut:
    return await _to_out(session, await _get_task(session, task_id))


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, request: Request, session: DbSession, admin: AdminUser) -> TaskOut:
    doc = await session.get(DdDoc, payload.doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文档不存在")

    await _assert_sheet_free(session, doc.id, payload.sheet_id)

    sheet_name = payload.sheet_name
    if not sheet_name:
        row = await session.scalar(
            select(DdDocSheet).where(DdDocSheet.doc_id == doc.id, DdDocSheet.sheet_id == payload.sheet_id)
        )
        sheet_name = row.sheet_name if row else None

    target_in = dict(payload.target or {})
    target_in.setdefault("source_tag", DEFAULT_SOURCE_TAG)
    quality_problem = validate_quality_policy(payload.columns, target_in)
    if quality_problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, quality_problem)

    task = DdTask(
        name=payload.name,
        code=await _unique_code(session, payload.name),
        doc_id=doc.id,
        sheet_id=payload.sheet_id,
        sheet_name=sheet_name,
        engine=payload.engine or doc.doc_type,
        group_id=doc.group_id,
        source_config=payload.source_config,
        columns=payload.columns,
        dedupe=payload.dedupe,
        target=target_in,
        post_actions=payload.post_actions,
        schedule=payload.schedule or _default_schedule(),
        remark=payload.remark,
    )
    session.add(task)
    await session.flush()

    await apply_schedule(session, task)

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_task",
        target_id=task.id,
        summary=f"新建同步任务 {task.name}",
        request=request,
    )
    return await _to_out(session, task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int, payload: TaskUpdate, request: Request, session: DbSession, admin: AdminUser
) -> TaskOut:
    task = await _get_task(session, task_id)
    quality_problem = validate_quality_policy(
        payload.columns if payload.columns is not None else task.columns,
        payload.target if payload.target is not None else task.target,
    )
    if quality_problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, quality_problem)

    if payload.name is not None:
        task.name = payload.name
    if payload.source_config is not None:
        task.source_config = payload.source_config
    if payload.columns is not None:
        task.columns = payload.columns
    if payload.dedupe is not None:
        task.dedupe = payload.dedupe
    if payload.target is not None:
        task.target = payload.target
    if payload.post_actions is not None:
        task.post_actions = payload.post_actions
    if payload.schedule is not None:
        problem = validate_schedule(payload.schedule)
        if problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
        task.schedule = payload.schedule
    if payload.status is not None:
        if payload.status not in (TASK_ENABLED, TASK_PAUSED):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是 enabled 或 paused")
        task.status = payload.status
    if payload.remark is not None:
        task.remark = payload.remark

    await apply_schedule(session, task)

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_task",
        target_id=task.id,
        summary=f"修改同步任务 {task.name}",
        request=request,
    )
    return await _to_out(session, task)


@router.delete("/{task_id}")
async def delete_task(task_id: int, request: Request, session: DbSession, admin: AdminUser) -> dict[str, str]:
    task = await _get_task(session, task_id)
    if manager.is_task_running(task.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "任务正在跑，等它结束再删")

    name = task.name

    from sqlalchemy import delete, select

    from app.models.run import DdRun, DdRunAction, DdRunIssue, DdRunLog

    run_ids = list((await session.execute(select(DdRun.id).where(DdRun.task_id == task_id))).scalars())
    if run_ids:
        for model in (DdRunLog, DdRunAction, DdRunIssue):
            await session.execute(delete(model).where(model.run_id.in_(run_ids)))
        await session.execute(delete(DdRun).where(DdRun.id.in_(run_ids)))

    await session.delete(task)
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_task",
        target_id=task_id,
        summary=f"删除同步任务 {name}（连同 {len(run_ids)} 条执行记录）",
        request=request,
    )
    return {"status": "ok"}


@router.post("/{task_id}/clone", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def clone_task(
    task_id: int, payload: TaskClone, request: Request, session: DbSession, admin: AdminUser
) -> TaskOut:
    """把配置复制到同一文档的另一个子表 —— 一份文档多个 sheet 时靠这个铺开。"""
    src = await _get_task(session, task_id)
    await _assert_sheet_free(session, src.doc_id, payload.sheet_id)

    sheet_name = payload.sheet_name
    if not sheet_name:
        row = await session.scalar(
            select(DdDocSheet).where(DdDocSheet.doc_id == src.doc_id, DdDocSheet.sheet_id == payload.sheet_id)
        )
        sheet_name = row.sheet_name if row else None

    target = dict(src.target or {})
    if payload.table_name:
        target["table_name"] = payload.table_name
    target["source_tag"] = target.get("source_tag") or DEFAULT_SOURCE_TAG

    name = payload.name or f"{src.name} - {sheet_name or payload.sheet_id}"
    task = DdTask(
        name=name,
        code=await _unique_code(session, name),
        doc_id=src.doc_id,
        sheet_id=payload.sheet_id,
        sheet_name=sheet_name,
        engine=src.engine,
        template_id=src.template_id,
        group_id=src.group_id,
        source_config=dict(src.source_config or {}),
        columns=[dict(c) for c in (src.columns or [])],
        dedupe=dict(src.dedupe or {}) or None,
        target=target,
        post_actions=[dict(a) for a in (src.post_actions or [])] or None,
        schedule=dict(src.schedule or _default_schedule()),
    )
    session.add(task)
    await session.flush()

    await apply_schedule(session, task)

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_task",
        target_id=task.id,
        summary=f"从任务 {src.name} 克隆出 {task.name}",
        request=request,
    )
    return await _to_out(session, task)


@router.post("/quick", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def quick_create(
    payload: TaskCreate, request: Request, session: DbSession, admin: AdminUser
) -> TaskOut:
    "读一次表头就自动配好：每个源列按同名映射到目标列，类型从样例值推断。"
    doc = await session.get(DdDoc, payload.doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文档不存在")
    target = payload.target or {}
    if not target.get("datasource_id") or not target.get("table_name"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "要选目标库和表名")
    target.setdefault("write_mode", WRITE_UPSERT)

    cfg = payload.source_config or {}
    preview_app, preview_secret = await _app_and_secret(session, doc)

    try:
        preview = await source_preview(
            preview_app,
            doc,
            secret=preview_secret,
            sheet_id=payload.sheet_id,
            cfg=cfg,
            limit=PREVIEW_SAMPLE_ROWS,
        )
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    header = preview.header
    samples = preview.samples
    engine = preview.engine

    if engine == "aitable":
        source_config = {"fields": header}
    else:
        header_row = int(cfg.get("header_row") or 1)
        source_config = {
            "header_row": header_row,
            "data_start_row": int(cfg.get("data_start_row") or header_row + 1),
            "col_start": str(cfg.get("col_start") or "A"),
            "col_end": str(cfg.get("col_end") or "Z"),
        }

    columns = [
        {
            "source": name,
            "target": name,
            "type": infer_type(samples[index]) if index < len(samples) else "text",
            "transform": infer_transform(samples[index]) if index < len(samples) else None,
        }
        for index, name in enumerate(header)
    ]

    if not columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这个子表没读到任何列，先确认它不是空的")

    payload.source_config = source_config
    payload.columns = columns
    payload.engine = payload.engine or engine
    payload.target = {**target, "source_tag": target.get("source_tag") or DEFAULT_SOURCE_TAG}

    if not payload.sheet_name:
        row = await session.scalar(
            select(DdDocSheet).where(DdDocSheet.doc_id == doc.id, DdDocSheet.sheet_id == payload.sheet_id)
        )
        payload.sheet_name = row.sheet_name if row else None

    return await create_task(payload, request, session, admin)


@router.post("/{task_id}/run", response_model=dict)
async def run_task(
    task_id: int,
    session: DbSession,
    admin: AdminUser,
    dry_run: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=100000),
) -> dict:
    task = await _get_task(session, task_id)
    if task.status != TASK_ENABLED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "任务已停用")
    if manager.is_task_running(task.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "这个任务正在跑，等它结束")

    run = DdRun(
        task_id=task.id,
        trigger_type=dry_run and "check" or TRIGGER_MANUAL,
        status="queued",
        dry_run=dry_run,
        row_limit=limit,
        triggered_by=admin.id,
    )
    session.add(run)
    await session.flush()
    run_id = run.id
    await session.commit()

    manager.spawn(run_id, task.id, dry_run=dry_run, row_limit=limit)
    return {"run_id": run_id, "trigger": TRIGGER_LABELS.get(run.trigger_type, ""), "dry_run": dry_run}


@router.post("/{task_id}/plan", response_model=PlanResult)
async def plan_task(task_id: int, session: DbSession, _: CurrentUser) -> PlanResult:
    """干跑：算出会执行哪些 DDL、目标表现状、映射了哪些列。不写数据。"""
    task = await _get_task(session, task_id)
    target = task.target or {}
    ds_id = target.get("datasource_id")
    table = task.target_table
    if not ds_id or not table:
        return PlanResult(ok=False, message="还没选目标库或表名")

    ds = await session.get(DdDatasource, int(ds_id))
    if ds is None:
        return PlanResult(ok=False, message="目标库已被删除")

    columns = {
        str(c.get("target")): str(c.get("type") or "text") for c in (task.columns or []) if c.get("target")
    }
    tag = {**DEFAULT_SOURCE_TAG, **(target.get("source_tag") or {})}
    for value in tag.values():
        if value:
            columns.setdefault(value, "text")

    from app.services.loader.dsn import describe

    result = PlanResult(
        table=table,
        datasource=describe(
            db_type=ds.db_type,
            host=ds.host,
            port=ds.port,
            database=ds.database,
            username=ds.username,
        ),
        mapped_columns=[
            {
                "source": str(c.get("source") or ""),
                "target": str(c.get("target") or ""),
                "type": str(c.get("type") or "text"),
            }
            for c in (task.columns or [])
        ],
    )

    try:
        secret = str(decrypt_secret(ds.password_enc).get("password") or "")

        def _run() -> None:
            engine = dsn_mod.make_engine(
                db_type=ds.db_type,
                host=ds.host,
                port=ds.port,
                database=ds.database,
                username=ds.username,
                password=secret,
                extra=ds.extra,
            )
            try:
                with engine.connect() as conn:
                    existing = existing_columns(conn, dialect_for(ds.db_type), table)
                    plan = plan_table(dialect_for(ds.db_type), table, columns, existing=existing)
                    result.will_create = plan.will_create
                    result.will_add_columns = [{"name": n, "type": t} for n, t in plan.will_add_columns]
                    result.existing_columns = plan.existing_columns
                    result.statements = plan.statements
            finally:
                engine.dispose()

        import asyncio

        await asyncio.to_thread(_run)
        result.ok = True
        result.message = (
            "表不存在，会先建表"
            if result.will_create
            else (f"会补 {len(result.will_add_columns)} 个列" if result.will_add_columns else "表结构已就绪")
        )
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.message = f"读目标表失败：{type(exc).__name__}"
    return result


@router.post("/{task_id}/check", response_model=CheckResult)
async def check_task(task_id: int, session: DbSession, _: CurrentUser) -> CheckResult:
    """自检：钉钉能不能读、目标库能不能连、结构对不对得上。"""
    task = await _get_task(session, task_id)
    doc = await session.get(DdDoc, task.doc_id)
    steps: list[CheckStep] = []

    if doc is None:
        return CheckResult(ok=False, steps=[CheckStep(name="文档", ok=False, message="文档已被删除")])

    try:
        app, secret = await _app_and_secret(session, doc)
        from app.services.sources import probe_source

        probe = await probe_source(app, doc, secret=secret, doc_type_hint=doc.doc_type)
        if not probe.ok:
            steps.append(CheckStep(name="源文档可读", ok=False, message=probe.error or "读不到源文档"))
        elif task.sheet_id in {item.id for item in probe.sub_items}:
            steps.append(CheckStep(name="源文档可读", ok=True, message="子表还在"))
        else:
            steps.append(
                CheckStep(
                    name="源文档可读",
                    ok=False,
                    message="读到了文档，但里面已经没有这个子表了 —— 可能被删或改名",
                    hint="去文档管理展开这份文档、点「重新读取」，再用新子表重建任务",
                )
            )
    except SourceError as exc:
        steps.append(CheckStep(name="源文档可读", ok=False, message=exc.message, hint=exc.hint))
    except HTTPException as exc:
        steps.append(CheckStep(name="源文档可读", ok=False, message=str(exc.detail)))

    target = task.target or {}
    ds_id = target.get("datasource_id")
    if not ds_id:
        steps.append(CheckStep(name="目标库", ok=False, message="还没选目标库"))
    else:
        ds = await session.get(DdDatasource, int(ds_id))
        if ds is None:
            steps.append(CheckStep(name="目标库", ok=False, message="目标库已被删除"))
        else:
            try:
                secret = str(decrypt_secret(ds.password_enc).get("password") or "")
                engine = dsn_mod.make_engine(
                    db_type=ds.db_type,
                    host=ds.host,
                    port=ds.port,
                    database=ds.database,
                    username=ds.username,
                    password=secret,
                    extra=ds.extra,
                )
                try:
                    with engine.connect() as conn:
                        existing = existing_columns(conn, dialect_for(ds.db_type), task.target_table)
                finally:
                    engine.dispose()
                steps.append(
                    CheckStep(
                        name="目标库可连",
                        ok=True,
                        message=f"{ds.name} · {task.target_table}"
                        + ("（表还不存在，首次运行会建）" if existing is None else "（表已存在）"),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                steps.append(
                    CheckStep(
                        name="目标库可连",
                        ok=False,
                        message=f"{type(exc).__name__}: {exc}",
                        hint="用「目标库」页的测试连接排查；确认这台机器能连到目标库。",
                    )
                )

    problems: list[str] = []
    if not task.columns:
        problems.append("没配字段映射")
    if not task.target_table:
        problems.append("没填目标表名")
    if (target.get("write_mode") or WRITE_UPSERT) == WRITE_UPSERT and not target.get("key_columns"):
        problems.append("按主键更新但没指定主键列")
    if problems:
        steps.append(CheckStep(name="任务配置", ok=False, message="；".join(problems)))
    else:
        steps.append(CheckStep(name="任务配置", ok=True, message="配置完整"))

    return CheckResult(ok=all(s.ok for s in steps), steps=steps)


from app.services.sources.preview_util import display_rows as _display_rows  # noqa: E402
from app.services.sources.preview_util import format_grid as _format_grid  # noqa: E402
from app.services.sources.preview_util import profiles as _profiles  # noqa: E402

INFER_ROWS = 200

MAX_PREVIEW_ROWS = 500

DISPLAY_ROWS = 200


async def _feishu_rows_preview(
    app: DdApp,
    doc: DdDoc,
    sheet_id: str,
    cfg: dict,
    rows_wanted: int,
    merge_ids: list[str],
    sheet_names: dict[str, str],
    *,
    secret: str,
) -> dict:
    "飞书的数据预览。"
    from app.services.feishu.client import FeishuClient
    from app.services.feishu.preview import preview_rows_feishu

    client = FeishuClient(app_id=app.id, app_key=app.app_key, app_secret=secret)
    return await preview_rows_feishu(
        client,
        node_id=doc.node_id,
        doc_type=doc.doc_type,
        sheet_id=sheet_id,
        cfg=cfg,
        rows_wanted=rows_wanted,
        merge_ids=merge_ids,
        sheet_names=sheet_names,
    )


async def _webflow_rows_preview(
    app: DdApp,
    doc: DdDoc,
    sheet_id: str,
    cfg: dict,
    rows_wanted: int,
    sheet_names: dict[str, str],
) -> dict:
    "WPS 个人版（网页取数）的数据预览。"
    from app.services.webflow.preview import preview_rows_webflow

    return await preview_rows_webflow(
        app, doc, sheet_id=sheet_id, cfg=cfg, limit=rows_wanted, sheet_names=sheet_names
    )


@router.post("/preview", response_model=dict)
async def preview_source(payload: dict, session: DbSession, _: CurrentUser) -> dict:
    "预览。给界面三样东西："
    doc_id = int(payload.get("doc_id") or 0)
    sheet_id = str(payload.get("sheet_id") or "")
    cfg = payload.get("source_config") or {}
    rows_wanted = min(int(payload.get("rows") or DISPLAY_ROWS), MAX_PREVIEW_ROWS)
    merge_ids = [str(s) for s in (payload.get("merge_sheet_ids") or []) if s]

    doc = await session.get(DdDoc, doc_id)
    if doc is None or not sheet_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "要提供文档和子表")

    cache_key = _preview_key(doc.id, sheet_id, cfg, rows_wanted, merge_ids)

    if not payload.get("refresh"):
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    name_rows = (
        await session.execute(
            select(DdDocSheet.sheet_id, DdDocSheet.sheet_name).where(
                DdDocSheet.doc_id == doc.id,
                DdDocSheet.sheet_id.in_([sheet_id, *merge_ids]),
            )
        )
    ).all()
    sheet_names = {r[0]: r[1] for r in name_rows}

    preview_app, preview_secret = await _app_and_secret(session, doc)
    platform = preview_app.platform or "dingtalk"
    if platform != "dingtalk":
        try:
            if platform == "wps":
                return await _webflow_rows_preview(preview_app, doc, sheet_id, cfg, rows_wanted, sheet_names)
            return await _feishu_rows_preview(
                preview_app,
                doc,
                sheet_id,
                cfg,
                rows_wanted,
                merge_ids,
                sheet_names,
                secret=preview_secret,
            )
        except SourceError as exc:
            base = _preview_envelope(ok=False)
            base.update({"error": exc.message, "hint": exc.hint})
            return base

    client = await _client_for_doc(session, doc)
    try:
        result = await asyncio.wait_for(
            _do_preview(client, doc, sheet_id, cfg, rows_wanted, merge_ids, sheet_names),
            timeout=PREVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        base = _preview_envelope(ok=False)
        base.update(
            {
                "error": f"读钉钉超过 {PREVIEW_TIMEOUT} 秒还没读完。",
                "hint": (
                    "多半是钉钉侧在限流或响应慢。等十几秒再点「重新读取」；"
                    "如果反复超时，把列范围（纵向）或数据列范围（横向）填小一点，"
                    "少读一些能明显变快。"
                ),
            }
        )
        return base

    _cache_put(cache_key, result)
    return result


PREVIEW_TIMEOUT = 25.0

PREVIEW_TTL = 45.0
_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}
_PREVIEW_CACHE_MAX = 200

WARM_LIMIT = 10


def _preview_key(
    doc_id: int,
    sheet_id: str,
    cfg: dict,
    rows_wanted: int,
    merge_ids: list[str],
) -> str:
    "缓存键。"
    payload = json.dumps(
        {
            "doc": doc_id,
            "sheet": sheet_id,
            "cfg": cfg,
            "rows": rows_wanted,
            "merge": sorted(merge_ids),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_get(key: str) -> dict | None:
    hit = _PREVIEW_CACHE.get(key)
    if hit is None:
        return None
    stamp, value = hit
    if time.time() - stamp > PREVIEW_TTL:
        _PREVIEW_CACHE.pop(key, None)
        return None

    return copy.deepcopy(value)


def _cache_put(key: str, value: dict) -> None:
    if not value.get("ok"):
        return
    if len(_PREVIEW_CACHE) >= _PREVIEW_CACHE_MAX:
        now = time.time()
        for stale in [k for k, (t, _) in _PREVIEW_CACHE.items() if now - t > PREVIEW_TTL]:
            _PREVIEW_CACHE.pop(stale, None)
        if len(_PREVIEW_CACHE) >= _PREVIEW_CACHE_MAX:
            oldest = min(_PREVIEW_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _PREVIEW_CACHE.pop(oldest, None)
    _PREVIEW_CACHE[key] = (time.time(), copy.deepcopy(value))


def _preview_envelope(ok: bool = True, **extra) -> dict:
    base = {
        "ok": ok,
        "header": [],
        "rows": [],
        "raw_rows": [],
        "total_preview": 0,
        "inferred_header_row": None,
        "suggested_types": [],
        "suggested_transforms": [],
        "column_stats": [],
        "raw_grid": [],
        "raw_grid_marks": [],
        "raw_origin": {"row": 1, "col": "A"},
        "raw_markers": {},
        "row_sources": [],
        "sheet_id": "",
        "sheet_name": "",
        "merged_sheet_names": [],
        "message": "",
    }
    base.update(extra)
    return base


async def _do_preview(
    client,
    doc,
    sheet_id: str,
    cfg: dict,
    rows_wanted: int,
    merge_ids: list[str],
    sheet_names: dict[str, str] | None = None,
) -> dict:
    from app.services.dingtalk.sheet_reader import read_rectangle
    from app.services.normalize.headers import infer_header_row

    def _envelope(**extra) -> dict:
        return _preview_envelope(**extra)

    async def _raw_grid(
        row_start: int,
        col_start_idx: int,
        n_rows: int = 15,
        n_cols: int = 16,
        header_rows: set[int] | None = None,
    ):
        "左上角原样读一块，给界面当「文档视图」。"
        grid = await read_rectangle(
            client,
            doc.node_id,
            sheet_id,
            row_start=row_start,
            row_end=row_start + n_rows - 1,
            col_start_index=col_start_idx,
            col_end_index=col_start_idx + n_cols - 1,
        )
        from app.services.dingtalk.sheet_reader import index_to_col

        shown, marks = _format_grid(grid, header_rows=header_rows)
        return {
            "raw_grid": shown,
            "raw_grid_marks": marks,
            "raw_origin": {"row": row_start, "col": index_to_col(col_start_idx)},
        }

    try:
        if doc.doc_type == "aitable":
            fields = await list_fields(client, doc.node_id, sheet_id)
            header = [f.name for f in fields]
            rows: list[list] = []
            async for record in iter_records(client, doc.node_id, sheet_id, limit=rows_wanted):
                rows.append([record.fields.get(name) for name in header])
            profiles = _profiles(header, rows)
            return _envelope(
                header=header,
                rows=_display_rows(header, rows, profiles),
                raw_rows=rows,
                total_preview=len(rows),
                suggested_types=[p["inferred_type"] for p in profiles],
                suggested_transforms=[p["suggested_transform"] for p in profiles],
                column_stats=profiles,
                message=f"多维表 · {len(header)} 个字段",
            )

        if str(cfg.get("orientation") or "vertical") == "matrix":
            from app.services.dingtalk.sheet_reader import read_date_matrix

            matrix = await read_date_matrix(
                client,
                doc.node_id,
                sheet_id,
                header_row=int(cfg.get("matrix_header_row") or 3),
                data_start_row=int(cfg.get("matrix_data_start_row") or 4),
                field_col=str(cfg.get("matrix_field_col") or "C"),
                date_start_col=str(cfg.get("matrix_date_start_col") or "E"),
                limit=rows_wanted,
            )
            rows = [list(row[1]) for row in matrix.rows]
            profiles = _profiles(matrix.header, rows)
            profiles[0]["inferred_type"] = "date"
            profiles[2]["inferred_type"] = "float"
            matrix_header_row = int(cfg.get("matrix_header_row") or 3)
            grid_start = max(matrix_header_row - 2, 1)
            grid = await _raw_grid(
                grid_start,
                0,
                header_rows={matrix_header_row - grid_start},
            )
            message = (
                f"日期交叉表：识别到 {matrix.date_count} 个连续日期，"
                f"显示 {len(rows)} 条日数据；汇总列不作为日期"
            )
            if matrix.formula_errors:
                message += (
                    f"；跳过 {len(matrix.formula_errors)} 个公式错误单元格，"
                    "按主键更新会保留已有值，整表重写会阻止执行"
                )
            if matrix.corrected_zero_percent:
                message += f"；{matrix.corrected_zero_percent} 个重复百分号零值已按 0 读取"
            return _envelope(
                header=matrix.header,
                rows=_display_rows(matrix.header, rows, profiles),
                raw_rows=rows,
                total_preview=len(rows),
                orientation="matrix",
                suggested_types=[p["inferred_type"] for p in profiles],
                suggested_transforms=[p["suggested_transform"] for p in profiles],
                column_stats=profiles,
                raw_markers={
                    "header_row": matrix_header_row,
                    "data_start_row": int(cfg.get("matrix_data_start_row") or 4),
                },
                message=message,
                **grid,
            )

        if str(cfg.get("orientation") or "vertical") == "horizontal":
            from app.services.dingtalk.sheet_reader import read_transposed

            pivot = await read_transposed(
                client,
                doc.node_id,
                sheet_id,
                field_col=str(cfg.get("field_col") or "A"),
                field_start_row=int(cfg.get("field_start_row") or 0),
                field_end_row=int(cfg.get("field_end_row") or 0),
                data_start_col=str(cfg.get("data_start_col") or "B"),
                data_end_col=str(cfg.get("data_end_col") or ""),
                record_name_row=int(cfg.get("record_name_row") or 0),
                record_column_name=str(cfg.get("record_column_name") or "记录"),
                max_records=rows_wanted,
            )
            rows = [list(r[1]) for r in pivot.rows]
            profiles = _profiles(pivot.header, rows)
            grid_start = max(pivot.first_field_row - 2, 1)
            header_rows = {
                r - grid_start
                for r in (pivot.first_field_row, int(cfg.get("record_name_row") or 0))
                if r and r >= grid_start
            }
            grid = await _raw_grid(grid_start, 0, header_rows=header_rows)
            return _envelope(
                header=pivot.header,
                rows=_display_rows(pivot.header, rows, profiles),
                raw_rows=rows,
                total_preview=len(rows),
                orientation="horizontal",
                suggested_types=[p["inferred_type"] for p in profiles],
                suggested_transforms=[p["suggested_transform"] for p in profiles],
                column_stats=profiles,
                raw_markers={
                    "field_row": pivot.first_field_row,
                    "field_col": str(cfg.get("field_col") or "A"),
                    "extent_row": pivot.extent_row,
                },
                message=(
                    f"横向表：字段名在第 {pivot.first_field_row} 行的 "
                    f"{cfg.get('field_col') or 'A'} 列往下，一列一条记录，"
                    f"共 {len(pivot.field_names)} 个字段 · 读到 {len(rows)} 条记录"
                    + (f"；数据范围按第 {pivot.extent_row} 行判断" if pivot.extent_row else "")
                ),
                **grid,
            )

        header_row = int(cfg.get("header_row") or 0)
        col_start = str(cfg.get("col_start") or "A")
        col_end = str(cfg.get("col_end") or "Z")
        data_start = int(cfg.get("data_start_row") or 0)

        probe = await read_range(client, doc.node_id, sheet_id, a1_address(col_start, 1, col_end, 15))
        if not header_row:
            header_row = infer_header_row(probe, start_row=1)
        if not data_start:
            data_start = header_row + 1

        shown_grid, grid_marks = _format_grid(probe, header_rows={header_row - 1})

        header_address = a1_address(col_start, header_row, col_end, header_row)
        head = await read_range(client, doc.node_id, sheet_id, header_address)
        header = normalize_headers(head[0] if head else [])
        main_name = (sheet_names or {}).get(sheet_id, sheet_id)

        rows = []
        async for _, values in iter_rows(
            client,
            doc.node_id,
            sheet_id,
            start_row=data_start,
            col_start=col_start,
            col_end=col_end,
            limit=max(rows_wanted, INFER_ROWS),
        ):
            rows.append(list(values))

        from app.services.dingtalk.sheet_reader import index_to_col, is_placeholder_header

        merge_notes: list[str] = []
        row_sources = [main_name] * len(rows)
        budget = max(rows_wanted // max(len(merge_ids), 1), 20)

        warm_budget = WARM_LIMIT
        for sid in merge_ids:
            if sid == sheet_id:
                continue
            name = (sheet_names or {}).get(sid, sid)
            other = await read_range(client, doc.node_id, sid, header_address)
            other_header = normalize_headers(other[0] if other else [], width=len(header))[: len(header)]

            conflicts: list[str] = []
            blanks: list[str] = []
            for index in range(len(header)):
                mine = header[index]
                theirs = other_header[index] if index < len(other_header) else ""
                if mine == theirs:
                    continue
                if is_placeholder_header(theirs) or not theirs.strip():
                    blanks.append(f"{index_to_col(index)}({mine})")
                    continue
                if is_placeholder_header(mine) or not mine.strip():
                    blanks.append(f"{index_to_col(index)}({theirs})")
                    continue
                conflicts.append(f"第{index + 1}列「{mine}」vs「{theirs}」")

            if conflicts:
                merge_notes.append(f"「{name}」的表头跟主表对不上：" + "、".join(conflicts[:5]))
                continue
            if blanks:
                merge_notes.append(f"「{name}」第 " + "、".join(blanks[:6]) + " 列没写表头（照常合并）")

            merged: list[list] = []
            async for _, values in iter_rows(
                client,
                doc.node_id,
                sid,
                start_row=data_start,
                col_start=col_start,
                col_end=col_end,
                limit=budget,
            ):
                merged.append(list(values))
            rows.extend(merged)
            row_sources.extend([name] * len(merged))
            merge_notes.append(f"「{name}」读到 {len(merged)} 行")

            if warm_budget > 0:
                warm_budget -= 1
                warm_key = _preview_key(doc.id, sid, cfg, rows_wanted, [])
                if _cache_get(warm_key) is None:
                    try:
                        own_header = normalize_headers(other[0] if other else [])
                        own_profiles = _profiles(own_header, merged)
                        own_shown = merged[:rows_wanted]
                        own_grid = await _raw_grid(1, 0, header_rows={header_row - 1})
                        _cache_put(
                            warm_key,
                            _envelope(
                                header=own_header,
                                rows=_display_rows(own_header, own_shown, own_profiles),
                                raw_rows=own_shown,
                                sheet_id=sid,
                                sheet_name=name,
                                total_preview=len(merged),
                                inferred_header_row=header_row,
                                data_start_row=data_start,
                                suggested_types=[p["inferred_type"] for p in own_profiles],
                                suggested_transforms=[p["suggested_transform"] for p in own_profiles],
                                column_stats=own_profiles,
                                raw_markers={
                                    "header_row": header_row,
                                    "data_start_row": data_start,
                                },
                                message=(
                                    f"「{name}」自己的表头在第 {header_row} 行，" f"读到 {len(merged)} 行"
                                ),
                                **own_grid,
                            ),
                        )
                        logger.info("已预热「%s」的独立预览（key=%s）", name, warm_key[:8])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("预热「%s」的独立预览失败：%s", name, exc)

        if warm_budget <= 0 and len(merge_ids) > WARM_LIMIT:
            merge_notes.append(f"（合并子表超过 {WARM_LIMIT} 张，只预热了前 {WARM_LIMIT} 张）")

        profiles = _profiles(header, rows)
        shown_rows = rows[:rows_wanted]
        drop = [p["name"] for p in profiles if p["suggestion"] == "drop"]
        note = f"表头在第 {header_row} 行，读了 {len(rows)} 行做类型判断" + (
            f"，界面展示前 {len(shown_rows)} 行" if len(rows) > len(shown_rows) else ""
        )
        if drop:
            note += f"；{len(drop)} 列基本是空的，建议不要：" + "、".join(drop[:6])
        if merge_notes:
            note += "；" + "；".join(merge_notes)

        return _envelope(
            header=header,
            rows=_display_rows(header, shown_rows, profiles),
            raw_rows=shown_rows,
            row_sources=row_sources[: len(shown_rows)],
            sheet_id=sheet_id,
            sheet_name=main_name,
            merged_sheet_names=[n for s, n in (sheet_names or {}).items() if s != sheet_id],
            total_preview=len(rows),
            inferred_header_row=header_row,
            data_start_row=data_start,
            suggested_types=[p["inferred_type"] for p in profiles],
            suggested_transforms=[p["suggested_transform"] for p in profiles],
            column_stats=profiles,
            raw_markers={"header_row": header_row, "data_start_row": data_start},
            raw_grid=shown_grid,
            raw_grid_marks=grid_marks,
            raw_origin={"row": 1, "col": col_start.upper()},
            message=note,
        )
    except DingTalkError as exc:
        base = _preview_envelope(ok=False)
        base.update({"error": exc.message, "hint": exc.hint})
        return base
