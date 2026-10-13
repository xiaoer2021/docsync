"后置动作的增删改查、试发与预览。"

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import delete, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.db import SessionLocal
from app.core.mask import mask_value
from app.models.action import (
    ACTION_DINGTALK_ROBOT,
    ACTION_INTERFACE,
    ACTION_KIND_HELP,
    ACTION_KIND_LABELS,
    ACTION_KINDS,
    ACTION_WEBHOOK,
    DdAction,
    channels_of,
)
from app.models.run import DdRun, DdRunAction
from app.models.task import DdTask
from app.schemas.actions import (
    ActionCreate,
    ActionKindOut,
    ActionOut,
    ActionPreviewOut,
    ActionRecordOut,
    ActionTestOut,
    ActionUpdate,
    ChannelResult,
)
from app.services import audit
from app.services.actions import (
    DEFAULT_ROBOT_CONTENT,
    TEMPLATE_FIELDS,
    execute,
    preview,
    sample_context,
)

router = APIRouter(prefix="/actions", tags=["actions"])

SECRET_KEYS = frozenset({"secret", "token"})

KIND_FIELDS: dict[str, list[dict[str, Any]]] = {
    ACTION_WEBHOOK: [
        {
            "key": "url",
            "label": "地址",
            "required": True,
            "placeholder": "https://你的观远/api/…/refresh?token=xxx",
            "hint": "会用 GET 请求访问一次，拿 2xx 就算成功。",
        },
    ],
    ACTION_INTERFACE: [
        {"key": "url", "label": "接口地址", "required": True},
        {
            "key": "method",
            "label": "方法",
            "type": "select",
            "options": ["POST", "GET", "PUT", "PATCH"],
        },
        {
            "key": "body",
            "label": "请求体",
            "type": "textarea",
            "template": True,
            "placeholder": '{"task": "{task_name}", "rows": {inserted}}',
            "hint": "可以留空。用 {task_name} 这类变量会被替换成真实值。",
        },
        {"key": "headers", "label": "请求头", "type": "kv", "placeholder": '{"Authorization": "Bearer xxx"}'},
    ],
    ACTION_DINGTALK_ROBOT: [
        {
            "key": "webhook",
            "label": "机器人 Webhook",
            "required": True,
            "placeholder": "https://oapi.dingtalk.com/robot/send?access_token=…",
        },
        {
            "key": "secret",
            "label": "加签密钥",
            "secret": True,
            "placeholder": "安全设置里选「加签」才有；没选就留空",
        },
        {
            "key": "content",
            "label": "消息内容",
            "type": "textarea",
            "template": True,
            "default": DEFAULT_ROBOT_CONTENT,
        },
        {"key": "at_all", "label": "@ 所有人", "type": "bool"},
    ],
}


def _mask_config(kind: str, config: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(config or {})
    for key in SECRET_KEYS:
        if out.get(key):
            out[key] = mask_value(str(out[key]))
    return out


def _mask_channels(channels: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "kind": str(c.get("kind") or ""),
            "config": _mask_config(str(c.get("kind") or ""), c.get("config")),
        }
        for c in channels or []
    ]


