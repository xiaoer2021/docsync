"执行前把源数据整理成可写行的逻辑。"

from __future__ import annotations

import datetime as dt

import pytest

from app.services.runner.prepare import (
    MappingError,
    SourceData,
    build_specs,
    prepare_rows,
)

HEADER = ["店铺", "产品编码", "订单金额（韩币）", "测评日期"]

RAW = [
    (2, ["星光性感", "A001", "1,000", "2026-10-06"]),
    (3, ["星光性感", "A002", "2,000", "2026-10-06"]),
    (4, ["智安科", "A003", "3,000", "2026-10-05"]),
]

SPECS = [
    {"source": "店铺", "target": "店铺", "type": "text"},
    {"source": "产品编码", "target": "产品编码", "type": "text"},
    {"source": "订单金额（韩币）", "target": "金额", "type": "float"},
    {"source": "测评日期", "target": "日期", "type": "date"},
]


def make_source(rows=None) -> SourceData:
    return SourceData(header=HEADER, rows=list(rows or RAW))


class TestBuildSpecs:
    def test_maps_fields(self):
        specs = build_specs(SPECS)
        assert [s.target for s in specs] == ["店铺", "产品编码", "金额", "日期"]
        assert specs[2].type == "float"

    def test_skips_rows_without_target(self):
        assert build_specs([{"source": "a", "target": ""}]) == []

    def test_default_type_is_text(self):
        assert build_specs([{"source": "a", "target": "a"}])[0].type == "text"


class TestPrepareRows:
    def test_short_dates_use_neighbors_within_the_same_sheet(self):
        source = SourceData(
            header=["测评日期"],
            rows=[
                (1346, [46261], "sheet-a"),
                (1347, [9.8], "sheet-a"),
                (1348, [9.9], "sheet-a"),
                (1359, [46275], "sheet-a"),
                (2, [9.8], "sheet-b"),
            ],
        )
        specs = build_specs([{"source": "测评日期", "target": "测评日期", "type": "date"}])
        out = prepare_rows(source, specs, target_types={"测评日期": "date"})
        assert out.rows[1]["测评日期"] == dt.date(2026, 9, 8)
        assert out.rows[2]["测评日期"] == dt.date(2026, 9, 9)
        assert out.rows[4]["测评日期"] is None
        assert len(out.repaired_dates) == 2

    def test_amount_text_becomes_zero_and_remark(self):
        source = SourceData(
            header=["订单金额（韩币）"],
            rows=[(2, ["属性错误退款"]), (3, ["12.5"])],
        )
        specs = build_specs([{"source": "订单金额（韩币）", "target": "订单金额（韩币）", "type": "float"}])
        out = prepare_rows(
            source,
            specs,
            target_types={"订单金额（韩币）": "bigint"},
            numeric_note_columns=["订单金额（韩币）"],
        )
        assert out.effective_types["订单金额（韩币）"] == "float"
        assert out.rows[0]["订单金额（韩币）"] == 0.0
        assert out.rows[0]["备注"] == "订单金额（韩币）：属性错误退款"
        assert out.rows[1]["订单金额（韩币）"] == 12.5
        assert out.amount_notes == 1
        assert out.invalid_cells == 0
        assert "原始值_未识别" not in out.columns

    def test_basic_mapping(self):
        out = prepare_rows(make_source(), build_specs(SPECS))
        assert len(out.rows) == 3
        assert out.rows[0]["店铺"] == "星光性感"
        assert out.rows[0]["金额"] == 1000.0
        assert out.rows[0]["日期"] == dt.date(2026, 10, 6)

    def test_missing_source_raises(self):
        from app.services.runner.prepare import MappingError

        with pytest.raises(MappingError, match="找不到"):
            prepare_rows(make_source(), build_specs([{"source": "不存在的列", "target": "x"}]))

    def test_no_specs_raises(self):
        from app.services.runner.prepare import MappingError

        with pytest.raises(MappingError):
            prepare_rows(make_source(), [])

    def test_quality_counts_and_blocks_selected_column(self):
        source = make_source(RAW + [(5, ["星光性感", "A004", "刷手退款", "2026-10-06"])])
        out = prepare_rows(
            source,
            build_specs(SPECS),
            target_types={"金额": "float"},
            quality_block_columns=["金额"],
        )
        assert out.invalid_cells == 1
        assert out.bad_rows == 1
        assert out.critical_cells == 1
        assert out.critical_issues[0]["row_no"] == 5
        assert out.rows[-1]["金额"] is None

    def test_optional_dirty_cell_is_reported_without_blocking(self):
        source = make_source(RAW + [(5, ["星光性感", "A004", "刷手退款", "2026-10-06"])])
        out = prepare_rows(source, build_specs(SPECS), target_types={"金额": "float"})
        assert out.invalid_cells == 1
        assert out.critical_cells == 0
        assert "刷手退款" in out.rows[-1]["原始值_未识别"]

    def test_selected_column_cannot_silently_retype_to_text(self):
        source = make_source([(2, ["星光性感", "A001", "刷手退款", "2026-10-06"])])
        out = prepare_rows(source, build_specs(SPECS), quality_block_columns=["金额"])
        assert out.effective_types["金额"] == "text"
        assert out.critical_cells == 1
        assert out.invalid_cells == 1
        assert out.critical_issues[0]["row_no"] == 2


