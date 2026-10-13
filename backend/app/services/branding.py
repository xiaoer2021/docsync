"品牌设置：名称、标题、标签页名、logo。"

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.setting import DdSetting

DEFAULTS: dict[str, str] = {
    "name": "在线表格同步",
    "title": "在线表格同步",
    "tab_title": "在线表格同步",
}

LIMITS: dict[str, int] = {"name": 20, "title": 40, "tab_title": 40}

LOGO_EXTS = ("png", "jpg", "svg", "webp")


def logo_dir() -> Path:
    return settings.data_dir / "branding"


def find_logo() -> Path | None:
    """当前 logo 文件。按扩展名逐个找 —— 用户传 png 还是 svg 都收。"""
    d = logo_dir()
    for ext in LOGO_EXTS:
        path = d / f"logo.{ext}"
        if path.exists():
            return path
    return None


def _payload(stored: dict[str, str | None]) -> dict:
    out: dict = {key: (stored.get(key) or default) for key, default in DEFAULTS.items()}
    path = find_logo()
    out["has_logo"] = path is not None

    out["logo_updated_at"] = (
        dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        if path is not None
        else None
    )
    return out


async def read_branding(session: AsyncSession) -> dict:
    stored = {row.key: row.value for row in (await session.scalars(select(DdSetting))).all()}
    return _payload(stored)


async def write_branding(session: AsyncSession, data: dict[str, str | None]) -> dict:
    """只改传进来的项。传空字符串表示**恢复默认**（删掉那一行）。"""
    rows = {row.key: row for row in (await session.scalars(select(DdSetting))).all()}
    for key in DEFAULTS:
        if key not in data:
            continue
        value = (data.get(key) or "").strip()
        row = rows.get(key)
        if not value:
            if row is not None:
                await session.delete(row)
            continue
        value = value[: LIMITS[key]]
        if row is None:
            session.add(DdSetting(key=key, value=value))
        else:
            row.value = value
    await session.flush()
    return await read_branding(session)


def save_logo(filename: str, content: bytes) -> None:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "png").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in LOGO_EXTS:
        raise ValueError(f"不支持的图片格式 .{ext}，请用 png / jpg / svg / webp")

    directory = logo_dir()
    directory.mkdir(parents=True, exist_ok=True)

    for other in LOGO_EXTS:
        old = directory / f"logo.{other}"
        if old.exists() and other != ext:
            old.unlink()
    (directory / f"logo.{ext}").write_bytes(content)


def clear_logo() -> None:
    """删掉自定义 logo，回到内置的那张。"""
    path = find_logo()
    if path is not None:
        path.unlink()
