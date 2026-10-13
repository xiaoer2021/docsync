"拆多值：一个格子里写了两个值，拆成两行。"

from __future__ import annotations

from app.services.normalize.splitter import (
    SEPARATOR_PRESETS,
    detect_split_columns,
    expand_rows,
    looks_like_single_number,
    separator_indexes,
    split_into_rows,
    split_multivalue,
)


class TestLooksLikeSingleNumber:
    def test_plain_numbers(self):
        assert looks_like_single_number("123")
        assert looks_like_single_number("123.45")
        assert looks_like_single_number("-123.45")

    def test_thousand_separator(self):
        """**这条是关键**：千分位逗号不是分隔符。"""
        assert looks_like_single_number("1,234.56")
        assert looks_like_single_number("1,234,567")
        assert split_multivalue("¥1,234.56", SEPARATOR_PRESETS["comma"]) == ["¥1,234.56"]

    def test_fullwidth_comma(self):
        assert looks_like_single_number("1，234.56")

    def test_percent_and_currency(self):
        "带 % 和货币符号的不用拆 —— 它们本来就没有分隔符。"
        assert split_multivalue("15%", SEPARATOR_PRESETS["comma"]) == ["15%"]
        assert split_multivalue("1234 元", ",") == ["1234 元"]

    def test_two_ids_are_not_a_number(self):
        assert not looks_like_single_number("9158,9262")

    def test_dates_are_not_numbers(self):
        assert not looks_like_single_number("2026-10-01")

    def test_text_is_not_a_number(self):
        assert not looks_like_single_number("阿里巴巴-充电宝")
        assert not looks_like_single_number("")


class TestSplitMultivalue:
    def test_plain_single_value(self):
        assert split_multivalue("杯子", SEPARATOR_PRESETS["comma"]) == ["杯子"]

    def test_comma_splits(self):
        assert split_multivalue("9158,9262", ",") == ["9158", "9262"]

    def test_fullwidth_comma_splits(self):
        assert split_multivalue("9158，9262", SEPARATOR_PRESETS["comma"]) == ["9158", "9262"]

    def test_dun_splits(self):
        assert split_multivalue("杯子、碟子、托盘", "、") == ["杯子", "碟子", "托盘"]

    def test_newline_splits(self):
        assert split_multivalue("A\r\nB", SEPARATOR_PRESETS["newline"]) == ["A", "B"]

    def test_number_with_thousand_separator_not_split(self):
        """**这条是重点**：一千二百三十四块五毛六，不是两个值。"""
        assert split_multivalue("1,234.56", SEPARATOR_PRESETS["comma"]) == ["1,234.56"]

    def test_trailing_separator_does_not_create_empty(self):
        """飞书的关联字段就长这样：结尾多一个分隔符。"""
        assert split_multivalue("A-,B-", ",") == ["A-", "B-"]
        assert split_multivalue("A,,B", ",") == ["A", "B"]

    def test_whitespace_trimmed(self):
        assert split_multivalue(" A , B ", ",") == ["A", "B"]

    def test_non_string_passthrough(self):
        assert split_multivalue(123, ",") == ["123"]
        assert split_multivalue(None, ",") == []
        assert split_multivalue(True, ",") == ["True"]

    def test_empty_separator_means_no_split(self):
        assert split_multivalue("A,B", "") == ["A,B"]

    def test_separator_chars_are_not_regex_metachars(self):
        """分隔符可能含正则元字符（``|``、``.``），不能被当正则解释。"""
        assert split_multivalue("A|B", "|") == ["A", "B"]
        assert split_multivalue("A.B", ".") == ["A", "B"]


class TestSeparatorIndexes:
    "「列名 → 预设」换算成「列下标 → 分隔符」。"

    def test_maps_names_to_indexes(self):
        """注意 `comma` 预设是**半角+全角两个字符**（, 和 ，），不是一个。"""
        assert separator_indexes(["甲", "乙", "丙"], {"乙": "comma"}) == {1: ",，"}

    def test_multiple_columns(self):
        out = separator_indexes(["甲", "乙"], {"甲": "dun", "乙": "newline"})
        assert out == {0: "、", 1: "\r\n"}

    def test_unknown_column_name_ignored(self):
        """配了一个表格里没有的列名 —— 忽略，别报错（可能是改了表头）。"""
        assert separator_indexes(["甲"], {"不存在的列": "comma"}) == {}

    def test_empty_preset_means_no_split(self):
        assert separator_indexes(["甲"], {"甲": ""}) == {}

    def test_none_config(self):
        assert separator_indexes(["甲"], None) == {}


