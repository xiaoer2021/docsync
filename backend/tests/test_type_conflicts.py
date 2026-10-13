"写入前的类型冲突检查。"

from __future__ import annotations

from app.services.loader.ddl import find_type_conflicts


class TestFindTypeConflicts:
    def test_text_into_bigint_is_a_conflict(self):
        conflicts = find_type_conflicts({"产品选项ID": "text"}, {"产品选项ID": "bigint"})
        assert len(conflicts) == 1
        assert conflicts[0]["column"] == "产品选项ID"
        assert conflicts[0]["existing"] == "bigint"

    def test_text_into_nvarchar_is_fine(self):
        assert find_type_conflicts({"产品名": "text"}, {"产品名": "nvarchar"}) == []

    def test_text_into_date_is_a_conflict(self):
        conflicts = find_type_conflicts({"测评日期": "text"}, {"测评日期": "date"})
        assert len(conflicts) == 1

    def test_no_existing_columns_means_no_conflict(self):
        """表还不存在 —— 会按实际类型新建，没有冲突可言。"""
        assert find_type_conflicts({"a": "text"}, None) == []

    def test_column_not_in_target_is_skipped(self):
        """映射了但目标表还没有这一列 —— 会自动补列，不是冲突。"""
        assert find_type_conflicts({"新列": "text"}, {"别的列": "bigint"}) == []

    def test_matching_numeric_types_are_fine(self):
        assert find_type_conflicts({"金额": "int"}, {"金额": "bigint"}) == []
        assert find_type_conflicts({"汇率": "float"}, {"汇率": "float"}) == []

    def test_case_insensitive_db_type(self):
        """SQL Server 的 DATA_TYPE 是小写，但别指望它永远是小写。"""
        conflicts = find_type_conflicts({"x": "text"}, {"x": "BIGINT"})
        assert len(conflicts) == 1

    def test_decimal_and_bit_are_conflicts(self):
        for db_type in ("decimal", "numeric", "bit", "real", "money", "datetime2"):
            assert find_type_conflicts({"c": "text"}, {"c": db_type}), db_type

    def test_json_into_numeric_is_a_conflict(self):
        assert find_type_conflicts({"c": "json"}, {"c": "bigint"})

    def test_reports_wanted_and_existing(self):
        c = find_type_conflicts({"c": "text"}, {"c": "bigint"})[0]
        assert c["wanted"] == "text"
        assert c["existing"] == "bigint"
