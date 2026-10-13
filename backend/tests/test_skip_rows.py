"跳过不该写进库的行：小计、合计、说明、签字行。"

from __future__ import annotations

from app.services.normalize.rowfilter import (
    DEFAULT_SKIP_WORDS,
    drop_skipped_rows,
    row_should_skip,
    skip_config,
)


class TestRowShouldSkip:
    def test_by_row_number(self):
        assert row_should_skip(["数据"], 13, skip_rows={13})

    def test_row_number_not_matched(self):
        assert not row_should_skip(["数据"], 12, skip_rows={13})

    def test_by_substring(self):
        """子串匹配，不是相等 —— 表里常写「月度总计」「本季合计」。"""
        assert row_should_skip(["月度总计", 250], 13, skip_words=["总计"])
        assert row_should_skip(["本季合计", 250], 13, skip_words=["合计"])

    def test_matches_any_cell(self):
        """关键词命中的格子在哪一列都算 —— 不限定某一列。"""
        assert row_should_skip(["A", "B", "小计说明"], 13, skip_words=["小计"])

    def test_numbers_never_match(self):
        """数字里不会有「总计」；只扫字符串，避免无谓的 str() 转换开销。"""
        assert not row_should_skip([1, 2, 3], 13, skip_words=["总计"])

    def test_no_config_never_skips(self):
        assert not row_should_skip(["月度总计"], 13)

    def test_row_no_none_is_safe(self):
        """多维表的记录没有行号 —— 不能因此崩掉。"""
        assert not row_should_skip(["数据"], None, skip_rows={13})
        assert row_should_skip(["总计"], None, skip_words=["总计"])


class TestDropSkippedRows:
    def test_drops_and_reports_reason(self):
        rows = [(12, ["A 部门", 100]), (13, ["月度总计", 250]), (14, ["B 部门", 300])]
        kept, dropped = drop_skipped_rows(rows, skip_words=["总计"])
        assert kept == [(12, ["A 部门", 100]), (14, ["B 部门", 300])]
        assert len(dropped) == 1

        assert "13" in dropped[0] and "总计" in dropped[0]

    def test_row_number_reason_is_different(self):
        """两种规则的理由必须分得开 —— 用户要采取的行动完全不同。"""
        rows = [(13, ["正常数据", 1])]
        _, dropped = drop_skipped_rows(rows, skip_rows={13})
        assert "你标了不写" in dropped[0]

    def test_keeps_source_sheet_segment(self):
        """行是 ``(行号, 值, 来源子表)`` —— 丢掉几行之后剩下的形状不能变。"""
        rows = [(1, ["A"], "s1"), (2, ["总计"], "s1")]
        kept, _ = drop_skipped_rows(rows, skip_words=["总计"])
        assert kept == [(1, ["A"], "s1")]

    def test_no_config_returns_same_object(self):
        rows = [(1, ["A"])]
        kept, dropped = drop_skipped_rows(rows)
        assert kept is rows and dropped == []

    def test_row_without_number(self):
        """没有行号的行（多维表）按内容照样能丢。"""
        rows = [(None, ["总计", 1]), (None, ["A 部门", 2])]
        kept, dropped = drop_skipped_rows(rows, skip_words=["总计"])
        assert len(kept) == 1 and len(dropped) == 1

    def test_empty_row_tuple_is_safe(self):
        kept, _ = drop_skipped_rows([()], skip_words=["总计"])
        assert kept == [()]


class TestSkipConfig:
    """从任务配置里解析 —— prepare 和预览**共用这一份**。"""

    def test_parses_both(self):
        rows, words = skip_config({"skip_rows": [13, "14"], "skip_words": ["总计", " 合计 "]})
        assert rows == {13, 14}
        assert words == ["总计", "合计"]

    def test_ignores_garbage(self):
        rows, words = skip_config({"skip_rows": ["abc", None], "skip_words": ["", "  "]})
        assert rows == set() and words == []

    def test_empty_config(self):
        assert skip_config(None) == (set(), [])
        assert skip_config({}) == (set(), [])


def test_default_words_cover_the_usual_suspects():
    """默认词只是给界面「一键填」用的，**不会自动生效**。"""
    for word in ("总计", "合计", "小计"):
        assert word in DEFAULT_SKIP_WORDS
