from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.models.doc import DdDocSheet
from app.services.normalize.coercions import is_empty


@dataclass(slots=True)
class SheetMeta:
    """一个文档下所有子表的元数据。"""

    names: dict[str, str] = field(default_factory=dict)

    history: dict[str, list[str]] = field(default_factory=dict)


async def sheet_ids(task: Any) -> list[str]:
    "这次要读的子表：主表打头，后面跟合并进来的那几张（去重）。"
    merged = [str(s) for s in ((task.source_config or {}).get("merge_sheet_ids") or []) if s]
    return [task.sheet_id] + [s for s in merged if s != task.sheet_id]


async def load_sheet_meta(session: Any, doc_id: int) -> SheetMeta:
    "一次查出子表名 + 列名历史。"
    rows = (await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc_id))).all()
    return SheetMeta(
        names={row.sheet_id: row.sheet_name for row in rows},
        history={row.sheet_id: list(row.column_names or []) for row in rows},
    )


async def remember_sheet_columns(
    doc_id: int,
    columns_by_sheet: dict[str, list[str]],
    types_by_sheet: dict[str, dict[str, str]] | None = None,
) -> None:
    "把这次读到的列名（和每列的性质）存成新的历史（下次比对的底子）。"
    if not columns_by_sheet:
        return
    try:
        from app.core.db import SessionLocal
        from app.services import doc_registry

        async with SessionLocal() as session:
            await doc_registry.store_sheet_columns(session, doc_id, columns_by_sheet, types_by_sheet)
            await session.commit()
    except Exception:  # noqa: BLE001 — 记账失败不该影响同步
        pass


def sheet_label(names: dict[str, str], sheet_id: str) -> str:
    return f"「{names.get(sheet_id, sheet_id)}」"


def is_blank_row(values: list[Any]) -> bool:
    "整行都没内容 —— 分隔用的空行，不是数据。"
    return not any(not is_empty(cell) for cell in values)


def note_column_changes(
    logger: Any,
    names: dict[str, str],
    sheet_ids_: list[str],
    current_by_sheet: dict[str, list[str]],
    history: dict[str, list[str]],
    mapped_sources: set[str],
) -> None:
    "跟上次的列名比一比：谁加了列、谁少了列，当场提醒。"
    from app.services.doc_registry import compare_columns

    added_notes: list[str] = []
    removed_notes: list[str] = []
    unmapped: list[str] = []

    for sid in sheet_ids_:
        before = history.get(sid) or []
        current = current_by_sheet.get(sid) or []
        added, removed = compare_columns(before, current)
        if not added and not removed:
            continue
        label = sheet_label(names, sid) if len(sheet_ids_) > 1 else "本表"
        if added:
            added_notes.append(f"{label}：{'、'.join(added[:5])}")
            unmapped.extend(c for c in added if c not in mapped_sources)
        if removed:
            removed_notes.append(f"{label}：{'、'.join(removed[:5])}")

    if added_notes:
        logger.warn("检测到子表新增了列：" + "；".join(added_notes[:5]))
        if unmapped:
            unique = list(dict.fromkeys(unmapped))
            logger.warn(
                "  其中这些还没配字段映射，**本次不会同步**："
                + "、".join(unique[:8])
                + ("…" if len(unique) > 8 else "")
                + "。要同步就去第 2 步把它们加进映射。"
            )
    if removed_notes:
        logger.warn(
            "检测到子表少了列："
            + "；".join(removed_notes[:5])
            + " —— 对应的字段映射会取不到值（那几列会是空的）"
        )