class TestSourceTags:
    def test_default_tags_added(self):
        out = prepare_rows(make_source(), build_specs(SPECS))
        assert "来源行号" in out.columns
        assert "数据指纹" in out.columns
        assert "最后同步时间" in out.columns

        assert [r["来源行号"] for r in out.rows] == [2, 3, 4]

    def test_custom_tag_names(self):
        out = prepare_rows(
            make_source(),
            build_specs(SPECS),
            tag_cfg={"row": "来源行号X", "doc": "来源文档", "fingerprint": "指纹X"},
            doc_node_id="wb123",
        )
        assert "来源行号X" in out.columns
        assert "来源文档" in out.columns
        assert "指纹X" in out.columns
        assert out.rows[0]["来源文档"] == "wb123"

    def test_disabled_tag_not_added(self):
        out = prepare_rows(
            make_source(),
            build_specs(SPECS),
            tag_cfg={"row": "", "fingerprint": "", "last_synced": ""},
        )
        assert out.columns == ["店铺", "产品编码", "金额", "日期"]
        assert out.fingerprint_column is None

    def test_first_synced_is_insert_only(self):
        out = prepare_rows(
            make_source(),
            build_specs(SPECS),
            tag_cfg={"first_synced": "首次同步时间"},
        )
        assert out.insert_only == ["首次同步时间"]

    def test_sheet_tag_uses_sheet_id(self):
        out = prepare_rows(
            make_source(), build_specs(SPECS), tag_cfg={"sheet": "来源工作表ID"}, sheet_id="st9"
        )
        assert out.rows[0]["来源工作表ID"] == "st9"


class TestFingerprint:
    def test_fingerprint_excludes_source_tags(self):
        "关键：指纹只算用户列。"
        morning = prepare_rows(
            make_source(),
            build_specs(SPECS),
            tag_cfg={"fingerprint": "fp", "last_synced": "最后同步时间"},
            now=dt.datetime(2026, 10, 6, 9, 0, 0),
        )
        evening = prepare_rows(
            make_source(),
            build_specs(SPECS),
            tag_cfg={"fingerprint": "fp", "last_synced": "最后同步时间"},
            now=dt.datetime(2026, 10, 6, 21, 0, 0),
        )
        assert morning.rows[0]["fp"] == evening.rows[0]["fp"]
        assert morning.rows[0]["最后同步时间"] != evening.rows[0]["最后同步时间"]

    def test_fingerprint_changes_when_data_changes(self):
        a = prepare_rows(make_source(), build_specs(SPECS), tag_cfg={"fingerprint": "fp"})
        changed = [(2, ["星光性感", "A001", "9,999", "2026-10-06"])]
        b = prepare_rows(make_source(changed), build_specs(SPECS), tag_cfg={"fingerprint": "fp"})
        assert a.rows[0]["fp"] != b.rows[0]["fp"]

    def test_fingerprint_same_across_row_positions(self):
        """同样的数据换个行号，指纹应当一致 —— 指纹描述的是数据本身。"""
        a = prepare_rows(make_source(), build_specs(SPECS), tag_cfg={"fingerprint": "fp"})
        moved = [(99, ["星光性感", "A001", "1,000", "2026-10-06"])]
        b = prepare_rows(make_source(moved), build_specs(SPECS), tag_cfg={"fingerprint": "fp"})
        assert a.rows[0]["fp"] == b.rows[0]["fp"]


