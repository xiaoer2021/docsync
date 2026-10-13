"文档结构登记：探测结果落库 + 变更对比。"

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doc import SHEET_ACTIVE, SHEET_MISSING, SHEET_RENAMED, DdDoc, DdDocSheet
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.sources import SourceError, all_sheet_headers, probe_source
from app.services.sources.base import ProbeResult, SubItem


def structure_hash(items: list[SubItem]) -> str:
    """结构指纹：只关心「有哪些子表、各叫什么」，名字变了才算变。"""
    parts = sorted(f"{item.id}:{item.name}" for item in items)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def diff_structure(old: list[DdDocSheet], new: list[SubItem]) -> dict[str, list[str]]:
    old_map = {row.sheet_id: row.sheet_name for row in old}
    new_map = {item.id: item.name for item in new}

    added = [new_map[sid] for sid in new_map if sid not in old_map]
    missing = [old_map[sid] for sid in old_map if sid not in new_map]
    renamed = [
        f"{old_map[sid]} → {new_map[sid]}"
        for sid in new_map
        if sid in old_map and old_map[sid] != new_map[sid]
    ]
    return {"added": added, "missing": missing, "renamed": renamed}


def drift_text(diff: dict[str, list[str]]) -> str | None:
    """给界面看的一句话。没有变化就返回 None。"""
    parts: list[str] = []
    if diff["added"]:
        parts.append(f"新增 {len(diff['added'])} 个子表：" + "、".join(diff["added"][:5]))
    if diff["renamed"]:
        parts.append(f"改名 {len(diff['renamed'])} 个：" + "、".join(diff["renamed"][:5]))
    if diff["missing"]:
        parts.append(f"消失 {len(diff['missing'])} 个：" + "、".join(diff["missing"][:5]))
    return "；".join(parts) if parts else None


async def store_structure(
    session: AsyncSession, doc: DdDoc, items: list[SubItem], *, only_multi_sheet: bool = False
) -> dict[str, list[str]]:
    "把探测到的子表清单写进缓存表，并算出结构变更。"
    existing = list((await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc.id))).all())
    diff = diff_structure(existing, items)
    now = dt.datetime.now()

    known = {row.sheet_id: row for row in existing}
    for item in items:
        row = known.get(item.id)
        if row is None:
            session.add(
                DdDocSheet(
                    doc_id=doc.id,
                    sheet_id=item.id,
                    sheet_name=item.name,
                    kind=item.kind,
                    field_count=item.field_count,
                    status=SHEET_ACTIVE,
                    last_seen_at=now,
                )
            )
            continue
        if row.sheet_name != item.name:
            row.sheet_name = item.name
            row.status = SHEET_RENAMED
        else:
            row.status = SHEET_ACTIVE
        row.kind = item.kind
        row.field_count = item.field_count
        row.last_seen_at = now

    for sid, row in known.items():
        if sid not in {item.id for item in items}:
            row.status = SHEET_MISSING

    doc.structure_hash = structure_hash(items)
    doc.structure_drift = drift_text(diff)

    await session.flush()
    return diff


async def probe_and_store(
    session: AsyncSession,
    doc: DdDoc,
    app: Any,
    *,
    secret: str,
    preferred_type: str | None = None,
    result: ProbeResult | None = None,
) -> ProbeResult:
    "探测一次并把结果写进文档记录（成功/失败都落账，方便界面上看原因）。"
    doc.last_probe_at = dt.datetime.now()
    if result is None:
        try:
            result = await probe_source(app, doc, secret=secret, doc_type_hint=preferred_type)
        except SourceError as exc:
            doc.last_probe_ok = False
            doc.last_probe_error = f"{exc.message}（{exc.code}）" if exc.code else exc.message
            raise

    if not result.ok:
        doc.last_probe_ok = False
        doc.last_probe_error = result.error
        return result

    doc.last_probe_ok = True
    doc.last_probe_error = None

    if result.resolved_node_id and result.resolved_node_id != doc.node_id:
        doc.node_id = result.resolved_node_id
    if not doc.doc_type and result.doc_type:
        doc.doc_type = result.doc_type
    await store_structure(session, doc, result.sub_items)
    return result


HEADER_SCAN_ROWS = 12


