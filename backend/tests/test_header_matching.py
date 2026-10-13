"在线表格的三类脏数据，平台必须自己扛住。"

from __future__ import annotations

from app.services.normalize.headers import header_key
from app.services.normalize.mapping import ColumnSpec, resolve_columns
from app.services.runner.orchestrator import missing_expected_headers


class TestHeaderKey:
    """宽松比较用的列名键。"""

    def test_spaces_are_ignored(self):
        assert header_key("订单 金额") == header_key("订单金额")

    def test_multiple_and_full_width_spaces(self):
        assert header_key("产品  编码") == header_key("产品编码")
        assert header_key("产品\u3000编码") == header_key("产品编码")

    def test_tabs_and_newlines(self):
        assert header_key("产品\t编码") == header_key("产品编码")
        assert header_key("产品\n编码") == header_key("产品编码")

    def test_full_width_brackets(self):
        assert header_key("金额（韩币）") == header_key("金额(韩币)")

    def test_case_insensitive(self):
        assert header_key("SKU") == header_key("sku")

    def test_trailing_decoration(self):
        assert header_key("数量*") == header_key("数量")
        assert header_key("数量：") == header_key("数量")

    def test_different_columns_stay_different(self):
        """宽松归宽松，不能把两列合并成一列。"""
        assert header_key("金额") != header_key("订单金额")
        assert header_key("订单号") != header_key("订单金额")

    def test_empty(self):
        assert header_key(None) == ""
        assert header_key("") == ""

    def test_header_check_uses_mapping_normalization(self):
        assert missing_expected_headers(["订单金额", "SKU"], ["订单 金额", "sku"]) == []

    def test_header_check_rejects_ambiguous_loose_match(self):
        assert missing_expected_headers(["订单金额"], ["订单 金额", "订单金额 "]) == ["订单金额"]


class TestInferHeaderRow:
    "表头行推断。"

    def test_normal_table_picks_first_row(self):
        from app.services.normalize.headers import infer_header_row

        rows = [["产品编码", "产品名"], ["A1", "杯子"], ["A2", "碟子"]]
        assert infer_header_row(rows) == 1

    def test_title_row_skipped(self):
        from app.services.normalize.headers import infer_header_row

        rows = [
            [None, "2026 全年销售目标计划表", None],
            ["部门", "计划", "人数"],
            ["A 部门", 800, 11],
        ]
        assert infer_header_row(rows) == 2

    def test_data_row_denser_than_header(self):
        "**数据行比表头行还满**时，不能选数据行。"
        from app.services.normalize.headers import infer_header_row

        rows = [
            [None, "💰 2026 全年销售目标计划表", None, None],
            [None, None, None, None],
            [None, "部门", "全年计划", "员工人数"],
            [None, "A 部门", 800, 11],
            [None, "B 部门", 300, 6],
        ]
        assert infer_header_row(rows) == 3

    def test_all_numeric_header_still_works(self):
        """表头全是数字（年份做列名）时，退回到「非空格子数」也要能用。"""
        from app.services.normalize.headers import infer_header_row

        rows = [["统计"], [2024, 2025, 2026], [1, 2, 3]]
        assert infer_header_row(rows) == 2

    def test_empty_gives_start_row(self):
        from app.services.normalize.headers import infer_header_row

        assert infer_header_row([]) == 1
        assert infer_header_row([], start_row=3) == 3


class TestResolveColumnsLoosely:
    """映射落地：精确匹配优先，匹配不到才宽松匹配。"""

    def spec(self, source: str, target: str = "x") -> ColumnSpec:
        return ColumnSpec(source=source, target=target)

    def test_exact_match_still_wins(self):
        header = ["金额", "订单 金额"]
        resolved, missing = resolve_columns(header, [self.spec("订单 金额")])
        assert not missing
        assert resolved[0].index == 1, "精确匹配必须优先，不能被宽松匹配抢走"

    def test_space_difference_still_matches(self):
        """各人写法不同不该让映射失效 —— 这是「填这里下次又跑那里去」的根源。"""
        resolved, missing = resolve_columns(["订单 金额"], [self.spec("订单金额")])
        assert not missing
        assert resolved[0].index == 0

    def test_full_width_bracket_matches(self):
        resolved, missing = resolve_columns(["金额（韩币）"], [self.spec("金额(韩币)")])
        assert not missing

    def test_case_difference_matches(self):
        resolved, missing = resolve_columns(["SKU"], [self.spec("sku")])
        assert not missing

    def test_ambiguous_loose_match_is_rejected(self):
        """两个列名宽松后一样（「金额」和「金额 」）→ 宁可不配，也不猜。"""
        resolved, missing = resolve_columns(["金额", "金额 "], [self.spec("金 额")])
        assert missing == ["金 额"]
        assert not resolved

    def test_truly_missing_column_still_reported(self):
        resolved, missing = resolve_columns(["产品编码"], [self.spec("订单号")])
        assert missing == ["订单号"]

    def test_column_letter_still_works(self):
        resolved, missing = resolve_columns(["a", "b", "c"], [self.spec("B")])
        assert not missing
        assert resolved[0].index == 1
