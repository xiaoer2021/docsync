"横向表（转置）读取。"

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
import respx

from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.dingtalk.sheet_reader import col_to_index, read_transposed

OAUTH = "https://oapi.dingtalk.com"
API = "https://api.dingtalk.com"
RANGE_RE = re.compile(r"/ranges/([A-Z]+\d+):([A-Z]+\d+)$")


def _split(ref: str) -> tuple[int, int]:
    m = re.match(r"^([A-Z]+)(\d+)$", ref)
    assert m, ref
    return col_to_index(m.group(1)), int(m.group(2))


def make_grid(rows: dict[int, dict[int, Any]], *, fill_rows: int = 400, fill_cols: int = 90):
    """按「(列, 行) → 值」的稀疏表造一个假的钉钉区域接口。"""

    def handler(request: httpx.Request) -> httpx.Response:
        m = RANGE_RE.search(unquote(request.url.path))
        if not m:
            return httpx.Response(200, json={"values": []})
        c1, r1 = _split(m.group(1))
        c2, r2 = _split(m.group(2))
        col_last = min(c2, c1 + fill_cols)
        row_last = min(r2, r1 + fill_rows)
        values = []
        for row in range(r1, row_last + 1):
            line = [rows.get(row, {}).get(col) for col in range(c1, col_last + 1)]
            values.append(line)
        return httpx.Response(200, json={"values": values})

    return handler


@pytest.fixture(autouse=True)
def _clear_token_cache():
    from app.services.dingtalk.client import _TOKEN_CACHE

    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


def _token() -> None:
    respx.get(f"{OAUTH}/gettoken").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "access_token": "tok", "expires_in": 7200})
    )


def make_client() -> DingTalkClient:
    return DingTalkClient(app_id=1, app_key="k", app_secret="s", operator_id="union-1")


LAYOUT = {
    1: {1: "1月", 2: "2月", 3: "3月"},
    2: {0: "销售额", 1: 1000, 2: 1200, 3: 1300},
    3: {0: "退款", 1: 100, 2: 120, 3: 130},
}


