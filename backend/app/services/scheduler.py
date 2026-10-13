"定时调度。"

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.app import DdApp
from app.models.run import RUN_QUEUED, TRIGGER_SCHEDULE, DdRun
from app.models.task import TASK_ENABLED, DdTask
from app.services.runner.manager import manager
from app.services.schedule_rules import next_after, next_watch

logger = logging.getLogger(__name__)


async def apply_schedule(session, task: DdTask, *, now: dt.datetime | None = None) -> None:
    "按任务当前的调度配置，把 ``next_run_at`` 重排一次。"
    now = now or dt.datetime.now()
    if task.status != TASK_ENABLED:
        task.next_run_at = None
        return
    task.next_run_at = next_after(task.schedule, now)


class Scheduler:
    """后台循环：到点了就把任务丢进执行队列。"""

    def __init__(self) -> None:
        self._job: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        "调度器在不在跑。界面上要能看到 —— 它挂了任务就永远不会自动跑，"
        return self._job is not None and not self._job.done()

    async def start(self) -> None:
        if not (settings.scheduler_enabled and settings.embedded_scheduler):
            logger.info("调度器已关闭（DOCSYNC_SCHEDULER_ENABLED / EMBEDDED_SCHEDULER）")
            return
        if self._job is not None and not self._job.done():
            return
        self._stopping.clear()
        self._job = asyncio.create_task(self._loop(), name="docsync-scheduler")
        logger.info("调度器已启动，每 %s 秒检查一次", settings.scheduler_tick_seconds)

    async def stop(self) -> None:
        self._stopping.set()
        if self._job is not None:
            self._job.cancel()
            await asyncio.gather(self._job, return_exceptions=True)
            self._job = None
        logger.info("调度器已停止")

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — 一轮出错不能让调度器整个死掉
                logger.exception("调度检查出错，下一轮继续")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(settings.scheduler_tick_seconds, 5))
            except asyncio.TimeoutError:
                pass

    async def tick(self, *, now: dt.datetime | None = None) -> int:
        """捞一次该跑的任务，返回这次起了几个。"""
        now = now or dt.datetime.now()
        fired = await self._tick_tasks(now)
        await self._tick_doc_watch(now)
        return fired

    async def _tick_doc_watch(self, now: dt.datetime) -> None:
        "到点的文档做一次「自动检测」：重新读子表清单 + 勾了的那几张查列。"
        from app.models.doc import DdDoc

        async with SessionLocal() as session:
            due = (
                (
                    await session.execute(
                        select(DdDoc)
                        .where(
                            DdDoc.watch_enabled.is_(True),
                            DdDoc.next_watch_at.is_not(None),
                            DdDoc.next_watch_at <= now,
                        )
                        .limit(10)
                    )
                )
                .scalars()
                .all()
            )
            if not due:
                return

            from app.services import doc_registry

            for doc in due:
                doc.next_watch_at = next_watch(doc, now) or (now + dt.timedelta(days=1))
                try:
                    app = await session.get(DdApp, doc.app_id)
                    if app is None or app.status != "enabled":
                        continue
                    from app.core.crypto import app_secret_of

                    secret = app_secret_of(app.app_secret_enc)

                    result = await doc_registry.probe_and_store(session, doc, app, secret=secret)

                    columns_changed = 0
                    if result.ok and (app.platform or "dingtalk") == "dingtalk":
                        from app.services.dingtalk.client import DingTalkClient

                        client = DingTalkClient(
                            app_id=app.id,
                            app_key=app.app_key,
                            app_secret=secret,
                            operator_id=doc.operator_union_id or app.default_operator_union_id,
                        )
                        columns_changed = await doc_registry.check_columns_for(session, doc, client)
                    elif result.ok:
                        columns_changed = await doc_registry.check_columns_for_any(
                            session, doc, app, secret=secret
                        )
                    logger.info(
                        "自动检测「%s」：%s 个子表%s",
                        doc.name,
                        len(result.sub_items),
                        f"，{columns_changed} 张表列有变化" if columns_changed else "",
                    )
                except Exception:  # noqa: BLE001 — 一份文档读不到不该影响其它文档
                    logger.exception("自动检测「%s」失败", doc.name)
            await session.commit()

    async def _tick_tasks(self, now: dt.datetime) -> int:
        """到点的同步任务派活，返回这次起了几个。"""
        fired = 0

        async with SessionLocal() as session:
            due = (
                (
                    await session.execute(
                        select(DdTask)
                        .where(
                            DdTask.status == TASK_ENABLED,
                            DdTask.next_run_at.is_not(None),
                            DdTask.next_run_at <= now,
                        )
                        .order_by(DdTask.next_run_at)
                        .limit(20)
                    )
                )
                .scalars()
                .all()
            )

            for task in due:
                if manager.is_task_running(task.id):
                    task.next_run_at = next_after(task.schedule, now)
                    continue

                run = DdRun(
                    task_id=task.id,
                    trigger_type=TRIGGER_SCHEDULE,
                    status=RUN_QUEUED,
                    queued_at=now,
                )
                session.add(run)
                await session.flush()

                task.next_run_at = next_after(task.schedule, now)
                manager.spawn(run.id, task.id)
                fired += 1
                logger.info("定时触发「%s」（下次 %s）", task.name, task.next_run_at or "不再自动跑")

            await session.commit()

        return fired

    async def sync_all(self) -> int:
        "把所有「该自动跑但没排上时间」的都补上。启动时调一次。"
        from app.models.doc import DdDoc

        now = dt.datetime.now()
        fixed = 0

        async with SessionLocal() as session:
            tasks = (
                (
                    await session.execute(
                        select(DdTask).where(DdTask.status == TASK_ENABLED, DdTask.next_run_at.is_not(None))
                    )
                )
                .scalars()
                .all()
            )
            for task in tasks:
                fresh = next_after(task.schedule, now)
                if fresh != task.next_run_at:
                    task.next_run_at = fresh
                    fixed += 1

            docs = (await session.execute(select(DdDoc).where(DdDoc.watch_enabled.is_(True)))).scalars().all()
            for doc in docs:
                if doc.next_watch_at is None:
                    doc.next_watch_at = next_watch(doc, now) or (now + dt.timedelta(days=1))
                    fixed += 1

            await session.commit()

        return fixed


scheduler = Scheduler()
