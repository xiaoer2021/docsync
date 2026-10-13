"""口令哈希与登录令牌。"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access"]


class TokenError(RuntimeError):
    pass


def _prehash(password: str) -> bytes:
    """bcrypt 只处理前 72 字节，先做 sha256 再 base64 以支持任意长度口令。"""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    if len(password) < settings.password_min_length:
        raise ValueError(f"口令至少 {settings.password_min_length} 位")
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: int,
    *,
    username: str = "",
    role: str = "viewer",
    expires_minutes: int | None = None,
) -> str:
    now = int(time.time())
    minutes = expires_minutes or settings.jwt_expire_minutes
    return jwt.encode(
        {
            "typ": "access",
            "sub": str(user_id),
            "username": username,
            "role": role,
            "iat": now,
            "exp": now + minutes * 60,
            "jti": uuid.uuid4().hex,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str, *, expect: TokenType = "access") -> dict[str, Any]:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("令牌已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("令牌无效") from exc
    if claims.get("typ") != expect:
        raise TokenError(f"令牌类型不符：期望 {expect}，实际 {claims.get('typ')}")
    return claims
