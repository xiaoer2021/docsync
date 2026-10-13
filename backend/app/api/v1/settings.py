"平台设置：名称、标题、标签页名、logo。"

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import AdminUser, DbSession
from app.schemas.branding import BrandingOut, BrandingUpdate, TuningOut, TuningUpdate
from app.services import audit, tunables
from app.services.branding import clear_logo, find_logo, read_branding, save_logo, write_branding

router = APIRouter(prefix="/settings", tags=["settings"])

MAX_LOGO_BYTES = 2 * 1024 * 1024


@router.get("/branding", response_model=BrandingOut)
async def get_branding(session: DbSession) -> BrandingOut:
    "当前品牌设置。"
    return BrandingOut(**await read_branding(session))


@router.put("/branding", response_model=BrandingOut)
async def put_branding(
    payload: BrandingUpdate, request: Request, session: DbSession, admin: AdminUser
) -> BrandingOut:
    out = await write_branding(session, payload.model_dump(exclude_unset=True))
    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_setting",
        summary="修改平台名称 / 标题",
        request=request,
    )
    return BrandingOut(**out)


@router.get("/tuning", response_model=TuningOut)
async def get_tuning(session: DbSession, admin: AdminUser) -> TuningOut:
    "调度参数。**要管理员** —— 这是运维配置，不是所有人该看到的。"
    return TuningOut(**await tunables.load(session))


@router.put("/tuning", response_model=TuningOut)
async def put_tuning(
    payload: TuningUpdate, request: Request, session: DbSession, admin: AdminUser
) -> TuningOut:
    out = await tunables.save(session, payload.model_dump(exclude_unset=True))

    tunables.apply_to_runtime()
    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_setting",
        summary=f"修改调度参数：{out}",
        request=request,
    )
    return TuningOut(**out)


@router.get("/branding/logo")
async def get_logo() -> FileResponse:
    path = find_logo()
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "还没有上传 logo")

    return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})


@router.post("/branding/logo", response_model=BrandingOut)
async def upload_logo(
    request: Request,
    session: DbSession,
    admin: AdminUser,
    file: UploadFile = File(...),
) -> BrandingOut:
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件是空的")
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片太大了，请控制在 2MB 以内")
    try:
        save_logo(file.filename or "logo.png", content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_setting",
        summary="更换平台 logo",
        request=request,
    )
    return BrandingOut(**await read_branding(session))


@router.delete("/branding/logo", response_model=BrandingOut)
async def reset_logo(request: Request, session: DbSession, admin: AdminUser) -> BrandingOut:
    clear_logo()
    audit.record(
        session,
        user=admin,
        action="update",
        target_type="dd_setting",
        summary="恢复默认 logo",
        request=request,
    )
    return BrandingOut(**await read_branding(session))
