"合并单元格：表头拼名 + 数据区按范围补值。"

from __future__ import annotations

from app.services.feishu.merges import (
    MergedRange,
    VerticalFill,
    combine_header_with_parent,
    parse_merges,
)


class TestParseMerges:
    def test_converts_to_one_based(self):
        """接口是 0 起，转成 1 起 —— 否则日志里的行号跟表格对不上。"""
        spans = parse_merges(
            [
                {
                    "start_row_index": 2,
                    "end_row_index": 3,
                    "start_column_index": 1,
                    "end_column_index": 1,
                }
            ]
        )
        assert len(spans) == 1
        assert (spans[0].start_row, spans[0].end_row) == (3, 4)

    def test_horizontal_and_vertical_flags(self):
        horizontal = MergedRange(start_row=3, end_row=3, start_col=6, end_col=18)
        vertical = MergedRange(start_row=3, end_row=4, start_col=1, end_col=1)
        assert horizontal.is_horizontal and not horizontal.is_vertical
        assert vertical.is_vertical and not vertical.is_horizontal

    def test_broken_entry_is_skipped_not_fatal(self):
        """少一块合并最多是那一处不补；抛异常会让整张表读不了，轻重差得远。"""
        spans = parse_merges(
            [
                {"start_row_index": 0, "end_row_index": 0, "start_column_index": 0, "end_column_index": 1},
                {"缺字段": 1},
                "不是字典",
            ]
        )
        assert len(spans) == 1

    def test_non_list_is_empty(self):
        assert parse_merges(None) == []
        assert parse_merges("x") == []


class TestCombineHeader:
    """表头两行：上面一行是「销售数据」这种大标题，下面一行是「件数/金额」。"""

    def _merges(self):
        return [
            MergedRange(start_row=1, end_row=1, start_col=1, end_col=2),
            MergedRange(start_row=1, end_row=1, start_col=3, end_col=4),
        ]

    def test_parent_prefixed_to_child(self):
        own = ["店铺", "件数", "金额", "件数", "金额"]
        parent = [None, "销售数据", None, "退货数据", None]
        out = combine_header_with_parent(own, parent, self._merges(), header_row=2, parent_row=1)
        assert out == [
            "店铺",
            "销售数据/件数",
            "销售数据/金额",
            "退货数据/件数",
            "退货数据/金额",
        ]

    def test_without_merges_nothing_prefixed(self):
        """**没有合并信息就不拼** —— 空的那格可能真的是空的，不能自己延伸。"""
        own = ["店铺", "件数", "金额"]
        parent = [None, "销售数据", None]
        out = combine_header_with_parent(own, parent, [], header_row=2, parent_row=1)
        assert out == ["店铺", "件数", "金额"]

    def test_vertical_merge_is_not_a_parent(self):
        """上下两行是**同一个格**（纵向合并）时，名字是自己的，不该加前缀。"""

        merges = [MergedRange(start_row=1, end_row=2, start_col=1, end_col=1)]
        own = ["", "部门"]
        parent = [None, "部门"]
        out = combine_header_with_parent(own, parent, merges, header_row=2, parent_row=1)
        assert out[1] == "部门"

    def test_same_name_parent_and_child_not_duplicated(self):
        merges = [MergedRange(start_row=1, end_row=1, start_col=1, end_col=1)]
        out = combine_header_with_parent(["", "金额"], [None, "金额"], merges, header_row=2, parent_row=1)
        assert out[1] == "金额", "父名和子名一样时拼成「金额/金额」是噪声"

    def test_child_only_kept_when_no_parent(self):
        out = combine_header_with_parent(["", "备注"], [None, None], [], header_row=2, parent_row=1)
        assert out[1] == "备注"


class TestVerticalFill:
    """数据区：B 列第 3~5 行是同一个「A 部门」。"""

    def _merges(self):
        return [MergedRange(start_row=3, end_row=5, start_col=1, end_col=1)]

    def test_fills_below_from_the_start_row(self):
        fill = VerticalFill(self._merges(), first_row=3)
        assert fill.apply(3, ["", "A 部门", 100]) == ["", "A 部门", 100]
        assert fill.apply(4, ["", None, 200]) == ["", "A 部门", 200]
        assert fill.apply(5, ["", "", 150]) == ["", "A 部门", 150]
        assert fill.filled == 2, "补了几个格子要数出来，日志要报"

    def test_does_not_touch_rows_outside_the_range(self):
        fill = VerticalFill(self._merges(), first_row=3)
        fill.apply(3, ["", "A 部门", 100])
        assert fill.apply(6, ["", None, 300]) == ["", None, 300]

    def test_existing_value_wins(self):
        """范围内那行**本来就有值**就不动它 —— 表格里明写了以它为准。"""
        fill = VerticalFill(self._merges(), first_row=3)
        fill.apply(3, ["", "A 部门", 100])
        assert fill.apply(4, ["", "B 部门", 200]) == ["", "B 部门", 200]
        assert fill.filled == 0

    def test_horizontal_merges_are_ignored(self):
        """横向合并不是数据区的事（那是表头），别乱补。"""
        fill = VerticalFill([MergedRange(start_row=3, end_row=3, start_col=1, end_col=2)], first_row=3)
        assert fill.apply(4, ["", None, None]) == ["", None, None]

    def test_merges_above_data_area_ignored(self):
        fill = VerticalFill([MergedRange(start_row=1, end_row=2, start_col=1, end_col=1)], first_row=5)
        assert fill.apply(6, ["", None]) == ["", None]

    def test_start_row_value_missing_means_nothing_to_fill(self):
        fill = VerticalFill(self._merges(), first_row=3)
        fill.apply(3, ["", None, 100])
        assert fill.apply(4, ["", None, 200]) == ["", None, 200]