def trim_header_cells(cells: list) -> list[str]:
    "把一行表头格规整成「真实的列名」。"
    from app.services.dingtalk.sheet_reader import is_placeholder_header
    from app.services.normalize.coercions import is_empty
    from app.services.normalize.headers import normalize_headers

    trimmed = list(cells)
    while trimmed and is_empty(trimmed[-1]):
        trimmed.pop()
    return [name for name in normalize_headers(trimmed) if not is_placeholder_header(name)]


async def _sheet_columns(
    client: DingTalkClient, doc: DdDoc, sheet_id: str, *, header_row: int | None
) -> list[str]:
    "读一个子表当前的列名。"
    from app.services.dingtalk.sheet_reader import read_range
    from app.services.normalize.headers import infer_header_row
    from app.services.tabular import a1_address

    addr = a1_address("A", 1, "CZ", max(header_row or 0, HEADER_SCAN_ROWS))
    grid = await read_range(client, doc.node_id, sheet_id, addr)
    if not grid:
        return []
    row = int(header_row or 0)
    if not (1 <= row <= len(grid)):
        row = infer_header_row(grid, start_row=1)
    if not (1 <= row <= len(grid)):
        return []
    return trim_header_cells(grid[row - 1])


def compare_columns(before: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    "比一次列变化，返回 ``(新增, 消失)``。"
    if not before:
        return [], []
    added = [c for c in current if c not in before and not _is_placeholder(c)]
    removed = [c for c in before if c not in current and not _is_placeholder(c)]
    return added, removed


def column_drift_text(
    added: list[str],
    removed: list[str],
    *,
    shifted: list[str] | None = None,
    renames: list[str] | None = None,
) -> str | None:
    "把一次**列**变化写成人看的一句话。没变化返回 None。"
    parts: list[str] = []
    if added:
        parts.append("新增 " + "、".join(added[:5]) + ("…" if len(added) > 5 else ""))
    if removed:
        parts.append("消失 " + "、".join(removed[:5]) + ("…" if len(removed) > 5 else ""))
    if renames:
        parts.append("疑似改名 " + "、".join(renames[:3]))
    if shifted:
        parts.append("**同一列名但内容性质变了**：" + "、".join(shifted[:3]))
    return "；".join(parts) if parts else None


def drift_in_kind(before: dict[str, str], after: dict[str, str]) -> list[str]:
    "同一列名、**性质变了**。返回人看的说明。"
    notes: list[str] = []
    for name, kind in after.items():
        old = before.get(name)
        if old and kind and old != kind:
            notes.append(f"{name}（{old} → {kind}）")
    return notes


def guess_renames(
    before: list[str],
    after: list[str],
    before_types: dict[str, str],
    after_types: dict[str, str],
    *,
    window: int = 3,
) -> list[str]:
    "猜「消失的列 ↔ 新增的列」是不是同一个东西改了名。"
    removed = [(i, name) for i, name in enumerate(before) if name not in after]
    added = [(i, name) for i, name in enumerate(after) if name not in before]
    if not removed or not added:
        return []

    notes: list[str] = []
    used: set[int] = set()
    for old_index, old_name in removed:
        best: tuple[int, str] | None = None
        for new_index, new_name in added:
            if new_index in used or abs(new_index - old_index) > window:
                continue
            old_kind = before_types.get(old_name)
            new_kind = after_types.get(new_name)

            if not old_kind or not new_kind or old_kind != new_kind:
                continue
            if best is None or abs(new_index - old_index) < abs(best[0] - old_index):
                best = (new_index, new_name)
        if best is not None:
            used.add(best[0])
            notes.append(f"{old_name} → {best[1]}")

    return notes


async def store_sheet_columns(
    session: AsyncSession,
    doc_id: int,
    columns_by_sheet: dict[str, list[str]],
    types_by_sheet: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, list[str]]]:
    "把这次读到的列名存成新的历史，返回每张表的变化。"
    sheets = list((await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc_id))).all())
    changed: dict[str, dict[str, list[str]]] = {}
    for sheet in sheets:
        current = columns_by_sheet.get(sheet.sheet_id)
        if current is None:
            continue
        before = list(sheet.column_names or [])
        before_types = dict(sheet.column_types or {})
        added, removed = compare_columns(before, current)
        if added or removed:
            changed[sheet.sheet_id] = {"added": added, "removed": removed}

        current_types = (types_by_sheet or {}).get(sheet.sheet_id) or {}

        shifted = drift_in_kind(before_types, current_types)
        if shifted:
            changed.setdefault(sheet.sheet_id, {"added": [], "removed": []})
            changed[sheet.sheet_id]["shifted"] = shifted

        renames = guess_renames(before, current, before_types, current_types)
        if renames:
            changed.setdefault(sheet.sheet_id, {"added": [], "removed": []})
            changed[sheet.sheet_id]["renamed"] = renames

        sheet.column_names = current
        if current_types:
            sheet.column_types = current_types
        sheet.field_count = len(current)
        sheet.last_column_check_at = dt.datetime.now()
        sheet.column_drift = column_drift_text(added, removed, shifted=shifted, renames=renames)
    await session.flush()
    return changed


