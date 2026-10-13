"检查一个登录档案还有没有效。"

from __future__ import annotations

from urllib.parse import urlparse

from app.services.webflow.actions import wait_for
from app.services.webflow.cdp import Browser, CdpError
from app.services.webflow.source import DEFAULT_WPS_ELEMENTS

__all__ = ["check_page", "profile_name_for"]

_LOGIN_HINTS = ("login", "passport", "signin", "account")


def profile_name_for(app_id: object) -> str:
    "应用 → 档案名。**一处定义**：预览、同步、检测都用它 ——"
    return f"app-{app_id if app_id is not None else 'x'}"


async def check_page(url: str, profile: str = "", *, timeout: float = 25.0) -> tuple[bool, str]:
    """用这个档案打开 ``url``，返回 ``(是否可用, 人话说明)``。"""
    if not url:
        return False, "这个应用下还没有登记文档，没法验证"

    grid = DEFAULT_WPS_ELEMENTS["表格选区层"]
    try:
        async with Browser(profile=profile) as browser:
            session = await browser.new_page()
            await browser.call("Page.navigate", {"url": url}, session=session)
            if await wait_for(browser, session, grid, timeout=timeout):
                return True, "能打开文档并读到表格内容"

            href = str(await browser.eval("location.href", session=session) or "")
            host = urlparse(href).netloc.lower()
            path = urlparse(href).path.lower()
            if any(hint in host or hint in path for hint in _LOGIN_HINTS):
                return False, "被跳到登录页 —— 登录态已过期，重新登录一次即可"
            return False, f"页面打开了但没读到表格（当前地址 {href[:100]}）—— 可能网页改版了"
    except CdpError as exc:
        return False, f"浏览器起不来：{exc.message}"
