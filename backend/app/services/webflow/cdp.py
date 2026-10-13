"一个最小的 Chromium DevTools Protocol 客户端。"

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets

from app.core.config import settings

log = logging.getLogger(__name__)

__all__ = ["Browser", "CdpError", "find_browser"]


class CdpError(RuntimeError):
    """CDP 调用失败。**带上方法名** —— 不然报错只剩一串错误码，没法排查。"""

    def __init__(self, method: str, message: str) -> None:
        super().__init__(f"{method} 失败：{message}")
        self.method = method
        self.message = message


_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/microsoft-edge",
    "/opt/chromium/chrome-linux/chrome",
    "/opt/chromium/chrome",
)


def find_browser(explicit: str | None = None) -> str:
    """找可用的浏览器可执行文件。找不到就抛错并**说清楚去哪儿配**。"""
    if explicit:
        if Path(explicit).exists():
            return explicit
        raise CdpError("启动浏览器", f"指定的浏览器不存在：{explicit}")
    for path in _CANDIDATES:
        if Path(path).exists():
            return path
    raise CdpError(
        "启动浏览器",
        "机器上没找到 Chromium 内核的浏览器。装一个（或把已有的路径配进"
        "环境变量 DOCSYNC_BROWSER）—— Edge 和 Chrome 都算。",
    )


_STALE_LOCK_FILES: tuple[str, ...] = (
    "DevToolsActivePort",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)


def _clear_stale_locks(user_data_dir: str) -> None:
    "删掉上一次留下的端口文件与单实例锁。"
    for name in _STALE_LOCK_FILES:
        with contextlib.suppress(OSError):
            (Path(user_data_dir) / name).unlink(missing_ok=True)


_SHARED: dict[str, Any] = {}
_SHARED_AT: dict[str, float] = {}
_PROFILE_LOCKS: dict[str, asyncio.Lock] = {}
_POOL_LOCK = asyncio.Lock()
IDLE_SECONDS = 300.0


async def acquire(profile: str) -> Browser:
    async with _POOL_LOCK:
        return await _acquire(profile)


async def _acquire(profile: str) -> Browser:
    """拿该档案的常驻浏览器（没有就起一个），顺手关掉闲置太久的其它实例。"""
    import time as _time

    now = _time.time()
    for name, browser in list(_SHARED.items()):
        busy = _PROFILE_LOCKS.get(name)
        if (
            name != profile
            and not (busy and busy.locked())
            and now - _SHARED_AT.get(name, now) > IDLE_SECONDS
        ):
            _SHARED.pop(name, None)
            _SHARED_AT.pop(name, None)
            with contextlib.suppress(Exception):
                await browser.close()
    browser = _SHARED.get(profile)
    if browser is None:
        browser = Browser(profile=profile)
        await browser.start()
        _SHARED[profile] = browser
        log.info("共用浏览器：为档案 %s 起了一个实例", profile or "(匿名)")
    _SHARED_AT[profile] = now
    return browser


async def close_shared(profile: str) -> None:
    async with _PROFILE_LOCKS.setdefault(profile or "", asyncio.Lock()), _POOL_LOCK:
        await _close_shared(profile)


async def _close_shared(profile: str) -> None:
    "关掉某个档案的常驻实例。"
    browser = _SHARED.pop(profile or "", None)
    _SHARED_AT.pop(profile or "", None)
    if browser is not None:
        with contextlib.suppress(Exception):
            await browser.close()
        log.info("共用浏览器：关掉了档案 %s 的实例（准备登录）", profile or "(匿名)")


async def close_all_shared() -> None:
    for profile in list(_SHARED):
        await close_shared(profile)


class _SharedBrowser:
    "``async with shared_browser(profile) as browser:`` —— 用法跟 ``Browser`` 一样，"

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.browser: Browser | None = None
        self.lock = _PROFILE_LOCKS.setdefault(profile or "", asyncio.Lock())
        self.pages: set[str] = set()

    async def __aenter__(self) -> Browser:
        await self.lock.acquire()
        try:
            self.browser = await acquire(self.profile)
            self.pages = set(self.browser._pages)
            return self.browser
        except BaseException:
            self.lock.release()
            raise

    async def __aexit__(self, *exc: object) -> None:
        try:
            if self.browser is not None:
                for session in set(self.browser._pages) - self.pages:
                    target = self.browser._pages.pop(session)
                    with contextlib.suppress(Exception):
                        await self.browser.call("Target.closeTarget", {"targetId": target})
                _SHARED_AT[self.profile] = time.time()
        finally:
            self.lock.release()


def shared_browser(profile: str) -> _SharedBrowser:
    return _SharedBrowser(profile)


