"WPS 登录（金山账号授权）：给界面一份**状态快照**，界面自己画。"

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.sources.base import SourceError
from app.services.webflow.actions import find_box, wait_for
from app.services.webflow.cdp import Browser, CdpError

log = logging.getLogger(__name__)

__all__ = [
    "LOGIN_LOCATORS",
    "click_at",
    "close_login",
    "fill",
    "pick_accounts",
    "poll_login",
    "send_key",
    "start_login",
    "tap",
    "tap_button",
    "type_text",
    "use_mode",
]

LOGIN_URL = "https://account.wps.cn/?qrcode=kdocs&from=v1-web-kdocs-login"

SESSION_TTL = 180.0

LOGIN_LOCATORS: dict[str, str] = {
    "同意协议": "//input[@id='loginProtocal']",
    "二维码图": "//div[contains(@class,'qrcode_img')]//img",
    "页签-手机": "//span[contains(@class,'f_icon_txt')][normalize-space(.)='手机']",
    "页签-专属账号": "//span[contains(@class,'f_icon_txt')][normalize-space(.)='专属账号']",
    "返回": "//span[normalize-space(.)='返回']",
    "手机-手机号": "//input[@id='phone']",
    "手机-验证码": "//input[@id='code']",
    "手机-发送验证码": "//a[contains(@class,'resendBtn')]",
    "手机-登录": "//a[contains(@class,'form_button')]",
    "专属-账号": "//input[@id='otherName']",
    "专属-验证": "//button[@id='other_commit']",
}


def _loc(app: object, key: str) -> tuple[str, str]:
    "取一个定位，返回 ``(xpath, 来源)``。"
    stored = getattr(app, "recipe", None)
    elements = stored.get("elements") if isinstance(stored, dict) else None
    name = f"登录-{key}"
    if isinstance(elements, dict) and str(elements.get(name) or "").strip():
        return str(elements[name]).strip(), "recipe"
    return LOGIN_LOCATORS[key], "default"


def locator_source(app: object) -> str:
    """整体走的哪条：``default``（全内置）/ ``recipe``（全映射）/ ``mixed``。"""
    sources = {_loc(app, key)[1] for key in LOGIN_LOCATORS}
    if sources == {"recipe"}:
        return "recipe"
    return "mixed" if "recipe" in sources else "default"


@dataclass
class _Login:
    app_id: int
    browser: Browser
    session: str
    started_at: float

    baseline: set[str] = field(default_factory=set)


_SESSIONS: dict[int, _Login] = {}


async def _drop(app_id: int) -> None:
    live = _SESSIONS.pop(app_id, None)
    if live is not None:
        await live.browser.close()


async def _expired(app_id: int) -> bool:
    live = _SESSIONS.get(app_id)
    return live is not None and time.monotonic() - live.started_at > SESSION_TTL


_LOGGED_IN_MARK = (
    "//*[normalize-space(.)='Sign Out' or normalize-space(.)='退出登录'"
    " or normalize-space(.)='Switch Account' or normalize-space(.)='切换账号']"
)

_ANON_MARK = "//*[contains(concat(' ', normalize-space(@class), ' '), ' login-guid-btn ')]"

_LOGIN_STAGE_JS = """
(() => {
  if (document.readyState !== 'complete') return 'loading';
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    if (!r.width || !r.height) return false;
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity || '1') <= 0.1) return false;
    return r.bottom > 0 && r.top < window.innerHeight;
  };
  const any = (sel) => Array.from(document.querySelectorAll(sel)).some(vis);

  if (any('.qrcode_img') || any('#qrcode_img') || any('#phone') || any('#code')
      || any('#otherName')) return 'form';

  if (Array.from(document.querySelectorAll('input[type=checkbox]')).some(vis)) return 'pick';
  return 'done';
})()
"""


async def _login_stage(browser: Browser, session: str) -> str:
    """'loading' | 'form'（登录页）| 'pick'（选账号页）| 'done'（都不像）。"""
    try:
        return str(await browser.eval(_LOGIN_STAGE_JS, session=session) or "loading")
    except CdpError:
        return "loading"


_CHECK_URL = "https://account.wps.cn/"

