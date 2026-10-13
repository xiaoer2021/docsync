"合并多张在线表格时，**按列名对齐**，不按位置。"

from __future__ import annotations

from app.services.dingtalk.sheet_reader import (
    align_headers,
    expand_row,
    is_placeholder_header,
)


class TestPlaceholderHeader:
    def test_placeholder_is_recognised(self):
        assert is_placeholder_header("列G")
        assert is_placeholder_header("列AA")

    def test_real_name_is_not_placeholder(self):
        assert not is_placeholder_header("产品编号")
        assert not is_placeholder_header("列")


class TestAlignByPositionIsWrong:
    """这些用例在原实现下会失败，正是要修的。"""

    def test_column_inserted_in_the_middle(self):
        """店铺2 中间插了一列 → 后面不该错位。"""
        main = ["产品编码", "产品名", "coupang条形码", "产品编号"]
        other = ["产品编码", "产品名", "产品编号", "新列"]

        names, maps = align_headers([main, other])

        assert names == ["产品编码", "产品名", "coupang条形码", "产品编号", "新列"]

        assert maps[1][2] == 3
        assert maps[1][3] == 4

    def test_column_missing_in_one_sheet(self):
        """店铺2 少了一列 → 那一列在它那边留空，不该报错。"""
        main = ["a", "b", "c"]
        other = ["a", "c"]

        names, maps = align_headers([main, other])

        assert names == ["a", "b", "c"]
        assert maps[1] == [0, 2]

    def test_data_lands_in_the_right_column(self):
        """插列之后，数据必须落到正确的列上 —— 这是整件事的目的。"""
        main = ["编码", "名称", "编号"]
        other = ["编码", "名称", "备注", "编号"]
        names, maps = align_headers([main, other])

        row = expand_row(["A1", "杯子", "急", "P9"], maps[1], len(names))

        assert row[names.index("编码")] == "A1"
        assert row[names.index("名称")] == "杯子"
        assert row[names.index("备注")] == "急"
        assert row[names.index("编号")] == "P9", "编号必须落回编号那一列，不能串到备注列"


class TestAlignHeaders:
    def test_single_sheet(self):
        names, maps = align_headers([["a", "b"]])
        assert names == ["a", "b"]
        assert maps == [[0, 1]]

    def test_main_order_wins(self):
        """列序以主表为准，新列追加在后面。"""
        names, _ = align_headers([["b", "a"], ["a", "b"]])
        assert names == ["b", "a"]

    def test_new_column_appended(self):
        names, _ = align_headers([["a"], ["a", "z"]])
        assert names == ["a", "z"]

    def test_same_name_twice_is_not_duplicated(self):
        names, _ = align_headers([["a", "b"], ["a", "b", "a"]])
        assert names == ["a", "b"]

    def test_placeholder_columns_are_dropped(self):
        """没表头的列（「列G」）不进合并列序 —— 那不是一列。"""
        names, maps = align_headers([["a", "列B", "c"]])
        assert names == ["a", "c"]
        assert maps == [[0, -1, 1]]

    def test_placeholder_in_second_sheet_is_dropped(self):
        names, _ = align_headers([["a", "b"], ["a", "列B"]])
        assert names == ["a", "b"]

    def test_empty_sheet_header(self):
        names, maps = align_headers([["a"], []])
        assert names == ["a"]
        assert maps[1] == []

    def test_all_placeholders(self):
        names, _ = align_headers([["列A", "列B"]])
        assert names == []


class TestExpandRow:
    def test_missing_columns_become_none(self):
        assert expand_row(["a"], [0], 3) == ["a", None, None]

    def test_dropped_columns_are_skipped(self):
        """-1 表示这一列不要，值直接丢掉。"""
        assert expand_row(["a", "别管我", "b"], [0, -1, 1], 2) == ["a", "b"]

    def test_short_row_is_padded(self):
        assert expand_row(["a"], [0, 1, 2], 3) == ["a", None, None]

    def test_row_longer_than_slot_is_safe(self):
        assert expand_row(["a", "b"], [0], 2) == ["a", None]

    def test_empty_row(self):
        assert expand_row([], [0, 1], 2) == [None, None]

    def test_none_values_are_kept_as_none(self):
        assert expand_row([None, "x"], [0, 1], 2) == [None, "x"]


class TestRealWorldCoupang:
    """照着真实场景走一遍：4 个店铺 sheet，表头各不一样。"""

    HEADERS = [
        ["产品编码", "产品名", "产品图片", "产品选项ID", "coupang条形码", "产品编号"],
        ["产品编码", "产品名", "产品图片", "产品图片2", "产品选项ID", "coupang条形码", "产品编号"],
        ["产品编码", "产品名", "产品图片", "产品选项ID", "产品编号"],
        ["产品编码", "产品名", "产品图片", "产品选项ID", "coupang条形码", "产品编号", "备注"],
    ]

    def test_all_sheets_merge_without_conflict(self):
        names, maps = align_headers(self.HEADERS)
        assert names == [
            "产品编码",
            "产品名",
            "产品图片",
            "产品选项ID",
            "coupang条形码",
            "产品编号",
            "产品图片2",
            "备注",
        ]
        assert len(maps) == 4

    def test_the_column_that_was_missing_stays_empty(self):
        """店铺3 没有「coupang条形码」→ 它那几行这一列留空，不串位。"""
        names, maps = align_headers(self.HEADERS)
        idx = names.index("coupang条形码")

        row = expand_row(["A1", "杯子", "img", "9072", "S003"], maps[2], len(names))
        assert row[idx] is None
        assert row[names.index("产品编号")] == "S003", "编号不能被顶到条形码那一列"

    def test_shop2_extra_column_goes_to_its_own_slot(self):
        names, maps = align_headers(self.HEADERS)
        row = expand_row(
            ["A1", "杯子", "img", "img2", "9072", "S003", "P9"],
            maps[1],
            len(names),
        )
        assert row[names.index("产品图片2")] == "img2"
        assert row[names.index("产品选项ID")] == "9072", "插了一列之后选项ID不能错位"
        assert row[names.index("coupang条形码")] == "S003"
        assert row[names.index("产品编号")] == "P9"

    def test_shop4_extra_column_kept(self):
        names, maps = align_headers(self.HEADERS)
        row = expand_row(["A1", "杯子", "img", "9072", "S003", "P9", "急"], maps[3], len(names))
        assert row[names.index("备注")] == "急"
