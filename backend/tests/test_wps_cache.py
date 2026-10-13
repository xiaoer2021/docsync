"""No time-only reuse, complete workbook selection and shared-browser lifetime."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from openpyxl import Workbook

from app.services.webflow import cdp, download, fastpath


def test_named_workbook_sheet_is_read_without_using_first_sheet(tmp_path):
    path = tmp_path / "example.xlsx"
    workbook = Workbook()
    workbook.active.title = "First"
    workbook.active.append(["Name", "Amount"])
    workbook.active.append(["first", 10])
    other = workbook.create_sheet("Selected")
    other.append(["Name", "Amount"])
    other.append(["selected", 20])
    workbook.save(path)
    workbook.close()
    assert download.sheet_names(path) == ["First", "Selected"]
    assert download.read_grid(path, "Selected") == [["Name", "Amount"], ["selected", "20"]]
    with pytest.raises(Exception, match="Missing"):
        download.read_grid(path, "Missing")


@pytest.mark.parametrize(
    "old_version,new_version,should_download", [("", "", True), ("1", "2", True), ("1", "1", False)]
)
async def test_cache_needs_source_version_evidence(
    tmp_path, monkeypatch, old_version, new_version, should_download
):
    monkeypatch.setattr(download, "DOWNLOADS_ROOT", str(tmp_path))
    directory = tmp_path / "app-1"
    directory.mkdir()
    dest = directory / "123.xlsx"
    dest.write_bytes(b"old")
    dest.with_name(dest.name + ".meta.json").write_text(json.dumps({"fver": old_version}), encoding="utf8")
    info = download.WpsFile(file_id="123", name="example", size=3)
    monkeypatch.setattr(download, "page_file", AsyncMock(return_value=info))
    monkeypatch.setattr(
        download,
        "_in_page_fetch",
        AsyncMock(
            return_value={
                "download_url": "https://files.example.com/test.xlsx",
                "fver": new_version,
            }
        ),
    )
    calls = []

    async def handle(request):
        calls.append(request.url)
        return httpx.Response(200, content=b"new")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        download.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    result, _ = await download.download_xlsx(object(), "session", 1)
    assert result == dest
    assert bool(calls) == should_download
    assert dest.read_bytes() == (b"new" if should_download else b"old")


async def test_fast_cache_invalid_response_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(fastpath, "DOWNLOADS_ROOT", str(tmp_path))
    directory = tmp_path / "app-1"
    directory.mkdir()
    (directory / "index.json").write_text(json.dumps({"url": "123"}), encoding="utf8")
    (directory / "cookies.json").write_text(json.dumps({"cookies": [{"name": "test", "value": "fake"}]}))
    (directory / "123.xlsx").write_bytes(b"123")
    (directory / "123.xlsx.meta.json").write_text(json.dumps({"fver": "1"}))
    original = httpx.AsyncClient

    async def handle(request):
        return httpx.Response(200, json={"fver": "1", "fize": "invalid"})

    monkeypatch.setattr(
        fastpath.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    assert await fastpath.reuse_if_unchanged(1, "url") is None


@pytest.mark.parametrize("contents", ["[]", "null", '{"cookies":[null,{}]}', "broken-json"])
def test_corrupt_cookie_cache_does_not_break_normal_read(tmp_path, monkeypatch, contents):
    monkeypatch.setattr(fastpath, "DOWNLOADS_ROOT", str(tmp_path))
    directory = tmp_path / "app-1"
    directory.mkdir()
    (directory / "cookies.json").write_text(contents, encoding="utf8")
    assert fastpath._cookie_header(1) == ""


async def test_concurrent_reads_share_one_browser_and_close_pages(monkeypatch):
    created = []

    class FakeBrowser:
        def __init__(self, profile):
            self._pages = {}
            self.call = AsyncMock()
            self.close = AsyncMock()
            created.append(self)

        async def start(self):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(cdp, "Browser", FakeBrowser)
    profile = "test-installation-cache"

    async def read(index):
        async with cdp.shared_browser(profile) as browser:
            browser._pages[f"session-{index}"] = f"target-{index}"
            await asyncio.sleep(0.01)

    await asyncio.gather(read(1), read(2))
    assert len(created) == 1
    assert not created[0]._pages
    assert created[0].call.await_count == 2
    await cdp.close_shared(profile)
    created[0].close.assert_awaited_once()