_QR_ONLY_JS = """
(() => {
  const items = Array.from(document.querySelectorAll('.f_icon_txt'));
  if (!items.length) return 0;
  let row = items[0].parentElement;
  for (let up = 0; up < 4 && row; up++) {
    if (row.querySelectorAll('.f_icon_txt').length >= 2) break;
    row = row.parentElement;
  }
  let n = 0;
  if (row && !row.querySelector('.qrcode_img, #qrcode_img')) {
    row.style.setProperty('display', 'none', 'important');
    n++;
  }
  items.forEach((el) => { el.style.setProperty('display', 'none', 'important'); n++; });
  return n;
})()
"""


async def _qr_only(browser: Browser, session: str) -> None:
    """把"别的登录方式"入口藏掉（每轮都调一下：金山会重渲染，藏过一次不等于一直藏）。"""
    try:
        await browser.eval(_QR_ONLY_JS, session=session)
    except CdpError:
        pass


async def _cookie_names(browser: Browser, session: str) -> set[str]:
    """当前页域下有哪些 cookie —— **只要名字**（值在 encrypted_value 里，读不到也不需要）。"""
    try:
        href = str(await browser.eval("location.href", session=session) or "")
        got = await browser.call("Network.getCookies", {"urls": [href]}, session=session)
    except CdpError:
        return set()
    return {str(c.get("name") or "") for c in (got.get("cookies") or []) if c.get("name")}


async def _logged_in(browser: Browser, session: str, baseline: set[str] | None = None) -> bool:
    "登上了没 —— **另开一个页签问金山账号页**：落到登录页=没登，落到个人中心=登了。"
    _ = baseline

    try:
        href = str(await browser.eval("location.href", session=session) or "")
    except CdpError:
        return False

    if await _login_stage(browser, session) in ("loading", "form", "pick"):
        return False

    if "wps.cn" not in href and "kdocs.cn" not in href:
        return False

    try:
        target = await browser.call("Target.createTarget", {"url": _CHECK_URL})
        tid = str(target["targetId"])
        attached = await browser.call("Target.attachToTarget", {"targetId": tid, "flatten": True})
        probe = str(attached["sessionId"])
    except (CdpError, KeyError):
        return False
    try:
        stage = "loading"
        for _ in range(10):
            await asyncio.sleep(1.0)
            stage = await _login_stage(browser, probe)
            if stage != "loading":
                break

        return stage not in ("loading", "form")
    except CdpError:
        return False
    finally:
        with contextlib.suppress(CdpError):
            await browser.call("Target.closeTarget", {"targetId": tid})


_SNAPSHOT_JS = """
(() => {
  const vis = (e) => { if (!e) return false;
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const val = (sel) => { const e = document.querySelector(sel); return e ? (e.value || '') : ''; };
  const out = {mode: 'qr', qr: '', accounts: [], buttons: [], title: '', texts: [],
               fields: {phone: '', code: '', name: ''}};

  const phone = document.querySelector('#phone');
  const other = document.querySelector('#otherName');

  const q = document.querySelector('.qrcode_img img') || document.querySelector('#qrcode_img img');
  const qrVisible = !!(q && vis(q));

  const boxes = Array.from(document.querySelectorAll('input[type=checkbox]')).filter(vis);

  if (phone && vis(phone)) out.mode = 'mobile';
  else if (other && vis(other)) out.mode = 'exclusive';
  else if (!qrVisible && boxes.length > 0) out.mode = 'pick';

  else if (!qrVisible) out.mode = 'unknown';

  if (qrVisible) out.qr = q.src || '';
  out.fields.phone = val('#phone');
  out.fields.code = val('#code');
  out.fields.name = val('#otherName');

  if (out.mode === 'pick') {
    const rows = boxes.map((e, i) => {

      let row = e.parentElement;
      for (let h = 0; h < 6 && row; h++) {
        const t = (row.textContent || '').trim();
        if (t.length >= 2 && t.length <= 40) break;
        row = row.parentElement;
      }
      const img = row ? row.querySelector('img') : null;
      return {i, checked: !!e.checked,
              name: row ? (row.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40) : '',
              avatar: img ? (img.getAttribute('src') || '') : ''};
    });

    const withAvatar = rows.filter((r) => r.avatar);
    out.accounts = withAvatar.length ? withAvatar : rows;
  }

  out.buttons = Array.from(document.querySelectorAll('button, a, [role=button]'))
    .filter(vis)
    .map((e, i) => ({i, text: (e.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 16)}))
    .filter((b) => b.text);

  out.title = (document.title || '').slice(0, 60);
  out.texts = [...new Set(Array.from(document.querySelectorAll('*'))
    .filter((e) => !e.children.length && vis(e))
    .map((e) => (e.textContent || '').trim().replace(/\\s+/g, ' '))
    .filter((t) => t && t.length <= 24))].slice(0, 8);
  return JSON.stringify(out);
})()
"""


