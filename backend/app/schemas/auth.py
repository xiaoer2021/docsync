"""登录与账号。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.core.config import settings


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str
    status: str
    remark: str | None = None
    last_login_at: dt.datetime | None = None
    created_at: dt.datetime | None = None


class LoginResponse(BaseModel):
    token: str
    expires_in: int
    user: UserOut


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=settings.password_min_length, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=settings.password_min_length, max_length=256)
    display_name: str | None = Field(default=None, max_length=64)
    role: str = "viewer"
    remark: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = None
    status: str | None = None
    remark: str | None = None


class UserResetPassword(BaseModel):
    new_password: str = Field(min_length=settings.password_min_length, max_length=256)
