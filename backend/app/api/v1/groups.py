"""业务分组。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.models.docgroup import DdDocGroup, DdDocGroupLink
from app.models.task import DdTask
from app.schemas.dingtalk import GroupCreate, GroupOut, GroupUpdate
from app.services import audit

router = APIRouter(prefix="/groups", tags=["groups"])


async def _counts(session: DbSession) -> tuple[dict[int, int], dict[int, int]]:
    "每个分组下有多少表单 / 任务。"
    doc_rows = await session.execute(
        select(DdDocGroupLink.group_id, func.count()).group_by(DdDocGroupLink.group_id)
    )
    task_rows = await session.execute(
        select(DdDocGroupLink.group_id, func.count(DdTask.id))
        .join(DdTask, DdTask.doc_id == DdDocGroupLink.doc_id)
        .group_by(DdDocGroupLink.group_id)
    )
    docs = {int(gid): int(c) for gid, c in doc_rows.all() if gid is not None}
    tasks = {int(gid): int(c) for gid, c in task_rows.all() if gid is not None}
    return docs, tasks


def _to_out(group: DdDocGroup, *, doc_count: int = 0, task_count: int = 0) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        sort_order=group.sort_order,
        remark=group.remark,
        doc_count=doc_count,
        task_count=task_count,
    )


async def _get(session: DbSession, group_id: int) -> DdDocGroup:
    group = await session.get(DdDocGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")
    return group


@router.get("", response_model=list[GroupOut])
async def list_groups(session: DbSession, _: CurrentUser) -> list[GroupOut]:
    groups = list(
        (await session.scalars(select(DdDocGroup).order_by(DdDocGroup.sort_order, DdDocGroup.id))).all()
    )
    docs, tasks = await _counts(session)
    return [_to_out(g, doc_count=docs.get(g.id, 0), task_count=tasks.get(g.id, 0)) for g in groups]


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate, request: Request, session: DbSession, admin: AdminUser
) -> GroupOut:
    exists = await session.scalar(select(DdDocGroup.id).where(DdDocGroup.name == payload.name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "已有同名分组")

    group = DdDocGroup(name=payload.name, sort_order=payload.sort_order, remark=payload.remark)
    session.add(group)
    await session.flush()
    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_doc_group",
        target_id=group.id,
        summary=f"新建分组 {group.name}",
        request=request,
    )
    return _to_out(group)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: int, payload: GroupUpdate, request: Request, session: DbSession, admin: AdminUser
) -> GroupOut:
    group = await _get(session, group_id)

    if payload.name and payload.name != group.name:
        exists = await session.scalar(
            select(DdDocGroup.id).where(DdDocGroup.name == payload.name, DdDocGroup.id != group.id)
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "已有同名分组")
        group.name = payload.name
    if payload.sort_order is not None:
        group.sort_order = payload.sort_order
    if payload.remark is not None:
        group.remark = payload.remark

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_doc_group",
        target_id=group.id,
        summary=f"修改分组 {group.name}",
        request=request,
    )
    docs, tasks = await _counts(session)
    return _to_out(group, doc_count=docs.get(group.id, 0), task_count=tasks.get(group.id, 0))


@router.delete("/{group_id}")
async def delete_group(
    group_id: int, request: Request, session: DbSession, admin: AdminUser
) -> dict[str, str]:
    group = await _get(session, group_id)

    docs, tasks = await _counts(session)
    used = docs.get(group.id, 0) + tasks.get(group.id, 0)
    if used:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"分组下还有 {docs.get(group.id, 0)} 份文档、{tasks.get(group.id, 0)} 个任务，先挪走或删掉",
        )

    name = group.name

    await session.execute(delete(DdDocGroupLink).where(DdDocGroupLink.group_id == group_id))
    await session.execute(delete(DdDocGroup).where(DdDocGroup.id == group_id))
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_doc_group",
        target_id=group_id,
        summary=f"删除分组 {name}",
        request=request,
    )
    return {"status": "ok"}
