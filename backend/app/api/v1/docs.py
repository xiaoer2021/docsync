"""文档登记：解析链接、读取结构、子表清单、自动检测开关。"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.crypto import decrypt_secret
from app.models.app import DOC_TYPES, DdApp, doc_type_label
from app.models.doc import SHEET_MISSING, DdDoc, DdDocSheet
from app.models.docgroup import DdDocGroup, DdDocGroupLink
from app.models.task import DdTask
from app.schemas.dingtalk import (
    ColumnCheckResult,
    DocBatchItem,
    DocBatchRequest,
    DocBatchResult,
    DocCreate,
    DocOut,
    DocResolveRequest,
    DocResolveResult,
    DocSearchHit,
    DocSearchResult,
    DocUpdate,
    ProbeAttempt,
    SubItemOut,
    WatchUpdate,
)
from app.services import audit
from app.services.dingtalk import drive
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError
from app.services.doc_registry import probe_and_store
from app.services.schedule_rules import schedule_label
from app.services.sources import (
    DocLinkError,
    SourceDocRef,
    SourceError,
    doc_url_for,
    parse_doc_link,
    probe_source,
)

router = APIRouter(prefix="/docs", tags=["docs"])

DEFAULT_WATCH_CRON = "0 4 * * *"


def _next_watch(doc: DdDoc, base: dt.datetime) -> dt.datetime | None:
    """下一次自动检测的时间。规则在叶子模块里，直接调就行。"""
    from app.services.schedule_rules import next_watch

    return next_watch(doc, base)


def _secret(app: DdApp) -> str:
    try:
        return str(decrypt_secret(app.app_secret_enc).get("app_secret") or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "这个应用的 AppSecret 解不开，去应用页重新填一次"
        ) from exc


async def _get_app(session: DbSession, app_id: int) -> DdApp:
    app = await session.get(DdApp, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "钉钉应用不存在")
    if app.status != "enabled":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"应用「{app.name}」已停用")
    return app


def _client(app: DdApp, operator_union_id: str | None) -> DingTalkClient:
    secret = _secret(app)
    if not secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这个应用还没配 AppSecret")
    return DingTalkClient(
        app_id=app.id,
        app_key=app.app_key,
        app_secret=secret,
        operator_id=operator_union_id or app.default_operator_union_id,
    )


async def _get_doc(session: DbSession, doc_id: int) -> DdDoc:
    doc = await session.get(DdDoc, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return doc


async def _client_for_doc(session: DbSession, doc: DdDoc) -> DingTalkClient:
    "造一个钉钉客户端。"
    app = await _get_app(session, doc.app_id)
    platform = app.platform or "dingtalk"
    if platform != "dingtalk":
        from app.services.sources import platform_label

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"这个功能暂时只支持钉钉，{platform_label(platform)}的还没做。",
        )
    return _client(app, doc.operator_union_id)


def _plain_secret(app: DdApp) -> str:
    "解出明文 AppSecret。"
    from app.core.crypto import app_secret_of

    return app_secret_of(app.app_secret_enc)


async def _app_and_secret(session: DbSession, doc: DdDoc) -> tuple[DdApp, str]:
    "文档归属的应用 + 明文 AppSecret。"
    app = await _get_app(session, doc.app_id)
    return app, _plain_secret(app)


async def _doc_stats(session: DbSession, doc_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    """(子表数, 已配任务数)。"""
    if not doc_ids:
        return {}, {}
    sheet_rows = await session.execute(
        select(DdDocSheet.doc_id, func.count())
        .where(DdDocSheet.doc_id.in_(doc_ids), DdDocSheet.status != SHEET_MISSING)
        .group_by(DdDocSheet.doc_id)
    )
    task_rows = await session.execute(
        select(DdTask.doc_id, func.count()).where(DdTask.doc_id.in_(doc_ids)).group_by(DdTask.doc_id)
    )
    return (
        {int(i): int(c) for i, c in sheet_rows.all()},
        {int(i): int(c) for i, c in task_rows.all()},
    )


async def _doc_groups(session: DbSession, doc_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    "一次查出一批表单的分组（按分组的排序），别每个表单查一遍。"
    if not doc_ids:
        return {}
    rows = await session.execute(
        select(DdDocGroupLink.doc_id, DdDocGroup.id, DdDocGroup.name)
        .join(DdDocGroup, DdDocGroup.id == DdDocGroupLink.group_id)
        .where(DdDocGroupLink.doc_id.in_(doc_ids))
        .order_by(DdDocGroup.sort_order, DdDocGroup.id)
    )
    out: dict[int, list[tuple[int, str]]] = {}
    for doc_id, group_id, group_name in rows.all():
        out.setdefault(int(doc_id), []).append((int(group_id), str(group_name)))
    return out


def _wanted_groups(group_ids: list[int] | None, group_id: int | None) -> list[int]:
    "把新老两种传法合成一份「要挂哪些分组」。`group_ids` 优先。"
    if group_ids is not None:
        return list(dict.fromkeys(int(g) for g in group_ids if g))
    return [int(group_id)] if group_id else []


async def _set_doc_groups(session: DbSession, doc_id: int, group_ids: list[int]) -> None:
    "整批替换这个表单的分组。"
    await session.execute(delete(DdDocGroupLink).where(DdDocGroupLink.doc_id == doc_id))
    for group_id in group_ids:
        session.add(DdDocGroupLink(doc_id=doc_id, group_id=group_id))
    doc = await session.get(DdDoc, doc_id)
    if doc is not None:
        doc.group_id = group_ids[0] if group_ids else None
    await session.flush()


async def _to_out(
    session: DbSession,
    doc: DdDoc,
    *,
    sheets: int = 0,
    tasks: int = 0,
    groups: list[tuple[int, str]] | None = None,
) -> DocOut:
    pairs = groups if groups is not None else (await _doc_groups(session, [doc.id])).get(doc.id, [])
    app = await session.get(DdApp, doc.app_id)
    return DocOut(
        id=doc.id,
        name=doc.name,
        doc_type=doc.doc_type,
        doc_type_label=doc_type_label(doc.doc_type, app.platform if app else None),
        platform=(app.platform if app else None) or "dingtalk",
        node_id=doc.node_id,
        source_url=doc.source_url,
        app_id=doc.app_id,
        app_name=app.name if app else None,
        operator_union_id=doc.operator_union_id,
        group_id=pairs[0][0] if pairs else None,
        group_name=pairs[0][1] if pairs else None,
        group_ids=[gid for gid, _ in pairs],
        group_names=[name for _, name in pairs],
        status=doc.status,
        remark=doc.remark,
        watch_enabled=doc.watch_enabled,
        watch_cron=doc.watch_cron,
        next_watch_at=doc.next_watch_at,
        last_probe_at=doc.last_probe_at,
        last_probe_ok=doc.last_probe_ok,
        last_probe_error=doc.last_probe_error,
        structure_drift=doc.structure_drift,
        sheet_count=sheets,
        task_count=tasks,
        unconfigured_count=max(sheets - tasks, 0),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=list[DocOut])
async def list_docs(
    session: DbSession,
    _: CurrentUser,
    group_id: int | None = Query(default=None),
    app_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    drift_only: bool = Query(default=False),
) -> list[DocOut]:
    stmt = select(DdDoc).order_by(DdDoc.id.desc())
    if group_id is not None:
        stmt = stmt.where(
            DdDoc.id.in_(select(DdDocGroupLink.doc_id).where(DdDocGroupLink.group_id == group_id))
        )
    if app_id is not None:
        stmt = stmt.where(DdDoc.app_id == app_id)
    if keyword:
        text = keyword.strip()
        stmt = stmt.where(DdDoc.name.contains(text) | DdDoc.node_id.contains(text))
    if drift_only:
        stmt = stmt.where(DdDoc.structure_drift.is_not(None))

    docs = list((await session.scalars(stmt)).all())
    ids = [d.id for d in docs]
    sheets, tasks = await _doc_stats(session, ids)

    groups = await _doc_groups(session, ids)
    return [
        await _to_out(
            session,
            d,
            sheets=sheets.get(d.id, 0),
            tasks=tasks.get(d.id, 0),
            groups=groups.get(d.id, []),
        )
        for d in docs
    ]


@router.get("/search", response_model=DocSearchResult)
async def search_docs(
    session: DbSession,
    _: CurrentUser,
    app_id: int = Query(...),
    keyword: str = Query(min_length=1, max_length=128),
    next_token: str | None = Query(default=None),
    operator_union_id: str | None = Query(default=None),
) -> DocSearchResult:
    "按名字搜钉钉文档，点一下就登记 —— 省掉让用户去复制链接。"
    app = await _get_app(session, app_id)
    try:
        client = _client(app, operator_union_id)
        hits, token = await drive.search_dentries(client, keyword, next_token=next_token)
    except DingTalkError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except HTTPException:
        raise

    known: dict[str, DdDoc] = {}
    if hits:
        rows = await session.scalars(
            select(DdDoc).where(DdDoc.app_id == app.id, DdDoc.node_id.in_([h.uuid for h in hits]))
        )
        known = {row.node_id: row for row in rows.all()}

    return DocSearchResult(
        keyword=keyword,
        next_token=token,
        items=[
            DocSearchHit(
                **hit.to_dict(),
                registered_doc_id=known[hit.uuid].id if hit.uuid in known else None,
                registered_name=known[hit.uuid].name if hit.uuid in known else None,
            )
            for hit in hits
        ],
    )


@router.get("/{doc_id}", response_model=DocOut)
async def get_doc(doc_id: int, session: DbSession, _: CurrentUser) -> DocOut:
    doc = await _get_doc(session, doc_id)
    sheets, tasks = await _doc_stats(session, [doc.id])
    return await _to_out(session, doc, sheets=sheets.get(doc.id, 0), tasks=tasks.get(doc.id, 0))


@router.get("/{doc_id}/subitems", response_model=list[SubItemOut])
async def list_subitems(doc_id: int, session: DbSession, _: CurrentUser) -> list[SubItemOut]:
    """子表清单，每个子表标出「已建任务 / 未建」。"""
    doc = await _get_doc(session, doc_id)
    rows = list(
        (
            await session.scalars(
                select(DdDocSheet).where(DdDocSheet.doc_id == doc.id).order_by(DdDocSheet.id)
            )
        ).all()
    )
    tasks = list((await session.scalars(select(DdTask).where(DdTask.doc_id == doc.id))).all())

    by_sheet: dict[str, DdTask] = {}
    for task in tasks:
        by_sheet[task.sheet_id] = task
        for sid in (task.source_config or {}).get("merge_sheet_ids") or []:
            by_sheet.setdefault(str(sid), task)

    used_ids = {
        int(spec.get("action_id"))
        for task in tasks
        for spec in (task.post_actions or [])
        if spec.get("action_id")
    }
    actions_by_task: dict[int, list] = {task.id: [] for task in tasks}
    if used_ids:
        from app.models.action import DdAction

        found = (await session.scalars(select(DdAction).where(DdAction.id.in_(used_ids)))).all()
        by_id = {a.id: a for a in found}
        for task in tasks:
            actions_by_task[task.id] = [
                by_id[int(spec["action_id"])]
                for spec in (task.post_actions or [])
                if spec.get("action_id") and int(spec["action_id"]) in by_id
            ]

    out: list[SubItemOut] = []
    for row in rows:
        task = by_sheet.get(row.sheet_id)
        merged_in = bool(task) and task.sheet_id != row.sheet_id
        out.append(
            SubItemOut(
                id=row.sheet_id,
                name=row.sheet_name,
                kind=row.kind,
                field_count=row.field_count,
                task_id=task.id if task else None,
                task_name=(f"{task.name}（合并进这个任务）" if merged_in else task.name) if task else None,
                task_status=task.status if task else None,
                last_run_status=task.last_run_status if task else None,
                last_run_at=task.last_run_at if task else None,
                schedule_label=schedule_label(task.schedule) if task else None,
                post_actions_label=(
                    _post_actions_label(task, actions_by_task.get(task.id, [])) if task else None
                ),
                auto_column_check=row.auto_column_check,
                column_drift=row.column_drift,
                configured=task is not None,
            )
        )
    return out


@router.patch("/{doc_id}/sheets/{sheet_id}/column-check")
async def set_sheet_column_check(
    doc_id: int,
    sheet_id: str,
    payload: dict,
    session: DbSession,
    admin: AdminUser,
) -> dict:
    "打开/关闭某个子表的「自动检测新增列」。"
    doc = await _get_doc(session, doc_id)
    row = await session.scalar(
        select(DdDocSheet).where(DdDocSheet.doc_id == doc.id, DdDocSheet.sheet_id == sheet_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个子表不在文档里")

    row.auto_column_check = bool(payload.get("enabled"))
    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_doc_sheet",
        target_id=row.id,
        summary=f"{'开启' if row.auto_column_check else '关闭'}自动检测新增列：{row.sheet_name}",
    )
    return {"status": "ok", "auto_column_check": row.auto_column_check}


def _post_actions_label(task: DdTask, actions: list) -> str | None:
    "后置动作的一句话说明。"
    from app.models.action import ACTION_KIND_LABELS, channels_of

    if not (task.post_actions or []):
        return "无"
    labels: list[str] = []
    for action in actions:
        for channel in channels_of(action):
            label = ACTION_KIND_LABELS.get(str(channel.get("kind")), str(channel.get("kind")))
            if label not in labels:
                labels.append(label)
    return " + ".join(labels) if labels else "已配（动作可能被删了）"


@router.post("/{doc_id}/check-columns", response_model=ColumnCheckResult)
async def check_columns(doc_id: int, session: DbSession, admin: AdminUser) -> ColumnCheckResult:
    "逐个子表比对列名，看哪张表多了或少了列。"
    from app.services import doc_registry

    doc = await _get_doc(session, doc_id)
    app, secret = await _app_and_secret(session, doc)

    if (app.platform or "dingtalk") == "dingtalk":
        try:
            client = await _client_for_doc(session, doc)
        except HTTPException as exc:
            return ColumnCheckResult(ok=False, error=str(exc.detail))
        try:
            result = await doc_registry.check_columns(session, doc, client)
        except DingTalkError as exc:
            return ColumnCheckResult(ok=False, error=f"{exc.message}（{exc.code}）")
    else:
        from app.services.sources import SourceError

        try:
            result = await doc_registry.check_columns_any(session, doc, app, secret=secret)
        except SourceError as exc:
            return ColumnCheckResult(ok=False, error=f"{exc.message}（{exc.code}）")

    audit.record(
        session,
        user=admin,
        action="check",
        target_type="dd_doc",
        target_id=doc.id,
        summary=f"列变化检查 {doc.name}：查了 {result['checked']} 个子表，{result['changed']} 个有变化",
    )
    return ColumnCheckResult(**result)


@router.post("/resolve", response_model=DocResolveResult)
async def resolve_doc(payload: DocResolveRequest, session: DbSession, _: CurrentUser) -> DocResolveResult:
    "只解析 + 探测，不落库。新增向导的第一步用。"

    app = await _get_app(session, payload.app_id)
    platform = app.platform or "dingtalk"

    try:
        ref = parse_doc_link(platform, payload.ref)
    except DocLinkError as exc:
        return DocResolveResult(node_id="", ok=False, error=str(exc))

    operator = payload.operator_union_id or app.default_operator_union_id

    try:
        result = await probe_source(
            app,
            SourceDocRef(node_id=ref.node_id),
            secret=_plain_secret(app),
            doc_type_hint=payload.doc_type or ref.doc_type,
        )
    except SourceError as exc:
        return DocResolveResult(
            node_id=ref.node_id,
            source_url=ref.source_url,
            ok=False,
            error=exc.message,
            hint=exc.hint,
            code=exc.code,
            http_status=exc.http_status,
            used_node_id=ref.node_id,
            used_operator_union_id=operator,
        )
    except HTTPException as exc:
        return DocResolveResult(
            node_id=ref.node_id, source_url=ref.source_url, ok=False, error=str(exc.detail)
        )

    if not result.ok:
        return DocResolveResult(
            node_id=ref.node_id,
            source_url=ref.source_url,
            ok=False,
            error=result.error,
            hint=result.hint,
            code=result.code,
            http_status=result.http_status,
            attempts=[ProbeAttempt(**a) for a in result.attempts],
            used_node_id=ref.node_id,
            used_operator_union_id=operator,
        )

    return DocResolveResult(
        node_id=ref.node_id,
        source_url=ref.source_url or doc_url_for(platform, ref.node_id, ref.doc_type),
        doc_type=result.doc_type,
        sub_id_hint=ref.sub_id_hint,
        used_node_id=ref.node_id,
        used_operator_union_id=operator,
        attempts=[ProbeAttempt(**a) for a in result.attempts],
        sub_items=[
            SubItemOut(id=i.id, name=i.name, kind=i.kind, field_count=i.field_count) for i in result.sub_items
        ],
    )


async def _create_one(
    session: DbSession,
    *,
    app: DdApp,
    ref_text: str,
    name: str | None,
    doc_type: str | None,
    operator_union_id: str | None,
    group_id: int | None,
    group_ids: list[int] | None = None,
    remark: str | None = None,
) -> tuple[DdDoc | None, DocBatchItem]:
    platform = app.platform or "dingtalk"
    try:
        ref = parse_doc_link(platform, ref_text)
    except DocLinkError as exc:
        return None, DocBatchItem(ref=ref_text, ok=False, error=str(exc))

    if not doc_type and ref.doc_type:
        doc_type = ref.doc_type

    if doc_type and doc_type not in DOC_TYPES:
        return None, DocBatchItem(ref=ref_text, ok=False, error=f"文档类型只能是 {' 或 '.join(DOC_TYPES)}")

    existing = await session.scalar(select(DdDoc).where(DdDoc.app_id == app.id, DdDoc.node_id == ref.node_id))
    if existing is not None:
        return existing, DocBatchItem(
            ref=ref_text,
            ok=True,
            skipped=True,
            doc_id=existing.id,
            node_id=existing.node_id,
            name=existing.name,
            doc_type=existing.doc_type,
            error="这份文档之前已经登记过，跳过",
        )

    try:
        probe = await probe_source(
            app,
            SourceDocRef(node_id=ref.node_id),
            secret=_plain_secret(app),
            doc_type_hint=doc_type,
        )
    except SourceError as exc:
        return None, DocBatchItem(
            ref=ref_text, ok=False, node_id=ref.node_id, error=exc.message, hint=exc.hint
        )

    if not probe.ok:
        return None, DocBatchItem(
            ref=ref_text, ok=False, node_id=ref.node_id, error=probe.error, hint=probe.hint
        )

    doc = DdDoc(
        name=(name or "").strip() or ref.node_id,
        doc_type=probe.doc_type or doc_type or "sheet",
        node_id=ref.node_id,
        source_url=ref.source_url or doc_url_for(platform, ref.node_id, ref.doc_type),
        app_id=app.id,
        operator_union_id=operator_union_id or None,
        remark=remark,
        last_probe_ok=True,
    )
    session.add(doc)
    await session.flush()

    await _set_doc_groups(session, doc.id, _wanted_groups(group_ids, group_id))

    probe_app, probe_secret = await _app_and_secret(session, doc)

    await probe_and_store(
        session,
        doc,
        probe_app,
        secret=probe_secret,
        preferred_type=doc.doc_type,
        result=probe,
    )

    return doc, DocBatchItem(
        ref=ref_text,
        ok=True,
        doc_id=doc.id,
        node_id=doc.node_id,
        name=doc.name,
        doc_type=doc.doc_type,
        sub_item_count=len(probe.sub_items),
    )


@router.post("", response_model=DocOut, status_code=status.HTTP_201_CREATED)
async def create_doc(payload: DocCreate, request: Request, session: DbSession, admin: AdminUser) -> DocOut:
    app = await _get_app(session, payload.app_id)
    doc, item = await _create_one(
        session,
        app=app,
        ref_text=payload.ref,
        name=payload.name,
        doc_type=payload.doc_type,
        operator_union_id=payload.operator_union_id,
        group_id=payload.group_id,
        group_ids=payload.group_ids,
        remark=payload.remark,
    )
    if doc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, item.error or "登记失败")
    if item.skipped:
        raise HTTPException(status.HTTP_409_CONFLICT, item.error or "这份文档已经登记过了")

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_doc",
        target_id=doc.id,
        summary=f"登记文档 {doc.name}（{doc.node_id}）",
        request=request,
    )
    sheets, tasks = await _doc_stats(session, [doc.id])
    return await _to_out(session, doc, sheets=sheets.get(doc.id, 0), tasks=tasks.get(doc.id, 0))


@router.post("/batch", response_model=DocBatchResult)
async def create_docs_batch(
    payload: DocBatchRequest, request: Request, session: DbSession, admin: AdminUser
) -> DocBatchResult:
    "批量登记。逐条预检，失败的行把原因带回去，其余照常入库。"
    app = await _get_app(session, payload.app_id)

    results: list[DocBatchItem] = []
    for raw in payload.refs:
        text = (raw or "").strip()
        if not text:
            continue
        _, item = await _create_one(
            session,
            app=app,
            ref_text=text,
            name=None,
            doc_type=None,
            operator_union_id=payload.operator_union_id,
            group_id=payload.group_id,
            group_ids=payload.group_ids,
        )
        results.append(item)

    ok_count = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.ok)

    if results:
        audit.record(
            session,
            user=admin,
            action="create",
            target_type="dd_doc",
            summary=f"批量登记 {len(results)} 份文档：成功 {ok_count}，跳过 {skipped}，失败 {failed}",
            request=request,
        )

    return DocBatchResult(
        total=len(results),
        ok_count=ok_count,
        failed_count=failed,
        skipped_count=skipped,
        items=results,
    )


@router.patch("/{doc_id}", response_model=DocOut)
async def update_doc(
    doc_id: int, payload: DocUpdate, request: Request, session: DbSession, admin: AdminUser
) -> DocOut:
    doc = await _get_doc(session, doc_id)

    if payload.name is not None:
        doc.name = payload.name
    if payload.doc_type is not None:
        if payload.doc_type not in DOC_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"文档类型只能是 {' 或 '.join(DOC_TYPES)}")
        doc.doc_type = payload.doc_type
    if payload.app_id is not None and payload.app_id != doc.app_id:
        doc.app_id = (await _get_app(session, payload.app_id)).id
    if payload.operator_union_id is not None:
        doc.operator_union_id = payload.operator_union_id or None
    if payload.group_ids is not None or payload.group_id is not None:
        await _set_doc_groups(session, doc.id, _wanted_groups(payload.group_ids, payload.group_id))
    if payload.status is not None:
        if payload.status not in ("enabled", "disabled"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是 enabled 或 disabled")
        doc.status = payload.status
    if payload.remark is not None:
        doc.remark = payload.remark
    if payload.watch_enabled is not None:
        doc.watch_enabled = payload.watch_enabled
        doc.next_watch_at = _next_watch(doc, dt.datetime.now()) if payload.watch_enabled else None
        doc.watch_cron = payload.watch_cron or doc.watch_cron or DEFAULT_WATCH_CRON
    elif payload.watch_cron is not None:
        doc.watch_cron = payload.watch_cron

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_doc",
        target_id=doc.id,
        summary=f"修改文档 {doc.name}",
        request=request,
    )
    sheets, tasks = await _doc_stats(session, [doc.id])
    return await _to_out(session, doc, sheets=sheets.get(doc.id, 0), tasks=tasks.get(doc.id, 0))


@router.post("/{doc_id}/probe", response_model=DocResolveResult)
async def probe_one(doc_id: int, session: DbSession, admin: AdminUser) -> DocResolveResult:
    """重新探测一份文档的结构。"""
    doc = await _get_doc(session, doc_id)
    app = await session.get(DdApp, doc.app_id)
    if app is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这份文档关联的应用已被删除")

    operator = doc.operator_union_id or app.default_operator_union_id
    try:
        probe_app, probe_secret = await _app_and_secret(session, doc)
        result = await probe_and_store(
            session, doc, probe_app, secret=probe_secret, preferred_type=doc.doc_type
        )
    except SourceError as exc:
        return DocResolveResult(
            node_id=doc.node_id,
            doc_type=doc.doc_type,
            ok=False,
            error=exc.message,
            hint=exc.hint,
            code=exc.code,
            http_status=exc.http_status,
            used_node_id=doc.node_id,
            used_operator_union_id=operator,
        )

    if not result.ok:
        return DocResolveResult(
            node_id=doc.node_id,
            doc_type=doc.doc_type,
            ok=False,
            error=result.error,
            hint=result.hint,
            code=result.code,
            http_status=result.http_status,
            attempts=[ProbeAttempt(**a) for a in result.attempts],
            used_node_id=doc.node_id,
            used_operator_union_id=operator,
        )

    return DocResolveResult(
        node_id=doc.node_id,
        source_url=doc.source_url,
        doc_type=doc.doc_type,
        sub_items=[
            SubItemOut(id=i.id, name=i.name, kind=i.kind, field_count=i.field_count) for i in result.sub_items
        ],
    )


@router.post("/{doc_id}/watch", response_model=DocOut)
async def set_watch(
    doc_id: int, payload: WatchUpdate, request: Request, session: DbSession, admin: AdminUser
) -> DocOut:
    doc = await _get_doc(session, doc_id)
    doc.watch_enabled = payload.watch_enabled
    doc.watch_cron = payload.watch_cron or doc.watch_cron or DEFAULT_WATCH_CRON

    doc.next_watch_at = _next_watch(doc, dt.datetime.now()) if payload.watch_enabled else None

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_doc",
        target_id=doc.id,
        summary=f"{'开启' if payload.watch_enabled else '关闭'}自动检测新增Sheet页：{doc.name}",
        request=request,
    )
    sheets, tasks = await _doc_stats(session, [doc.id])
    return await _to_out(session, doc, sheets=sheets.get(doc.id, 0), tasks=tasks.get(doc.id, 0))


@router.delete("/{doc_id}")
async def delete_doc(doc_id: int, request: Request, session: DbSession, admin: AdminUser) -> dict[str, str]:
    doc = await _get_doc(session, doc_id)

    task_count = await session.scalar(select(func.count()).select_from(DdTask).where(DdTask.doc_id == doc.id))
    if task_count:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"这份文档下还有 {task_count} 个同步任务，先把任务删掉再删文档",
        )

    name = doc.name

    sheets = list((await session.scalars(select(DdDocSheet).where(DdDocSheet.doc_id == doc.id))).all())
    for row in sheets:
        await session.delete(row)

    await session.execute(delete(DdDocGroupLink).where(DdDocGroupLink.doc_id == doc.id))
    await session.flush()
    await session.delete(doc)

    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_doc",
        target_id=doc_id,
        summary=f"删除文档 {name}",
        request=request,
    )
    return {"status": "ok"}
