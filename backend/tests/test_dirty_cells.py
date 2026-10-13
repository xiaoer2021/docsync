"在线表格的脏数据，平台自己扛住 —— 不丢、不停下、不让用户操心类型。"

from __future__ import annotations

from app.services.loader.ddl import abstract_type_for_db, plan_widen_columns
from app.services.loader.dialects import dialect_for
from app.services.normalize.headers import header_key
from app.services.normalize.mapping import ColumnSpec, resolve_columns
from app.services.runner.prepare import (
    DEFAULT_DIRTY_COLUMN,
    SourceData,
    negotiate_type,
    prepare_rows,
)


def build(values, *, col_type="int", target_db="bigint", dirty=DEFAULT_DIRTY_COLUMN):
    return prepare_rows(
        SourceData(header=["金额"], rows=[(i + 2, [v]) for i, v in enumerate(values)]),
        [ColumnSpec(source="金额", target="金额", type=col_type)],
        target_types={"金额": target_db} if target_db else None,
        dirty_column=dirty,
    )


class TestDirtyCellsAreMovedNotDropped:
    """核心：填错的格子搬到「未识别」列，数据还在。"""

    def test_other_rows_survive(self):
        """300 行好数据 + 1 行脏数据 → 全部保留，不是失败。"""
        out = build(["100"] * 300 + ["刷手退款"])
        assert len(out.rows) == 301, "脏格子不该让整批数据消失"
        assert out.rows[0]["金额"] == 100

    def test_dirty_value_is_moved_to_its_own_column(self):
        """原文进「未识别」列 —— 不是丢掉。"""
        out = build(["100", "刷手退款"])
        assert out.rows[0][DEFAULT_DIRTY_COLUMN] is None, "好行不该有脏数据标记"
        assert "刷手退款" in out.rows[1][DEFAULT_DIRTY_COLUMN]
        assert "金额=" in out.rows[1][DEFAULT_DIRTY_COLUMN], "要标出是哪一列的"

    def test_fraction_is_not_rounded_into_integer_column(self):
        out = build(["100", "182.5"])
        assert out.rows[1]["金额"] is None
        assert "182.5" in out.rows[1][DEFAULT_DIRTY_COLUMN]
        assert out.invalid_cells == 1

    def test_dirty_column_is_in_the_output(self):
        out = build(["100", "刷手退款"])
        assert DEFAULT_DIRTY_COLUMN in out.columns

    def test_dirty_column_can_be_renamed(self):
        out = build(["100", "刷手退款"], dirty="备注_问题数据")
        assert "备注_问题数据" in out.columns
        assert "刷手退款" in out.rows[1]["备注_问题数据"]

    def test_dirty_column_can_be_turned_off(self):
        out = build(["100", "刷手退款"], dirty="")
        assert DEFAULT_DIRTY_COLUMN not in out.columns
        assert out.rows[1]["金额"] is None

    def test_empty_cells_are_not_dirty(self):
        """空格子是正常的，不该被当成脏数据。"""
        out = build(["100", None, ""])
        assert DEFAULT_DIRTY_COLUMN not in out.columns, "没有脏数据就不该多这一列"
        assert all(r["金额"] == 100 or r["金额"] is None for r in out.rows)

    def test_several_bad_columns_go_into_one_cell(self):
        out = prepare_rows(
            SourceData(
                header=["金额", "数量"],
                rows=[(2, ["刷手退款", "abc"])] + [(i, ["100", "5"]) for i in range(3, 53)],
            ),
            [
                ColumnSpec(source="金额", target="金额", type="int"),
                ColumnSpec(source="数量", target="数量", type="int"),
            ],
            target_types={"金额": "bigint", "数量": "bigint"},
        )
        cell = out.rows[0][DEFAULT_DIRTY_COLUMN]
        assert "金额=刷手退款" in cell and "数量=abc" in cell
        assert len(out.rows) == 51

    def test_multiple_values_in_one_row_are_joined(self):
        """一行里两列都填错 → 一条记录里两个都记下来。"""
        out = prepare_rows(
            SourceData(
                header=["a", "b"],
                rows=[(2, ["xx", "yy"])] + [(i, ["1", "2"]) for i in range(3, 53)],
            ),
            [
                ColumnSpec(source="a", target="a", type="int"),
                ColumnSpec(source="b", target="b", type="int"),
            ],
            target_types={"a": "bigint", "b": "bigint"},
        )
        cell = out.rows[0][DEFAULT_DIRTY_COLUMN]
        assert "a=xx" in cell and "b=yy" in cell

    def test_clean_table_gets_no_extra_column(self):
        """整张表干干净净 → 不该凭空多一列全是 NULL 的。"""
        out = build(["100", "200"])
        assert DEFAULT_DIRTY_COLUMN not in out.columns
        assert "金额" in out.columns

    def test_all_rows_clean_means_no_dirty_key_either(self):
        out = build(["100", "200"])
        assert all(DEFAULT_DIRTY_COLUMN not in r for r in out.rows)


