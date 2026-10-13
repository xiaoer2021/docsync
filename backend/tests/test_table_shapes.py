"表格形态扫描：拿各种**真实世界里会长成什么样**的表去压识别器和读法。"

from __future__ import annotations

import pytest

from app.services.sources.layout import detect_layout


def _blank(n: int) -> list:
    return [None] * n


class TestVerticalShapes:
    """纵向表（表头在上、一行一条记录）—— 绝大多数在线表格的样子。"""

    def test_merged_title_on_first_row(self):
        """第一行是合并的大标题 —— 最普遍的一种。"""
        rows = [
            [None, "2026 年 8 月销售明细", None, None],
            ["订单号", "客户", "金额", "日期"],
            ["A001", "张三", 100, "2026-08-01"],
        ]
        found = detect_layout(rows)
        assert found.orientation == "vertical"
        assert found.header_row == 2

    def test_two_comment_rows_above_header(self):
        """表头上面垫了两行说明（填表须知之类）。"""
        rows = [
            [None, "请按格式填写，不要改列名", None],
            [None, "统计口径：含税", None],
            ["产品", "数量", "单价"],
            ["杯子", 10, 9.9],
        ]
        found = detect_layout(rows)
        assert found.orientation == "vertical"
        assert found.header_row == 3

    def test_leading_blank_rows(self):
        """开头几行是空的。"""
        rows = [_blank(3), _blank(3), ["编码", "名称", "数量"], ["A1", "杯子", 5]]
        found = detect_layout(rows)
        assert found.orientation == "vertical"
        assert found.header_row == 3

    def test_date_column_does_not_look_like_cross_tab(self):
        "**重要**：纵向表里有一个日期列（极常见），不能被误判成交叉表。"
        rows = [
            ["订单号", "日期", "金额"],
            ["A001", "2026-10-01", 100],
            ["A002", "2026-10-02", 120],
            ["A003", "2026-10-03", 90],
            ["A004", "2026-10-04", 110],
        ]
        found = detect_layout(rows)
        assert found.orientation == "vertical", "日期在**列**里不是交叉表 —— 判错的话整个读法都会错"

    def test_first_column_empty_header_starts_at_b(self):
        rows = [
            [None, "产品", "数量"],
            [None, "杯子", 10],
            [None, "碟子", 20],
        ]
        found = detect_layout(rows)
        assert found.orientation == "vertical"

    def test_header_only_no_data(self):
        rows = [["产品", "数量"]]
        found = detect_layout(rows)
        assert found.orientation == "vertical"
        assert found.header_row == 1


class TestCrossTabShapes:
    """交叉表（左边科目、右边按日期/月份铺开）。"""

    def test_months_cross_year_without_year(self):
        "月份从 10 月跨到次年 2 月 —— 而表头没写年份。"
        rows = [
            [None, "科目"] + [f"{m}月" for m in (10, 11, 12, 1, 2)],
            [None, "销售额", 10, 20, 30, 40, 50],
            [None, "成本", 5, 10, 15, 20, 25],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.axis_kind == "month"
        assert found.axis_count == 5, "跨年那一步断了"
        assert found.date_start_col == "C"

    def test_month_axis_with_total_column_after(self):
        """月份右边还有一列「合计」—— 轴要在合计处停住，不能把它算成一个月。"""
        rows = [
            [None, "科目"] + [f"{m}月" for m in range(1, 5)] + ["合计"],
            [None, "销售额", 10, 20, 30, 40, 100],
            [None, "成本", 5, 10, 15, 20, 50],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.axis_count == 4, "「合计」不是月份，不该并进轴里"

    def test_three_months_is_enough(self):
        """刚好 3 个月 —— 卡在阈值上，要认。"""
        rows = [
            [None, "科目", "1月", "2月", "3月"],
            [None, "销售额", 1, 2, 3],
            [None, "成本", 4, 5, 6],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.axis_count == 3

    def test_days_spanning_month_boundary(self):
        """日期轴跨月（10-30 → 11-01），衔接要顺。"""
        rows = [
            [None, "科目", "10-30", "10-31", "11-01", "11-02"],
            [None, "销售额", 1, 2, 3, 4],
            [None, "成本", 5, 6, 7, 8],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.axis_kind == "day"
        assert found.axis_count == 4

    def test_title_row_above_axis(self):
        """轴那一行上面还有标题行。"""
        rows = [
            [None, "2026 全年销售目标计划表", None, None, None],
            _blank(5),
            [None, "科目", "1月", "2月", "3月"],
            [None, "销售额", 1, 2, 3],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.header_row == 3

    def test_subject_column_before_populated_columns(self):
        "科目列前面还有一列（比如说“序号”），科目列要取对。"
        rows = [
            ["序号", "科目", "1月", "2月", "3月"],
            [1, "销售额", 10, 20, 30],
            [2, "成本", 5, 10, 15],
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.field_col == "B", "序号列是数字，不该被当成科目列"

    def test_axis_not_at_the_far_right_of_scan(self):
        """轴后面还有一堆空列 —— 不该影响轴的长度。"""
        rows = [
            [None, "科目", "1月", "2月", "3月"] + _blank(10),
            [None, "销售额", 1, 2, 3] + _blank(10),
        ]
        found = detect_layout(rows)
        assert found.orientation == "matrix"
        assert found.axis_count == 3


class TestSuspiciousShapes:
    """看着含糊、**不该贸然换读法**的形态。宁可保守，也别静静读错。"""

    def test_two_months_is_not_enough(self):
        rows = [["部门", "1月", "2月"], ["A", 1, 2], ["B", 3, 4]]
        assert detect_layout(rows).orientation == "vertical"

    def test_two_dates_is_not_enough(self):
        rows = [["科目", "10-01", "10-02"], ["销售额", 1, 2]]
        assert detect_layout(rows).orientation == "vertical"

    def test_empty(self):
        found = detect_layout([])
        assert found.orientation == "vertical"
        assert found.confidence == "low"

    def test_all_blank_rows(self):
        found = detect_layout([_blank(5), _blank(5), _blank(5)])
        assert found.orientation == "vertical"

    def test_year_numbers_are_not_a_date_axis(self):
        "一行里是 2024 2025 2026（年份做列名）—— 不该当成日期轴。"
        rows = [
            ["项目", 2024, 2025, 2026],
            ["销售额", 100, 200, 300],
        ]
        found = detect_layout(rows)
        assert found.orientation == "vertical", "年份做列名不是日期轴"


class TestReasonsAreAlwaysGiven:
    """理由**必须**给 —— 它是用户唯一能发现「识别错了」的线索。"""

    @pytest.mark.parametrize(
        "rows",
        [
            [[None, "标题"], ["产品", "数量"], ["杯子", 1]],
            [[None, "科目", "1月", "2月", "3月"], [None, "销售额", 1, 2, 3]],
            [],
        ],
    )
    def test_every_result_explains_itself(self, rows):
        found = detect_layout(rows)
        assert found.reasons, "没有理由的话，界面就没法让用户判断对错"
        assert all(isinstance(r, str) and r for r in found.reasons)
