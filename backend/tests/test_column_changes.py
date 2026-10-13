"运行时「列变化」检查 —— 用历史列名比对，零额外请求。"

from __future__ import annotations

from app.services.doc_registry import column_drift_text, compare_columns
from app.services.sheet_meta import note_column_changes as _note_column_changes


class _StubLogger:
    """只记下说了什么。"""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.lines.append(("info", message))

    def warn(self, message: str) -> None:
        self.lines.append(("warn", message))

    def error(self, message: str) -> None:
        self.lines.append(("error", message))

    @property
    def warns(self) -> list[str]:
        return [m for level, m in self.lines if level == "warn"]

    @property
    def text(self) -> str:
        return "\n".join(m for _, m in self.lines)


class TestCompareColumns:
    def test_first_check_reports_nothing(self):
        """第一次看这张表没有底子可比 —— 否则所有列都会被报成「新增」。"""
        assert compare_columns([], ["a", "b"]) == ([], [])

    def test_added(self):
        assert compare_columns(["a"], ["a", "b"]) == (["b"], [])

    def test_removed(self):
        assert compare_columns(["a", "b"], ["a"]) == ([], ["b"])

    def test_no_change(self):
        assert compare_columns(["a", "b"], ["a", "b"]) == ([], [])

    def test_placeholder_is_ignored(self):
        """「列G」这种没表头的占位跟着数据变，不该天天假报变化。"""
        assert compare_columns(["a"], ["a", "列G"]) == ([], [])
        assert compare_columns(["a", "列B"], ["a"]) == ([], [])

    def test_detailed_name_in_place_of_placeholder_counts(self):
        """原来没表头、现在补上了表头 → 算「新增了一列」（确实是新信息）。"""
        assert compare_columns(["a", "列B"], ["a", "备注"]) == (["备注"], [])


class TestColumnDriftText:
    def test_added(self):
        assert column_drift_text(["备注"], []) == "新增 备注"

    def test_removed(self):
        assert column_drift_text([], ["备注"]) == "消失 备注"

    def test_both(self):
        assert column_drift_text(["b"], ["a"]) == "新增 b；消失 a"

    def test_nothing(self):
        assert column_drift_text([], []) is None

    def test_long_list_is_truncated(self):
        text = column_drift_text([f"c{i}" for i in range(9)], [])
        assert text is not None and text.endswith("…")


class TestRunTimeReminder:
    """跑一次同步就能发现「谁加了列」—— 而且不额外花请求。"""

    def note(self, current, history, mapped=()):
        logger = _StubLogger()
        _note_column_changes(logger, {"s1": "店铺1"}, ["s1"], current, history, set(mapped))
        return logger

    def test_new_column_is_reported(self):
        logger = self.note({"s1": ["编码", "名称", "新列"]}, {"s1": ["编码", "名称"]})
        assert any("新增了列" in m and "新列" in m for m in logger.warns)

    def test_unmapped_new_column_is_called_out(self):
        """加了列但没配映射 → 必须说清「本次不会同步」，否则用户以为已经进去了。"""
        logger = self.note({"s1": ["编码", "新列"]}, {"s1": ["编码"]}, mapped=["编码"])
        assert any("不会同步" in m and "新列" in m for m in logger.warns)

    def test_mapped_new_column_is_not_flagged_unmapped(self):
        logger = self.note({"s1": ["编码", "新列"]}, {"s1": ["编码"]}, mapped=["编码", "新列"])
        assert not any("不会同步" in m for m in logger.warns)

    def test_removed_column_is_reported(self):
        logger = self.note({"s1": ["编码"]}, {"s1": ["编码", "旧列"]})
        assert any("少了列" in m and "旧列" in m for m in logger.warns)

    def test_first_run_is_silent(self):
        """头一次跑没有历史，不该报一堆「新增」。"""
        logger = self.note({"s1": ["编码", "名称"]}, {})
        assert logger.warns == []

    def test_no_change_is_silent(self):
        logger = self.note({"s1": ["编码"]}, {"s1": ["编码"]})
        assert logger.warns == []

    def test_placeholder_is_not_reported(self):
        logger = self.note({"s1": ["编码", "列G"]}, {"s1": ["编码"]})
        assert logger.warns == []

    def test_multiple_sheets_are_labelled(self):
        logger = _StubLogger()
        _note_column_changes(
            logger,
            {"s1": "店铺1", "s2": "店铺2"},
            ["s1", "s2"],
            {"s1": ["a"], "s2": ["a", "新列"]},
            {"s1": ["a"], "s2": ["a"]},
            set(),
        )
        text = logger.text
        assert "店铺2" in text and "新列" in text
        assert "店铺1" not in text, "没变化的表不该被点名"
