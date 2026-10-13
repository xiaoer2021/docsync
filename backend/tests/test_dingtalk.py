"""钉钉接入层的单元测试（用 respx 回放响应）。"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.dingtalk import aitable_reader, contact, sheet_reader
from app.services.dingtalk.client import _TOKEN_CACHE, DingTalkClient, get_access_token
from app.services.dingtalk.errors import DingTalkError, is_permission_error
from app.services.dingtalk.urls import DocRefError, parse_doc_ref

OAUTH = "https://oapi.dingtalk.com"
API = "https://api.dingtalk.com"


@pytest.fixture(autouse=True)
def _clear_token_cache():
    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


def make_client(app_id: int = 1, operator: str = "union-1") -> DingTalkClient:
    return DingTalkClient(app_id=app_id, app_key="key", app_secret="secret", operator_id=operator)


def mock_token(router: respx.Router, token: str = "tok-1") -> None:
    router.get(f"{OAUTH}/gettoken").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "access_token": token, "expires_in": 7200})
    )


class TestParseDocRef:
    def test_nodes_url(self):
        ref = parse_doc_ref("https://alidocs.dingtalk.com/i/nodes/oP0MAxxxxxYmDO")
        assert ref.node_id == "oP0MAxxxxxYmDO"
        assert ref.source_url is not None

    def test_url_with_iframe_query(self):
        ref = parse_doc_ref(
            "https://alidocs.dingtalk.com/i/nodes/pwkXXXX?iframeQuery=sheetId%3Dst123%26viewId%3Dv1"
        )
        assert ref.node_id == "pwkXXXX"
        assert ref.sub_id_hint == "st123"

    def test_url_with_trailing_params(self):
        ref = parse_doc_ref("https://alidocs.dingtalk.com/i/nodes/abc123XYZ?utm_source=portal")
        assert ref.node_id == "abc123XYZ"

    def test_bare_id(self):
        ref = parse_doc_ref("  abc123XYZ  ")
        assert ref.node_id == "abc123XYZ"
        assert ref.source_url is None

    def test_link_embedded_in_text(self):
        ref = parse_doc_ref("文档在这里 https://alidocs.dingtalk.com/i/nodes/n1 你看看")
        assert ref.node_id == "n1"

    def test_unknown_url_rejected(self):
        with pytest.raises(DocRefError, match="认不出"):
            parse_doc_ref("https://example.com/foo/bar")

    def test_empty_rejected(self):
        with pytest.raises(DocRefError):
            parse_doc_ref("   ")


class TestA1:
    def test_col_roundtrip(self):
        for index, letters in [(0, "A"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA")]:
            assert sheet_reader.index_to_col(index) == letters
            assert sheet_reader.col_to_index(letters) == index

    def test_lowercase_input(self):
        assert sheet_reader.col_to_index("c") == 2

    def test_bad_column(self):
        with pytest.raises(ValueError):
            sheet_reader.col_to_index("A1")

    def test_address(self):
        assert sheet_reader.a1_address("a", 2, "f", 2001) == "A2:F2001"


class TestSimplify:
    def test_scalar_passthrough(self):
        assert aitable_reader.simplify(32) == 32
        assert aitable_reader.simplify("文本") == "文本"
        assert aitable_reader.simplify(None) is None

    def test_person_like_dict_takes_name(self):
        assert aitable_reader.simplify({"name": "张三", "unionId": "u1"}) == "张三"

    def test_list_of_scalars_joined(self):
        assert aitable_reader.simplify(["A", "B", "C"]) == "A、B、C"

    def test_list_of_dicts_to_json(self):
        out = aitable_reader.simplify([{"name": "张三"}, {"name": "李四"}])
        assert out == "张三、李四"

    def test_unknown_dict_kept_as_json(self):
        out = aitable_reader.simplify({"foo": "bar"})
        assert out is not None and "foo" in out

    def test_empty_list(self):
        assert aitable_reader.simplify([]) is None


class TestClient:
    @respx.mock
    async def test_token_fetch_and_cache(self):
        route = respx.get(f"{OAUTH}/gettoken").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "access_token": "t1", "expires_in": 7200})
        )
        first = await get_access_token(app_id=1, app_key="k", app_secret="s")
        second = await get_access_token(app_id=1, app_key="k", app_secret="s")
        assert first == second == "t1"
        assert route.call_count == 1, "第二次应该走缓存，不该再打接口"

    @respx.mock
    async def test_token_error_raises(self):
        respx.get(f"{OAUTH}/gettoken").mock(
            return_value=httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid appsecret"})
        )
        with pytest.raises(DingTalkError) as exc:
            await get_access_token(app_id=2, app_key="k", app_secret="bad")
        assert exc.value.errcode == 40001
        assert exc.value.hint, "应该带上修复建议"

    @respx.mock
    async def test_empty_token_rejected(self):
        respx.get(f"{OAUTH}/gettoken").mock(return_value=httpx.Response(200, json={"errcode": 0}))
        with pytest.raises(DingTalkError, match="access_token"):
            await get_access_token(app_id=3, app_key="k", app_secret="s")

    @respx.mock
    async def test_business_error_carries_hint(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            return_value=httpx.Response(
                403,
                json={
                    "code": "forbidden.accessDenied",
                    "message": "The operator has no permission.",
                },
            )
        )
        with pytest.raises(DingTalkError) as exc:
            await sheet_reader.list_sheets(make_client(), "wb1")
        assert exc.value.code == "forbidden.accessDenied"
        assert "协作者" in (exc.value.hint or "")

    @respx.mock
    async def test_permission_hint_detection(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            return_value=httpx.Response(
                403,
                json={
                    "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                    "message": "no permission",
                },
            )
        )
        with pytest.raises(DingTalkError) as exc:
            await sheet_reader.list_sheets(make_client(), "wb1")
        assert is_permission_error(exc.value)
        assert "Document.Workbook.Read" in (exc.value.hint or "")

    @respx.mock
    async def test_retry_then_success(self):
        mock_token(respx.mock)
        route = respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            side_effect=[
                httpx.Response(503, json={"code": "serviceBusy", "message": "busy"}),
                httpx.Response(200, json={"value": [{"id": "s1", "name": "Sheet1"}]}),
            ]
        )
        client = DingTalkClient(app_id=1, app_key="k", app_secret="s", operator_id="union-1", max_retries=2)
        sheets = await sheet_reader.list_sheets(client, "wb1")
        assert [s.id for s in sheets] == ["s1"]
        assert route.call_count == 2

    @respx.mock
    async def test_missing_operator_refused_before_any_call(self):
        """没有操作人就别去打钉钉 —— 只会换回一个含混的「找不到」。"""
        route = respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        client = DingTalkClient(app_id=1, app_key="k", app_secret="s")
        with pytest.raises(DingTalkError) as exc:
            await sheet_reader.list_sheets(client, "wb1")
        assert exc.value.code == "MISSING_OPERATOR"
        assert route.call_count == 0
        assert "操作人" in (exc.value.hint or "")

    @respx.mock
    async def test_operator_id_sent(self):
        mock_token(respx.mock)
        route = respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        await sheet_reader.list_sheets(make_client(operator="union-9"), "wb1")
        assert route.calls[0].request.url.params["operatorId"] == "union-9"


class TestSheetReader:
    @respx.mock
    async def test_list_sheets(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets").mock(
            return_value=httpx.Response(
                200,
                json={"value": [{"id": "st1", "name": "星光性感"}, {"id": "st2", "name": "智安科"}]},
            )
        )
        sheets = await sheet_reader.list_sheets(make_client(), "wb1")
        assert [(s.id, s.name) for s in sheets] == [("st1", "星光性感"), ("st2", "智安科")]

    @respx.mock
    async def test_iter_rows_keeps_excel_row_numbers(self):
        mock_token(respx.mock)

        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets/st1/ranges/A2%3AC4").mock(
            return_value=httpx.Response(
                200,
                json={
                    "values": [
                        ["a1", "b1", "c1"],
                        [None, "", None],
                        ["a3", "b3", "c3"],
                    ]
                },
            )
        )

        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets/st1/ranges/A5%3AC7").mock(
            return_value=httpx.Response(200, json={"values": []})
        )
        client = make_client()
        rows = [
            (row_no, values)
            async for row_no, values in sheet_reader.iter_rows(
                client,
                "wb1",
                "st1",
                start_row=2,
                col_start="A",
                col_end="C",
                batch_size=3,
            )
        ]
        assert [r[0] for r in rows] == [2, 4], "空行要跳过，但行号必须保留表格里的原始行号"
        assert rows[0][1][0] == "a1"

    @respx.mock
    async def test_iter_rows_paginates(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets/st1/ranges/A2%3AB3").mock(
            return_value=httpx.Response(200, json={"values": [["a", "b"], ["c", "d"]]})
        )
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets/st1/ranges/A4%3AB5").mock(
            return_value=httpx.Response(200, json={"values": [["e", "f"]]})
        )
        rows = [
            (no, values)
            async for no, values in sheet_reader.iter_rows(
                make_client(),
                "wb1",
                "st1",
                start_row=2,
                col_start="A",
                col_end="B",
                batch_size=2,
            )
        ]
        assert [r[0] for r in rows] == [2, 3, 4]

    @respx.mock
    async def test_iter_rows_respects_limit(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/doc/workbooks/wb1/sheets/st1/ranges/A2%3AA4").mock(
            return_value=httpx.Response(200, json={"values": [["a"], ["b"], ["c"]]})
        )
        rows = [
            row
            async for row in sheet_reader.iter_rows(
                make_client(),
                "wb1",
                "st1",
                start_row=2,
                col_start="A",
                col_end="A",
                batch_size=3,
                limit=2,
            )
        ]
        assert len(rows) == 2


class TestAitableReader:
    @respx.mock
    async def test_list_tables(self):
        mock_token(respx.mock)
        respx.get(f"{API}/v1.0/notable/bases/base1/sheets").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "tb1", "name": "数据表"}]})
        )
        tables = await aitable_reader.list_tables(make_client(), "base1")
        assert [(t.id, t.name) for t in tables] == [("tb1", "数据表")]

    @respx.mock
    async def test_iter_records_paginates_by_cursor(self):
        mock_token(respx.mock)
        route = respx.post(f"{API}/v1.0/notable/bases/base1/sheets/tb1/records/list").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "hasMore": True,
                        "nextToken": "cursor-2",
                        "records": [{"id": "r1", "fields": {"数字": 1, "人员": {"name": "张三"}}}],
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "hasMore": False,
                        "records": [{"id": "r2", "fields": {"数字": 2}}],
                    },
                ),
            ]
        )
        records = [r async for r in aitable_reader.iter_records(make_client(), "base1", "tb1")]
        assert [r.id for r in records] == ["r1", "r2"]
        assert records[0].fields["人员"] == "张三"

        second_body = route.calls[1].request.content.decode()
        assert "cursor-2" in second_body

    @respx.mock
    async def test_iter_records_stops_when_no_more(self):
        mock_token(respx.mock)
        respx.post(f"{API}/v1.0/notable/bases/base1/sheets/tb1/records/list").mock(
            return_value=httpx.Response(200, json={"hasMore": False, "records": []})
        )
        records = [r async for r in aitable_reader.iter_records(make_client(), "base1", "tb1")]
        assert records == []

    @respx.mock
    async def test_iter_records_respects_limit(self):
        mock_token(respx.mock)
        respx.post(f"{API}/v1.0/notable/bases/base1/sheets/tb1/records/list").mock(
            return_value=httpx.Response(
                200,
                json={"hasMore": True, "nextToken": "x", "records": [{"id": "r1", "fields": {}}]},
            )
        )
        records = [r async for r in aitable_reader.iter_records(make_client(), "base1", "tb1", limit=1)]
        assert len(records) == 1


class TestContact:
    @respx.mock
    async def test_resolve_by_mobile(self):
        mock_token(respx.mock)
        respx.post(f"{OAUTH}/topapi/v2/user/getbymobile").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "result": {"userid": "u1"}})
        )
        respx.post(f"{OAUTH}/topapi/v2/user/get").mock(
            return_value=httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "result": {
                        "userid": "u1",
                        "unionid": "union-abc",
                        "name": "张三",
                        "dept_name_list": ["运营部"],
                    },
                },
            )
        )
        found = await contact.resolve_by_mobile(make_client(), "13800000000")
        assert found is not None
        assert found.union_id == "union-abc"
        assert found.name == "张三"
        assert found.dept == "运营部"

    @respx.mock
    async def test_mobile_not_found(self):
        mock_token(respx.mock)
        respx.post(f"{OAUTH}/topapi/v2/user/getbymobile").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "result": {}})
        )
        assert await contact.resolve_by_mobile(make_client(), "13800000000") is None

    @respx.mock
    async def test_union_id_must_be_converted_to_user_id(self):
        "回归：拿 unionId 当 userId 去查通讯录，钉钉只会回「找不到该用户」。"
        mock_token(respx.mock)
        by_union = respx.post(f"{OAUTH}/topapi/user/getbyunionid").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "result": {"userid": "u-real"}})
        )
        detail = respx.post(f"{OAUTH}/topapi/v2/user/get").mock(
            return_value=httpx.Response(
                200,
                json={"errcode": 0, "result": {"userid": "u-real", "unionid": "union-op-1", "name": "张三"}},
            )
        )

        found = await contact.contact_by_union_id(make_client(), "union-op-1")
        assert found is not None
        assert found.name == "张三"

        assert by_union.called, "必须先按 unionId 换 userId"
        assert "u-real" in detail.calls[0].request.content.decode()

        assert "union-op-1" not in detail.calls[0].request.content.decode()

    @respx.mock
    async def test_unknown_union_id_returns_none(self):
        mock_token(respx.mock)
        respx.post(f"{OAUTH}/topapi/user/getbyunionid").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "result": {}})
        )
        assert await contact.contact_by_union_id(make_client(), "union-ghost") is None
