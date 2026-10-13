"步骤解释器：把「元素库 + 步骤表」当成数据跑。"

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.services.sources.base import SourceError
from app.services.webflow.actions import (
    _key,
    click,
    find_box,
    read_clipboard,
    select_used_range,
    type_text,
    wait_for,
    xpath_literal,
)
from app.services.webflow.cdp import Browser, CdpError

__all__ = ["ElementLibrary", "FlowError", "Step", "parse_flow", "run_flow"]


class FlowError(SourceError):
    "某一步失败。"

    def __init__(self, index: int, action: str, detail: str) -> None:
        super().__init__(
            f"第 {index} 步（{action}）失败：{detail}",
            hint="到「网页取数」的步骤里核对这一步的配置；元素找不到时先看一眼"
            "元素库里的 XPath 还对不对（网页改版后 XPath 会失效）。",
        )
        self.index = index
        self.action = action


@dataclass
class Step:
    action: str
    raw: dict[str, Any] = field(default_factory=dict)
    index: int = 0


_ACTIONS = {
    "goto",
    "sleep",
    "wait",
    "if",
    "endif",
    "click",
    "rightclick",
    "type",
    "select_used_range",
    "select_sheet",
    "copy_menu",
    "key",
    "clipboard",
}


def parse_flow(raw: list[dict[str, Any]] | None) -> list[Step]:
    "把配置解析成步骤列表。**不认识的动词直接跳过**（不报错）："
    steps: list[Step] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if action not in _ACTIONS:
            continue
        steps.append(Step(action=action, raw=item, index=len(steps) + 1))
    return steps


class ElementLibrary:
    "元素库：名称 → XPath。"

    def __init__(self, items: dict[str, str] | None) -> None:
        self._items: dict[str, str] = {}
        for name, xpath in (items or {}).items():
            self._items[_elem_key(str(name))] = str(xpath)

    def xpath(self, name: str) -> str:
        found = self._items.get(_elem_key(name))
        if not found:
            known = "、".join(sorted(self._items)) or "（元素库是空的）"
            raise KeyError(f"元素库里没有「{name}」。现有元素：{known}")
        return found


def _elem_key(text: str) -> str:
    "元素名的比对键。**不叫 ``_key``** —— 那个名字是「敲一个键」的动作，"
    return "".join(str(text).split()).replace("（", "(").replace("）", ")")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "false", "False", "0")
    return bool(value)


async def run_flow(
    browser: Browser,
    session: str,
    steps: list[Step],
    elements: ElementLibrary,
    *,
    origin: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    "跑完一串步骤，返回全部变量（含 ``clipboard_text``）。"
    env: dict[str, Any] = dict(variables or {})
    index = 0
    while index < len(steps):
        step = steps[index]
        action = step.action
        raw = step.raw

        if action == "if":
            if not _truthy(env.get(str(raw.get("var") or ""))):
                index = _matching_endif(steps, index)
                continue
            index += 1
            continue
        if action == "endif":
            index += 1
            continue

        try:
            await _do(browser, session, step, elements, env, origin)
        except KeyError as exc:
            raise FlowError(step.index, action, str(exc)) from exc
        except CdpError as exc:
            raise FlowError(step.index, action, exc.message) from exc
        index += 1

    return env


def _matching_endif(steps: list[Step], start: int) -> int:
    """``steps[start]`` 是 ``if``，返回配对 ``endif`` 的下标（没有就到最后）。"""
    depth = 0
    for offset in range(start, len(steps)):
        if steps[offset].action == "if":
            depth += 1
        elif steps[offset].action == "endif":
            depth -= 1
            if depth == 0:
                return offset + 1
    return len(steps)


async def _do(
    browser: Browser,
    session: str,
    step: Step,
    elements: ElementLibrary,
    env: dict[str, Any],
    origin: str,
) -> None:
    raw = step.raw
    action = step.action
    timeout = float(raw.get("timeout") or 15.0)

    if action == "goto":
        await browser.call("Page.navigate", {"url": str(raw.get("url") or "")}, session=session)
        return

    if action == "wait":
        xpath = elements.xpath(str(raw.get("element") or ""))

        appear = raw.get("appear", True) is not False
        found = await wait_for(browser, session, xpath, timeout=timeout, appear=appear)
        env[str(raw.get("output") or "wait_result")] = found
        return

    if action in ("click", "rightclick", "copy_menu"):
        xpath = elements.xpath(str(raw.get("element") or ""))

        if not await wait_for(browser, session, xpath, timeout=timeout):
            raise FlowError(
                step.index,
                action,
                f"等了 {timeout:.0f} 秒也没出现：{xpath}"
                "（右键菜单要先右键、菜单弹出需要一点时间；也可能是上一步没生效）",
            )
        if action == "click":
            await click(browser, session, xpath)
        elif action == "rightclick":
            box = await find_box(browser, session, xpath)
            offset = (
                float(raw.get("offset_x") or 0.0),
                float(raw.get("offset_y") or 0.0),
            )
            ratio = raw.get("offset_ratio")
            if isinstance(ratio, list | tuple) and len(ratio) == 2 and box is not None:
                offset = (box.w * float(ratio[0]), box.h * float(ratio[1]))
            await click(
                browser,
                session,
                xpath,
                button="right",
                anchor=str(raw.get("anchor") or "center"),  # type: ignore[arg-type]
                offset=offset,
            )
        else:
            await click(browser, session, xpath)
        return

    if action == "sleep":
        await asyncio.sleep(float(raw.get("seconds") or 1.0))
        return

    if action == "type":
        xpath = elements.xpath(str(raw.get("element") or ""))
        if not await wait_for(browser, session, xpath, timeout=timeout):
            raise FlowError(step.index, action, f"等了 {timeout:.0f} 秒也没看到输入框：{xpath}")
        await type_text(
            browser,
            session,
            xpath,
            str(raw.get("text") or ""),
            submit=raw.get("submit", True) is not False,
        )
        return

    if action == "select_used_range":
        xpath = elements.xpath(str(raw.get("element") or ""))
        if not await wait_for(browser, session, xpath, timeout=timeout):
            raise FlowError(step.index, action, f"等了 {timeout:.0f} 秒也没看到表格：{xpath}")
        await select_used_range(browser, session, xpath)
        return

    if action == "select_sheet":
        name = str(env.get(str(raw.get("var") or "sheet")) or "").strip()
        if not name:
            return
        base = elements.xpath(str(raw.get("element") or "工作表页签"))
        xpath = f"{base}[normalize-space(.)={xpath_literal(name)}]"
        if not await wait_for(browser, session, xpath, timeout=timeout):
            raise FlowError(
                step.index,
                action,
                f"没找到工作表页签「{name}」：{xpath}"
                "（文档改过名 / 页签被折叠了 / 元素库里「工作表页签」的 XPath 失效）",
            )
        await click(browser, session, xpath)
        return

    if action == "copy_menu":
        await click(browser, session, elements.xpath(str(raw.get("element") or "右键菜单复制项")))
        return

    if action == "key":
        await _key(
            browser,
            session,
            str(raw.get("key") or ""),
            modifiers=int(raw.get("modifiers") or 0),
        )
        return

    if action == "clipboard":
        text = await read_clipboard(browser, session, origin)
        env[str(raw.get("output") or "clipboard_text")] = text
        return

    raise FlowError(step.index, action, "这个动作还没实现")