class TestExpandRows:
    """按「列下标 → 分隔符」展开成多行 —— prepare 和预览共用的那份。"""

    def test_expands_one_column(self):
        rows = [["订单1", "9158,9262", "张三"]]
        assert expand_rows(rows, {1: ","}) == [
            ["订单1", "9158", "张三"],
            ["订单1", "9262", "张三"],
        ]

    def test_row_without_split_untouched(self):
        rows = [["A", "单个", "B"]]
        assert expand_rows(rows, {1: ","}) == [["A", "单个", "B"]]

    def test_two_columns_expand_sequentially(self):
        """两列都配了：先展第 0 列，展开后的每一行再展第 1 列。"""
        rows = [["x,y", "1,2"]]
        assert expand_rows(rows, {0: ",", 1: ","}) == [
            ["x", "1"],
            ["x", "2"],
            ["y", "1"],
            ["y", "2"],
        ]

    def test_no_separators_returns_same_object(self):
        rows = [["A"]]
        assert expand_rows(rows, {}) is rows

    def test_column_index_out_of_range_ignored(self):
        assert expand_rows([["A"]], {5: ","}) == [["A"]]

    def test_thousand_separator_not_expanded(self):
        """跟 prepare 一样：`1,234.56` 是一个数，不展开。"""
        rows = [["1,234.56"]]
        assert expand_rows(rows, {0: ","}) == [["1,234.56"]]


class TestDetectSplitColumns:
    "自动认出「一个格子里写了多个值」的列。"

    def test_consistent_two_parts_is_detected(self):
        rows = [["订单1", "9158,9262"], ["订单2", "9270,9281"], ["订单3", "9300,9310"]]
        assert detect_split_columns(["订单号", "单品编码"], rows) == {1: ",，"}

    def test_inconsistent_part_count_not_detected(self):
        "有一行不是 2 份就不认 —— 那是备注里的逗号，不是多值。"
        rows = [["a,b"], ["今天下雨，没发货"], ["c,d,e"]]
        assert detect_split_columns(["备注"], rows) == {}

    def test_number_with_thousand_separator_not_detected(self):
        """`1,234.56` 是钱，不是两个值。"""
        rows = [["1,234.56"], ["2,345.67"], ["3,456.78"]]
        assert detect_split_columns(["金额"], rows) == {}

    def test_space_separated_names_not_detected(self):
        """「张三, 李四」这种带空格的挡得住 —— 一份里有空格就不认。"""
        rows = [["张三, 李四"], ["王五, 赵六"], ["孙七, 周八"]]
        assert detect_split_columns(["负责人"], rows) == {}

    def test_chinese_comma_names_ARE_detected_a_known_limitation(self):
        "⚠ **已知局限，不是 bug，别去「修」它。**"
        rows = [["张三，李四"], ["王五，赵六"], ["孙七，周八"]]
        assert detect_split_columns(["负责人"], rows) == {0: ",，"}

    def test_single_value_column_not_detected(self):
        rows = [["单个"], ["单个"], ["单个"]]
        assert detect_split_columns(["名称"], rows) == {}

    def test_too_few_values_not_detected(self):
        """样本太少是碰运气 —— 至少 3 个非空值才判。"""
        assert detect_split_columns(["编码"], [["a,b"], ["c,d"]]) == {}

    def test_too_many_columns_means_we_are_wrong(self):
        header = [f"列{i}" for i in range(8)]
        rows = [[f"a{i},b{i}" for i in range(8)] for _ in range(4)]
        assert detect_split_columns(header, rows, max_columns=5) == {}

    def test_dun_separator(self):
        rows = [["杯子、碟子"], ["托盘、碗"], ["筷子、勺"]]
        assert detect_split_columns(["品名"], rows) == {0: "、"}

    def test_empty_input(self):
        assert detect_split_columns([], []) == {}
        assert detect_split_columns(["A"], []) == {}

    def test_blank_cells_ignored(self):
        """空值不参与判断 —— 某几行没填不代表这一列不是多值列。"""
        rows = [["a,b"], [None], ["c,d"], [""], ["e,f"]]
        assert detect_split_columns(["编码"], rows) == {0: ",，"}


class TestSplitIntoRows:
    def test_one_column_two_values_becomes_two_rows(self):
        rows = split_into_rows(["订单1", "9158,9262", "张三"], [1], ",")
        assert rows == [
            ["订单1", "9158", "张三"],
            ["订单1", "9262", "张三"],
        ]

    def test_other_columns_copied(self):
        """展开时其余列的值**复制**过去 —— 不然那条记录的信息就缺了。"""
        rows = split_into_rows(["A", "x,y", "2026-10-01"], [1], ",")
        assert all(row[0] == "A" and row[2] == "2026-10-01" for row in rows)

    def test_no_split_returns_original_row(self):
        rows = split_into_rows(["A", "单个", "B"], [1], ",")
        assert rows == [["A", "单个", "B"]]

    def test_columns_not_configured_are_untouched(self):
        """只拆第 0 列 —— 第 1 列原样复制过去。"""
        rows = split_into_rows(["A,B", "C"], [0], ",")
        assert rows == [["A", "C"], ["B", "C"]]

    def test_two_columns_different_counts(self):
        "两列都写了多个：取最长的决定行数，短的**用最后一个补齐**。"
        rows = split_into_rows(["x,y,z", "1,2"], [0, 1], ",")
        assert rows == [["x", "1"], ["y", "2"], ["z", "2"]]

    def test_no_columns_configured(self):
        assert split_into_rows(["A", "B"], [], ",") == [["A", "B"]]

    def test_empty_row(self):
        assert split_into_rows([], [0], ",") == [[]]

    def test_column_index_out_of_range_is_ignored(self):
        assert split_into_rows(["A"], [5], ",") == [["A"]]