async def check_columns(session: AsyncSession, doc: DdDoc, client: DingTalkClient) -> dict:
    "逐个子表比对列名，返回「哪张表多了/少了哪几列」。"
    from app.models.task import DdTask
    from app.services.dingtalk import aitable_reader

    sheets = list((await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc.id))).all())
    tasks = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc.id))).all())
    header_rows: dict[str, int] = {}
    for task in tasks:
        row = (task.source_config or {}).get("header_row")
        if task.sheet_id and row:
            header_rows[task.sheet_id] = int(row)

    results: list[dict] = []
    errors: list[str] = []

    for sheet in sheets:
        try:
            if doc.doc_type == "aitable":
                fields = await aitable_reader.list_fields(client, doc.node_id, sheet.sheet_id)
                current = [f.name for f in fields]
            else:
                current = await _sheet_columns(
                    client, doc, sheet.sheet_id, header_row=header_rows.get(sheet.sheet_id)
                )
        except DingTalkError as exc:
            errors.append(f"「{sheet.sheet_name}」读不到：{exc.message}")
            continue

        before = list(sheet.column_names or [])
        added, removed = compare_columns(before, current)

        results.append(
            {
                "sheet_id": sheet.sheet_id,
                "sheet_name": sheet.sheet_name,
                "first_check": not before,
                "column_count": len(current),
                "added": added,
                "removed": removed,
            }
        )
        sheet.column_names = current
        sheet.field_count = len(current)
        sheet.column_drift = column_drift_text(added, removed)

    doc.last_column_check_at = dt.datetime.now()
    await session.flush()

    changed = [r for r in results if r["added"] or r["removed"]]
    return {
        "ok": True,
        "checked": len(results),
        "changed": len(changed),
        "sheets": results,
        "changed_sheets": changed,
        "errors": errors,
    }


async def check_columns_for(session: AsyncSession, doc: DdDoc, client: DingTalkClient) -> int:
    "只查那些勾了「自动检测新增列」的子表，返回有几个变了。"
    from app.models.task import DdTask
    from app.services.dingtalk import aitable_reader

    sheets = list(
        (
            await session.scalars(
                select(DdDocSheet).where(DdDocSheet.doc_id == doc.id, DdDocSheet.auto_column_check.is_(True))
            )
        ).all()
    )
    if not sheets:
        return 0

    tasks = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc.id))).all())
    header_rows: dict[str, int] = {}
    for task in tasks:
        row = (task.source_config or {}).get("header_row")
        if task.sheet_id and row:
            header_rows[task.sheet_id] = int(row)

    changed = 0
    for sheet in sheets:
        try:
            if doc.doc_type == "aitable":
                fields = await aitable_reader.list_fields(client, doc.node_id, sheet.sheet_id)
                current = [f.name for f in fields]
            else:
                current = await _sheet_columns(
                    client, doc, sheet.sheet_id, header_row=header_rows.get(sheet.sheet_id)
                )
        except DingTalkError:
            continue

        before = list(sheet.column_names or [])
        added, removed = compare_columns(before, current)
        if added or removed:
            changed += 1
            sheet.column_drift = column_drift_text(added, removed)
        sheet.column_names = current
        sheet.field_count = len(current)
        sheet.last_column_check_at = dt.datetime.now()

    await session.flush()
    return changed


