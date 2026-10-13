"读子表表头时的列名规整。"

from __future__ import annotations

from app.services.doc_registry import trim_header_cells


class TestTrimHeaderCells:
    def test_trailing_blanks_are_dropped(self):
        row = ["店铺", "产品编码", None, "", "  ", None]
        assert trim_header_cells(row) == ["店铺", "产品编码"]

    def test_full_width_row_is_not_padded(self):
        """一行只有 3 个真列名，不该因为读的范围是 104 列就报 104 列。"""
        row = ["日期", "店铺", "金额"] + [None] * 101
        assert len(trim_header_cells(row)) == 3

    def test_middle_placeholders_are_dropped(self):
        """中间空列会被补成「列C」，那是占位符不是真列名。"""
        row = ["日期", None, "金额"]
        assert trim_header_cells(row) == ["日期", "金额"]

    def test_duplicate_names_still_get_suffixes(self):
        """重名要加后缀 —— 否则按名字找列会串。"""
        assert trim_header_cells(["金额", "金额"]) == ["金额", "金额_1"]

    def test_all_empty(self):
        assert trim_header_cells([None, "", "  "]) == []

    def test_empty_input(self):
        assert trim_header_cells([]) == []

    def test_real_header_is_untouched(self):
        row = ["测评日期", "店铺", "产品编码", "订单号", "订单金额（韩币）"]
        assert trim_header_cells(row) == row
