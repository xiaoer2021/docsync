"""归一化层：类型转换、表头推断、列映射、去重与指纹。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.normalize.coercions import (
    ConvertError,
    convert,
    format_temporal,
    infer_transform,
    infer_type,
    to_bool,
    to_date,
    to_datetime,
    to_number,
    to_percent,
)
from app.services.normalize.headers import infer_header_row, normalize_headers
from app.services.normalize.mapping import (
    ColumnSpec,
    dedupe_rows,
    map_row,
    resolve_columns,
    row_fingerprint,
)


class TestNumbers:
    def test_plain(self):
        assert to_number("1234.5") == 1234.5

    def test_thousands_separator(self):
        assert to_number("1,234,567") == 1234567

    def test_currency_symbols(self):
        assert to_number("₩12,000") == 12000
        assert to_number("¥ 88.80") == 88.8
        assert to_number("$1,299") == 1299

    def test_fullwidth_digits(self):
        assert to_number("１２３") == 123

    def test_empty_tokens(self):
        for token in ("", "-", "—", "/", "无", "N/A", "null", None):
            assert to_number(token) is None

    def test_garbage_raises(self):
        with pytest.raises(ConvertError):
            to_number("abc")

    def test_scientific_and_fractional_forms(self):
        assert to_number("1.5e3") == 1500.0
        assert to_number(".5") == 0.5

    def test_nonfinite_values_are_rejected(self):
        for value in (float("inf"), float("nan"), "1e999"):
            with pytest.raises(ConvertError):
                to_number(value)

    def test_percent(self):
        assert to_percent("12.5%") == 0.125
        assert to_percent("12.5") == 12.5


class TestDates:
    def test_excel_serial(self):
        assert to_date(45658) == dt.date(2025, 1, 1)
        assert to_date(45231) == dt.date(2023, 11, 1)

    def test_excel_serial_roundtrip(self):
        for day in (dt.date(2020, 1, 1), dt.date(2026, 10, 6), dt.date(2030, 12, 31)):
            serial = (dt.datetime(day.year, day.month, day.day) - dt.datetime(1899, 12, 30)).days
            assert to_date(serial) == day

    def test_various_text_formats(self):
        for text in ("2026-10-06", "2026/10/06", "2026.10.06", "20261006", "2026年10月6日"):
            assert to_date(text) == dt.date(2026, 10, 6), text

    def test_datetime_text(self):
        assert to_datetime("2026-10-06 13:20:30") == dt.datetime(2026, 10, 6, 13, 20, 30)

    def test_unix_timestamp_precedes_excel_serial(self):
        timestamp = 1_700_000_000
        assert to_datetime(timestamp) == dt.datetime.fromtimestamp(timestamp)

    def test_ambiguous_slash_date_is_rejected(self):
        with pytest.raises(ConvertError):
            to_date("08/09/2026")

    def test_small_number_not_a_date(self):
        with pytest.raises(ConvertError):
            to_datetime(100)

    def test_garbage_raises(self):
        with pytest.raises(ConvertError):
            to_date("不是日期")


class TestBools:
    @pytest.mark.parametrize("value", ["是", "Y", "true", "1", "√"])
    def test_truthy(self, value):
        assert to_bool(value) is True

    @pytest.mark.parametrize("value", ["否", "N", "false", "0", "×"])
    def test_falsy(self, value):
        assert to_bool(value) is False

    def test_unknown_raises(self):
        with pytest.raises(ConvertError):
            to_bool("也许")


class TestConvert:
    def test_text_trims_and_clips(self):
        assert convert("  abc  ", "text") == "abc"
        assert convert("abcdef", "text", max_length=3) == "abc"

    def test_fullwidth_to_half(self):
        assert convert("ＡＢＣ１２３", "text", transform="fullwidth_to_half") == "ABC123"

    def test_int_rejects_fraction(self):
        with pytest.raises(ConvertError, match="不是整数"):
            convert("1234.6", "int")

    def test_unknown_type(self):
        with pytest.raises(ConvertError):
            convert("x", "不存在的类型")


class TestInfer:
    def test_int_column(self):
        assert infer_type(["1", "2", "3"]) == "float"

    def test_float_column(self):
        assert infer_type(["1.5", "2", "3.25"]) == "float"

    def test_pure_date_column_inferred_as_date(self):
        """没有时分秒就当纯日期 —— 落库是 DATE 列，显示也不带 T00:00:00。"""
        assert infer_type(["2026-10-06", "2026-10-05"]) == "date"
        assert infer_type([45658, 45659]) == "date"

    def test_column_with_time_inferred_as_datetime(self):
        assert infer_type(["2026-10-06 13:20:00", "2026-10-05 08:00:00"]) == "datetime"

    def test_mixed_date_and_datetime_stays_datetime(self):
        assert infer_type(["2026-10-06", "2026-10-05 08:00:00"]) == "datetime"

    def test_format_temporal(self):
        assert format_temporal(dt.datetime(2024, 8, 7, 0, 0, 0)) == "2024-08-07"
        assert format_temporal(dt.datetime(2024, 8, 7, 9, 30, 0)) == "2024-08-07 09:30:00"
        assert format_temporal(dt.date(2024, 8, 7)) == "2024-08-07"
        assert format_temporal("原样") == "原样"
        assert format_temporal(45511) == 45511

    def test_bool_column(self):
        assert infer_type(["是", "否", "是"]) == "bool"

    def test_text_column(self):
        assert infer_type(["产品A", "产品B"]) == "text"

    def test_all_empty(self):
        assert infer_type(["", None, "-"]) == "text"

    def test_percent_transform(self):
        assert infer_transform(["12%", "30%"]) == "percent"


class TestHeaders:
    def test_infer_picks_fullest_row(self):
        rows = [
            ["某公司月度报表", None, None],
            ["产品编码", "产品名称", "数量"],
            ["A001", "苹果", 10],
        ]
        assert infer_header_row(rows) == 2

    def test_infer_skips_leading_blank(self):
        rows = [[None, None], ["a", "b"], [1, 2]]
        assert infer_header_row(rows) == 2

    def test_normalize_fills_blanks(self):
        assert normalize_headers(["产品", None, "数量"]) == ["产品", "列B", "数量"]

    def test_normalize_dedupes(self):
        assert normalize_headers(["名称", "名称"]) == ["名称", "名称_1"]


class TestMapping:
    HEADER = ["店铺", "产品编码", "订单金额（韩币）", "测评日期"]

    def test_resolve_by_name(self):
        specs = [ColumnSpec("产品编码", "产品编码")]
        resolved, missing = resolve_columns(self.HEADER, specs)
        assert missing == []
        assert resolved[0].index == 1

    def test_resolve_by_column_letter(self):
        specs = [ColumnSpec("A", "店铺名")]
        resolved, _ = resolve_columns(self.HEADER, specs)
        assert resolved[0].index == 0

    def test_missing_source_reported(self):
        specs = [ColumnSpec("不存在的列", "x")]
        resolved, missing = resolve_columns(self.HEADER, specs)
        assert resolved == []
        assert missing == ["不存在的列"]

    def test_map_row_converts(self):
        specs = [
            ColumnSpec("店铺", "店铺"),
            ColumnSpec("订单金额（韩币）", "金额", type="float"),
            ColumnSpec("测评日期", "日期", type="date"),
        ]
        resolved, _ = resolve_columns(self.HEADER, specs)
        result = map_row(["星光性感", "A001", "1,234.5", "2026-10-06"], resolved)
        assert result.issues == []
        assert result.values["金额"] == 1234.5
        assert result.values["日期"] == dt.date(2026, 10, 6)

    def test_map_row_records_issue_without_killing_row(self):
        specs = [ColumnSpec("订单金额（韩币）", "金额", type="float")]
        resolved, _ = resolve_columns(self.HEADER, specs)
        result = map_row(["x", "y", "不是数字", "z"], resolved)
        assert result.values["金额"] is None
        assert result.issues and result.issues[0][0] == "金额"

    def test_required_empty_flagged(self):
        specs = [ColumnSpec("产品编码", "编码", required=True)]
        resolved, _ = resolve_columns(self.HEADER, specs)
        result = map_row(["店铺", None, "1", "d"], resolved)
        assert any("必填" in reason for _, reason in result.issues)

    def test_default_used_when_empty(self):
        specs = [ColumnSpec("店铺", "店铺", default="未知")]
        resolved, _ = resolve_columns(self.HEADER, specs)
        result = map_row([None, "a", "b", "c"], resolved)
        assert result.values["店铺"] == "未知"


class TestFingerprintAndDedupe:
    def test_fingerprint_stable_regardless_of_key_order(self):
        a = row_fingerprint({"x": 1, "y": "2"})
        b = row_fingerprint({"y": "2", "x": 1})
        assert a == b

    def test_fingerprint_changes_with_value(self):
        assert row_fingerprint({"x": 1}) != row_fingerprint({"x": 2})

    def test_dedupe_keeps_last(self):
        rows = [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "a", "v": 3}]
        out, dropped = dedupe_rows(rows, ["k"], keep="last")
        assert dropped == 1
        assert {r["k"]: r["v"] for r in out} == {"a": 3, "b": 2}

    def test_dedupe_keeps_first(self):
        rows = [{"k": "a", "v": 1}, {"k": "a", "v": 3}]
        out, _ = dedupe_rows(rows, ["k"], keep="first")
        assert out[0]["v"] == 1

    def test_no_keys_passthrough(self):
        rows = [{"k": "a"}, {"k": "a"}]
        out, dropped = dedupe_rows(rows, [])
        assert len(out) == 2 and dropped == 0
