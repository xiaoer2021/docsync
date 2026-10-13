"""品牌设置的进出参。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BrandingOut(BaseModel):
    name: str
    title: str
    tab_title: str
    has_logo: bool = False
    logo_updated_at: str | None = None


class BrandingUpdate(BaseModel):
    "只改传进来的项。"

    name: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=40)
    tab_title: str | None = Field(default=None, max_length=40)


class TuningOut(BaseModel):
    """调度相关的可调参数。都是整数，单位是秒（除并发数）。"""

    worker_max_concurrency: int
    queue_wait_timeout_seconds: int
    run_timeout_seconds: int


class TuningUpdate(BaseModel):
    worker_max_concurrency: int | None = Field(default=None, ge=1, le=32)
    queue_wait_timeout_seconds: int | None = Field(default=None, ge=30, le=24 * 3600)
    run_timeout_seconds: int | None = Field(default=None, ge=60, le=24 * 3600)
