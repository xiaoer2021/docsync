"""跳过 / 替换规则：跳整行、把某个格子的值换掉。"""

from __future__ import annotations

from app.services.normalize.rules import apply_rules, parse_rules

HEADER = ["月份", "经营科目", "金额", "备注"]


class TestParseRules:
    def test_drops_half_filled_rules(self):
        """界面上刚点「加一条」还没填完的半截规则不该让预览报错。"""
        raw = [
            {"column": "金额", "match": "", "action": "replace", "value": "0"},
            {"column": "", "match": "总计", "action": ""},
            {"column": "", "match": "总计", "action": "skip"},
            "不是字典",
        ]
        parsed = parse_rules(raw)
        assert len(parsed) == 1
        assert parsed[0]["action"] == "skip"

    def test_not_a_list(self):
        assert parse_rules(None) == []
        assert parse_rules({"a": 1}) == []


class TestSkip:
    def test_skip_any_column(self):
        rows = [
            ["1月", "收入", "100", "正常"],
            ["合计", "", "100", ""],
        ]
        result = apply_rules(rows, HEADER, [{"match": "总计", "action": "skip"}])
        assert len(result.rows) == 2
        result = apply_rules(rows, HEADER, [{"match": "合计", "action": "skip"}])
        assert len(result.rows) == 1
        assert result.skipped_rows == [2]

    def test_skip_substring(self):
        """「月度总计」也要跳 —— 表里不会只写「总计」两个字。"""
        rows = [["1月", "月度总计", "100", ""]]
        result = apply_rules(rows, HEADER, [{"match": "总计", "action": "skip"}])
        assert result.skipped_rows == [1]

    def test_skip_only_in_named_column(self):
        """限定列以后，别的列写同样的词不该跳。"""
        rows = [["总计", "收入", "100", ""]]
        rules = [{"column": "经营科目", "match": "总计", "action": "skip"}]
        assert apply_rules(rows, HEADER, rules).skipped_rows == []

    def test_skip_uses_loose_column_match(self):
        """列名比对是宽松的：有多余空格、全角括号也算同一列。"""
        rows = [["a", "b", "c", "d"]]
        rules = [{"column": " 金额 ", "match": "c", "action": "skip"}]
        assert apply_rules(rows, HEADER, rules).skipped_rows == [1]


class TestReplace:
    def test_replace_placeholder_with_zero(self):
        rows = [["1月", "收入", "-", ""]]
        rules = [{"column": "金额", "match": "-", "action": "replace", "value": "0"}]
        result = apply_rules(rows, HEADER, rules)
        assert result.rows[0] == ["1月", "收入", "0", ""]
        assert result.replaced_cells == 1
        assert result.hits[0].before == "-"

    def test_replace_any_column(self):
        """不填列 = 任意列都换。"""
        rows = [["-", "-", "-", "-"]]
        rules = [{"match": "-", "action": "replace", "value": ""}]
        result = apply_rules(rows, HEADER, rules)
        assert result.rows[0] == ["", "", "", ""]
        assert result.replaced_cells == 4

    def test_replace_is_whole_cell(self):
        """整格替换，不是只换掉匹配到的那一段 —— 用户就是要这格别带单位。"""
        rows = [["1月", "收入", "1,234 元", ""]]
        rules = [{"column": "金额", "match": "元", "action": "replace", "value": "0"}]
        assert apply_rules(rows, HEADER, rules).rows[0][2] == "0"

    def test_replace_to_empty_string(self):
        rows = [["1月", "收入", "N/A", ""]]
        rules = [{"column": "金额", "match": "N/A", "action": "replace", "value": ""}]
        assert apply_rules(rows, HEADER, rules).rows[0][2] == ""

    def test_later_rule_overrides_earlier(self):
        rows = [["1月", "收入", "N/A", ""]]
        rules = [
            {"column": "金额", "match": "N/A", "action": "replace", "value": "0"},
            {"column": "金额", "match": "0", "action": "replace", "value": "1"},
        ]
        assert apply_rules(rows, HEADER, rules).rows[0][2] == "1"

    def test_skip_wins_over_replace(self):
        """整行被跳过之后，替换它没有意义 —— 别报「替换了 3 格」然后又没写。"""
        rows = [["合计", "-", "-", "-"]]
        rules = [
            {"match": "合计", "action": "skip"},
            {"match": "-", "action": "replace", "value": "0"},
        ]
        result = apply_rules(rows, HEADER, rules)
        assert result.rows == []
        assert result.replaced_cells == 0
        assert result.skipped_rows == [1]


class TestBasics:
    def test_no_rules_copies_rows(self):
        rows = [["a", "b"]]
        result = apply_rules(rows, HEADER, [])
        assert result.rows == [["a", "b"]]
        assert result.hits == []
        assert result.rows[0] is not rows[0]

    def test_row_numbers_use_first_row(self):
        rows = [["合计", "", "", ""]]
        rules = [{"match": "合计", "action": "skip"}]
        assert apply_rules(rows, HEADER, rules, first_row=5).skipped_rows == [5]

    def test_header_shorter_than_row_is_safe(self):
        rows = [["a", "b", "c", "d", "e"]]
        rules = [{"match": "e", "action": "replace", "value": "x"}]
        result = apply_rules(rows, ["列1"], rules)
        assert result.rows[0][4] == "x"