async def _sheet_columns_any(
    app: Any, doc: DdDoc, sheet_id: str, *, header_row: int | None, secret: str
) -> list[str]:
    """读一个子表当前的列名 —— **按平台分派**。"""
    from app.services.sources import preview_source

    cfg: dict[str, Any] = {"header_row": int(header_row)} if header_row else {}
    preview = await preview_source(
        app, doc, secret=secret, sheet_id=sheet_id, cfg=cfg, limit=HEADER_SCAN_ROWS
    )
    return trim_header_cells(list(preview.header))


def _header_rows_of(tasks: list[Any]) -> dict[str, int]:
    """每个子表该用哪一行当表头 —— 以**任务里配的**为准（那是用户确认过的）。"""
    rows: dict[str, int] = {}
    for task in tasks:
        row = (task.source_config or {}).get("header_row")
        if task.sheet_id and row:
            rows[str(task.sheet_id)] = int(row)
    return rows


async def check_columns_any(session: AsyncSession, doc: DdDoc, app: Any, *, secret: str = "") -> dict:
    "逐个子表比对列名 —— **平台无关版**（钉钉 / 飞书 / WPS 都走这条）。"
    from app.models.task import DdTask

    sheets = list((await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc.id))).all())
    tasks = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc.id))).all())
    header_rows = _header_rows_of(tasks)

    results: list[dict] = []
    errors: list[str] = []

    bulk: dict[str, list[str]] | None = None
    try:
        bulk = await all_sheet_headers(app, doc, header_rows=header_rows, secret=secret)
    except SourceError as exc:
        errors.append(f"一次读取没成，退回逐表读：{exc.message}")

    for sheet in sheets:
        current = bulk.get(str(sheet.sheet_id)) if bulk is not None else None
        if current is None:
            try:
                current = await _sheet_columns_any(
                    app,
                    doc,
                    sheet.sheet_id,
                    header_row=header_rows.get(str(sheet.sheet_id)),
                    secret=secret,
                )
            except SourceError as exc:
                errors.append(f"「{sheet.sheet_name}」读不到：{exc.message}")
                continue

        before = list(sheet.column_names or [])
        added, removed = compare_columns(before, current)
        results.append(
            {
                "sheet_id": sheet.sheet_id,
                "sheet_name": sheet.sheet_name,
                "first_check": not before,
                "column_count": len(current),
                "added": added,
                "removed": removed,
            }
        )
        sheet.column_names = current
        sheet.field_count = len(current)
        sheet.column_drift = column_drift_text(added, removed)

    doc.last_column_check_at = dt.datetime.now()
    await session.flush()

    changed = [r for r in results if r["added"] or r["removed"]]
    return {
        "ok": True,
        "checked": len(results),
        "changed": len(changed),
        "sheets": results,
        "changed_sheets": changed,
        "errors": errors,
    }


async def check_columns_for_any(session: AsyncSession, doc: DdDoc, app: Any, *, secret: str = "") -> int:
    "只查勾了「自动检测新增列」的子表（平台无关版），返回有几个变了。"
    from app.models.task import DdTask

    sheets = list(
        (
            await session.scalars(
                select(DdDocSheet).where(DdDocSheet.doc_id == doc.id, DdDocSheet.auto_column_check.is_(True))
            )
        ).all()
    )
    if not sheets:
        return 0

    tasks = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc.id))).all())
    header_rows = _header_rows_of(tasks)

    changed = 0

    bulk: dict[str, list[str]] | None = None
    try:
        bulk = await all_sheet_headers(app, doc, header_rows=header_rows, secret=secret)
    except SourceError:
        bulk = None

    for sheet in sheets:
        current = bulk.get(str(sheet.sheet_id)) if bulk is not None else None
        if current is None:
            try:
                current = await _sheet_columns_any(
                    app,
                    doc,
                    sheet.sheet_id,
                    header_row=header_rows.get(str(sheet.sheet_id)),
                    secret=secret,
                )
            except SourceError:
                continue

        before = list(sheet.column_names or [])
        added, removed = compare_columns(before, current)
        if added or removed:
            changed += 1
            sheet.column_drift = column_drift_text(added, removed)
        sheet.column_names = current
        sheet.field_count = len(current)
        sheet.last_column_check_at = dt.datetime.now()

    await session.flush()
    return changed


def _is_placeholder(name: str) -> bool:
    from app.services.dingtalk.sheet_reader import is_placeholder_header

    return is_placeholder_header(name) or not name.strip()
