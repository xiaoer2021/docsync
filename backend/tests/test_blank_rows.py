"读取时的空行判断。"

from __future__ import annotations

from app.services.sheet_meta import is_blank_row as _is_blank_row


class TestIsBlankRow:
    def test_all_empty(self):
        assert _is_blank_row([None, "", "  ", None]) is True

    def test_empty_list(self):
        assert _is_blank_row([]) is True

    def test_one_value_is_enough(self):
        """只要有一个格子有值，这行就是数据 —— 绝不能丢。"""
        assert _is_blank_row([None, "", "x", None]) is False

    def test_zero_is_a_value(self):
        """0 是有意义的值，不是空。当成空会把金额 0 的行整行吃掉。"""
        assert _is_blank_row([0, None, ""]) is False

    def test_false_is_a_value(self):
        assert _is_blank_row([False, None]) is False

    def test_whitespace_only_is_empty(self):
        assert _is_blank_row(["  ", "\t", "\n"]) is True

    def test_real_row(self):
        assert _is_blank_row(["星光性感", "AAV.SRHZDB.Z", 45511]) is False


class TestDryRunDoesNotOverwriteLastSummary:
    "试跑不能写任务的「上次结果」。"

    def test_only_non_dry_runs_touch_task_fields(self):
        import inspect

        from app.services.runner import orchestrator

        source = inspect.getsource(orchestrator._finish)
        guarded = source.split("if not is_dry:")[1]

        for field in ("task.last_run_at", "task.last_run_status", "task.last_summary"):
            line = next((ln for ln in guarded.splitlines() if ln.strip().startswith(field)), None)
            assert line, f"{field} 应该在「非试跑」分支里"
            indent = len(line) - len(line.lstrip())
            assert indent >= 16, f"{field} 缩进 {indent}，说明它不在 if not is_dry 里面"

        line = next(ln for ln in source.splitlines() if ln.strip().startswith("task.next_run_at"))
        indent = len(line) - len(line.lstrip())
        assert indent < 16, "next_run_at 不该被试跑守卫挡住"
