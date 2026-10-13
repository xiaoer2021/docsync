"分块读取的单元格上限，以及多子表合并。"

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.dingtalk.sheet_reader import (
    MAX_CELLS,
    a1_address,
    assert_range_ok,
    column_count,
    iter_rows,
    rows_per_read,
)
from app.services.runner.prepare import SourceData, build_specs, prepare_rows

API = "https://api.dingtalk.com"
OAUTH = "https://oapi.dingtalk.com"


def make_client() -> DingTalkClient:
    return DingTalkClient(app_id=1, app_key="k", app_secret="s", operator_id="union-1")


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


class TestRangeLimits:
    def test_column_count(self):
        assert column_count("A", "A") == 1
        assert column_count("A", "F") == 6
        assert column_count("A", "Z") == 26

    def test_narrow_table_can_read_many_rows(self):
        assert rows_per_read("A", "F") == 4666

    def test_wide_table_reads_fewer_rows(self):
        assert rows_per_read("A", "Z") == 1076

    def test_ceiling_still_applies(self):
        assert rows_per_read("A", "B", ceiling=2000) == 2000

    def test_never_returns_zero(self):
        assert rows_per_read("A", "ZZ") >= 1

    def test_range_too_large_is_caught_locally(self):
        """别等钉钉报英文错，自己先拦下来。"""
        address = a1_address("A", 1, "Z", 2000)
        with pytest.raises(DingTalkError) as exc:
            assert_range_ok(address, "A", "Z", 1, 2000)
        assert exc.value.code == "RANGE_TOO_LARGE"
        assert "30000" in exc.value.message

        assert "列" in (exc.value.hint or "")

    def test_range_at_limit_passes(self):
        assert_range_ok("A1:Z1000", "A", "Z", 1, 1000)

    def test_limit_constant_is_30000(self):
        assert MAX_CELLS == 30000


class TestIterRowsBatching:
    @respx.mock
    async def test_wide_sheet_splits_by_cells_not_rows(self):
        """26 列时第一批不能是 2000 行 —— 那样会超 30000 格。"""
        _token()
        seen: list[str] = []

        def capture(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={"values": []})

        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(side_effect=capture)

        rows = [
            row
            async for row in iter_rows(
                make_client(),
                "wb1",
                "st1",
                start_row=1,
                col_start="A",
                col_end="Z",
                batch_size=2000,
            )
        ]
        assert rows == []
        assert seen, "应该至少请求过一次"

        assert "A1:Z1076" in seen[0], f"实际请求：{seen[0]}"

    @respx.mock
    async def test_narrow_sheet_uses_ceiling(self):
        _token()
        seen: list[str] = []
        respx.get(url__regex=rf"{API}/v1\.0/doc/workbooks/wb1/sheets/st1/ranges/.*").mock(
            side_effect=lambda req: (seen.append(req.url.path), httpx.Response(200, json={"values": []}))[1]
        )
        _ = [
            row
            async for row in iter_rows(
                make_client(),
                "wb1",
                "st1",
                start_row=1,
                col_start="A",
                col_end="F",
                batch_size=2000,
            )
        ]
        assert "A1:F2000" in seen[0]


class TestMergeSheets:
    HEADER = ["店铺", "产品编码", "金额"]
    SPECS = [
        {"source": "店铺", "target": "店铺", "type": "text"},
        {"source": "产品编码", "target": "产品编码", "type": "text"},
        {"source": "金额", "target": "金额", "type": "float"},
    ]

    def test_merged_rows_carry_their_own_sheet_id(self):
        "合并 4 个店铺 sheet 时，每行要能标出自己来自哪张表。"
        source = SourceData(
            header=self.HEADER,
            rows=[
                (2, ["店铺1", "A001", "100"], "st1"),
                (2, ["店铺2", "A002", "200"], "st2"),
            ],
        )
        out = prepare_rows(
            source,
            build_specs(self.SPECS),
            tag_cfg={"sheet": "来源工作表ID", "fingerprint": "数据指纹"},
            sheet_id="st1",
        )
        assert [r["来源工作表ID"] for r in out.rows] == ["st1", "st2"]

    def test_single_sheet_rows_fall_back_to_task_sheet(self):
        source = SourceData(header=self.HEADER, rows=[(2, ["店铺1", "A001", "100"])])
        out = prepare_rows(
            source,
            build_specs(self.SPECS),
            tag_cfg={"sheet": "来源工作表ID"},
            sheet_id="st-only",
        )
        assert out.rows[0]["来源工作表ID"] == "st-only"

    def test_merge_fingerprint_ignores_sheet_tag(self):
        """指纹不该把「来源工作表」算进去，否则同一个 sheet 换个位置就会被判成变了。"""
        rows = [(2, ["店铺1", "A001", "100"], "st1")]
        a = prepare_rows(
            SourceData(header=self.HEADER, rows=rows),
            build_specs(self.SPECS),
            tag_cfg={"sheet": "来源工作表ID", "fingerprint": "fp"},
        )
        b = prepare_rows(
            SourceData(header=self.HEADER, rows=[(2, ["店铺1", "A001", "100"], "st9")]),
            build_specs(self.SPECS),
            tag_cfg={"sheet": "来源工作表ID", "fingerprint": "fp"},
        )
        assert a.rows[0]["fp"] == b.rows[0]["fp"]
