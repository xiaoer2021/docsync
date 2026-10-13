"调度器的导入与启动。"

from __future__ import annotations

import datetime as dt

import pytest

from app.services.schedule_rules import (
    MIN_INTERVAL_SEC,
    WATCH_CRON,
    next_after,
    next_watch,
    schedule_label,
    validate_schedule,
)

BASE = dt.datetime(2026, 10, 6, 10, 30, 0)


class TestNoCircularImport:
    def test_importing_scheduler_works(self):
        """导入调度器不能炸 —— 炸了就是循环导入，而且会被静默吞掉。"""
        from app.services import scheduler

        assert scheduler is not None

    def test_wait_for_timeout_is_caught(self):
        "``asyncio.wait_for`` 的超时必须是 ``asyncio.TimeoutError`` 才接得住。"
        import asyncio

        async def boom() -> None:
            await asyncio.sleep(1)

        async def run() -> str:
            try:
                await asyncio.wait_for(boom(), timeout=0.01)
            except asyncio.TimeoutError:
                return "caught"
            except TimeoutError:  # noqa: B014 — 故意分开写，就是要验证哪个能接住
                return "caught-by-builtin"
            return "not-caught"

        assert asyncio.run(run()) == "caught"

    def test_schedule_rules_is_a_leaf(self):
        """规则模块不能反过来依赖调度器/执行器，否则又绕回去了。"""
        from pathlib import Path

        import app.services.schedule_rules as rules

        source = Path(rules.__file__).read_text(encoding="utf-8")
        assert "from app.services.scheduler" not in source
        assert "from app.services.runner" not in source

    def test_orchestrator_can_be_imported_after_scheduler(self):
        from app.services.runner.orchestrator import execute_run
        from app.services.scheduler import scheduler

        assert callable(execute_run)
        assert scheduler is not None


class TestNextAfter:
    def test_manual_never_schedules(self):
        assert next_after(None, BASE) is None
        assert next_after({}, BASE) is None
        assert next_after({"kind": "manual"}, BASE) is None

    def test_interval(self):
        assert next_after({"kind": "interval", "interval_sec": 3600}, BASE) == BASE + dt.timedelta(hours=1)

    def test_interval_has_a_floor(self):
        assert next_after({"kind": "interval", "interval_sec": 1}, BASE) == BASE + dt.timedelta(
            seconds=MIN_INTERVAL_SEC
        )

    def test_zero_interval_is_manual(self):
        assert next_after({"kind": "interval", "interval_sec": 0}, BASE) is None

    def test_cron_daily(self):
        assert next_after({"kind": "cron", "cron_expr": "0 9 * * *"}, BASE) == dt.datetime(
            2026, 10, 7, 9, 0, 0
        )

    def test_bad_cron_returns_none_not_crash(self):
        assert next_after({"kind": "cron", "cron_expr": "完全不是 cron"}, BASE) is None
        assert next_after({"kind": "cron", "cron_expr": ""}, BASE) is None


class TestValidateSchedule:
    def test_manual_ok(self):
        assert validate_schedule({"kind": "manual"}) is None
        assert validate_schedule(None) is None

    def test_interval_too_short(self):
        assert "60 秒" in (validate_schedule({"kind": "interval", "interval_sec": 10}) or "")

    def test_interval_not_a_number(self):
        assert validate_schedule({"kind": "interval", "interval_sec": "一小时"}) is not None

    def test_cron_field_count(self):
        problem = validate_schedule({"kind": "cron", "cron_expr": "0 9 * *"})
        assert problem and "5 段" in problem

    def test_cron_invalid(self):
        assert validate_schedule({"kind": "cron", "cron_expr": "99 99 * * *"}) is not None

    def test_cron_valid(self):
        assert validate_schedule({"kind": "cron", "cron_expr": "30 2 * * *"}) is None


class TestScheduleLabel:
    def test_labels_read_like_chinese(self):
        assert schedule_label(None) == "手动"
        assert schedule_label({"kind": "interval", "interval_sec": 3600}) == "每 1 小时"
        assert schedule_label({"kind": "interval", "interval_sec": 1800}) == "每 30 分钟"
        assert schedule_label({"kind": "cron", "cron_expr": "0 9 * * *"}) == "cron：0 9 * * *"


class FakeDoc:
    def __init__(self, watch_enabled: bool, watch_cron: str | None = None) -> None:
        self.watch_enabled = watch_enabled
        self.watch_cron = watch_cron


class TestNextWatch:
    def test_disabled_returns_none(self):
        assert next_watch(FakeDoc(False), BASE) is None

    def test_default_cron_is_4am(self):
        got = next_watch(FakeDoc(True), BASE)
        assert got == dt.datetime(2026, 10, 7, 4, 0, 0)
        assert WATCH_CRON == "0 4 * * *"

    def test_custom_cron(self):
        got = next_watch(FakeDoc(True, "0 */6 * * *"), BASE)
        assert got == dt.datetime(2026, 10, 6, 12, 0, 0)

    def test_blank_cron_falls_back(self):
        assert next_watch(FakeDoc(True, "   "), BASE) == dt.datetime(2026, 10, 7, 4, 0, 0)

    def test_bad_cron_returns_none(self):
        assert next_watch(FakeDoc(True, "乱写的"), BASE) is None


@pytest.mark.parametrize("kind", ["manual", "interval", "cron"])
def test_every_kind_has_a_label(kind: str):
    assert schedule_label({"kind": kind, "cron_expr": "0 9 * * *", "interval_sec": 60})
