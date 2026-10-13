"WPS 个人版：登记（列工作表）与预览的分派。"

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient, Response

from tests.conftest import auth_header

URL = "https://www.kdocs.cn/l/testPublicSheet"
SHEETS = ["看板导出", "提成导出", "T+1导出"]


async def _wps_app(client: AsyncClient, token: str) -> dict:
    res = await client.post(
        "/api/v1/apps",
        headers=auth_header(token),
        json={"platform": "wps", "name": f"WPS 个人 {uuid4().hex[:6]}"},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _register(client: AsyncClient, token: str, app_id: int) -> Response:
    return await client.post(
        "/api/v1/docs",
        headers=auth_header(token),
        json={"app_id": app_id, "ref": f"【金山文档 | WPS云文档】 测试表\n{URL}"},
    )


def _patch_sheets(monkeypatch, names) -> None:
    """登记时会去列工作表页签 —— 单测里不打真浏览器。"""

    async def fake(recipe, *, logger=None):
        if isinstance(names, Exception):
            raise names
        return list(names)

    monkeypatch.setattr("app.services.webflow.source.list_sheets", fake)


def _reader(text: str, calls: list[str] | None = None):
    async def read(recipe, *, sheet="", cfg=None, logger=None):
        if calls is not None:
            calls.append(recipe.url)
        from app.services.webflow.source import to_source_data

        return to_source_data(text, cfg)

    return read


def _fail_reader(message: str = "网页里没取到表格数据", hint: str = "可能是被踢到登录页了"):
    async def read(recipe, *, sheet="", cfg=None, logger=None):
        from app.services.sources.base import SourceError

        raise SourceError(message, hint=hint)

    return read


def _patch_read(monkeypatch, read) -> None:
    """登记（列页签）之外，预览也 import 了一份 read_webflow —— 都要打上。"""
    monkeypatch.setattr("app.services.webflow.source.read_webflow", read)
    monkeypatch.setattr("app.services.webflow.preview.read_webflow", read)


class TestWpsRegistration:
    async def test_subtable_name_reports_sheet_count(self, client: AsyncClient, admin_token, monkeypatch):
        """下载的工作簿按工作表名登记，数量和名称均保持完整。"""
        _patch_sheets(monkeypatch, SHEETS)
        app = await _wps_app(client, admin_token)

        res = await _register(client, admin_token, app["id"])
        assert res.status_code == 201, res.text
        doc = res.json()
        assert doc["node_id"] == URL
        assert doc["sheet_count"] == len(SHEETS)

        subs = await client.get(f"/api/v1/docs/{doc['id']}/subitems", headers=auth_header(admin_token))
        names = [s["name"] for s in subs.json()]
        assert names == SHEETS
        assert [s["id"] for s in subs.json()] == SHEETS

    async def test_unreadable_link_is_not_registered(self, client: AsyncClient, admin_token, monkeypatch):
        """读不到工作表就**不落库** —— 别让一个失效链接「登记成功」。"""
        from app.services.sources.base import SourceError

        _patch_sheets(monkeypatch, SourceError("这份链接里没读到工作表。", hint="确认是表格"))
        app = await _wps_app(client, admin_token)

        res = await _register(client, admin_token, app["id"])
        assert res.status_code == 400, res.text
        assert "没读到工作表" in res.json()["detail"]

        listed = await client.get(
            "/api/v1/docs", headers=auth_header(admin_token), params={"app_id": app["id"]}
        )
        assert listed.json() == []


class TestWpsPreviewDispatch:
    async def test_preview_reads_webflow_not_feishu(self, client: AsyncClient, admin_token, monkeypatch):
        calls: list[str] = []
        _patch_sheets(monkeypatch, SHEETS)
        _patch_read(monkeypatch, _reader("月份\t金额\n1月\t100\n2月\t200", calls))

        async def boom(*args, **kwargs):
            raise AssertionError("WPS 文档被送进飞书读取器了 —— 分派又错了")

        monkeypatch.setattr("app.api.v1.tasks._feishu_rows_preview", boom)

        app = await _wps_app(client, admin_token)
        doc = (await _register(client, admin_token, app["id"])).json()
        calls.clear()

        res = await client.post(
            "/api/v1/tasks/preview",
            headers=auth_header(admin_token),
            json={
                "doc_id": doc["id"],
                "sheet_id": "T+1导出",
                "source_config": {"orientation": "vertical"},
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True, body
        assert body["header"] == ["月份", "金额"]
        assert body["row_numbers"] == [2, 3]
        assert calls == [URL]

    async def test_read_failure_is_a_friendly_envelope(self, client: AsyncClient, admin_token, monkeypatch):
        """预览读不到时回 ok=False + 原因，**不是** 500 —— 界面上要能显示人话。"""
        _patch_sheets(monkeypatch, SHEETS)
        app = await _wps_app(client, admin_token)
        doc = (await _register(client, admin_token, app["id"])).json()

        _patch_read(monkeypatch, _fail_reader())

        res = await client.post(
            "/api/v1/tasks/preview",
            headers=auth_header(admin_token),
            json={"doc_id": doc["id"], "sheet_id": "看板导出", "source_config": {}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is False
        assert "没取到表格数据" in body["error"]
        assert "登录" in body["hint"]