class TestDedupe:
    def test_dedupe_keeps_last(self):
        rows = [
            (2, ["星光性感", "A001", "1,000", "2026-10-06"]),
            (3, ["星光性感", "A001", "2,000", "2026-10-06"]),
        ]
        out = prepare_rows(
            make_source(rows),
            build_specs(SPECS),
            dedupe_cfg={"keys": ["产品编码"], "keep": "last"},
        )
        assert len(out.rows) == 1
        assert out.rows[0]["金额"] == 2000.0
        assert out.deduped == 1

        assert out.rows[0]["来源行号"] == 3

    def test_dedupe_ignores_keys_not_in_columns(self):
        out = prepare_rows(
            make_source(),
            build_specs(SPECS),
            dedupe_cfg={"keys": ["列名不存在"], "keep": "last"},
        )
        assert len(out.rows) == 3
        assert out.deduped == 0


class TestAutoWiden:
    "配置的类型装不下实际数据时，自动往宽了让一步。"

    def test_bool_column_with_big_numbers_widens_to_float(self):
        specs = build_specs([{"source": "空包费", "target": "空包费", "type": "bool"}])
        source = SourceData(
            header=["空包费"],
            rows=[(2, ["16"]), (3, ["15"]), (4, ["15.6"]), (5, ["0"])],
        )
        out = prepare_rows(source, specs)
        assert out.effective_types["空包费"] == "float"
        assert out.auto_adjustments and out.auto_adjustments[0]["configured"] == "bool"

        assert [r["空包费"] for r in out.rows] == [16.0, 15.0, 15.6, 0.0]
        assert not out.issue_summary

    def test_text_values_widen_numeric_column_to_text(self):
        """金额列里写了「刷手退款」这类备注 —— 自动按文本存，别把值吃掉。"""
        specs = build_specs([{"source": "订单金额（韩币）", "target": "金额", "type": "float"}])
        source = SourceData(
            header=["订单金额（韩币）"],
            rows=[(2, ["23800"]), (3, ["刷手退款"])],
        )
        out = prepare_rows(source, specs)
        assert out.effective_types["金额"] == "text"
        assert out.rows[1]["金额"] == "刷手退款"

    def test_int_widens_to_float(self):
        specs = build_specs([{"source": "数量", "target": "数量", "type": "int"}])
        source = SourceData(header=["数量"], rows=[(2, ["3"]), (3, ["3.5"])])
        out = prepare_rows(source, specs)
        assert out.effective_types["数量"] == "float"

    def test_fitting_type_is_untouched(self):
        specs = build_specs([{"source": "金额", "target": "金额", "type": "float"}])
        source = SourceData(header=["金额"], rows=[(2, ["1"]), (3, ["2.5"])])
        out = prepare_rows(source, specs)
        assert out.effective_types["金额"] == "float"
        assert out.auto_adjustments == []

    def test_date_column_is_never_auto_widened(self):
        "日期列不自动放宽成文本 —— 那会让整列在 BI 里失去日期类型。"
        specs = build_specs([{"source": "测评日期", "target": "日期", "type": "date"}])
        source = SourceData(header=["测评日期"], rows=[(2, ["2026-10-06"]), (3, ["9.8"])])
        out = prepare_rows(source, specs)
        assert out.effective_types["日期"] == "date"
        assert out.auto_adjustments == []

        assert out.rows[0]["日期"] == dt.date(2026, 10, 6)
        assert out.issue_summary and out.issue_summary[0]["rows"] == 1

    def test_negotiate_type_directly(self):
        from app.services.runner.prepare import negotiate_type

        assert negotiate_type("bool", ["0", "1", "16"]) == ("int", True)
        assert negotiate_type("bool", ["是", "否"]) == ("bool", False)

        assert negotiate_type("int", ["1.5"]) == ("float", True)
        assert negotiate_type("int", ["1", "2", "3.0"]) == ("int", False)
        assert negotiate_type("float", ["abc"]) == ("text", True)
        assert negotiate_type("text", [1, "a"]) == ("text", False)
        assert negotiate_type("date", ["9.8"]) == ("date", False)

    def test_text_in_number_column_does_not_blow_up_the_run(self):
        "金额列里写了「刷手退款」这种备注 —— 只该放宽类型，绝不能把 run 炸掉。"
        from app.services.runner.prepare import negotiate_type

        assert negotiate_type("int", ["23800", "刷手退款"]) == ("text", True)
        assert negotiate_type("float", ["1.5", "属性错误退款"]) == ("text", True)
        assert negotiate_type("int", ["刷手退款"]) == ("text", True)

    def test_text_in_number_column_becomes_a_bad_row_not_a_crash(self):
        specs = build_specs([{"source": "金额", "target": "金额", "type": "int"}])
        source = SourceData(header=["金额"], rows=[(2, ["23800"]), (3, ["刷手退款"])])
        out = prepare_rows(source, specs)

        assert out.effective_types["金额"] == "text"
        assert [r["金额"] for r in out.rows] == ["23800", "刷手退款"]
        assert out.bad_rows == 0


