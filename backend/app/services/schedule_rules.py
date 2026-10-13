"调度规则：时间怎么算、表达式合不合法。"

from __future__ import annotations

import datetime as dt

from croniter import croniter

from app.models.task import SCHEDULE_CRON, SCHEDULE_INTERVAL, SCHEDULE_MANUAL

WATCH_CRON = "0 4 * * *"

MIN_INTERVAL_SEC = 60


def schedule_label(schedule: dict | None) -> str:
    """给界面看的一句人话。"""
    if not schedule:
        return "手动"
    kind = str(schedule.get("kind") or SCHEDULE_MANUAL)
    if kind == SCHEDULE_INTERVAL:
        seconds = int(schedule.get("interval_sec") or 0)
        if seconds <= 0:
            return "手动"
        if seconds % 3600 == 0:
            return f"每 {seconds // 3600} 小时"
        if seconds % 60 == 0:
            return f"每 {seconds // 60} 分钟"
        return f"每 {seconds} 秒"
    if kind == SCHEDULE_CRON:
        expr = str(schedule.get("cron_expr") or "").strip()
        return f"cron：{expr}" if expr else "手动"
    return "手动"


def next_after(schedule: dict | None, base: dt.datetime) -> dt.datetime | None:
    "算出 ``base`` 之后的下一次运行时间。手动或没配就返回 None。"
    if not schedule:
        return None
    kind = str(schedule.get("kind") or SCHEDULE_MANUAL)

    if kind == SCHEDULE_INTERVAL:
        seconds = int(schedule.get("interval_sec") or 0)
        if seconds <= 0:
            return None
        return base + dt.timedelta(seconds=max(seconds, MIN_INTERVAL_SEC))

    if kind == SCHEDULE_CRON:
        expr = str(schedule.get("cron_expr") or "").strip()
        if not expr:
            return None
        try:
            return croniter(expr, base).get_next(dt.datetime)
        except (ValueError, KeyError):
            return None

    return None


def validate_schedule(schedule: dict | None) -> str | None:
    "保存时校验调度配置。返回错误说明，没问题返回 None。"
    if not schedule:
        return None
    kind = str(schedule.get("kind") or SCHEDULE_MANUAL)

    if kind == SCHEDULE_INTERVAL:
        try:
            seconds = int(schedule.get("interval_sec") or 0)
        except (TypeError, ValueError):
            return "间隔必须是整数秒"
        if seconds and seconds < MIN_INTERVAL_SEC:
            return f"间隔最短 {MIN_INTERVAL_SEC} 秒"
        return None

    if kind == SCHEDULE_CRON:
        expr = str(schedule.get("cron_expr") or "").strip()
        if not expr:
            return "选了 cron 但没填表达式"
        fields = expr.split()
        if len(fields) != 5:
            return f"cron 要 5 段（分 时 日 月 周），你填了 {len(fields)} 段：{expr}"
        try:
            if not croniter.is_valid(expr):
                return f"cron 表达式不合法：{expr}"
        except (ValueError, KeyError):
            return f"cron 表达式不合法：{expr}"
        return None

    return None


def next_watch(doc, base: dt.datetime) -> dt.datetime | None:
    """文档下一次自动检测的时间。"""
    if not getattr(doc, "watch_enabled", False):
        return None
    expr = (doc.watch_cron or "").strip() or WATCH_CRON
    return next_after({"kind": SCHEDULE_CRON, "cron_expr": expr}, base)