def _merge_config(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    "更新时合并 config。"
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if key in SECRET_KEYS and (value in (None, "") or "*" in str(value)):
            continue
        if value is None and key not in SECRET_KEYS:
            merged.pop(key, None)
            continue
        merged[key] = value
    return merged


def _channels_in(raw: list[Any] | None) -> list[dict[str, Any]]:
    """校验并整理前端传来的 channels。"""
    out: list[dict[str, Any]] = []
    for item in raw or []:
        kind = str(getattr(item, "kind", None) or (item or {}).get("kind") or "")
        config = getattr(item, "config", None)
        if config is None and isinstance(item, dict):
            config = item.get("config")
        if kind not in ACTION_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不认识的动作类型「{kind}」")
        out.append({"kind": kind, "config": dict(config or {})})
    if not out:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少要配一个类型")
    return out


def _merge_channels(old: list[dict[str, Any]] | None, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并新老 channels —— 同类型的保留原密钥，避免打码值被存回去。"""
    old_by_kind = {str(c.get("kind")): c.get("config") or {} for c in old or []}
    return [
        {
            "kind": c["kind"],
            "config": _merge_config(old_by_kind.get(c["kind"]), c.get("config")),
        }
        for c in new
    ]


def _kind_label(channels: list[dict[str, Any]]) -> str:
    labels = [ACTION_KIND_LABELS.get(str(c.get("kind")), str(c.get("kind"))) for c in channels]
    return " + ".join(labels)


async def _usage(session: DbSession) -> dict[int, int]:
    rows = (
        (await session.execute(select(DdTask.post_actions).where(DdTask.post_actions.is_not(None))))
        .scalars()
        .all()
    )
    counter: dict[int, int] = {}
    for specs in rows:
        for spec in specs or []:
            try:
                aid = int(spec.get("action_id"))
            except (TypeError, ValueError):
                continue
            counter[aid] = counter.get(aid, 0) + 1
    return counter


def _to_out(action: DdAction, *, used_by: int = 0) -> ActionOut:
    channels = channels_of(action)
    return ActionOut(
        id=action.id,
        name=action.name,
        channels=_mask_channels(channels),
        kind_label=_kind_label(channels),
        enabled=action.enabled,
        remark=action.remark,
        used_by=used_by,
        created_at=action.created_at,
    )


async def _get(session: DbSession, action_id: int) -> DdAction:
    action = await session.get(DdAction, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个后置动作不存在")
    return action


@router.get("/kinds", response_model=list[ActionKindOut])
async def list_kinds(_: CurrentUser) -> list[ActionKindOut]:
    return [
        ActionKindOut(
            kind=kind,
            label=ACTION_KIND_LABELS.get(kind, kind),
            help=ACTION_KIND_HELP.get(kind, ""),
            fields=KIND_FIELDS.get(kind, []),
        )
        for kind in ACTION_KINDS
    ]


@router.get("/template-fields", response_model=list[str])
async def list_template_fields(_: CurrentUser) -> list[str]:
    """消息/请求体里能用的变量。"""
    return list(TEMPLATE_FIELDS)


@router.post("/preview", response_model=ActionPreviewOut)
async def preview_channel(payload: dict, _: CurrentUser) -> ActionPreviewOut:
    "拿样例数据渲染一遍，看看发出去长什么样。不真发。"
    kind = str(payload.get("kind") or "")
    if kind not in ACTION_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不认识的动作类型「{kind}」")
    return ActionPreviewOut(
        rendered=preview({"kind": kind, "config": payload.get("config") or {}}, sample_context())
    )


@router.get("", response_model=list[ActionOut])
async def list_actions(session: DbSession, _: CurrentUser) -> list[ActionOut]:
    actions = list((await session.scalars(select(DdAction).order_by(DdAction.id))).all())
    usage = await _usage(session)
    return [_to_out(a, used_by=usage.get(a.id, 0)) for a in actions]


@router.post("", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
async def create_action(
    payload: ActionCreate, request: Request, session: DbSession, admin: AdminUser
) -> ActionOut:
    exists = await session.scalar(select(DdAction.id).where(DdAction.name == payload.name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "已有同名后置动作")

    channels = _channels_in(payload.channels)
    action = DdAction(
        name=payload.name,
        channels=channels,
        kind=channels[0]["kind"],
        config=channels[0]["config"],
        enabled=payload.enabled,
        remark=payload.remark,
    )
    session.add(action)
    await session.flush()
    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_action",
        target_id=action.id,
        summary=f"新建后置动作 {action.name}（{_kind_label(channels)}）",
        request=request,
    )
    return _to_out(action)


@router.patch("/{action_id}", response_model=ActionOut)
async def update_action(
    action_id: int, payload: ActionUpdate, request: Request, session: DbSession, admin: AdminUser
) -> ActionOut:
    action = await _get(session, action_id)

    if payload.name and payload.name != action.name:
        exists = await session.scalar(
            select(DdAction.id).where(DdAction.name == payload.name, DdAction.id != action.id)
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "已有同名后置动作")
        action.name = payload.name

    if payload.channels is not None:
        channels = _merge_channels(channels_of(action), _channels_in(payload.channels))
        action.channels = channels
        action.kind = channels[0]["kind"]
        action.config = channels[0]["config"]

    if payload.enabled is not None:
        action.enabled = payload.enabled
    if payload.remark is not None:
        action.remark = payload.remark

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_action",
        target_id=action.id,
        summary=f"修改后置动作 {action.name}",
        request=request,
    )
    usage = await _usage(session)
    return _to_out(action, used_by=usage.get(action.id, 0))


@router.delete("/{action_id}")
async def delete_action(
    action_id: int, request: Request, session: DbSession, admin: AdminUser
) -> dict[str, str]:
    action = await _get(session, action_id)
    usage = await _usage(session)
    used = usage.get(action.id, 0)
    if used:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"还有 {used} 个同步任务在用它，先把任务里的引用去掉再删",
        )

    name = action.name
    await session.execute(delete(DdAction).where(DdAction.id == action_id))
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_action",
        target_id=action_id,
        summary=f"删除后置动作 {name}",
        request=request,
    )
    return {"status": "ok"}


@router.get("/{action_id}/records", response_model=list[ActionRecordOut])
async def list_records(
    action_id: int,
    session: DbSession,
    _: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActionRecordOut]:
    "这个动作**实际发生过**的执行记录。"
    rows = await session.execute(
        select(DdRunAction, DdRun.task_id, DdTask.name)
        .join(DdRun, DdRun.id == DdRunAction.run_id)
        .outerjoin(DdTask, DdTask.id == DdRun.task_id)
        .where(DdRunAction.action_id == action_id)
        .order_by(DdRunAction.id.desc())
        .limit(limit)
    )
    return [
        ActionRecordOut(
            id=rec.id,
            run_id=rec.run_id,
            task_name=task_name,
            trigger_on=rec.trigger_on,
            status=rec.status,
            kind=rec.kind,
            started_at=rec.started_at,
            duration_ms=rec.duration_ms,
            http_status=rec.http_status,
            error_message=rec.error_message,
        )
        for rec, _task_id, task_name in rows.all()
    ]


@router.post("/{action_id}/test", response_model=ActionTestOut)
async def test_action(action_id: int, session: DbSession, _: AdminUser) -> ActionTestOut:
    "拿一份样例数据把每个渠道都真发一次。"
    action = await _get(session, action_id)
    ctx = sample_context()
    results: list[ChannelResult] = []

    for channel in channels_of(action):
        kind = str(channel.get("kind") or "")
        started = time.monotonic()
        outcome = await execute(channel, ctx)
        results.append(
            ChannelResult(
                kind=kind,
                label=ACTION_KIND_LABELS.get(kind, kind),
                ok=outcome.ok,
                http_status=outcome.http_status,
                detail=outcome.detail,
                error=outcome.error,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        )

    async with SessionLocal() as audit_session:
        audit.record(
            audit_session,
            user=None,
            action="test",
            target_type="dd_action",
            target_id=action.id,
            summary=f"试发后置动作 {action.name}："
            + "、".join(f"{r.label}{'成功' if r.ok else '失败'}" for r in results),
        )
        await audit_session.commit()

    return ActionTestOut(ok=all(r.ok for r in results), results=results)
