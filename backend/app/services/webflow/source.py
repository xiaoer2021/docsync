"WPS 网页授权、下载工作簿并转为平台无关的 SourceData。"

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.normalize.headers import normalize_headers
from app.services.sources.base import SourceError
from app.services.sources.data import SourceData
from app.services.webflow.cdp import shared_browser

__all__ = [
    "DEFAULT_WPS_ELEMENTS",
    "DEFAULT_WPS_STEPS",
    "WebRecipe",
    "WebflowSource",
    "apply_layout",
    "list_sheets",
    "read_webflow",
    "recipe_for",
    "to_grid",
    "to_source_data",
]

DEFAULT_WPS_ELEMENTS: dict[str, str] = {
    "协作邀请弹窗关闭按钮": (
        "//div[@id='util-popup']//div[contains(@class,'wps-login-panel__header')]//button"
    ),
    "工作表页签": ("//*[contains(concat(' ', normalize-space(@class), ' '), ' sheet-name ')]"),
    "表格选区层": "//div[@id='et_select_grid']",
    "右键菜单复制项": (
        "//div[contains(@class,'panel-item-content')]"
        "[normalize-space(.)='复制' or normalize-space(.)='Copy']"
    ),
}

DEFAULT_WPS_STEPS: list[dict[str, Any]] = [
    {"action": "wait", "element": "工作表页签", "timeout": 15, "output": "has_sheets"},
    {"action": "wait", "element": "协作邀请弹窗关闭按钮", "timeout": 5, "output": "has_modal"},
    {"action": "if", "var": "has_modal"},
    {"action": "click", "element": "协作邀请弹窗关闭按钮"},
    {"action": "endif"},
    {"action": "sleep", "seconds": 2},
    {"action": "select_used_range", "element": "表格选区层"},
    {"action": "sleep", "seconds": 1},
    {"action": "rightclick", "element": "表格选区层", "anchor": "topleft", "offset_ratio": [0.2, 0.25]},
    {"action": "copy_menu", "element": "右键菜单复制项", "timeout": 8},
    {"action": "clipboard", "output": "clipboard_text"},
]


@dataclass
class WebRecipe:
    """一次网页取数要的全部配置。"""

    url: str
    elements: dict[str, str] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)

    profile: str = ""

    wait: float = 15.0


def recipe_for(app: object, url: str) -> WebRecipe:
    "应用记录 + 网址 → 一次网页取数要的配方。"
    from app.services.webflow.check import profile_name_for

    stored = getattr(app, "recipe", None)
    stored = stored if isinstance(stored, dict) else {}
    return WebRecipe(
        url=url,
        elements=stored.get("elements") or DEFAULT_WPS_ELEMENTS,
        steps=stored.get("steps") or DEFAULT_WPS_STEPS,
        profile=profile_name_for(getattr(app, "id", None)),
    )


@dataclass
class WebflowSource:
    "``DocSource`` 实现：一个网址就是一份数据。"

    profile: str = "webflow"
    recipe: dict[str, Any] | None = None

    profile_name: str = ""

    async def read(self, task: object, doc: object, logger: object, **_: object) -> SourceData:
        "读一份网页。"
        url = str(getattr(doc, "node_id", "") or "")
        stored = self.recipe or {}
        return await read_webflow(
            WebRecipe(
                url=url,
                elements=stored.get("elements") or DEFAULT_WPS_ELEMENTS,
                steps=stored.get("steps") or DEFAULT_WPS_STEPS,
                profile=self.profile_name,
            ),
            sheet=str(getattr(task, "sheet_id", "") or ""),
            cfg=getattr(task, "source_config", None) or {},
            logger=logger,  # type: ignore[arg-type]
        )


async def read_all_sheets_first_rows(recipe: WebRecipe, *, rows: int = 12) -> dict[str, list[list[str]]]:
    "开**一次**页面、下**一次**文件，返回每张表的前几行。"
    log = logging.getLogger(__name__)
    if not recipe.url:
        raise SourceError("没配网页地址", hint="到「读数据」那步填上要读的网页链接。")

    from app.services.webflow.actions import wait_for
    from app.services.webflow.download import download_xlsx, sheet_grids

    async with shared_browser(recipe.profile) as browser:
        session = await browser.new_page()
        await browser.call("Page.navigate", {"url": recipe.url}, session=session)
        if not await wait_for(browser, session, DEFAULT_WPS_ELEMENTS["工作表页签"], timeout=recipe.wait):
            log.info("网页取数：没找到表格外壳（可能不是表格，或页面没加载出来）")
            return {}
        path, _info = await download_xlsx(browser, session, _app_id_of(recipe.profile))

    grids = sheet_grids(path, rows)
    log.info("网页取数：一次读出 %s 张表的前 %s 行", len(grids), rows)
    return grids


def _app_id_of(profile: str) -> int:
    """档案名 ``app-<id>`` → id。下载按应用分目录（取不到就用 0，共用目录）。"""
    name = (profile or "").removeprefix("app-")
    return int(name) if name.isdigit() else 0