class TestReadTransposed:
    @respx.mock
    async def test_basic_transpose(self):
        _token()
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(LAYOUT)
        )

        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            data_start_col="B",
            record_name_row=1,
        )

        assert pivot.header == ["记录", "销售额", "退款"]
        assert pivot.field_names == ["销售额", "退款"]

        assert len(pivot.rows) == 3
        assert [r[1] for r in pivot.rows] == [
            ["1月", 1000, 100],
            ["2月", 1200, 120],
            ["3月", 1300, 130],
        ]

    @respx.mock
    async def test_record_column_name_configurable(self):
        _token()
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(LAYOUT)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            data_start_col="B",
            record_name_row=1,
            record_column_name="月份",
        )
        assert pivot.header[0] == "月份"

    @respx.mock
    async def test_falls_back_to_column_letter_without_names(self):
        """没给记录名行时用列号兜底 —— 否则落库后没法定位是哪一列。"""
        _token()
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(LAYOUT)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            data_start_col="B",
            record_name_row=0,
        )
        assert [r[1][0] for r in pivot.rows] == ["B", "C", "D"]

    @respx.mock
    async def test_stops_at_blank_columns(self):
        """横向表右边常有一大片空列，不能一直扫下去。"""
        _token()
        layout = {
            1: {1: "1月", 2: "2月"},
            2: {0: "销售额", 1: 1000, 2: 1200},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            data_start_col="B",
            record_name_row=1,
        )
        assert len(pivot.rows) == 2
        assert pivot.field_names == ["销售额"]

        assert [r[1][0] for r in pivot.rows] == ["1月", "2月"]

    @respx.mock
    async def test_explicit_end_row_and_col(self):
        """显式给了范围就不做自动探测。"""
        _token()
        seen: list[str] = []
        handler = make_grid(LAYOUT)

        def spy(request: httpx.Request) -> httpx.Response:
            seen.append(unquote(request.url.path))
            return handler(request)

        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(side_effect=spy)
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            field_end_row=3,
            data_start_col="B",
            data_end_col="D",
            record_name_row=1,
        )
        assert pivot.header == ["记录", "销售额", "退款"]
        assert len(pivot.rows) == 3

        assert not any("A202" in p for p in seen)

    @respx.mock
    async def test_skips_merged_title_row(self):
        "开头一行合并的大标题：只有 A1 有值，B1 往后因为合并全是空的。"
        _token()
        layout = {
            1: {0: "某公司月度经营数据"},
            2: {1: "1月", 2: "2月", 3: "3月"},
            3: {0: "销售额", 1: 1000, 2: 1200, 3: 1300},
            4: {0: "退款", 1: 100, 2: 120, 3: 130},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=0,
            data_start_col="B",
            record_name_row=2,
        )

        assert pivot.field_names == ["销售额", "退款"]
        assert pivot.header == ["记录", "销售额", "退款"]
        assert [r[1] for r in pivot.rows] == [
            ["1月", 1000, 100],
            ["2月", 1200, 120],
            ["3月", 1300, 130],
        ]

    @respx.mock
    async def test_merged_title_also_skipped_without_record_row(self):
        """记录名那行也没给的时候，范围探测要退回字段行，不能被标题行带偏。"""
        _token()
        layout = {
            1: {0: "标题"},
            2: {0: "销售额", 1: 1000, 2: 1200},
            3: {0: "退款", 1: 100, 2: 120},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(), "wb1", "st1", field_col="A", field_start_row=0, data_start_col="B"
        )
        assert pivot.field_names == ["销售额", "退款"]
        assert len(pivot.rows) == 2

    @respx.mock
    async def test_empty_field_column_raises_with_hint(self):
        "找不到字段名必须报错，不能静默返回空。"
        _token()
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid({})
        )
        with pytest.raises(DingTalkError) as exc:
            await read_transposed(make_client(), "wb1", "st1", field_col="A", data_start_col="B")
        assert exc.value.code == "NO_FIELD_COLUMN"
        assert "字段名" in (exc.value.hint or "")

    @respx.mock
    async def test_field_names_on_the_very_first_row(self):
        """很多横向表第 1 行就是字段名，没有标题行 —— 自动探测要能认出来。"""
        _token()
        layout = {
            1: {0: "销售额", 1: 1000, 2: 1200},
            2: {0: "退款", 1: 100, 2: 120},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=0,
            data_start_col="B",
        )
        assert pivot.header == ["记录", "销售额", "退款"]
        assert len(pivot.rows) == 2

    @respx.mock
    async def test_skips_leading_blank_rows(self):
        """开头有标题行/空行时，自动探测要跳过它们找到字段区。"""
        _token()
        layout = {
            3: {0: "销售额", 1: 1000},
            4: {0: "退款", 1: 100},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(), "wb1", "st1", field_col="A", field_start_row=0, data_start_col="B"
        )
        assert pivot.field_names == ["销售额", "退款"]

    @respx.mock
    async def test_all_blank_data_column_skipped(self):
        """全是空的那一列不该变成一条空记录。"""
        _token()
        layout = {
            1: {1: "1月", 2: "2月", 3: "3月"},
            2: {0: "销售额", 1: 1000, 3: 1300},
        }
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=make_grid(layout)
        )
        pivot = await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            data_start_col="B",
            record_name_row=1,
        )
        assert [r[1][0] for r in pivot.rows] == ["1月", "3月"]

    @respx.mock
    async def test_reads_wide_tables_in_column_chunks(self):
        """列特别多时要按列切块，否则一次请求就超 30000 格。"""
        _token()
        seen: list[str] = []
        handler = make_grid(LAYOUT)

        def spy(request: httpx.Request) -> httpx.Response:
            seen.append(unquote(request.url.path))
            return handler(request)

        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(side_effect=spy)

        await read_transposed(
            make_client(),
            "wb1",
            "st1",
            field_col="A",
            field_start_row=2,
            field_end_row=201,
            data_start_col="B",
            data_end_col="FZ",
        )
        data_reads = [p for p in seen if ":FZ201" in p or ":FZ" in p or "201" in p]

        data_reads = [p for p in data_reads if "2" in p and "201" in p]
        assert len(data_reads) >= 2, f"应该切成多块，实际：{data_reads}"

        for path in data_reads:
            m = RANGE_RE.search(path)
            if not m:
                continue
            c1, r1 = _split(m.group(1))
            c2, r2 = _split(m.group(2))
            assert (c2 - c1 + 1) * (r2 - r1 + 1) <= 30000, path