@dataclass
class Browser:
    "一个受管的浏览器进程 + 一条 CDP 连接。"

    user_data_dir: str = ""

    profile: str = ""
    executable: str | None = None

    extra_args: list[str] = field(default_factory=list)

    PROFILES_ROOT = str(settings.profiles_dir)

    _proc: asyncio.subprocess.Process | None = None
    _ws: Any = None
    _pages: dict[str, str] = field(default_factory=dict)
    _seq: int = 0
    _owned_dir: bool = False
    _tmp: str = ""

    async def __aenter__(self) -> Browser:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        """启动浏览器。**档案坏了会自动重来一次**（见下面的说明）。"""
        try:
            await self._start_once()
        except CdpError as exc:
            if not self.profile or "提前退出" not in str(exc):
                raise
            broken = f"{self.user_data_dir}.broken-{int(time.time())}"
            log.warning("浏览器起不来，怀疑是登录档案坏了，挪开重试：%s → %s", self.user_data_dir, broken)
            with contextlib.suppress(OSError):
                shutil.move(self.user_data_dir, broken)

            self.user_data_dir = ""
            self._tmp = ""
            self._owned_dir = False
            await self._start_once()

    async def _start_once(self) -> None:
        exe = find_browser(self.executable or os.environ.get("DOCSYNC_BROWSER"))
        if not self.user_data_dir:
            root = Path(self.PROFILES_ROOT)
            if self.profile:
                root.mkdir(parents=True, exist_ok=True)
            if self.profile and root.is_dir():
                self.user_data_dir = str(root / self.profile)
                Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
            else:
                self._tmp = tempfile.mkdtemp(prefix="docsync-browser-")
                self.user_data_dir = self._tmp
                self._owned_dir = True

        _clear_stale_locks(self.user_data_dir)

        args = [
            exe,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--lang=zh-CN",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.user_data_dir}",
            *self.extra_args,
            "about:blank",
        ]
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        port = await self._wait_for_port()
        self._ws = await websockets.connect(
            await self._browser_ws(port),
            max_size=64 * 1024 * 1024,
        )

    async def _wait_for_port(self, timeout: float = 30.0) -> int:
        "等 DevToolsActivePort 文件出现。"
        path = Path(self.user_data_dir) / "DevToolsActivePort"
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if path.exists():
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if lines and lines[0].strip().isdigit():
                    return int(lines[0].strip())
            if self._proc is not None and self._proc.returncode is not None:
                raise CdpError("启动浏览器", f"进程提前退出（码 {self._proc.returncode}）")
            await asyncio.sleep(0.15)
        raise CdpError("启动浏览器", f"{timeout:.0f} 秒内没等到调试端口，浏览器可能起不来")

    async def _browser_ws(self, port: int, timeout: float = 20.0) -> str:
        "要 browser 级的 ws 地址（不是某个页面的）—— 见模块头的说明。"
        url = f"http://127.0.0.1:{port}/json/version"
        deadline = asyncio.get_running_loop().time() + timeout
        last: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return str(resp.json()["webSocketDebuggerUrl"])
            except Exception as exc:  # noqa: BLE001 — 连不上就再等一会儿
                last = exc
                await asyncio.sleep(0.3)
        raise CdpError("连接浏览器", f"调试端口 {port} 一直没响应：{last}")

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            if self._ws is not None:
                await self._ws.close()
        self._ws = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            if self._proc.returncode is None:
                self._proc.kill()
        self._proc = None

        if self._owned_dir and self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._tmp = ""
        self._owned_dir = False

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session: str | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """发一条命令等结果。失败抛 ``CdpError``。"""
        if self._ws is None:
            raise CdpError(method, "连接还没建立")
        self._seq += 1
        message: dict[str, Any] = {"id": self._seq, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        await self._ws.send(json.dumps(message))

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise CdpError(method, f"{timeout:.0f} 秒没等到结果")
            raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            data = json.loads(raw)

            if data.get("id") != self._seq:
                continue
            if "error" in data:
                error = data["error"]
                raise CdpError(method, str(error.get("message") or error))
            return dict(data.get("result") or {})

    async def new_page(self, url: str = "about:blank") -> str:
        """开一个页签，返回 sessionId。"""
        target = await self.call("Target.createTarget", {"url": url})
        attached = await self.call(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": True},
        )
        session = str(attached["sessionId"])
        self._pages[session] = str(target["targetId"])

        await self.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, session=session)

        for method in ("Page.enable", "Runtime.enable", "DOM.enable"):
            await self.call(method, session=session)

        await self._pretend_chinese(session)
        return session

    async def _pretend_chinese(self, session: str) -> None:
        "让页面**按简体中文渲染**。"
        with contextlib.suppress(CdpError):
            await self.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
                session=session,
            )
        with contextlib.suppress(CdpError):
            await self.call("Emulation.setLocaleOverride", {"locale": "zh-CN"}, session=session)
        with contextlib.suppress(CdpError):
            await self.call("Network.enable", session=session)
            await self.call(
                "Network.setExtraHTTPHeaders",
                {"headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}},
                session=session,
            )

    async def eval(self, expression: str, *, session: str, timeout: float = 30.0) -> Any:
        """在页面里跑一段 JS，返回它的值（按值传回，不是句柄）。"""
        result = await self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
            session=session,
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise CdpError("Runtime.evaluate", str(detail.get("text") or detail))
        return (result.get("result") or {}).get("value")

    async def screenshot(self, *, session: str, clip: dict[str, float] | None = None) -> bytes:
        """截图。带 ``clip`` 就是**只截一块** —— 登录二维码靠这个取。"""
        params: dict[str, Any] = {"format": "png"}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        result = await self.call("Page.captureScreenshot", params, session=session)
        return base64.b64decode(result["data"])