async def _snapshot(live: _Login) -> dict:
    raw = await live.browser.eval(_SNAPSHOT_JS, session=live.session)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


async def _ready(app: object) -> _Login | None:
    app_id = int(app.id)
    live = _SESSIONS.get(app_id)
    if live is None or await _expired(app_id):
        return None
    return live


async def _view(browser: Browser, session: str) -> tuple[int, int]:
    """视口尺寸（CSS 像素）—— 界面拿它把点击位置换算回页面坐标。"""
    width = int(await browser.eval("window.innerWidth", session=session) or 0)
    height = int(await browser.eval("window.innerHeight", session=session) or 0)
    return max(width, 1), max(height, 1)


async def _shot(browser: Browser, session: str, clip: dict | None = None) -> str:
    "截**视口**（1:1、不缩放），返回 base64 PNG。"
    if clip is None:
        width, height = await _view(browser, session)
        clip = {"x": 0, "y": 0, "width": width, "height": height}
    return base64.b64encode(await browser.screenshot(session=session, clip=clip)).decode("ascii")


_CARD_JS = """
(() => {
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    if (!r.width || !r.height) return false;
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity || '1') <= 0.1) return false;
    return r.bottom > 0 && r.top < window.innerHeight;
  };

  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return {x: r.left, y: r.top, w: r.width, h: r.height};
  };

  const mainEl = document.querySelector('.main') || document.querySelector('#mainWrap');
  const card = mainEl && vis(mainEl) ? rectOf(mainEl) : null;

  const union = (els) => {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const el of els) {
      if (!vis(el)) continue;
      const r = el.getBoundingClientRect();
      x1 = Math.min(x1, r.left); y1 = Math.min(y1, r.top);
      x2 = Math.max(x2, r.right); y2 = Math.max(y2, r.bottom);
    }
    return isFinite(x1) ? {x: x1, y: y1, w: x2 - x1, h: y2 - y1} : null;
  };

  const cardSels = ['.qrcode_img', '#qrcode_img', '#phone', '#code', '#otherName',
                    '.f_icon_txt'];
  const cardFallback = union(cardSels.flatMap((s) => Array.from(document.querySelectorAll(s))));

  let pick = null;
  const boxes = Array.from(document.querySelectorAll('input[type=checkbox]')).filter(vis);
  if (boxes.length) {
    let node = boxes[0].parentElement;
    for (let up = 0; up < 6 && node && node.parentElement; up++) {
      const n = node.parentElement;
      const b = n.getBoundingClientRect();
      if (b.width > window.innerWidth * 0.6 && b.height > window.innerHeight * 0.6) break;
      node = n;
    }
    const r = node.getBoundingClientRect();
    pick = {x: r.left, y: r.top, w: r.width, h: r.height};
  }

  let dialog = null;
  const btns = Array.from(document.querySelectorAll('button,a,div,span'))
    .filter((el) => vis(el) && (el.innerText || '').replace(/\s/g, '') === '登录');
  if (btns.length) {
    let node = btns[0];
    for (let up = 0; up < 8 && node && node.parentElement; up++) {
      const n = node.parentElement;
      const b = n.getBoundingClientRect();
      if (b.width > window.innerWidth * 0.6 && b.height > window.innerHeight * 0.6) break;
      node = n;
    }
    const r = node.getBoundingClientRect();
    dialog = {x: r.left, y: r.top, w: r.width, h: r.height};
  }
  return {card: card || cardFallback, pick: pick, dialog: dialog};
})()
"""