class TestConstantColumns:
    """手动加的列：源文档里没有，值由「空值填」给（批次号、固定标记）。"""

    def test_constant_column_written_every_row(self):
        specs = build_specs(
            [
                {"source": "编码", "target": "编码", "type": "text"},
                {"source": "", "target": "批次号", "type": "text", "default": "B20261006"},
            ]
        )
        source = SourceData(header=["编码"], rows=[(2, ["A1"]), (3, ["A2"])])
        out = prepare_rows(source, specs)
        assert [r["批次号"] for r in out.rows] == ["B20261006", "B20261006"]

        assert out.missing_sources == []

    def test_zero_default_fills_blanks(self):
        """「空值填 0」写进去的必须是数字 0，不是字符串 '0'。"""
        specs = build_specs([{"source": "金额", "target": "金额", "type": "float", "default": "0"}])
        source = SourceData(header=["金额"], rows=[(2, ["12.5"]), (3, [""]), (4, [None])])
        out = prepare_rows(source, specs)
        assert [r["金额"] for r in out.rows] == [12.5, 0.0, 0.0]

    def test_bad_default_is_reported_not_silently_written(self):
        specs = build_specs([{"source": "金额", "target": "金额", "type": "float", "default": "不知道"}])
        source = SourceData(header=["金额"], rows=[(2, [""])])
        out = prepare_rows(source, specs)
        assert any("空值填" in item["reason"] for item in out.issues)

    def test_no_source_and_no_default_is_reported(self):
        """源列空、又没给默认值 —— 这种列写进去全是 NULL，得报出来。"""
        specs = build_specs([{"source": "", "target": "没用的列", "type": "text"}])
        source = SourceData(header=["编码"], rows=[(2, ["A1"])])
        with pytest.raises(MappingError):
            prepare_rows(source, specs)

    def test_constant_column_never_reads_the_last_cell(self):
        "手动加的列下标是 -1，绝不能取到 values[-1]（最后一个元素）。"
        specs = build_specs(
            [
                {"source": "", "target": "批次号", "type": "text", "default": "BATCH"},
                {"source": "编码", "target": "编码", "type": "text"},
            ]
        )
        source = SourceData(header=["编码", "末列"], rows=[(2, ["A1", "别拿我当批次号"])])
        out = prepare_rows(source, specs)
        assert out.rows[0]["批次号"] == "BATCH"


class TestBadRows:
    def test_issue_list_is_capped(self):
        """类型放宽兜不住时（日期列），坏行明细要有上限，不能刷爆。"""
        specs = build_specs([{"source": "日期", "target": "日期", "type": "date"}])
        source = SourceData(header=["日期"], rows=[(i, ["9.8"]) for i in range(2, 60)])
        out = prepare_rows(source, specs, max_issues=5)
        assert len(out.issues) <= 5
        assert out.bad_rows == 58

        assert len(out.issue_summary) == 1
        assert out.issue_summary[0]["rows"] == 58

    def test_required_empty_drops_row(self):
        specs = build_specs([{"source": "产品编码", "target": "产品编码", "type": "text", "required": True}])
        rows = [(2, ["店铺", None, "1", "d"]), (3, ["店铺", "A002", "1", "d"])]
        out = prepare_rows(make_source(rows), specs)
        assert len(out.rows) == 1
        assert out.skipped_required == 1

    def test_all_columns_filled_even_when_missing(self):
        """每行都要有全部键，否则拼 INSERT 时列数会对不上。"""
        rows = [(2, ["店铺"])]
        out = prepare_rows(make_source(rows), build_specs(SPECS))
        for name in out.columns:
            assert name in out.rows[0]
