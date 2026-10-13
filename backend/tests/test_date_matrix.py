from __future__ import annotations

import pytest

from app.services.dingtalk import sheet_reader
from app.services.dingtalk.errors import DingTalkError


@pytest.mark.asyncio
async def test_date_matrix_reads_dates_and_ignores_monthly_total(monkeypatch):
    async def fake_range(_client, _book, _sheet, _address):
        return [[46296, 46297, None]]

    async def fake_rows(*_args, **_kwargs):
        yield 5, ["实际销售额", 125579.47, 22391.04, "#DIV/0!"]
        yield 6, ["转化率", None, "0%%", None]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    monkeypatch.setattr(sheet_reader, "iter_rows", fake_rows)
    result = await sheet_reader.read_date_matrix(None, "book", "sheet")
    assert result.header == ["日期", "经营科目", "数值"]
    assert result.rows == [
        (5, ["2026-10-01", "实际销售额", 22391.04]),
        (5, ["2026-10-02", "实际销售额", 0.0]),
        (6, ["2026-10-01", "转化率", 0.0]),
    ]

    assert result.formula_errors == ["F5: #DIV/0!"]
    assert result.corrected_zero_percent == 1


@pytest.mark.asyncio
async def test_date_matrix_rejects_missing_date(monkeypatch):
    async def fake_range(_client, _book, _sheet, _address):
        return [[46296, 46298]]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    with pytest.raises(DingTalkError, match="不连续"):
        await sheet_reader.read_date_matrix(None, "book", "sheet")


_MONTH_CONFIG = dict(header_row=4, data_start_row=5, field_col="B", date_start_col="G")


@pytest.mark.asyncio
async def test_date_matrix_accepts_month_axis(monkeypatch):
    "右边铺的是 `1月 2月…` 而不是逐日日期时，照样能读。"

    async def fake_range(_client, _book, _sheet, _address):
        return [["1月", "2月", "3月", None]]

    async def fake_rows(*_args, **_kwargs):
        yield 5, ["A 部门", None, None, None, None, 45, 44, 51]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    monkeypatch.setattr(sheet_reader, "iter_rows", fake_rows)
    result = await sheet_reader.read_date_matrix(None, "book", "sheet", **_MONTH_CONFIG)

    assert result.header == ["月份", "经营科目", "数值"]
    assert result.date_count == 3

    assert [row[1][0] for row in result.rows] == ["01月", "02月", "03月"]


@pytest.mark.asyncio
async def test_date_matrix_month_axis_crosses_year(monkeypatch):
    "月份跨年（10月→2月）而表头**没写年份**时不能断。"

    async def fake_range(_client, _book, _sheet, _address):
        return [["10月", "11月", "12月", "1月", "2月"]]

    async def fake_rows(*_args, **_kwargs):
        yield 5, ["销售额", None, None, None, None, 10, 20, 30, 40, 50]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    monkeypatch.setattr(sheet_reader, "iter_rows", fake_rows)
    result = await sheet_reader.read_date_matrix(None, "book", "sheet", **_MONTH_CONFIG)

    assert result.date_count == 5, "跨年那一步断了"
    assert [row[1][0] for row in result.rows] == ["10月", "11月", "12月", "01月", "02月"]


@pytest.mark.asyncio
async def test_date_matrix_month_axis_stops_at_total_column(monkeypatch):
    """月份右边一列「合计」—— 轴要在它那儿停，不能被算成一个月。"""

    async def fake_range(_client, _book, _sheet, _address):
        return [["1月", "2月", "3月", "合计"]]

    async def fake_rows(*_args, **_kwargs):
        yield 5, ["销售额", None, None, None, None, 10, 20, 30, 60]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    monkeypatch.setattr(sheet_reader, "iter_rows", fake_rows)
    result = await sheet_reader.read_date_matrix(None, "book", "sheet", **_MONTH_CONFIG)

    assert result.date_count == 3, "「合计」不是月份"
    assert [row[1][0] for row in result.rows] == ["01月", "02月", "03月"]


@pytest.mark.asyncio
async def test_date_matrix_month_axis_with_year(monkeypatch):
    """写了年份就用 `2026-01` 这种形式。"""

    async def fake_range(_client, _book, _sheet, _address):
        return [["2026-01", "2026-02"]]

    async def fake_rows(*_args, **_kwargs):
        yield 5, ["科目", None, None, None, None, 1, 2]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    monkeypatch.setattr(sheet_reader, "iter_rows", fake_rows)
    result = await sheet_reader.read_date_matrix(None, "book", "sheet", **_MONTH_CONFIG)
    assert [row[1][0] for row in result.rows] == ["2026-01", "2026-02"]


@pytest.mark.asyncio
async def test_date_matrix_month_axis_must_be_consecutive(monkeypatch):
    """月份断了也要报错 —— 跟日期一样，那是配置错了，不能静静读错。"""

    async def fake_range(_client, _book, _sheet, _address):
        return [["1月", "2月", "5月"]]

    monkeypatch.setattr(sheet_reader, "read_range", fake_range)
    with pytest.raises(DingTalkError, match="月份表头不连续"):
        await sheet_reader.read_date_matrix(None, "book", "sheet", **_MONTH_CONFIG)
