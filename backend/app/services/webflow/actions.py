"网页取数用到的**原语动作**：等元素、点元素、填输入、右键、读剪贴板。"

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.services.webflow.cdp import Browser, CdpError

__all__ = ["Box", "click", "read_clipboard", "type_text", "wait_for", "xpath_literal"]

Anchor = Literal["center", "topleft"]


@dataclass
class Box:
    """元素在**视口**里的方框，CSS 像素。"""

    x: float
    y: float
    w: float
    h: float
    visible: bool

    sized: bool = True

    def point(
        self,
        anchor: Anchor = "center",
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> tuple[float, float]:
        "算出点哪儿。"
        origin_x, origin_y = (
            (self.x, self.y) if anchor == "topleft" else (self.x + self.w / 2, self.y + self.h / 2)
        )
        return origin_x + offset[0], origin_y + offset[1]


_FIND_JS = """
(() => {
  const el = document.evaluate(%s, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  if (!el) return null;
  try { el.scrollIntoView({block: 'center', inline: 'center'}); } catch (e) {}
  const b = el.getBoundingClientRect();
  const st = getComputedStyle(el);
  const sized = b.width > 0 && b.height > 0
    && st.visibility !== 'hidden' && st.display !== 'none';
  const visible = sized && Number(st.opacity) > 0;
  return {x: b.left, y: b.top, w: b.width, h: b.height,
          visible: visible, sized: sized};
})()
"""


def _quote(text: str) -> str:
    """把字符串塞进 JS 字面量。用 JSON 转义 —— 自己拼引号在 XPath 里有单双引号时会炸。"""
    import json

    return json.dumps(text, ensure_ascii=False)


def xpath_literal(text: str) -> str:
    "把任意文本包成 XPath 字符串字面量。"
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"

    pieces: list[str] = []
    buf = ""
    for ch in text:
        if ch in "\"'":
            if buf:
                pieces.append(f"'{buf}'")
                buf = ""

            pieces.append('"\'"' if ch == "'" else "'\"'")
        else:
            buf += ch
    if buf:
        pieces.append(f"'{buf}'")
    return "concat(" + ", ".join(pieces) + ")"


async def find_box(browser: Browser, session: str, xpath: str) -> Box | None:
    """找到元素就返回它的方框，找不到返回 None（**不抛错** —— 等待逻辑要用）。"""
    value = await browser.eval(_FIND_JS % _quote(xpath), session=session)
    if not isinstance(value, dict):
        return None
    return Box(
        x=float(value["x"]),
        y=float(value["y"]),
        w=float(value["w"]),
        h=float(value["h"]),
        visible=bool(value["visible"]),
        sized=bool(value.get("sized", value["visible"])),
    )


async def wait_for(
    browser: Browser,
    session: str,
    xpath: str,
    *,
    timeout: float = 15.0,
    appear: bool = True,
    interval: float = 0.3,
) -> bool:
    "等元素出现（或消失）。到了返回 True，超时返回 False。"
    deadline = time.monotonic() + timeout
    while True:
        box = await find_box(browser, session, xpath)
        here = box is not None and box.visible
        if here == appear:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval)


async def click(
    browser: Browser,
    session: str,
    xpath: str,
    *,
    button: Literal["left", "right"] = "left",
    anchor: Anchor = "center",
    offset: tuple[float, float] = (0.0, 0.0),
) -> None:
    "点（或右键）一个元素。"
    box = await find_box(browser, session, xpath)
    if box is None:
        raise CdpError("点击元素", f"没找到元素：{xpath}")
    if not box.visible:
        raise CdpError("点击元素", f"元素不可见（点不到）：{xpath}")
    x, y = box.point(anchor, offset)
    buttons = 2 if button == "right" else 1
    for kind in ("mousePressed", "mouseReleased"):
        await browser.call(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": x,
                "y": y,
                "button": button,
                "buttons": buttons,
                "clickCount": 1,
            },
            session=session,
        )


