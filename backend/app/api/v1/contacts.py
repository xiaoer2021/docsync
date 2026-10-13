"""通讯录：把手机号/姓名换成 unionId。"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.crypto import decrypt_secret
from app.models.app import DdApp, DdContact
from app.schemas.dingtalk import ContactOut
from app.services.dingtalk import contact as contact_svc
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError

router = APIRouter(prefix="/contacts", tags=["contacts"])


async def _app_or_404(session: AsyncSession, app_id: int) -> DdApp:
    app = await session.get(DdApp, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "钉钉应用不存在")
    return app


async def _client(app: DdApp) -> DingTalkClient:
    try:
        secret = str(decrypt_secret(app.app_secret_enc).get("app_secret") or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这个应用的 AppSecret 解不开，重新填一次") from exc
    if not secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这个应用还没配 AppSecret")
    return DingTalkClient(app_id=app.id, app_key=app.app_key, app_secret=secret)


async def _cache(session: AsyncSession, app_id: int, found: contact_svc.Contact, source: str) -> None:
    if not found.union_id:
        return
    existing = await session.scalar(
        select(DdContact).where(DdContact.app_id == app_id, DdContact.union_id == found.union_id)
    )
    record = existing or DdContact(app_id=app_id, union_id=found.union_id)
    record.user_id = found.user_id
    record.name = found.name
    record.mobile = found.mobile
    record.dept = found.dept
    record.source = source
    record.synced_at = dt.datetime.now()
    if existing is None:
        session.add(record)


@router.get("", response_model=list[ContactOut])
async def list_cached(
    session: DbSession,
    _: CurrentUser,
    app_id: int = Query(...),
    keyword: str | None = Query(default=None),
) -> list[ContactOut]:
    """已经查过的人。选人时先看这里，不用每次打接口。"""
    stmt = select(DdContact).where(DdContact.app_id == app_id).order_by(DdContact.id.desc())
    rows = list((await session.scalars(stmt)).all())
    if keyword:
        text = keyword.strip()
        rows = [r for r in rows if (r.name and text in r.name) or (r.mobile and text in r.mobile)]
    return [
        ContactOut(
            user_id=r.user_id,
            union_id=r.union_id,
            name=r.name,
            mobile=r.mobile,
            dept=r.dept,
            from_cache=True,
        )
        for r in rows
    ]


@router.get("/resolve", response_model=ContactOut)
async def resolve(
    session: DbSession,
    admin: AdminUser,
    app_id: int = Query(...),
    mobile: str = Query(min_length=5, max_length=32),
) -> ContactOut:
    """手机号 → userId → unionId。这是拿 operatorId 最快的路。"""
    app = await _app_or_404(session, app_id)
    client = await _client(app)

    try:
        found = await contact_svc.resolve_by_mobile(client, mobile)
    except DingTalkError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if found is None or not found.union_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "没查到这个人。可能号码不对、人已离职，或者应用缺少通讯录权限。",
        )

    await _cache(session, app.id, found, "mobile")
    return ContactOut(**found.to_dict())


@router.get("/search", response_model=list[ContactOut])
async def search(
    session: DbSession,
    admin: AdminUser,
    app_id: int = Query(...),
    keyword: str | None = Query(default=None),
    dept_id: int = Query(default=1),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ContactOut]:
    "按姓名挑人。"
    app = await _app_or_404(session, app_id)
    client = await _client(app)

    try:
        rows = await contact_svc.list_department_users(client, dept_id=dept_id, keyword=keyword, limit=limit)
    except DingTalkError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    for row in rows:
        await _cache(session, app.id, row, "search")

    return [ContactOut(**row.to_dict()) for row in rows]
