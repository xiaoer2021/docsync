"""执行历史：列表、详情、实时日志、取消。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.mask import mask_text
from app.models.run import (
    RUN_CANCELED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_STATUS_LABELS,
    TRIGGER_LABELS,
    DdRun,
    DdRunIssue,
    DdRunLog,
)
from app.models.task import DdTask
from app.schemas.sync import RunDetail, RunOut
from app.services import audit
from app.services.runner.logbus import read_stream
from app.services.runner.manager import manager

router = APIRouter(prefix="/runs", tags=["runs"])


def _public_log(content: str) -> str:
    if "[parameters:" in content.lower() or "[sql:" in content.lower():
        return "数据库错误详情包含批量参数，已隐藏；请查看上方错误摘要。"
    return mask_text(content)


def _to_out(run: DdRun, *, task_name: str | None = None) -> RunOut:
    error_message = run.error_message
    if error_message and ("[parameters:" in error_message.lower() or "[sql:" in error_message.lower()):
        error_message = "数据库写入失败；历史错误包含批量参数，已隐藏。请检查目标表列类型和约束。"
    elif error_message:
        error_message = mask_text(error_message)[:500]
    return RunOut(
        id=run.id,
        task_id=run.task_id,
        task_name=task_name,
        trigger_type=run.trigger_type,
        trigger_label=TRIGGER_LABELS.get(run.trigger_type, run.trigger_type),
        status=run.status,
        status_label=(
            "发现异常"
            if run.dry_run and run.status == "partial"
            else RUN_STATUS_LABELS.get(run.status, run.status)
        ),
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        rows_read=run.rows_read,
        rows_written=run.rows_written,
        rows_inserted=run.rows_inserted,
        rows_updated=run.rows_updated,
        rows_unchanged=run.rows_unchanged,
        rows_failed=run.rows_failed,
        batches=run.batches,
        dry_run=run.dry_run,
        row_limit=run.row_limit,
        error_type=run.error_type,
        error_message=error_message,
        stats=run.stats,
    )


async def _task_names(session: DbSession, task_ids: list[int]) -> dict[int, str]:
    if not task_ids:
        return {}
    rows = await session.execute(select(DdTask.id, DdTask.name).where(DdTask.id.in_(task_ids)))
    return {int(i): str(n) for i, n in rows.all()}


@router.get("")
async def list_runs(
    session: DbSession,
    _: CurrentUser,
    task_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=500),
) -> dict:
    "执行记录，带总数和分页。"
    from sqlalchemy import func

    conditions = []
    if task_id is not None:
        conditions.append(DdRun.task_id == task_id)
    if status_filter:
        conditions.append(DdRun.status == status_filter)

    count_stmt = select(func.count()).select_from(DdRun)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(await session.scalar(count_stmt) or 0)

    stmt = select(DdRun)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(DdRun.id.desc()).offset(offset).limit(limit)

    runs = list((await session.scalars(stmt)).all())
    names = await _task_names(session, [r.task_id for r in runs])
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_to_out(r, task_name=names.get(r.task_id)) for r in runs],
    }


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: int, session: DbSession, _: CurrentUser) -> RunDetail:
    run = await session.get(DdRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "执行记录不存在")

    names = await _task_names(session, [run.task_id])
    base = _to_out(run, task_name=names.get(run.task_id))

    live: list[str] = []
    from app.services.runner.logbus import hub

    backlog = hub._backlog.get(run_id) or []  # noqa: SLF001 — 只读快照，故意的

    if hub and backlog and manager.is_run_running(run_id):
        live = list(backlog)

    logs = (
        await session.scalars(
            select(DdRunLog.content).where(DdRunLog.run_id == run_id).order_by(DdRunLog.seq)
        )
    ).all()

    issues = (await session.scalars(select(DdRunIssue).where(DdRunIssue.run_id == run_id).limit(200))).all()

    return RunDetail(
        **base.model_dump(),
        logs=[_public_log(line) for line in [*(logs or []), *live][-500:]],
        issues=[
            {
                "row_no": i.row_no,
                "column": i.column,
                "reason": i.reason,
                "raw": i.raw,
            }
            for i in issues
        ],
    )


@router.get("/{run_id}/log/stream")
async def stream_log(run_id: int, request: Request, _: CurrentUser):
    "实时日志（SSE）。"
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        run = await session.get(DdRun, run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "执行记录不存在")

    async def event_source():
        if not manager.is_run_running(run_id):
            async with SessionLocal() as session:
                rows = (
                    await session.scalars(
                        select(DdRunLog.content).where(DdRunLog.run_id == run_id).order_by(DdRunLog.seq)
                    )
                ).all()
            for line in rows or []:
                yield {"event": "log", "data": _public_log(line)}
            yield {"event": "end", "data": "done"}
            return

        async for line in read_stream(run_id):
            if await request.is_disconnected():
                break
            yield {"event": "log", "data": _public_log(line)}
        yield {"event": "end", "data": "done"}

    return EventSourceResponse(event_source())


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request, session: DbSession, admin: AdminUser) -> dict[str, str]:
    run = await session.get(DdRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "执行记录不存在")
    if run.status not in (RUN_QUEUED, RUN_RUNNING):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这次执行已经结束了")

    run.cancel_requested = True

    if run.status == RUN_QUEUED and not manager.is_run_running(run_id):
        run.status = RUN_CANCELED

    audit.record(
        session,
        user=admin,
        action="cancel",
        target_type="dd_run",
        target_id=run_id,
        summary=f"取消执行 #{run_id}",
        request=request,
    )
    return {"status": "ok"}