async def type_text(
    browser: Browser,
    session: str,
    xpath: str,
    text: str,
    *,
    submit: bool = False,
) -> None:
    "把文字填进某个输入框。"
    focused = await browser.eval(_FOCUS_JS % _quote(xpath), session=session)
    if not focused:
        raise CdpError("填写输入框", f"没能把焦点放到：{xpath}")

    await browser.call("Input.insertText", {"text": text}, session=session)

    if not _contains(await browser.eval(_VALUE_JS % _quote(xpath), session=session), text):
        await _type_by_key(browser, session, text)

    if submit:
        await _key(browser, session, "Enter")


def _contains(value: Any, text: str) -> bool:
    return text in str(value if value is not None else "")


async def select_used_range(
    browser: Browser,
    session: str,
    grid_xpath: str,
    *,
    offset: tuple[float, float] = (40.0, 30.0),
) -> None:
    "选中整块**已用区域**（A1 → Ctrl+Shift+End）。"
    await click(browser, session, grid_xpath, anchor="topleft", offset=offset)

    await _key(browser, session, "End", modifiers=2 | 8)


async def copy_selection(browser: Browser, session: str) -> None:
    "Ctrl+C 复制当前选区。"
    await _key(browser, session, "c", modifiers=2)


_VALUE_JS = """
(() => {
  const el = document.evaluate(%s, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  return el ? String(el.value ?? '') : '';
})()
"""


async def _type_by_key(browser: Browser, session: str, text: str) -> None:
    "逐字符发**真实按键事件**。"
    for ch in text:
        vk = ord(ch.upper())
        await browser.call(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "text": ch,
                "unmodifiedText": ch,
                "key": ch,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            },
            session=session,
        )
        await browser.call(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": ch,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            },
            session=session,
        )


_FOCUS_JS = """
(() => {
  const el = document.evaluate(%s, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  if (!el) return false;
  el.focus();
  if (typeof el.select === 'function') el.select();
  return document.activeElement === el;
})()
"""

_KEY_CODES: dict[str, int] = {
    "Enter": 13,
    "Tab": 9,
    "Escape": 27,
    "Backspace": 8,
    "Delete": 46,
    "ArrowUp": 38,
    "ArrowDown": 40,
    "a": 65,
}


async def _key(browser: Browser, session: str, key: str, *, modifiers: int = 0) -> None:
    """敲一个键。``modifiers`` 位掩码：1=Alt 2=Ctrl 4=Meta 8=Shift。"""
    code = _KEY_CODES.get(key, 0)
    for kind in ("rawKeyDown", "keyUp"):
        params: dict[str, Any] = {
            "type": kind,
            "key": key,
            "code": key,
            "modifiers": modifiers,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
        }
        if key == "Enter":
            params["text"] = "\r"
        await browser.call("Input.dispatchKeyEvent", params, session=session)


_CLIPBOARD_JS = """
(async () => {
  try {
    return await navigator.clipboard.readText();
  } catch (e) {
    return '__DOCSYNC_CLIPBOARD_ERROR__' + (e && e.message ? e.message : String(e));
  }
})()
"""


async def read_clipboard(browser: Browser, session: str, origin: str) -> str:
    "读剪贴板 —— **走浏览器侧，不碰操作系统剪贴板**。"
    await browser.call(
        "Browser.grantPermissions",
        {"origin": origin, "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]},
    )
    value = await browser.eval(_CLIPBOARD_JS, session=session)
    text = "" if value is None else str(value)
    if text.startswith("__DOCSYNC_CLIPBOARD_ERROR__"):
        raise CdpError("读剪贴板", text.removeprefix("__DOCSYNC_CLIPBOARD_ERROR__"))
    return text


def parse_tsv(text: str, *, has_header: bool = True) -> tuple[list[str], list[list[str]]]:
    "把剪贴板里的 TSV 拆成 ``(表头, 数据行)``。"
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return [], []
    rows = [line.split("\t") for line in lines]
    if not has_header:
        return [], rows
    return rows[0], rows[1:]


def tsv_to_grid(header: list[str], rows: list[list[str]]) -> list[list[Any]]:
    """拼回带表头的网格，直接喂给现有管线（跟钉钉/飞书读出来的形状一致）。"""
    return ([list(header)] if header else []) + [list(row) for row in rows]
