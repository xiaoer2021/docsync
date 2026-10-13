"""表头分段取行：前面维度取第 1 行、后面月份取第 2 行，拼出一行列名。"""

from __future__ import annotations

from app.services.normalize.headers import compose_header

GRID = [
    ["店铺", "国家", "品类", "单品", "2026年", None, None],
    [None, None, None, None, "1月", "2月", "3月"],
    ["SHOP1", "US", "3C", "A1", "1200", "1350", "980"],
    ["SHOP2", "JP", "家居", "B2", "800", "900", "1100"],
]

SEGMENTS = [
    {"col_start": "A", "col_end": "D", "row": 1},
    {"col_start": "E", "row": 2},
]


class TestComposeHeader:
    def test_typical_dimension_then_months(self):
        values, max_row = compose_header(GRID, SEGMENTS, first_row=1, width=7)
        assert values == ["店铺", "国家", "品类", "单品", "1月", "2月", "3月"]

        assert max_row == 2

    def test_the_merged_title_is_dropped(self):
        """第 1 行 E 那格是「2026年」，不是列名 —— 必须被第 2 行盖掉。"""
        values, _ = compose_header(GRID, SEGMENTS, first_row=1, width=7)
        assert "2026年" not in values

    def test_open_ended_segment_goes_to_last_column(self):
        values, _ = compose_header(GRID, [{"col_start": "A", "row": 1}], first_row=1, width=4)
        assert values == ["店铺", "国家", "品类", "单品"]

    def test_uncovered_columns_fall_back_to_first_segment(self):
        """只配了 A~D 就结束 —— E 往后退回第一段的行，不留空。"""
        values, _ = compose_header(GRID, [{"col_start": "A", "col_end": "D", "row": 1}], first_row=1, width=7)
        assert values[:4] == ["店铺", "国家", "品类", "单品"]
        assert values[4] == "2026年"

    def test_segments_in_any_order(self):
        """两段写反了顺序也要对 —— 按列段覆盖，跟书写顺序无关。"""
        segments = [
            {"col_start": "E", "row": 2},
            {"col_start": "A", "col_end": "D", "row": 1},
        ]
        values, _ = compose_header(GRID, segments, first_row=1, width=7)
        assert values == ["店铺", "国家", "品类", "单品", "1月", "2月", "3月"]

    def test_first_row_offset(self):
        """grid[0] 不一定是原表第 1 行 —— 行号要报原表的号。"""
        grid = [["1月", "2月", "3月"], ["1200", "1350", "980"]]
        values, max_row = compose_header(
            grid, [{"col_start": "E", "row": 2}], first_row=2, width=3, col_start_index=4
        )
        assert values == ["1月", "2月", "3月"]
        assert max_row == 2

    def test_window_starting_beyond_column_a(self):
        "**只读 E~G 时，段里写「E」指的是窗口第 1 格，不是原表第 5 格。**"
        grid = [
            ["2026年", None, None],
            ["1月", "2月", "3月"],
            ["1200", "1350", "980"],
        ]
        segments = [{"col_start": "E", "row": 2}]
        values, _ = compose_header(grid, segments, first_row=1, width=3, col_start_index=4)
        assert values == ["1月", "2月", "3月"]

    def test_window_with_mixed_segments(self):
        """窗口从 E 开始：前两格取第 1 行、后一格取第 2 行。"""
        grid = [
            ["基准", "单位", "2026年"],
            [None, None, "1月"],
        ]
        segments = [
            {"col_start": "E", "col_end": "F", "row": 1},
            {"col_start": "G", "row": 2},
        ]
        values, max_row = compose_header(grid, segments, first_row=1, width=3, col_start_index=4)
        assert values == ["基准", "单位", "1月"]
        assert max_row == 2

    def test_column_window_offset(self):
        """只读 A~D 时，段里的列号仍是绝对列号。"""
        values, _ = compose_header(
            GRID,
            [{"col_start": "A", "col_end": "D", "row": 1}],
            first_row=1,
            col_start_index=0,
            width=4,
        )
        assert values == ["店铺", "国家", "品类", "单品"]

    def test_no_segments_returns_empty(self):
        assert compose_header(GRID, None, width=7) == ([], 0)
        assert compose_header(GRID, [], width=7) == ([], 0)

    def test_bad_config_does_not_crash(self):
        """配置写错（行号不是数字、列号乱写）不能变成 500。"""
        values, _ = compose_header(
            GRID, [{"col_start": "??", "col_end": "D", "row": "abc"}], first_row=1, width=7
        )
        assert len(values) == 7

    def test_row_beyond_grid_gives_blanks(self):
        values, max_row = compose_header(GRID, [{"col_start": "A", "row": 99}], first_row=1, width=2)
        assert values == [None, None]
        assert max_row == 99

    def test_reversed_range_still_covered(self):
        """col_start/col_end 写反了也把这段盖上，而不是一个格子都不盖。"""
        values, _ = compose_header(GRID, [{"col_start": "D", "col_end": "A", "row": 1}], first_row=1, width=4)
        assert values == ["店铺", "国家", "品类", "单品"]
