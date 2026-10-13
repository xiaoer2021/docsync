"执行调度：谁在跑、能不能再跑一个。"

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from app.core.config import settings
from app.services import tunables

logger = logging.getLogger(__name__)


class RunManager:
    """跟踪正在跑的 run，并按并发上限排队。"""

    def __init__(self, max_concurrency: int | None = None) -> None:
        self._limit = max(max_concurrency or settings.worker_max_concurrency, 1)
        self._tasks: dict[int, asyncio.Task] = {}

        self._by_task: dict[int, int] = {}

        self._active = 0

    def set_limit(self, value: int) -> None:
        """改并发上限，**立刻生效**。"""
        new = max(int(value), 1)
        if new != self._limit:
            logger.info("并发上限 %s → %s", self._limit, new)
        self._limit = new

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def queue_state(self) -> dict[str, int]:
        return {
            "limit": self._limit,
            "active": self._active,
            "waiting": max(len(self._tasks) - self._active, 0),
        }

    async def _acquire(self, timeout: float) -> bool:
        """等一个名额。等到返回 True（已计数），超时返回 False。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._active >= self._limit:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False

            await asyncio.sleep(min(0.5, remaining))
        self._active += 1
        return True

    def _release(self) -> None:
        self._active = max(self._active - 1, 0)

    @property
    def running_runs(self) -> set[int]:
        return {run_id for run_id, task in self._tasks.items() if not task.done()}

    def is_task_running(self, task_id: int) -> bool:
        run_id = self._by_task.get(task_id)
        if run_id is None:
            return False
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def is_run_running(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def spawn(
        self,
        run_id: int,
        task_id: int,
        *,
        dry_run: bool = False,
        row_limit: int | None = None,
    ) -> None:
        """丢到后台跑。并发满了就排队等着 —— **但不会无限期等**。"""
        from app.services.runner.orchestrator import execute_run

        async def runner() -> None:
            state = self.queue_state
            if state["active"] >= self._limit:
                logger.info(
                    "执行 #%s 排队：现在 %s 个在执行（并发上限 %s）",
                    run_id,
                    state["active"],
                    self._limit,
                )

            if not await self._acquire(tunables.get("queue_wait_timeout_seconds")):
                minutes = tunables.get("queue_wait_timeout_seconds") // 60
                logger.error(
                    "执行 #%s 排队超过 %s 分钟仍没排上 —— 前面的执行多半卡住了",
                    run_id,
                    minutes,
                )
                await _mark_stuck(
                    run_id,
                    f"排队超过 {minutes} 分钟没排上，前面的执行卡住了。已标为超时，请重跑。",
                )
                return

            try:
                await asyncio.wait_for(
                    execute_run(run_id, dry_run=dry_run, row_limit=row_limit),
                    timeout=tunables.get("run_timeout_seconds"),
                )
            except asyncio.TimeoutError:
                minutes = tunables.get("run_timeout_seconds") // 60
                logger.error("执行 #%s 超过 %s 分钟仍未结束，已强制中止", run_id, minutes)

                await _mark_stuck(run_id, f"跑了超过 {minutes} 分钟还没结束，已强制中止。")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — execute_run 自己会记账，这里只兜底记日志
                logger.exception("执行 #%s 异常退出", run_id)
            finally:
                self._release()

        job = asyncio.create_task(runner(), name=f"docsync-run-{run_id}")
        self._tasks[run_id] = job
        self._by_task[task_id] = run_id
        job.add_done_callback(lambda _t: self._forget(run_id, task_id))

    def _forget(self, run_id: int, task_id: int) -> None:
        self._tasks.pop(run_id, None)
        if self._by_task.get(task_id) == run_id:
            self._by_task.pop(task_id, None)

    async def shutdown(self) -> None:
        pending = [t for t in self._tasks.values() if not t.done()]
        for job in pending:
            job.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.info("已停止 %s 个在跑的同步任务", len(pending))


manager = RunManager()


async def _notify(run_id: int) -> None:
    "执行到了终态就发通知 —— **哪怕这条是「被收掉的」**。"
    try:
        from app.services.actions import run_post_actions

        await run_post_actions(run_id)
    except Exception:  # noqa: BLE001 — 通知发不出去不能反过来把收尾搞崩
        logger.exception("发送执行 #%s 的后置通知失败", run_id)


async def _mark_stuck(run_id: int, message: str) -> None:
    "把一个卡住的执行标成「超时」并写上原因。"
    from app.core.db import SessionLocal
    from app.models.run import RUN_QUEUED, RUN_RUNNING, RUN_TIMEOUT, DdRun

    marked = False
    try:
        async with SessionLocal() as session:
            run = await session.get(DdRun, run_id)
            if run is None or run.status not in (RUN_QUEUED, RUN_RUNNING):
                return
            now = dt.datetime.now()
            if run.started_at is None:
                run.started_at = run.queued_at
            run.status = RUN_TIMEOUT
            run.finished_at = now
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
            run.error_message = message
            await session.commit()
            marked = True
    except Exception:  # noqa: BLE001 — 收尾失败不能反过来把调度搞崩
        logger.exception("把执行 #%s 标成超时失败", run_id)
        return

    if marked:
        await _notify(run_id)


async def reap_orphans() -> int:
    "把上次进程退出时留下的「排队中 / 运行中」标成失败，返回收掉几条。"
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models.run import RUN_FAILED, RUN_QUEUED, RUN_RUNNING, DdRun

    async with SessionLocal() as session:
        stale = (
            (await session.execute(select(DdRun).where(DdRun.status.in_([RUN_QUEUED, RUN_RUNNING]))))
            .scalars()
            .all()
        )
        if not stale:
            return 0

        now = dt.datetime.now()
        for run in stale:
            run.status = RUN_FAILED
            run.finished_at = now

            run.started_at = None
            run.duration_ms = None
            run.error_message = "平台重启，这次执行没跑完（进程重启时队列里的活丢了）。重新点一次运行即可。"
        reaped = [run.id for run in stale]
        await session.commit()

    for run_id in reaped:
        await _notify(run_id)
    return len(reaped)
