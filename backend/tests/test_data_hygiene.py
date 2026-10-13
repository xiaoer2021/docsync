"数据卫生：多人维护的在线表格里**必然会遇到**的脏东西。"

from __future__ import annotations

from app.services.normalize.coercions import (
    clean_text,
    infer_transform,
    to_percent,
    to_text,
)


class TestInvisibleCharacters:
    "从网页/钉钉/飞书粘贴过来必带的隐形字符。"

    def test_zero_width_space_removed(self):
        assert clean_text("SKU007\u200b") == "SKU007"

    def test_zero_width_joiner_and_non_joiner(self):
        assert clean_text("A\u200cB\u200dC") == "ABC"

    def test_bom_removed(self):
        assert clean_text("\ufeff订单号") == "订单号"

    def test_direction_marks_removed(self):
        """阿拉伯语/希伯来语环境里粘贴常带方向标记，中文表里纯属噪声。"""
        assert clean_text("\u202a数量\u202c") == "数量"

    def test_two_values_equal_after_cleaning(self):
        """**这条是重点**：清理前后「看起来一样」的两个值，清理后要真的相等。"""
        cleaned = clean_text("订单号\u200b")
        assert cleaned == clean_text("订单号")
        assert cleaned == "订单号"

    def test_normal_text_untouched(self):
        assert clean_text("  订单 金额  ") == "订单 金额"

    def test_nbsp_trimmed_at_edges(self):
        """不换行空格（从 Excel 复制常见）在两端时要去掉。"""
        assert clean_text("\u00a0数量\u00a0") == "数量"


class TestInnerNewlines:
    "格内换行。有人在一个格子里写两行（一行两个单号）。"

    def test_crlf_becomes_space(self):
        assert clean_text("9158\r\n9262") == "9158 9262"

    def test_bare_lf(self):
        assert clean_text("A\nB") == "A B"

    def test_bare_cr(self):
        assert clean_text("A\rB") == "A B"

    def test_multiple_newlines_normalized(self):
        """连续换行不要求折叠成几个空格，关键是**换行符不残留**。"""
        cleaned = clean_text("A\n\n\nB")
        assert cleaned is not None
        assert "\n" not in cleaned and "\r" not in cleaned
        assert cleaned.startswith("A") and cleaned.endswith("B")

    def test_newline_only_cell_is_empty(self):
        assert clean_text("\n") is None
        assert clean_text("\r\n  ") is None

    def test_zero_width_between_cr_and_lf(self):
        """零宽字符可能正好夹在 `\\r` 和 `\\n` 之间 —— 先清字符才能认出这是一个换行。"""
        assert clean_text("A\r\u200b\nB") == "A B"

    def test_to_text_also_cleaned(self):
        """走 to_text 的路径（文本列）同样要干净。"""
        assert to_text("A\r\nB\u200b") == "A B"


class TestMixedPercent:
    "同一列里 `0.15` 和 `15%` 混写 —— **静默差 100 倍**。"

    def test_any_percent_sign_means_percent_column(self):
        assert infer_transform(["0.15", "15%", "0.2"]) == "percent"

    def test_all_percent_still_percent(self):
        assert infer_transform(["15%", "20%"]) == "percent"

    def test_no_percent_is_not_percent_column(self):
        """整列都没有 % —— 不能自作主张除以 100。"""
        assert infer_transform(["15", "20", "25"]) is None

    def test_plain_decimals_not_percent(self):
        assert infer_transform(["0.15", "0.2", "0.3"]) is None

    def test_to_percent_handles_both_forms(self):
        """两种写法都归到同一个口径 —— 这是「整列按百分比」能成立的前提。"""
        assert to_percent("15%") == 0.15
        assert to_percent("0.15") == 0.15

    def test_fullwidth_percent_sign(self):
        """全角 ％ 也算。"""
        assert infer_transform(["15％", "0.2"]) == "percent"
        assert to_percent("15％") == 0.15

    def test_mixed_column_becomes_consistent(self):
        """**这条是重点**：混写的一列，转换之后口径要一致。"""
        values = ["0.15", "15%", "0.2"]
        transform = infer_transform(values)
        assert transform == "percent"
        converted = [to_percent(v) for v in values]
        assert converted == [0.15, 0.15, 0.2], "同一个口径：都在 0~1 之间"
