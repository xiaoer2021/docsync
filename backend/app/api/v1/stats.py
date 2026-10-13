"概览统计。"

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.action import DdAction
from app.models.doc import DdDoc, DdDocSheet
from app.models.run import (
    RUN_FAILED,
    RUN_RUNNING,
    RUN_STATUS_LABELS,
    RUN_SUCCESS,
    TRIGGER_LABELS,
    DdRun,
)
from app.models.task import SCHEDULE_MANUAL, TASK_ENABLED, DdTask
from app.services.schedule_rules import schedule_label

router = APIRouter(prefix="/stats", tags=["stats"])

WINDOW_DAYS = 7
RECENT_RUNS = 10


@router.get("/overview")
async def overview(session: DbSession, _: CurrentUser) -> dict[str, Any]:
    now = dt.datetime.now()
    since = now - dt.timedelta(days=WINDOW_DAYS)

    doc_total = int(await session.scalar(select(func.count()).select_from(DdDoc)) or 0)
    sheet_total = int(await session.scalar(select(func.count()).select_from(DdDocSheet)) or 0)
    task_total = int(await session.scalar(select(func.count()).select_from(DdTask)) or 0)
    task_enabled = int(
        await session.scalar(select(func.count()).select_from(DdTask).where(DdTask.status == TASK_ENABLED))
        or 0
    )
    action_total = int(await session.scalar(select(func.count()).select_from(DdAction)) or 0)

    tasks = list((await session.scalars(select(DdTask))).all())

    scheduled = [
        t
        for t in tasks
        if t.status == TASK_ENABLED
        and str((t.schedule or {}).get("kind") or SCHEDULE_MANUAL) != SCHEDULE_MANUAL
        and t.next_run_at is not None
    ]
    scheduled.sort(key=lambda t: t.next_run_at or now)

    tasks_by_task_sheet = {(t.doc_id, t.sheet_id) for t in tasks}
    merged_sheets: set[tuple[int, str]] = set()
    for task in tasks:
        for sheet in (task.source_config or {}).get("merge_sheet_ids") or []:
            if sheet:
                merged_sheets.add((task.doc_id, str(sheet)))

    sheets = list(await session.scalars(select(DdDocSheet)))
    unconfigured = [
        s
        for s in sheets
        if (s.doc_id, s.sheet_id) not in tasks_by_task_sheet and (s.doc_id, s.sheet_id) not in merged_sheets
    ]

    window_runs = list(
        (await session.scalars(select(DdRun).where(DdRun.queued_at >= since).order_by(DdRun.id.desc()))).all()
    )
    ok = sum(1 for r in window_runs if r.status == RUN_SUCCESS)
    bad = sum(1 for r in window_runs if r.status in (RUN_FAILED, "timeout"))
    running = int(
        await session.scalar(select(func.count()).select_from(DdRun).where(DdRun.status == RUN_RUNNING)) or 0
    )
    window_rows = sum(r.rows_written for r in window_runs)

    recent = (await session.scalars(select(DdRun).order_by(DdRun.id.desc()).limit(RECENT_RUNS))).all()
    task_names = {t.id: t.name for t in tasks}

    failures = (
        await session.scalars(
            select(DdRun).where(DdRun.status.in_([RUN_FAILED, "timeout"])).order_by(DdRun.id.desc()).limit(5)
        )
    ).all()

    return {
        "counts": {
            "docs": doc_total,
            "sheets": sheet_total,
            "tasks": task_total,
            "tasks_enabled": task_enabled,
            "actions": action_total,
            "sheets_without_task": len(unconfigured),
            "scheduled_tasks": len(scheduled),
            "runs_running": running,
        },
        "window": {
            "days": WINDOW_DAYS,
            "runs": len(window_runs),
            "success": ok,
            "failed": bad,
            "rows_written": window_rows,
            "success_rate": round(ok / len(window_runs) * 100, 1) if window_runs else None,
        },
        "upcoming": [
            {
                "task_id": t.id,
                "name": t.name,
                "schedule_label": schedule_label(t.schedule),
                "next_run_at": t.next_run_at,
                "target_table": t.target_table,
                "write_mode": t.write_mode,
            }
            for t in scheduled[:8]
        ],
        "recent_runs": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "task_name": task_names.get(r.task_id, f"（任务 {r.task_id} 已删除）"),
                "status": r.status,
                "status_label": RUN_STATUS_LABELS.get(r.status, r.status),
                "trigger_type": r.trigger_type,
                "trigger_label": TRIGGER_LABELS.get(r.trigger_type, r.trigger_type),
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "duration_ms": r.duration_ms,
                "rows_read": r.rows_read,
                "rows_written": r.rows_written,
                "rows_inserted": r.rows_inserted,
                "rows_updated": r.rows_updated,
                "rows_unchanged": r.rows_unchanged,
                "rows_failed": r.rows_failed,
                "error_message": r.error_message,
            }
            for r in recent
        ],
        "failures": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "task_name": task_names.get(r.task_id, f"（任务 {r.task_id} 已删除）"),
                "finished_at": r.finished_at,
                "error_type": r.error_type,
                "error_message": r.error_message,
            }
            for r in failures
        ],
        "todo": _todo(len(unconfigured), len(scheduled), successes=ok, failures=bad),
    }


def _todo(unconfigured: int, scheduled: int, *, successes: int, failures: int) -> list[dict[str, str]]:
    "「接下来该干什么」——把最该处理的事顶到最前面。"
    items: list[dict[str, str]] = []
    if failures:
        items.append(
            {
                "kind": "error",
                "text": f"最近有 {failures} 次执行失败",
                "to": "/runs",
                "action": "看执行历史",
            }
        )
    if unconfigured:
        items.append(
            {
                "kind": "warn",
                "text": f"{unconfigured} 个子表还没配同步任务",
                "to": "/docs",
                "action": "去文档管理配",
            }
        )
    if not scheduled:
        items.append(
            {
                "kind": "info",
                "text": "还没有任务配定时 —— 现在都得手动点「运行」",
                "to": "/tasks",
                "action": "去配定时",
            }
        )
    if not items:
        items.append({"kind": "ok", "text": "一切正常，没有待处理的事", "to": "", "action": ""})
    return items