async def _card_clip(browser: Browser, session: str, width: int, height: int) -> dict:
    "该截哪一块 —— 按**当前是哪一屏**挑：选账号屏只要那张卡片，其它屏要登录卡片。"
    try:
        data = await browser.eval(_CARD_JS, session=session) or {}
    except CdpError:
        data = {}
    stage = await _login_stage(browser, session)
    card = data.get("card")
    pick = data.get("pick")
    dialog = data.get("dialog")
    if stage == "pick":
        box = pick or dialog or card
    else:
        box = card

        if box and box.get("w", 0) > width * 0.6 and box.get("h", 0) > height * 0.6:
            box = dialog or pick or box
        elif not box:
            box = dialog or pick
    if not box:
        box = {"x": 0, "y": 0, "w": float(width), "h": float(height)}

    log.info(
        "WPS 登录：裁剪 %s（屏=%s；候选 card=%s pick=%s dialog=%s）",
        box,
        stage,
        card,
        pick,
        dialog,
    )
    pad = 28.0
    x = max(0.0, float(box["x"]) - pad)
    y = max(0.0, float(box["y"]) - pad)
    right = min(float(width), float(box["x"]) + float(box["w"]) + pad)
    bottom = min(float(height), float(box["y"]) + float(box["h"]) + pad)
    return {
        "x": round(x),
        "y": round(y),
        "width": round(max(40.0, right - x)),
        "height": round(max(40.0, bottom - y)),
    }


async def _state(app: object, app_id: int) -> dict:
    "当前该给界面看什么：**一帧真页面** + 是哪一屏 + 有哪些字段/账号。"
    live = _SESSIONS.get(app_id)
    if live is None:
        return {"status": "expired"}
    if await _expired(app_id):
        await _drop(app_id)
        return {"status": "expired"}

    try:
        href = str(await live.browser.eval("location.href", session=live.session) or "")
        anon = bool(
            await live.browser.eval("!!document.querySelector('.login-guid-btn')", session=live.session)
        )
        got = await live.browser.call("Network.getCookies", {"urls": [href]}, session=live.session)
        names = ",".join(sorted(str(c.get("name", "")) for c in (got.get("cookies") or [])))
        log.info(
            "WPS 登录轮询：app-%s 游客入口=%s href=%s cookies=[%s]",
            app_id,
            anon,
            href,
            names[:160],
        )
    except CdpError as exc:
        log.info("WPS 登录轮询：app-%s 读状态失败（%s）", app_id, exc)

    if not live.baseline:
        try:
            if await _login_stage(live.browser, live.session) == "form":
                live.baseline = await _cookie_names(live.browser, live.session)
                log.info("WPS 登录：记下游客基线（app-%s，%s 个）", app_id, len(live.baseline))
        except CdpError:
            pass

    if await _logged_in(live.browser, live.session, live.baseline):
        await asyncio.sleep(1.5)
        if not await _logged_in(live.browser, live.session, live.baseline):
            log.info("WPS 登录：第一次判成功但复检又变回游客，继续等（app-%s）", app_id)
        else:
            await _drop(app_id)
            log.info("WPS 登录成功：app-%s", app_id)
            return {"status": "ok"}

    try:
        await _qr_only(live.browser, live.session)
        snap = await _snapshot(live)
        width, height = await _view(live.browser, live.session)
        clip = await _card_clip(live.browser, live.session, width, height)
        image = await _shot(live.browser, live.session, clip)
    except CdpError:
        await _drop(app_id)
        return {"status": "expired"}

    return {
        "status": "waiting",
        "source": locator_source(app),
        "image": image,
        "view": {"w": clip["width"], "h": clip["height"], "x": clip["x"], "y": clip["y"]},
        **snap,
    }


async def _tap_at(browser: Browser, session: str, x: float, y: float) -> None:
    """在指定坐标点一下（左键，一按一放）。"""
    for kind in ("mousePressed", "mouseReleased"):
        await browser.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
            session=session,
        )


