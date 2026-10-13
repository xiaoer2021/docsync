"「文档视图」里的日期显示。"

from __future__ import annotations

from app.services.sources.preview_util import column_is_date as _column_is_date
from app.services.sources.preview_util import format_grid as _format_grid


class TestColumnIsDate:
    def test_pure_serials(self):
        assert _column_is_date([45511, 45512, 45513]) is True

    def test_mixed_text_and_serial(self):
        """文本日期和序列号混着写，也要认出来。"""
        assert _column_is_date(["2024-08-07", "2024-08-07", 45511, 45512]) is True

    def test_order_numbers_are_not_dates(self):
        "订单号列里有值跑出序列号区间 → 不是日期列。"
        assert _column_is_date([45231, 17480, 40080, 26440]) is False

    def test_plain_numbers_not_dates(self):
        assert _column_is_date([12345, 6789]) is False

    def test_text_not_dates(self):
        assert _column_is_date(["AAV.SRHZDB.Z", "AAV.JWRT.S"]) is False

    def test_too_few_values(self):
        assert _column_is_date([45511]) is False
        assert _column_is_date([]) is False

    def test_serials_with_blanks(self):
        assert _column_is_date([45511, None, "", 45512]) is True


class TestFormatGrid:
    def test_data_row_numbers_are_left_alone(self):
        "数据行里的订单号不能被改写成日期。"
        grid = [
            ["测评日期", "订单号"],
            ["2024-08-07", 45231],
            ["2024-08-07", 17480],
            [45511, 26440],
        ]
        shown, marks = _format_grid(grid, header_rows={0})
        assert [r[1] for r in shown[1:]] == [45231, 17480, 26440]
        assert marks[1] == ""

        assert shown[3][0] == "2024-08-07"

    def test_mixed_date_column_converted_throughout(self):
        grid = [
            ["测评日期"],
            ["2024-08-07"],
            ["2024-08-08"],
            [45511],
            [45512],
        ]
        shown, marks = _format_grid(grid, header_rows={0})
        assert [r[0] for r in shown[1:]] == ["2024-08-07", "2024-08-08", "2024-08-07", "2024-08-08"]
        assert marks[0] == "date"

    def test_header_row_serials_converted(self):
        """表头行里的序列号要转 —— 那种「一天一列」的表，日期就写在表头。"""
        grid = [
            ["经营科目", 46296, 46297],
            ["销售额", 1000, 1200],
        ]
        shown, marks = _format_grid(grid, header_rows={0})
        assert shown[0][1] != 46296 and str(shown[0][1]).startswith("2026-")
        assert shown[1][1] == 1000
        assert marks[1] == "date-header"

    def test_header_cell_does_not_break_column_detection(self):
        """表头格写的是「测评日期」四个字，不是日期 —— 判断要用数据行。"""
        grid = [["测评日期"], ["2024-08-07"], [45511]]
        shown, marks = _format_grid(grid, header_rows={0})
        assert shown[2][0] == "2024-08-07"
        assert marks[0] == "date"

    def test_all_serials_column_is_a_date_column(self):
        "整列都是序列号时只能当日期 —— 这是 Excel 序列号天生的歧义。"
        grid = [["x", 45231], ["y", 45232]]
        shown, marks = _format_grid(grid)
        assert shown[0][1] == "2023-11-01"
        assert marks[1] == "date"

    def test_empty_grid(self):
        assert _format_grid([]) == ([], [])