class TestWholeColumnRetyped:
    "整列大半装不下 → 类型判断错了，自动换掉，不停下。"

    def test_mostly_offending_column_is_retyped(self):
        out = build(["16", "15", "3"] * 40, col_type="bool", target_db="bit")
        assert len(out.retyped_columns) == 1
        item = out.retyped_columns[0]
        assert item["column"] == "金额"
        assert item["from_label"] == "是否"
        assert item["label"] in ("整数", "小数")

    def test_retyped_column_is_not_an_error(self):
        """平台自己处理，不该报错、不该留空 —— 那等于毁掉这列大部分数据。"""
        out = build(["16", "15", "3"] * 40, col_type="bool", target_db="bit")
        assert out.rows, "配错类型的列不该让所有行消失"
        assert all(r["金额"] is not None for r in out.rows)
        assert out.blocked_values == []

    def test_few_offenders_are_moved_not_retyped(self):
        """三成的脏值属于「个别格子填错」，搬家处理。"""
        out = build(["100"] * 70 + ["刷手退款"] * 30)
        assert out.retyped_columns == []
        assert len(out.blocked_values) == 1
        assert out.blocked_values[0]["count"] == 30

    def test_totally_chaotic_column_falls_back_to_text(self):
        """完全混乱没法判断的 → 兜底文本，一格都不丢。"""
        chaotic = ["100", "刷手退款", "2024-01-01", "是", "abc", "3.14"] * 10
        out = build(chaotic)
        assert out.effective_types["金额"] == "text"
        assert all(r["金额"] is not None for r in out.rows)
        assert not out.blocked_values, "文本能装下一切，不该有漏掉的"


class TestTargetColumnWidened:
    """目标表那一列的宽度也跟着放宽 —— 只放宽、不收紧。"""

    def test_int_to_float(self):
        stmts = plan_widen_columns(
            dialect_for("sqlserver"), "t", {"数量": "float"}, existing={"数量": "bigint"}
        )
        assert len(stmts) == 1
        assert "FLOAT(53)" in stmts[0]

    def test_bit_to_int(self):
        stmts = plan_widen_columns(
            dialect_for("sqlserver"), "t", {"空包费": "int"}, existing={"空包费": "bit"}
        )
        assert len(stmts) == 1

    def test_narrowing_is_refused(self):
        """绝不把列改窄 —— 那会丢已有数据。"""
        stmts = plan_widen_columns(
            dialect_for("sqlserver"), "t", {"金额": "int"}, existing={"金额": "nvarchar"}
        )
        assert stmts == []

    def test_already_wide_enough_is_untouched(self):
        stmts = plan_widen_columns(
            dialect_for("sqlserver"), "t", {"金额": "int"}, existing={"金额": "bigint"}
        )
        assert stmts == []

    def test_only_widens(self):
        """只允许往宽了走，反向一步都不做。"""
        stmts = plan_widen_columns(dialect_for("sqlserver"), "t", {"a": "text"}, existing={"a": "bigint"})
        assert len(stmts) == 1, "数值 → 文本是放宽，允许"

    def test_unknown_column_is_skipped(self):
        stmts = plan_widen_columns(dialect_for("sqlserver"), "t", {"新列": "int"}, existing=None)
        assert stmts == []

    def test_date_column_is_not_touched(self):
        stmts = plan_widen_columns(dialect_for("sqlserver"), "t", {"日期": "text"}, existing={"日期": "date"})
        assert stmts == [], "日期列不能被改成文本"


class TestHeaderMatching:
    """列名宽松匹配 —— 各人写法不同不该让映射失效。"""

    def test_spaces_are_ignored(self):
        assert header_key("订单 金额") == header_key("订单金额")

    def test_full_width_brackets(self):
        assert header_key("金额（韩币）") == header_key("金额(韩币)")

    def test_case_insensitive(self):
        assert header_key("SKU") == header_key("sku")

    def test_different_columns_stay_different(self):
        assert header_key("金额") != header_key("订单金额")

    def test_resolve_matches_loosely(self):
        resolved, missing = resolve_columns(["订单 金额"], [ColumnSpec(source="订单金额", target="x")])
        assert not missing and resolved[0].index == 0

    def test_exact_match_still_wins(self):
        resolved, _ = resolve_columns(["金额", "订单 金额"], [ColumnSpec(source="订单 金额", target="x")])
        assert resolved[0].index == 1

    def test_ambiguous_loose_match_is_rejected(self):
        """宽松后一样 → 宁可不配，也不猜错。"""
        resolved, missing = resolve_columns(["金额", "金额 "], [ColumnSpec(source="金 额", target="x")])
        assert missing == ["金 额"] and not resolved

    def test_column_letter_still_works(self):
        resolved, missing = resolve_columns(["a", "b", "c"], [ColumnSpec(source="B", target="x")])
        assert not missing and resolved[0].index == 1


class TestAbstractTypeMapping:
    def test_numeric(self):
        assert abstract_type_for_db("bigint") == "int"
        assert abstract_type_for_db("float") == "float"
        assert abstract_type_for_db("bit") == "bool"

    def test_text(self):
        assert abstract_type_for_db("nvarchar") == "text"

    def test_date(self):
        assert abstract_type_for_db("date") == "date"
        assert abstract_type_for_db("datetime2") == "datetime"

    def test_never_maps_date_to_text(self):
        for t in ("date", "datetime", "datetime2"):
            assert abstract_type_for_db(t) != "text"


class TestExistingBehaviourKept:
    """新建的列保持原来的放宽行为。"""

    def test_widening_chain(self):
        assert negotiate_type("bool", ["0", "1", "16"]) == ("int", True)
        assert negotiate_type("int", ["1.5"]) == ("float", True)

    def test_date_never_auto_widened(self):
        assert negotiate_type("date", ["9.8"]) == ("date", False)