async def click_at(app: object, *, x: float, y: float) -> dict:
    """把界面上点的那一下**原样点回页面上**（x/y 是页面 CSS 像素）。"""
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}
    await _tap_at(live.browser, live.session, float(x), float(y))
    await asyncio.sleep(0.6)
    return await _state(app, int(app.id))


async def type_text(app: object, text: str) -> dict:
    """把一段文字打到页面**当前焦点**处（先在映射画面上点输入框）。"""
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}
    await live.browser.call("Input.insertText", {"text": text}, session=live.session)
    await asyncio.sleep(0.4)
    return await _state(app, int(app.id))


_KEY_CODES: dict[str, int] = {
    "Enter": 13,
    "Backspace": 8,
    "Tab": 9,
    "Delete": 46,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
    "Escape": 27,
}


async def send_key(app: object, key: str) -> dict:
    """敲一个功能键（退格 / 回车 / Tab / 方向键…）。"""
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}
    code = _KEY_CODES.get(key, 0)
    for kind in ("rawKeyDown", "keyUp"):
        params: dict[str, Any] = {
            "type": kind,
            "key": key,
            "code": key,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
        }
        if key == "Enter":
            params["text"] = "\r"
        await live.browser.call("Input.dispatchKeyEvent", params, session=live.session)
    await asyncio.sleep(0.4)
    return await _state(app, int(app.id))


async def _click_loc(app: object, live: _Login, key: str, *, required: bool = True) -> bool:
    "按定位点一下。``required=False`` 时找不到就静静返回 False。"
    xpath, _ = _loc(app, key)
    box = await find_box(live.browser, live.session, xpath)
    if box is None or not box.sized:
        if required:
            raise SourceError(
                f"登录页上找不到「{key}」。",
                hint="金山大概改版了 —— 在应用里把「登录-」开头的映射改一下（兜底那条路）。",
            )
        return False
    x, y = box.point()
    for kind in ("mousePressed", "mouseReleased"):
        await live.browser.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
            session=live.session,
        )
    return True


async def start_login(app: object) -> dict:
    """开一个登录会话（同一个应用已经有活着的会话就**接着用**）。"""
    app_id = int(app.id)

    if app_id in _SESSIONS and not await _expired(app_id):
        return await _state(app, app_id)

    await _drop(app_id)

    from app.services.webflow import cdp as _cdp
    from app.services.webflow.check import profile_name_for

    await _cdp.close_shared(profile_name_for(app_id))
    browser = Browser(profile=profile_name_for(app_id))
    try:
        await browser.start()
        session = await browser.new_page()
        await browser.call("Page.navigate", {"url": LOGIN_URL}, session=session)

        await wait_for(browser, session, LOGIN_LOCATORS["二维码图"], timeout=12)
        live = _Login(app_id, browser, session, time.monotonic())
        _SESSIONS[app_id] = live

        live.baseline = await _cookie_names(browser, session)
        log.info("WPS 登录：游客基线 %s 个 cookie（%s）", len(live.baseline), sorted(live.baseline))

        await _ensure_agreed(app, _SESSIONS[app_id])
    except CdpError as exc:
        _SESSIONS.pop(app_id, None)
        await browser.close()
        raise SourceError(f"浏览器起不来：{exc.message}", hint="服务器上要能跑 Chromium。") from exc

    return await _state(app, app_id)


async def poll_login(app: object) -> dict:
    """问一句「现在到哪一步了」。"""
    return await _state(app, int(app.id))


async def use_mode(app: object, mode: str) -> dict:
    "切到某一屏：``qr`` / ``mobile`` / ``exclusive``。"
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}

    await live.browser.call("Page.navigate", {"url": LOGIN_URL}, session=live.session)
    await asyncio.sleep(2.0)

    await _ensure_agreed(app, live)
    if mode != "qr":
        await asyncio.sleep(0.3)
        key = "页签-手机" if mode == "mobile" else "页签-专属账号"
        await _click_loc(app, live, key)
    await asyncio.sleep(1.2)
    return await _state(app, int(app.id))


