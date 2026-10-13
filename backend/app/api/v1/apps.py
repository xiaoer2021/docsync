"""钉钉应用凭证：增删改查 + 验证 + 权限清单。"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.mask import mask_value
from app.models.app import DOC_TYPE_LABELS, DdApp
from app.models.doc import DdDoc
from app.schemas.dingtalk import (
    AppCreate,
    AppOut,
    AppTestResult,
    AppUpdate,
    ScopeGuide,
    ScopeInfo,
    TestStep,
)
from app.services import audit
from app.services.dingtalk.client import DingTalkClient, fetch_access_token, forget_token
from app.services.dingtalk.errors import DOC_AUTHOR_GUIDE, REQUIRED_SCOPES, DingTalkError
from app.services.dingtalk.resolve import probe_doc
from app.services.feishu.client import FeishuClient
from app.services.feishu.client import fetch_tenant_access_token as fetch_feishu_token
from app.services.feishu.client import forget_token as forget_feishu_token
from app.services.feishu.errors import FeishuError
from app.services.feishu.probe import probe_feishu
from app.services.sources import (
    KNOWN_PLATFORMS,
    READY_PLATFORMS,
    forget_tokens,
    platform_label,
)

router = APIRouter(prefix="/apps", tags=["apps"])


def _secret_of(app: DdApp) -> str:
    try:
        return str(decrypt_secret(app.app_secret_enc).get("app_secret") or "")
    except Exception:  # noqa: BLE001 — 解不开时后续会以「凭证不可用」的形式暴露出来
        return ""


async def _doc_counts(session: DbSession, app_ids: list[int]) -> dict[int, int]:
    if not app_ids:
        return {}
    rows = await session.execute(
        select(DdDoc.app_id, func.count()).where(DdDoc.app_id.in_(app_ids)).group_by(DdDoc.app_id)
    )
    return {int(app_id): int(count) for app_id, count in rows.all()}


def _effective_recipe(app: DdApp) -> dict | None:
    "这个应用**当前生效**的配方：存了的用存的，没存的给内置默认。"
    if (app.platform or "") != "wps":
        return None
    from app.services.webflow.source import DEFAULT_WPS_ELEMENTS, DEFAULT_WPS_STEPS

    stored = app.recipe if isinstance(app.recipe, dict) else {}
    return {
        "elements": stored.get("elements") or DEFAULT_WPS_ELEMENTS,
        "steps": stored.get("steps") or DEFAULT_WPS_STEPS,
    }


def _to_out(app: DdApp, *, doc_count: int = 0) -> AppOut:
    secret = _secret_of(app)
    return AppOut(
        id=app.id,
        platform=app.platform,
        name=app.name,
        app_key=mask_value(app.app_key),
        app_key_masked=mask_value(app.app_key),
        app_secret_masked=mask_value(secret) if secret else "",
        has_secret=bool(app.app_secret_enc),
        default_operator_union_id=app.default_operator_union_id,
        default_operator_name=app.default_operator_name,
        token_expires_at=app.token_expires_at,
        last_token_at=app.last_token_at,
        last_token_error=app.last_token_error,
        status=app.status,
        remark=app.remark,
        recipe=_effective_recipe(app),
        doc_count=doc_count,
        created_at=app.created_at,
    )


async def _get_app(session: DbSession, app_id: int) -> DdApp:
    app = await session.get(DdApp, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "钉钉应用不存在")
    return app


@router.get("/scopes", response_model=ScopeGuide)
async def scope_guide(_: CurrentUser) -> ScopeGuide:
    """需要开哪些权限、各自干什么用，以及「怎么把应用加为文档协作者」。"""
    return ScopeGuide(
        scopes=[ScopeInfo(**item) for item in REQUIRED_SCOPES],
        author_guide=DOC_AUTHOR_GUIDE,
    )


@router.get("", response_model=list[AppOut])
async def list_apps(session: DbSession, _: CurrentUser) -> list[AppOut]:
    apps = list((await session.scalars(select(DdApp).order_by(DdApp.id))).all())
    counts = await _doc_counts(session, [a.id for a in apps])
    return [_to_out(a, doc_count=counts.get(a.id, 0)) for a in apps]


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
async def create_app(payload: AppCreate, request: Request, session: DbSession, admin: AdminUser) -> AppOut:
    if payload.platform not in KNOWN_PLATFORMS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"不认识的平台：{payload.platform}。可选：{'、'.join(KNOWN_PLATFORMS)}",
        )

    if payload.platform != "wps" and not (payload.app_key and payload.app_secret):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{platform_label(payload.platform)}的 AppKey 和 AppSecret 都要填。",
        )

    exists = await session.scalar(select(DdApp.id).where(DdApp.name == payload.name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "已有同名的应用")

    app = DdApp(
        platform=payload.platform,
        name=payload.name,
        app_key=payload.app_key.strip(),
        app_secret_enc=encrypt_secret({"app_secret": payload.app_secret.strip()}),
        default_operator_union_id=payload.default_operator_union_id,
        default_operator_name=payload.default_operator_name,
        remark=payload.remark,
        recipe=payload.recipe,
    )
    session.add(app)
    await session.flush()

    audit.record(
        session,
        user=admin,
        action="create",
        target_type="dd_app",
        target_id=app.id,
        summary=f"新建{platform_label(app.platform)}应用 {app.name}",
        request=request,
    )
    return _to_out(app)


@router.get("/{app_id}", response_model=AppOut)
async def get_app(app_id: int, session: DbSession, _: CurrentUser) -> AppOut:
    app = await _get_app(session, app_id)
    counts = await _doc_counts(session, [app.id])
    return _to_out(app, doc_count=counts.get(app.id, 0))


@router.patch("/{app_id}", response_model=AppOut)
async def update_app(
    app_id: int, payload: AppUpdate, request: Request, session: DbSession, admin: AdminUser
) -> AppOut:
    app = await _get_app(session, app_id)

    if payload.name and payload.name != app.name:
        exists = await session.scalar(select(DdApp.id).where(DdApp.name == payload.name, DdApp.id != app.id))
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "已有同名的应用")
        app.name = payload.name

    if "recipe" in payload.model_fields_set:
        app.recipe = payload.recipe

    if payload.app_key and "*" not in payload.app_key:
        app.app_key = payload.app_key.strip()

        forget_tokens(app)
    if payload.app_secret:
        app.app_secret_enc = encrypt_secret({"app_secret": payload.app_secret.strip()})

        forget_tokens(app)
        app.last_token_error = None
    if payload.default_operator_union_id is not None:
        app.default_operator_union_id = payload.default_operator_union_id or None
    if payload.default_operator_name is not None:
        app.default_operator_name = payload.default_operator_name or None
    if payload.status is not None:
        if payload.status not in ("enabled", "disabled"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是 enabled 或 disabled")
        app.status = payload.status
    if payload.remark is not None:
        app.remark = payload.remark

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_app",
        target_id=app.id,
        summary=f"修改{platform_label(app.platform)}应用 {app.name}",
        request=request,
    )
    counts = await _doc_counts(session, [app.id])
    return _to_out(app, doc_count=counts.get(app.id, 0))


@router.delete("/{app_id}")
async def delete_app(app_id: int, request: Request, session: DbSession, admin: AdminUser) -> dict[str, str]:
    app = await _get_app(session, app_id)
    used = await session.scalar(select(func.count()).select_from(DdDoc).where(DdDoc.app_id == app.id))
    if used:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"还有 {used} 份文档在用这个应用，先把它们改到别的应用或删掉",
        )

    name = app.name

    forget_tokens(app)
    await session.delete(app)
    audit.record(
        session,
        user=admin,
        action="delete",
        target_type="dd_app",
        target_id=app_id,
        summary=f"删除钉钉应用 {name}",
        request=request,
    )
    return {"status": "ok"}


async def _test_wps(session: DbSession, app: DdApp) -> AppTestResult:
    "验 WPS 应用：拿它自己的档案打开一份已登记的文档，看还读不读得到。"
    from app.services.webflow.check import check_page, profile_name_for

    doc = await session.scalar(select(DdDoc).where(DdDoc.app_id == app.id).order_by(DdDoc.id).limit(1))
    url = str(getattr(doc, "node_id", "") or "")
    if not url:
        return AppTestResult(
            ok=False,
            steps=[
                TestStep(
                    name="读文档（用登录档案）",
                    ok=False,
                    message="这个应用下还没有登记文档，先登记一份再验证",
                    hint="去「表单管理 → 登记在线表格」，粘一个金山文档的分享链接。",
                )
            ],
        )

    ok, message = await check_page(url, profile_name_for(app.id))

    now = dt.datetime.now()
    app.last_token_at = now

    app.last_token_error = None if ok else message

    if ok:
        hint = None
    elif "登录" in message:
        hint = "登录态多半过期了：点这个应用那行的「扫码登录」，重新扫码（或手机号）登一次。"
    else:
        hint = "多半是网页改版了：展开这个页面的「取数配方」，按 F12 抄一遍新的 XPath。"

    return AppTestResult(
        ok=ok,
        steps=[TestStep(name="读文档（用登录档案）", ok=ok, message=message, hint=hint)],
    )


async def _test_feishu(session: DbSession, app: DdApp, secret: str) -> AppTestResult:
    "飞书的验证：换凭证 → 逐个已登记文档试读一次。"
    steps: list[TestStep] = []

    try:
        _, expires_in = await fetch_feishu_token(app.app_key, secret)
        forget_feishu_token(app.id)
        app.last_token_at = dt.datetime.now()
        app.token_expires_at = dt.datetime.now() + dt.timedelta(seconds=expires_in)
        app.last_token_error = None
        steps.append(
            TestStep(
                name="换取访问凭证",
                ok=True,
                message=f"成功，有效期 {expires_in // 60} 分钟",
            )
        )
    except FeishuError as exc:
        app.last_token_error = str(exc.message)
        steps.append(
            TestStep(
                name="换取访问凭证",
                ok=False,
                message=exc.message,
                hint=exc.hint or "去飞书开放平台核对 App ID / App Secret（在「凭证与基础信息」里）。",
            )
        )
        return AppTestResult(ok=False, steps=steps)

    client = FeishuClient(app_id=app.id, app_key=app.app_key, app_secret=secret)

    docs = (await session.scalars(select(DdDoc).where(DdDoc.app_id == app.id))).all()
    if not docs:
        steps.append(
            TestStep(
                name="读取文档",
                ok=True,
                optional=True,
                message="这个应用还没有登记任何文档",
                hint="凭证是通的。去「表单管理 → 新增在线表」登记一个飞书表格再回来验证。",
            )
        )
        return AppTestResult(ok=True, steps=steps)

    for doc in docs:
        label = f"读取「{doc.name or doc.node_id}」"
        try:
            outcome = await probe_feishu(client, doc.node_id, doc_type_hint=doc.doc_type)
        except FeishuError as exc:
            steps.append(TestStep(name=label, ok=False, message=exc.message, hint=exc.hint))
            continue

        if outcome.ok:
            steps.append(TestStep(name=label, ok=True, message=f"{len(outcome.sub_items)} 个子表"))
        else:
            steps.append(
                TestStep(
                    name=label,
                    ok=False,
                    message=outcome.error or "读不到",
                    hint=outcome.hint,
                )
            )

    ok = all(step.ok for step in steps if not step.optional)
    return AppTestResult(ok=ok, steps=steps)


@router.post("/{app_id}/test", response_model=AppTestResult)
async def test_app(app_id: int, session: DbSession, admin: AdminUser) -> AppTestResult:
    "逐步验证：换凭证 → 各项权限 → 逐个文档能不能读。"
    app = await _get_app(session, app_id)

    if (app.platform or "dingtalk") not in READY_PLATFORMS:
        return AppTestResult(
            ok=False,
            steps=[
                TestStep(
                    name="平台连接器",
                    ok=False,
                    message=f"{platform_label(app.platform)} 的对接还在接入中，暂时不能验证",
                    hint="凭证已经存下了。接入完成后回来点「验证」就行。",
                )
            ],
        )

    if (app.platform or "dingtalk") == "wps":
        return await _test_wps(session, app)

    secret = _secret_of(app)
    if not secret:
        return AppTestResult(
            ok=False,
            steps=[TestStep(name="读取 AppSecret", ok=False, message="AppSecret 解不开，重新填一次")],
        )

    if (app.platform or "dingtalk") == "feishu":
        return await _test_feishu(session, app, secret)

    steps: list[TestStep] = []

    token_ok = False
    try:
        _, expires_in = await fetch_access_token(app.app_key, secret)
        forget_token(app.id)
        app.last_token_at = dt.datetime.now()
        app.token_expires_at = dt.datetime.now() + dt.timedelta(seconds=expires_in)
        app.last_token_error = None
        token_ok = True
        steps.append(
            TestStep(
                name="换取访问凭证",
                ok=True,
                message=f"成功，有效期 {expires_in // 60} 分钟",
            )
        )
    except DingTalkError as exc:
        app.last_token_error = str(exc.message)
        steps.append(TestStep(name="换取访问凭证", ok=False, message=exc.message, hint=exc.hint))

    if not token_ok:
        return AppTestResult(ok=False, steps=steps)

    client = DingTalkClient(app_id=app.id, app_key=app.app_key, app_secret=secret)

    if not app.default_operator_union_id:
        steps.append(
            TestStep(
                name="文件搜索权限",
                ok=False,
                optional=True,
                message="还没设操作人，这一项验不了",
                hint="搜文档也要带 operatorId。先去上一步给应用设一个操作人，再回来验证。",
            )
        )
    else:
        try:
            from app.services.dingtalk.drive import search_dentries

            search_client = DingTalkClient(
                app_id=app.id,
                app_key=app.app_key,
                app_secret=secret,
                operator_id=app.default_operator_union_id,
            )
            await search_dentries(search_client, app.name or "a", max_results=1)
            steps.append(
                TestStep(
                    name="文件搜索权限",
                    ok=True,
                    message="可以按关键词搜在线表格（Storage.Dentry.Search）",
                )
            )
        except DingTalkError as exc:
            steps.append(
                TestStep(
                    name="文件搜索权限",
                    ok=False,
                    optional=True,
                    message=exc.message,
                    hint=exc.hint
                    or "没开 Storage.Dentry.Search 的话，「搜在线表格」这个入口用不了。"
                    "只用粘贴链接/ID 登记的话可以不开，不影响同步。",
                )
            )

    if app.default_operator_union_id:
        from app.services.dingtalk import contact as contact_svc

        try:
            found = await contact_svc.contact_by_union_id(client, app.default_operator_union_id)
            if found is None:
                steps.append(
                    TestStep(
                        name="操作人在通讯录里查得到",
                        ok=True,
                        message=(
                            "通讯录里查不到这个 unionId 对应的姓名 —— "
                            "多半是这个人不在本组织、或通讯录权限只覆盖了部分人。"
                            "只要下面「文档能不能读」那几项是通的，同步就不受影响。"
                        ),
                    )
                )
            else:
                steps.append(
                    TestStep(
                        name="操作人在通讯录里查得到",
                        ok=True,
                        message=f"当前操作人：{found.name or app.default_operator_union_id}",
                    )
                )
        except DingTalkError as exc:
            steps.append(
                TestStep(
                    name="通讯录读权限",
                    ok=False,
                    optional=True,
                    message=f"通讯录查询失败：{exc.message}",
                    hint=exc.hint or "通讯录权限没开。不影响读文档，只影响「按姓名选人」。",
                )
            )

    docs = list((await session.scalars(select(DdDoc).where(DdDoc.app_id == app.id))).all())
    for doc in docs[:20]:
        doc_client = DingTalkClient(
            app_id=app.id,
            app_key=app.app_key,
            app_secret=secret,
            operator_id=doc.operator_union_id or app.default_operator_union_id,
        )
        label = f"{doc.name}（{DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type)}）"
        if doc.doc_type == "aitable":
            need = "读多维表需要 Notable.Base.Read.All，去开放平台给应用勾上再发布版本"
        else:
            need = "读钉钉表格需要 Document.Workbook.Read，去开放平台给应用勾上再发布版本"
        try:
            result = await probe_doc(doc_client, doc.node_id, preferred_type=doc.doc_type)
            if result.ok:
                steps.append(TestStep(name=label, ok=True, message=f"读到 {len(result.sub_items)} 个子表"))
            else:
                steps.append(
                    TestStep(
                        name=label,
                        ok=False,
                        message=result.error or "读取失败",
                        hint=result.hint or need,
                    )
                )
        except DingTalkError as exc:
            steps.append(TestStep(name=label, ok=False, message=exc.message, hint=exc.hint or need))

    return AppTestResult(ok=all(s.ok for s in steps if not s.optional), steps=steps)


def _require_wps(app: DdApp) -> None:
    if (app.platform or "") != "wps":
        from app.services.sources import platform_label

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"只有 WPS 个人版能扫码登录，当前是{platform_label(app.platform)}。",
        )


@router.post("/{app_id}/wps-login", response_model=dict)
async def wps_login_start(app_id: int, session: DbSession, admin: AdminUser) -> dict:
    "开始扫码登录，返回一张二维码截图（``image`` 是 base64 PNG）。"
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        return await login_svc.start_login(app)
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.get("/{app_id}/wps-login", response_model=dict)
async def wps_login_poll(app_id: int, session: DbSession, admin: AdminUser) -> dict:
    """问一句「扫上了没」。没扫上就再给一张新二维码（金山那边会自己刷新）。"""
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    return await login_svc.poll_login(app)


@router.post("/{app_id}/wps-login/click", response_model=dict)
async def wps_login_click(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    '把界面上点的那一下**原样点回页面**：``{"x": 120, "y": 340}``（页面 CSS 像素）。'
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    return await login_svc.click_at(app, x=float(payload.get("x") or 0), y=float(payload.get("y") or 0))


@router.post("/{app_id}/wps-login/type", response_model=dict)
async def wps_login_type(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    """把一段文字打到页面**当前焦点**处：``{"text": "13800000000"}``。"""
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    return await login_svc.type_text(app, str(payload.get("text") or ""))


@router.post("/{app_id}/wps-login/key", response_model=dict)
async def wps_login_key(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    """敲一个功能键：``{"key": "Backspace"}``（普通字符走 /type）。"""
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    return await login_svc.send_key(app, str(payload.get("key") or ""))


@router.post("/{app_id}/wps-login/mode", response_model=dict)
async def wps_login_mode(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    '切登录方式：``{"mode": "qr"|"mobile"|"exclusive"}``。'
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        return await login_svc.use_mode(app, str(payload.get("mode") or "qr"))
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.post("/{app_id}/wps-login/fill", response_model=dict)
async def wps_login_fill(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    """往表单里填字：``{"field": "phone"|"code"|"name", "text": "..."}``。"""
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        return await login_svc.fill(app, str(payload.get("field") or ""), str(payload.get("text") or ""))
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.post("/{app_id}/wps-login/tap", response_model=dict)
async def wps_login_tap(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    """点个按钮：``{"action": "send_code"|"submit"|"back"}``。"""
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        return await login_svc.tap(app, str(payload.get("action") or "submit"))
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.post("/{app_id}/wps-login/button", response_model=dict)
async def wps_login_button(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    '点页面上第 ``index`` 个可点元素：``{"index": 3}``。'
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        return await login_svc.tap_button(app, int(payload.get("index") or 0))
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.post("/{app_id}/wps-login/accounts", response_model=dict)
async def wps_login_accounts(app_id: int, payload: dict, session: DbSession, admin: AdminUser) -> dict:
    '勾选指定账号；给了 ``submit`` 就顺便把那个按钮点了：``{"indexes": [0], "submit": 3}``。'
    from app.services.sources.base import SourceError
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    try:
        wanted = [int(i) for i in (payload.get("indexes") or [])]
        submit = payload.get("submit")
        return await login_svc.pick_accounts(app, wanted, submit=None if submit is None else int(submit))
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc


@router.delete("/{app_id}/wps-login", response_model=dict)
async def wps_login_cancel(app_id: int, session: DbSession, admin: AdminUser) -> dict:
    """取消扫码（关掉那个留着的浏览器）。"""
    from app.services.webflow import login as login_svc

    app = await _get_app(session, app_id)
    _require_wps(app)
    await login_svc.close_login(app)
    return {"status": "closed"}