async def read_webflow(
    recipe: WebRecipe,
    *,
    sheet: str = "",
    cfg: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> SourceData:
    "打开网页 → **下载整份 xlsx** → 按工作表名读 → ``SourceData``。"
    log = logger or logging.getLogger(__name__)
    if not recipe.url:
        raise SourceError("没配网页地址", hint="到「读数据」那步填上要读的网页链接。")

    from app.services.webflow import fastpath
    from app.services.webflow.actions import wait_for
    from app.services.webflow.download import download_xlsx, read_grid

    app_id = _app_id_of(recipe.profile)

    path = await fastpath.reuse_if_unchanged(app_id, recipe.url)
    if path is None:
        async with shared_browser(recipe.profile) as browser:
            log.info("网页取数：已启动浏览器")
            session = await browser.new_page()
            await browser.call("Page.navigate", {"url": recipe.url}, session=session)

            await wait_for(browser, session, DEFAULT_WPS_ELEMENTS["工作表页签"], timeout=recipe.wait)
            path, info = await download_xlsx(browser, session, app_id)

            await fastpath.save_cookies(browser, session, app_id)
            fastpath.remember_file(app_id, recipe.url, info.file_id)

    grid = read_grid(path, sheet)
    if not grid:
        raise SourceError(
            f"这份文档里没读到数据（{path.name}）",
            hint="确认这张工作表有内容；也可能登录态过期了，去应用里重新登录一次。",
        )
    source = apply_layout(grid, cfg)
    log.info(
        "网页取数：取到 %s 行 × %s 列（工作表「%s」）",
        len(source.rows),
        len(source.header),
        sheet or "第一张",
    )
    return source


async def list_sheets(recipe: WebRecipe, *, logger: logging.Logger | None = None) -> list[str]:
    "这份文档里有哪些工作表 —— 直接来自**下载下来的 xlsx**。"
    log = logger or logging.getLogger(__name__)
    if not recipe.url:
        raise SourceError("没配网页地址", hint="到「读数据」那步填上要读的网页链接。")

    from app.services.webflow.actions import wait_for
    from app.services.webflow.download import download_xlsx, sheet_names

    async with shared_browser(recipe.profile) as browser:
        session = await browser.new_page()
        await browser.call("Page.navigate", {"url": recipe.url}, session=session)

        if not await wait_for(browser, session, DEFAULT_WPS_ELEMENTS["工作表页签"], timeout=recipe.wait):
            log.info("网页取数：没找到表格外壳（可能不是表格，或页面没加载出来）")
            return []
        path, _info = await download_xlsx(browser, session, _app_id_of(recipe.profile))

    names = sheet_names(path)
    log.info(f"网页取数：读到 {len(names)} 个工作表")
    return names


def to_grid(text: str) -> list[list[str]]:
    """剪贴板 TSV → **网格**（含表头那一行）。空行丢掉。"""
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    return [line.split("\t") for line in lines]


def _pos_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 1 else default


def to_source_data(text: str, cfg: dict[str, Any] | None = None) -> SourceData:
    "剪贴板文本 → ``SourceData``。**纯函数**，不碰浏览器，单独测。"
    grid = to_grid(text)
    if not grid:
        raise SourceError(
            "网页里没取到表格数据",
            hint="多半是两种情况：① 被踢到登录页了（这种网页需要登录，"
            "去应用里重新登录一次）；② 网页改版了，元素库里的 XPath 失效 —— "
            "步骤配置里能看到具体卡在第几步。",
        )
    return apply_layout(grid, cfg)


def apply_layout(grid: list[list[str]], cfg: dict[str, Any] | None = None) -> SourceData:
    "按读取配置把整块网格切成 ``SourceData``（表头行 + 数据行）。"
    cfg = dict(cfg or {})
    orientation = str(cfg.get("orientation") or "vertical")
    if orientation != "vertical":
        raise SourceError(
            "网页取数只支持「纵向表」（一行一条记录）。",
            hint="横向表 / 日期交叉表还没做 —— 需要先按列探测，怕猜错就先把入口挡住。"
            "如果这张表就是横向的，先在文档里把它转成纵向。",
        )

    header_row = _pos_int(cfg.get("header_row"), 1)
    data_start = _pos_int(cfg.get("data_start_row"), header_row + 1)

    if header_row > len(grid):
        raise SourceError(
            f"表头在第 {header_row} 行，但整块只读到 {len(grid)} 行。",
            hint="检查「表头在第几行」填得对不对。",
        )

    width = max((len(row) for row in grid), default=0)
    header = normalize_headers(grid[header_row - 1], width=width or None)

    rows: list[tuple[int, list]] = []
    for offset, raw in enumerate(grid[data_start - 1 :]):
        rows.append((data_start + offset, list(raw)))

    return SourceData(header=header, rows=rows)
