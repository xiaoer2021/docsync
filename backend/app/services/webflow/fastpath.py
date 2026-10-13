'WPS 的「秒回」路径：用存档的 cookie 直接问一句"文件变了吗"，不用开页面。'

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from app.services.webflow.cdp import Browser, CdpError
from app.services.webflow.download import DOWNLOADS_ROOT

log = logging.getLogger(__name__)

_DOWNLOAD_API = "https://www.kdocs.cn/api/v3/office/file/{file_id}/download"


def _app_dir(app_id: int) -> Path:
    path = Path(DOWNLOADS_ROOT) / f"app-{app_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cookies_path(app_id: int) -> Path:
    return _app_dir(app_id) / "cookies.json"


def _index_path(app_id: int) -> Path:
    return _app_dir(app_id) / "index.json"


def _read_dict(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def save_cookies(browser: Browser, session: str, app_id: int) -> None:
    '把当前会话的 cookie 存下来（下次好走"秒回"那条路）。'
    try:
        got = await browser.call(
            "Network.getCookies",
            {"urls": ["https://www.kdocs.cn/", "https://www.kdocs.cn"]},
            session=session,
        )
    except CdpError:
        return
    jar = [
        {
            "name": str(c.get("name") or ""),
            "value": str(c.get("value") or ""),
            "domain": str(c.get("domain") or ""),
            "path": str(c.get("path") or "/"),
        }
        for c in (got.get("cookies") or [])
        if c.get("name")
    ]
    if not jar:
        return
    try:
        _cookies_path(app_id).write_text(json.dumps({"at": time.time(), "cookies": jar}), encoding="utf-8")
    except OSError:
        return
    log.info("WPS 秒回：存下 %s 条 cookie（app-%s）", len(jar), app_id)


def _cookie_header(app_id: int) -> str:
    path = _cookies_path(app_id)
    if not path.exists():
        return ""
    data = _read_dict(path)
    jar = data.get("cookies") or []
    if not isinstance(jar, list):
        return ""
    return "; ".join(
        f"{c['name']}={c['value']}"
        for c in jar
        if isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("value"), str)
    )


def remember_file(app_id: int, node_id: str, file_id: str) -> None:
    """记住「这个网址对应哪个文件 id」—— 秒回那条路要知道文件 id 才能查版本。"""
    if not node_id or not file_id:
        return
    path = _index_path(app_id)
    index = _read_dict(path)
    index[node_id] = file_id
    try:
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _file_id_of(app_id: int, node_id: str) -> str:
    path = _index_path(app_id)
    if not path.exists():
        return ""
    value = str(_read_dict(path).get(node_id) or "")
    return value if value.isascii() and value.isdigit() else ""


async def reuse_if_unchanged(app_id: int, node_id: str) -> Path | None:
    """文件没变就返回本地那份的路径（**不用开页面**）；否则 None（调用方走正常流程）。"""
    file_id = _file_id_of(app_id, node_id)
    if not file_id:
        return None
    header = _cookie_header(app_id)
    if not header:
        return None
    dest = _app_dir(app_id) / f"{file_id}.xlsx"
    meta_path = dest.with_name(dest.name + ".meta.json")
    if not dest.exists() or not meta_path.exists():
        return None
    meta = _read_dict(meta_path)
    if not meta:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(_DOWNLOAD_API.format(file_id=file_id), headers={"Cookie": header})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        log.info(
            "WPS 秒回：查版本返回 %s（cookie 多半过期了），退回开浏览器",
            resp.status_code,
        )
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    fver = str(payload.get("fver") or "")
    try:
        fize = int(payload.get("fize") or 0)
    except (ValueError, TypeError):
        return None
    if not fver:
        return None
    if (
        fver == str(meta.get("fver") or "")
        and (not fize or fize == dest.stat().st_size)
        and dest.stat().st_size > 0
    ):
        log.info("WPS 秒回：文件没变（fver=%s），直接用本地那份 %s", fver, dest)
        return dest
    log.info("WPS 秒回：文件变了（fver %s → %s），去下载", meta.get("fver"), fver)
    return None
