"FastAPI 应用入口。"

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1 import api_router
from app.core.config import settings
from app.core.mask import mask_text

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()

    settings.validate_security()

    try:
        from app.services.runner.manager import reap_orphans

        reaped = await reap_orphans()
        if reaped:
            logger.warning("收掉 %s 条上次没跑完的执行记录（标记为失败）", reaped)
    except Exception:  # noqa: BLE001 — 收尾失败不该拦住整个服务启动
        logger.exception("清理上次残留的执行记录失败，服务继续")

    try:
        from app.core.db import SessionLocal
        from app.services import tunables

        async with SessionLocal() as session:
            tuning = await tunables.load(session)
        tunables.apply_to_runtime()
        logger.info("调度参数：%s", tuning)
    except Exception:  # noqa: BLE001
        logger.exception("读取调度参数失败，用默认值")

    from app.services.scheduler import scheduler

    try:
        fixed = await scheduler.sync_all()
        if fixed:
            logger.info("重排了 %s 个定时任务的下次运行时间", fixed)
        await scheduler.start()
    except Exception:  # noqa: BLE001 — 调度起不来也不该让整个服务起不来
        logger.exception("调度器启动失败，服务继续（任务只能手动跑）")

    yield

    from app.services.runner.manager import manager

    await scheduler.stop()
    await manager.shutdown()
    from app.services.webflow import cdp, login

    await login.close_all()
    await cdp.close_all_shared()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": mask_text(f"{type(exc).__name__}: {exc}")}},
    )


@app.get("/health")
async def health(response: Response) -> dict:
    """健康检查。既给容器编排用，也给界面上的「服务状态」用。"""
    from sqlalchemy import text

    from app.core.db import engine
    from app.services.runner.manager import manager
    from app.services.scheduler import scheduler

    db_ok = True
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = mask_text(f"{type(exc).__name__}: {exc}")
    if not db_ok:
        response.status_code = 503

    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "env": settings.env,
        "database": {
            "ok": db_ok,
            "kind": "sqlite" if settings.is_sqlite else "mysql",
            "error": db_error,
        },
        "scheduler": {
            "enabled": settings.scheduler_enabled and settings.embedded_scheduler,
            "running": scheduler.running,
        },
        "queue": manager.queue_state,
    }
