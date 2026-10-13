"执行日志：落盘 + 入库 + 实时推给界面。"

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path

from app.core.config import settings
from app.core.mask import mask_text


class LogHub:
    "按 run 分组的实时日志广播。"

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[str | None]]] = {}
        self._backlog: dict[int, list[str]] = {}
        self._closed: set[int] = set()

    def subscribe(self, run_id: int) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2000)

        for line in self._backlog.get(run_id, []):
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:  # pragma: no cover
                break
        if run_id in self._closed:
            queue.put_nowait(None)
            return queue
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: int, queue: asyncio.Queue[str | None]) -> None:
        group = self._subscribers.get(run_id)
        if group:
            group.discard(queue)
            if not group:
                self._subscribers.pop(run_id, None)

    def publish(self, run_id: int, line: str) -> None:
        self._backlog.setdefault(run_id, []).append(line)

        if len(self._backlog[run_id]) > 500:
            del self._backlog[run_id][:200]
        for queue in list(self._subscribers.get(run_id, ())):
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:  # pragma: no cover — 订阅者太慢就丢，不拖累执行
                pass

    def close(self, run_id: int) -> None:
        self._closed.add(run_id)
        for queue in list(self._subscribers.get(run_id, ())):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover
                pass
        self._subscribers.pop(run_id, None)

    def forget(self, run_id: int) -> None:
        self._subscribers.pop(run_id, None)
        self._backlog.pop(run_id, None)
        self._closed.discard(run_id)


hub = LogHub()


class RunLogger:
    "一个 run 的日志写入器。"

    def __init__(self, run_id: int, *, path_base: Path | None = None) -> None:
        self.run_id = run_id
        base = path_base or settings.logs_dir
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"{run_id}.log"
        self.lines: list[tuple[str, str]] = []
        self.bytes = 0
        self.truncated = False
        self._file = None

    def _ensure_file(self):
        if self._file is None:
            self._file = self.path.open("a", encoding="utf-8", newline="\n")
        return self._file

    def log(self, message: str, *, level: str = "info") -> None:
        message = mask_text(message)
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        hub.publish(self.run_id, line)

        if self.bytes < settings.run_log_max_bytes:
            handle = self._ensure_file()
            handle.write(line + "\n")
            handle.flush()
            self.bytes += len(line.encode("utf-8")) + 1
        else:
            self.truncated = True

        if len(self.lines) < settings.run_log_db_max_lines:
            self.lines.append((level, line))

    def info(self, message: str) -> None:
        self.log(message)

    def warn(self, message: str) -> None:
        self.log(f"⚠ {message}", level="warn")

    def error(self, message: str) -> None:
        self.log(f"✗ {message}", level="error")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


async def read_stream(run_id: int, *, timeout: float = 3600.0) -> AsyncIterator[str]:
    """给 SSE 用的异步迭代器。执行结束或超时就收尾。"""
    queue = hub.subscribe(run_id)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return
            if item is None:
                return
            yield item
    finally:
        hub.unsubscribe(run_id, queue)
