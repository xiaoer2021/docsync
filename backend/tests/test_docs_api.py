"""凭证接入与文档登记的接口测试（钉钉侧用 respx 回放）。"""

from __future__ import annotations

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import auth_header

OAUTH = "https://oapi.dingtalk.com"
API = "https://api.dingtalk.com"


def _token() -> None:
    respx.get(f"{OAUTH}/gettoken").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "access_token": "tok", "expires_in": 7200})
    )


def _app_payload(name: str = "测试应用") -> dict:
    return {
        "name": name,
        "app_key": "ding_test_key",
        "app_secret": "ding_test_secret_value",
        "default_operator_union_id": "union-op-1",
        "default_operator_name": "张三",
    }


async def _create_app(client: AsyncClient, token: str, name: str = "测试应用") -> dict:
    res = await client.post("/api/v1/apps", headers=auth_header(token), json=_app_payload(name))
    assert res.status_code == 201, res.text
    return res.json()


class TestAppApi:
    async def test_create_and_masked_secret(self, client: AsyncClient, admin_token: str):
        app = await _create_app(client, admin_token, "应用A")
        assert app["name"] == "应用A"
        assert app["has_secret"] is True

        assert "ding_test_secret_value" not in str(app)

    async def test_duplicate_name(self, client: AsyncClient, admin_token: str):
        await _create_app(client, admin_token, "应用B")
        res = await client.post("/api/v1/apps", headers=auth_header(admin_token), json=_app_payload("应用B"))
        assert res.status_code == 409

    async def test_viewer_cannot_create(self, client: AsyncClient, viewer_token: str):
        res = await client.post("/api/v1/apps", headers=auth_header(viewer_token), json=_app_payload("应用C"))
        assert res.status_code == 403

    async def test_scopes_guide(self, client: AsyncClient, admin_token: str):
        res = await client.get("/api/v1/apps/scopes", headers=auth_header(admin_token))
        assert res.status_code == 200
        body = res.json()
        scopes = [s["scope"] for s in body["scopes"]]
        assert "Document.Workbook.Read" in scopes
        assert "Notable.Base.Read.All" in scopes
        assert body["author_guide"]

    @respx.mock
    async def test_app_test_ok(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用D")

        respx.post(f"{OAUTH}/topapi/user/getbyunionid").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "result": {"userid": "u-op"}})
        )
        respx.post(f"{OAUTH}/topapi/v2/user/get").mock(
            return_value=httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "result": {"userid": "u-op", "unionid": "union-op-1", "name": "张三"},
                },
            )
        )

        respx.post(f"{API}/v2.0/storage/dentries/search").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        res = await client.post(f"/api/v1/apps/{app['id']}/test", headers=auth_header(admin_token))
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        names = [s["name"] for s in body["steps"]]
        assert "换取访问凭证" in names
        assert "文件搜索权限" in names
        assert "操作人在通讯录里查得到" in names

    @respx.mock
    async def test_app_test_bad_secret(self, client: AsyncClient, admin_token: str):
        respx.get(f"{OAUTH}/gettoken").mock(
            return_value=httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid appsecret"})
        )
        app = await _create_app(client, admin_token, "应用E")
        res = await client.post(f"/api/v1/apps/{app['id']}/test", headers=auth_header(admin_token))
        body = res.json()
        assert body["ok"] is False
        step = body["steps"][0]
        assert step["ok"] is False
        assert step["hint"], "失败步骤必须给出修复建议"