async def fill(app: object, field: str, text: str) -> dict:
    "往表单里填字：``phone`` / ``code`` / ``name``。"
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}

    key = {"phone": "手机-手机号", "code": "手机-验证码", "name": "专属-账号"}.get(field)
    if key is None:
        raise SourceError(f"不认识的输入框：{field}")
    await _click_loc(app, live, key)
    await live.browser.call("Input.insertText", {"text": text}, session=live.session)
    await asyncio.sleep(0.2)
    return await _state(app, int(app.id))


async def tap(app: object, action: str) -> dict:
    """点一个按钮：``send_code`` / ``submit`` / ``back``。"""
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}

    if action == "send_code":
        await _click_loc(app, live, "手机-发送验证码")
    elif action == "submit":
        key = "专属-验证" if (await _snapshot(live)).get("mode") == "exclusive" else "手机-登录"
        await _click_loc(app, live, key)
    elif action == "back":
        await _click_loc(app, live, "返回", required=False)
    else:
        raise SourceError(f"不认识的按钮：{action}")
    await asyncio.sleep(1.5)
    return await _state(app, int(app.id))


async def _ensure_agreed(app: object, live: _Login) -> None:
    "确保「同意协议」是**勾上**的。"
    xpath, _ = _loc(app, "同意协议")
    from app.services.webflow.actions import _quote

    try:
        js = (
            "(() => { const e = document.evaluate("
            + _quote(xpath)
            + ", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;"
            " return e ? !!e.checked : null; })()"
        )
        state = await live.browser.eval(js, session=live.session)
    except CdpError:
        return
    if state is False:
        await _click_loc(app, live, "同意协议", required=False)
        await asyncio.sleep(0.3)


async def _tap_button_index(live: _Login, index: int) -> None:
    """点页面上第 ``index`` 个"能点的东西"（判定与快照 ``buttons`` 同口径）。"""
    items: Any = await live.browser.eval(
        "(() => Array.from(document.querySelectorAll('button, a, [role=button]'))"
        ".filter((e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);"
        " return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'"
        " && (e.textContent || '').trim(); })"
        ".map((e) => { const r = e.getBoundingClientRect();"
        " return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]; }))()",
        session=live.session,
    )
    if not isinstance(items, list) or index < 0 or index >= len(items):
        raise SourceError(
            "那个按钮已经不在了（页面可能已经跳走）。",
            hint="点「重新开始」再看一眼当前这一屏。",
        )
    x, y = items[index]
    for kind in ("mousePressed", "mouseReleased"):
        await live.browser.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
            session=live.session,
        )


async def tap_button(app: object, index: int) -> dict:
    '点页面上第 ``index`` 个"能点的东西"（序号与快照 ``buttons[].i`` 同口径）。'
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}

    await _ensure_agreed(app, live)
    await _tap_button_index(live, index)
    await asyncio.sleep(1.5)
    return await _state(app, int(app.id))


async def pick_accounts(app: object, indexes: list[int], *, submit: int | None = None) -> dict:
    "勾选指定账号；``submit`` 给了就**在这次调用里**把那个按钮一起点了。"
    live = await _ready(app)
    if live is None:
        return {"status": "expired"}

    boxes: Any = await live.browser.eval(
        "(() => Array.from(document.querySelectorAll('input[type=checkbox]'))"
        ".filter((e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);"
        " return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; })"
        ".map((e) => { const r = e.getBoundingClientRect();"
        " return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2),"
        " !!e.checked]; }))()",
        session=live.session,
    )
    wanted = {int(i) for i in (indexes or [])}
    for index, item in enumerate(boxes or []):
        if not isinstance(item, list) or len(item) < 3:
            continue
        x, y, checked = item
        if bool(checked) == (index in wanted):
            continue
        for kind in ("mousePressed", "mouseReleased"):
            await live.browser.call(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
                session=live.session,
            )
        await asyncio.sleep(0.2)
    if submit is not None:
        await asyncio.sleep(0.3)
        await _ensure_agreed(app, live)
        await _tap_button_index(live, int(submit))
    await asyncio.sleep(1.5)
    return await _state(app, int(app.id))


async def close_login(app: object) -> None:
    await _drop(int(app.id))


async def close_all() -> None:
    """进程退出 / 测试清理用。"""
    for app_id in list(_SESSIONS):
        await _drop(app_id)
