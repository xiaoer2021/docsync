"平台可调参数：并发上限、两个超时。"

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import DdSetting

DEFAULTS: dict[str, int] = {
    "worker_max_concurrency": 6,
    "queue_wait_timeout_seconds": 300,
    "run_timeout_seconds": 1800,
}

LIMITS: dict[str, tuple[int, int]] = {
    "worker_max_concurrency": (1, 32),
    "queue_wait_timeout_seconds": (30, 24 * 3600),
    "run_timeout_seconds": (60, 24 * 3600),
}

LABELS: dict[str, str] = {
    "worker_max_concurrency": "同时执行的个数",
    "queue_wait_timeout_seconds": "排队最多等多久（秒）",
    "run_timeout_seconds": "单次执行超时（秒）",
}

_cache: dict[str, int] = dict(DEFAULTS)


def get(key: str) -> int:
    return _cache.get(key, DEFAULTS[key])


def current() -> dict[str, int]:
    return dict(_cache)


async def _rows(session: AsyncSession) -> dict[str, DdSetting]:
    found = await session.scalars(select(DdSetting).where(DdSetting.key.in_(list(DEFAULTS))))
    return {row.key: row for row in found.all()}


def _clamp(key: str, value: int) -> int:
    low, high = LIMITS[key]
    return min(max(value, low), high)


async def load(session: AsyncSession) -> dict[str, int]:
    """从库里读一遍，刷新内存副本。启动时和执行相关的地方都靠它。"""
    rows = await _rows(session)
    for key, default in DEFAULTS.items():
        row = rows.get(key)
        try:
            value = int(row.value) if row is not None and row.value is not None else default
        except (TypeError, ValueError):
            value = default
        _cache[key] = _clamp(key, value)
    return current()


async def save(session: AsyncSession, data: dict[str, int | None]) -> dict[str, int]:
    rows = await _rows(session)
    for key, value in data.items():
        if key not in DEFAULTS or value is None:
            continue
        clamped = _clamp(key, int(value))
        row = rows.get(key)
        if row is None:
            session.add(DdSetting(key=key, value=str(clamped)))
        else:
            row.value = str(clamped)
    await session.flush()
    return await load(session)


def apply_to_runtime() -> None:
    "把并发上限推给执行队列 —— 改完立刻生效，不用重启。"
    from app.services.runner.manager import manager

    manager.set_limit(get("worker_max_concurrency"))
