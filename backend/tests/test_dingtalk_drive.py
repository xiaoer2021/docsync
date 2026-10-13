"""钉钉与文档相关的接口。"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.dingtalk import drive
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError

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


class TestSearchDentries:
    @respx.mock
    async def test_search_returns_doc_ids(self):
        """搜出来的 dentryUuid 就是文档节点 ID，能直接拿去读。"""
        _token()
        route = respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "dentryUuid": "EpGBa2Lm8aRmzkkNhplMx1prWgN7R35y",
                            "name": "Coupang平台货品",
                            "creator": {"userId": "u1", "name": "张三"},
                            "modifier": {"userId": "u2", "name": "李四"},
                        },
                        {"dentryUuid": "PwkSecondDoc1", "name": "Coupang-钉钉营销单"},
                    ],
                    "nextToken": "page-2",
                },
            )
        )

        hits, token = await drive.search_dentries(make_client(), "Coupang", max_results=20)

        assert [h.uuid for h in hits] == [
            "EpGBa2Lm8aRmzkkNhplMx1prWgN7R35y",
            "PwkSecondDoc1",
        ]
        assert hits[0].name == "Coupang平台货品"
        assert hits[0].creator == "张三"
        assert token == "page-2"

        assert route.calls[0].request.url.params["operatorId"] == "union-1"
        assert "Coupang" in route.calls[0].request.content.decode()

    @respx.mock
    async def test_page_size_capped_at_50(self):
        _token()
        route = respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await drive.search_dentries(make_client(), "x", max_results=500)
        body = route.calls[0].request.content.decode().replace(" ", "")
        assert '"maxResults":50' in body, f"要压到官方上限 50，实际：{body}"

    @respx.mock
    async def test_next_token_forwarded(self):
        _token()
        route = respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await drive.search_dentries(make_client(), "x", next_token="cursor-9")
        assert "cursor-9" in route.calls[0].request.content.decode()

    @respx.mock
    async def test_items_without_uuid_dropped(self):
        _token()
        respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(
                200, json={"items": [{"name": "没有 uuid"}, {"dentryUuid": "ok1", "name": "有"}]}
            )
        )
        hits, _ = await drive.search_dentries(make_client(), "x")
        assert [h.uuid for h in hits] == ["ok1"]

    @respx.mock
    async def test_permission_error_is_readable(self):
        _token()
        respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(
                403,
                json={
                    "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                    "message": "no permission",
                },
            )
        )
        with pytest.raises(DingTalkError) as exc:
            await drive.search_dentries(make_client(), "x")
        assert "Storage.Dentry.Search" in (exc.value.hint or "")

    @respx.mock
    async def test_empty_keyword_still_calls(self):
        _token()
        route = respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(200, json={"items": [], "nextToken": ""})
        )
        hits, token = await drive.search_dentries(make_client(), "   ")
        assert hits == []
        assert token is None
        assert route.called