class TestDocApi:
    async def test_docs_route_not_shadowed_by_swagger(self, client: AsyncClient, admin_token: str):
        "回归：Swagger UI 曾经挂在 /api/v1/docs，把「文档登记」接口整个遮住。"
        res = await client.get("/api/v1/docs", headers=auth_header(admin_token))
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        assert isinstance(res.json(), list)

    @respx.mock
    async def test_missing_operator_is_called_out(self, client: AsyncClient, admin_token: str):
        """没配 operatorId 时不该让钉钉回一个含混的「找不到」，要直接说清缺什么。"""
        _token()
        res = await client.post(
            "/api/v1/apps",
            headers=auth_header(admin_token),
            json={"name": "没操作人的应用", "app_key": "k1", "app_secret": "s1"},
        )
        app = res.json()

        result = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "someNode123456", "app_id": app["id"]},
        )
        body = result.json()
        assert body["ok"] is False
        assert body["code"] == "MISSING_OPERATOR"
        assert "操作人" in (body["hint"] or "")

    @respx.mock
    async def test_failure_reports_what_was_sent(self, client: AsyncClient, admin_token: str):
        """失败时要带出：用的哪个文档 ID、以谁的身份读、钉钉原始错误码。"""
        _token()
        app = await _create_app(client, admin_token, "应用Diag")
        for kind in ("workbooks", "bases"):
            path = (
                f"{API}/v1.0/doc/workbooks/diagNode12345/sheets"
                if kind == "workbooks"
                else f"{API}/v1.0/notable/bases/diagNode12345/sheets"
            )
            respx.get(path).mock(
                return_value=httpx.Response(
                    404,
                    json={
                        "code": "invalidRequest.document.notFound",
                        "message": "Fail to find the requested resource by the given baseId.",
                    },
                )
            )

        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "diagNode12345", "app_id": app["id"]},
        )
        body = res.json()
        assert body["ok"] is False
        assert body["code"] == "invalidRequest.document.notFound"
        assert body["http_status"] == 404
        assert body["used_node_id"] == "diagNode12345"
        assert body["used_operator_union_id"] == "union-op-1"
        labels = [a["label"] for a in body["attempts"]]
        assert labels == ["钉钉表格", "多维表"], "两种类型都试过就要都报出来"

    @respx.mock
    async def test_forced_doc_type_skips_the_other(self, client: AsyncClient, admin_token: str):
        """手动指定类型时不该再去试另一种。"""
        _token()
        app = await _create_app(client, admin_token, "应用Force")
        route = respx.get(f"{API}/v1.0/notable/bases/forceNode12345/sheets").mock(
            return_value=httpx.Response(
                403, json={"code": "forbidden.accessDenied", "message": "no permission"}
            )
        )
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "forceNode12345", "app_id": app["id"], "doc_type": "aitable"},
        )
        body = res.json()
        assert body["ok"] is False
        assert route.call_count == 1
        assert len(body["attempts"]) == 1
        assert body["attempts"][0]["label"] == "多维表"

    @respx.mock
    async def test_resolve_sheet_doc(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用F")
        respx.get(f"{API}/v1.0/doc/workbooks/oP0MAxxxxxYmDO/sheets").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "st1", "name": "店铺1-星光性感"},
                        {"id": "st2", "name": "店铺2-智安科"},
                    ]
                },
            )
        )
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "https://alidocs.dingtalk.com/i/nodes/oP0MAxxxxxYmDO", "app_id": app["id"]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["doc_type"] == "sheet"
        assert len(body["sub_items"]) == 2

    @respx.mock
    async def test_resolve_falls_back_to_aitable(self, client: AsyncClient, admin_token: str):
        """表格探不通时应该自动换多维表再试一次。"""
        _token()
        app = await _create_app(client, admin_token, "应用G")
        respx.get(f"{API}/v1.0/doc/workbooks/baseXYZ/sheets").mock(
            return_value=httpx.Response(
                400,
                json={
                    "code": "invalidRequest.resource.notWorkbook",
                    "message": "not a workbook",
                },
            )
        )
        respx.get(f"{API}/v1.0/notable/bases/baseXYZ/sheets").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "tb1", "name": "数据表"}]})
        )
        respx.get(f"{API}/v1.0/notable/bases/baseXYZ/sheets/tb1/fields").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "f1", "name": "字段A"}]})
        )
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "baseXYZ", "app_id": app["id"]},
        )
        body = res.json()
        assert body["ok"] is True
        assert body["doc_type"] == "aitable"
        assert body["sub_items"][0]["field_count"] == 1

    @respx.mock
    async def test_resolve_reports_hint(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用H")
        respx.get(f"{API}/v1.0/doc/workbooks/nopeDoc1/sheets").mock(
            return_value=httpx.Response(
                403, json={"code": "forbidden.accessDenied", "message": "The operator has no permission."}
            )
        )
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "nopeDoc1", "app_id": app["id"]},
        )
        body = res.json()
        assert body["ok"] is False
        assert "协作者" in (body["hint"] or "")

    @respx.mock
    async def test_create_doc_then_subitems(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用I")
        wb = "wbCreate1"
        respx.get(f"{API}/v1.0/doc/workbooks/{wb}/sheets").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "st1", "name": "店铺1"},
                        {"id": "st2", "name": "店铺2"},
                        {"id": "st3", "name": "店铺3"},
                    ]
                },
            )
        )
        res = await client.post(
            "/api/v1/docs",
            headers=auth_header(admin_token),
            json={"ref": wb, "app_id": app["id"], "name": "Coupang平台货品"},
        )
        assert res.status_code == 201, res.text
        doc = res.json()
        assert doc["name"] == "Coupang平台货品"
        assert doc["doc_type"] == "sheet"
        assert doc["sheet_count"] == 3
        assert doc["task_count"] == 0
        assert doc["unconfigured_count"] == 3

        sub = await client.get(f"/api/v1/docs/{doc['id']}/subitems", headers=auth_header(admin_token))
        items = sub.json()
        assert len(items) == 3
        assert all(not i["configured"] for i in items)
        assert items[0]["name"] == "店铺1"

    @respx.mock
    async def test_duplicate_doc_rejected(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用J")
        wb = "wbDup1"
        respx.get(f"{API}/v1.0/doc/workbooks/{wb}/sheets").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "s1", "name": "表1"}]})
        )
        first = await client.post(
            "/api/v1/docs", headers=auth_header(admin_token), json={"ref": wb, "app_id": app["id"]}
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/docs", headers=auth_header(admin_token), json={"ref": wb, "app_id": app["id"]}
        )
        assert second.status_code == 409

    @respx.mock
    async def test_batch_register_mixed(self, client: AsyncClient, admin_token: str):
        _token()
        app = await _create_app(client, admin_token, "应用K")
        respx.get(f"{API}/v1.0/doc/workbooks/wbOkDoc1/sheets").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "s1", "name": "表1"}]})
        )
        respx.get(f"{API}/v1.0/doc/workbooks/wbBadDoc1/sheets").mock(
            return_value=httpx.Response(
                404, json={"code": "invalidRequest.document.notFound", "message": "not found"}
            )
        )
        respx.get(f"{API}/v1.0/notable/bases/wbBadDoc1/sheets").mock(
            return_value=httpx.Response(
                404, json={"code": "invalidRequest.document.notFound", "message": "not found"}
            )
        )
        res = await client.post(
            "/api/v1/docs/batch",
            headers=auth_header(admin_token),
            json={"app_id": app["id"], "refs": ["wbOkDoc1", "wbBadDoc1", "不是个链接"]},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 3
        assert body["ok_count"] == 1
        assert body["failed_count"] == 2
        assert body["items"][0]["ok"] is True
        assert body["items"][1]["ok"] is False
        assert body["items"][2]["ok"] is False

    async def test_short_ref_rejected_as_id(self, client: AsyncClient, admin_token: str):
        """太短的字符串既不像链接也不像 nodeId，要提前拦下来而不是拿去打接口。"""
        app = await _create_app(client, admin_token, "应用M")
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "nope", "app_id": app["id"]},
        )
        body = res.json()
        assert body["ok"] is False
        assert "ID 看起来不对" in body["error"]

    async def test_bad_ref_gives_readable_error(self, client: AsyncClient, admin_token: str):
        app = await _create_app(client, admin_token, "应用L")
        res = await client.post(
            "/api/v1/docs/resolve",
            headers=auth_header(admin_token),
            json={"ref": "https://example.com/nothing", "app_id": app["id"]},
        )
        body = res.json()
        assert body["ok"] is False
        assert "认不出" in body["error"]


class TestGroupApi:
    async def test_crud(self, client: AsyncClient, admin_token: str):
        created = await client.post(
            "/api/v1/groups", headers=auth_header(admin_token), json={"name": "Coupang分组"}
        )
        assert created.status_code == 201
        gid = created.json()["id"]

        renamed = await client.patch(
            f"/api/v1/groups/{gid}", headers=auth_header(admin_token), json={"name": "Coupang"}
        )
        assert renamed.json()["name"] == "Coupang"

        deleted = await client.delete(f"/api/v1/groups/{gid}", headers=auth_header(admin_token))
        assert deleted.status_code == 200

    async def test_duplicate(self, client: AsyncClient, admin_token: str):
        await client.post("/api/v1/groups", headers=auth_header(admin_token), json={"name": "G唯一"})
        again = await client.post("/api/v1/groups", headers=auth_header(admin_token), json={"name": "G唯一"})
        assert again.status_code == 409
