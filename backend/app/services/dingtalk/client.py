"""HTTP 客户端与访问凭证缓存。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.services.dingtalk.errors import (
    DingTalkError,
    is_permission_error,
    permission_hint_for,
)

_TOKEN_CACHE: dict[int, tuple[str, float]] = {}
_LOCKS: dict[int, asyncio.Lock] = {}

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _with_scope_hint(exc: DingTalkError, path: str) -> DingTalkError:
    "给「缺权限」错误补上这个接口真正需要的权限点。"
    if is_permission_error(exc):
        exc.hint = permission_hint_for(path)
    return exc


def _lock_for(key: int) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def forget_token(app_id: int) -> None:
    _TOKEN_CACHE.pop(app_id, None)


async def fetch_access_token(
    app_key: str, app_secret: str, *, timeout: float | None = None
) -> tuple[str, int]:
    "换 accessToken。返回 (token, 有效秒数)。"
    url = f"{settings.dingtalk_oauth_base.rstrip('/')}/gettoken"
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.dingtalk_timeout_seconds) as client:
            res = await client.get(url, params={"appkey": app_key, "appsecret": app_secret})
    except httpx.HTTPError as exc:
        raise DingTalkError(f"连接钉钉失败：{exc}") from exc

    try:
        body = res.json()
    except ValueError as exc:
        raise DingTalkError(
            f"钉钉返回了非 JSON 内容（HTTP {res.status_code}）", http_status=res.status_code
        ) from exc

    errcode = body.get("errcode")
    if errcode not in (0, None):
        raise DingTalkError(
            str(body.get("errmsg") or "换取访问凭证失败"),
            errcode=int(errcode) if isinstance(errcode, int) else None,
            http_status=res.status_code,
        )

    token = body.get("access_token")
    if not token:
        raise DingTalkError(
            f"钉钉没有返回 access_token（HTTP {res.status_code}）", http_status=res.status_code
        )

    return str(token), int(body.get("expires_in") or 7200)


async def get_access_token(
    *,
    app_id: int,
    app_key: str,
    app_secret: str,
    force: bool = False,
) -> str:
    """带缓存地取 token。并发调用同一应用只会换一次。"""
    now = time.time()
    cached = _TOKEN_CACHE.get(app_id)
    if not force and cached and cached[1] > now:
        return cached[0]

    async with _lock_for(app_id):
        cached = _TOKEN_CACHE.get(app_id)
        if not force and cached and cached[1] > time.time():
            return cached[0]

        token, expires_in = await fetch_access_token(app_key, app_secret)

        expires_at = time.time() + expires_in - settings.dingtalk_token_refresh_margin_seconds
        _TOKEN_CACHE[app_id] = (token, expires_at)
        return token


class DingTalkClient:
    "钉钉新版开放接口客户端。"

    def __init__(
        self,
        *,
        app_id: int,
        app_key: str,
        app_secret: str,
        operator_id: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.app_secret = app_secret
        self.operator_id = operator_id
        self.timeout = timeout or settings.dingtalk_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.dingtalk_max_retries

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        with_operator: bool = True,
    ) -> Any:
        if with_operator and not self.operator_id:
            raise DingTalkError(
                "这个请求缺少操作人（operatorId）。",
                code="MISSING_OPERATOR",
                hint=(
                    "钉钉要求每个读文档的请求都说明「以谁的身份读」。"
                    "去「钉钉应用」页给这个应用补一个操作人（手机上填手机号解析最省事），"
                    "或者在文档详情页给这份文档单独指定操作人。"
                ),
            )

        query: dict[str, Any] = {k: v for k, v in (params or {}).items() if v is not None}
        if with_operator and self.operator_id:
            query.setdefault("operatorId", self.operator_id)

        url = f"{settings.dingtalk_api_base.rstrip('/')}/{path.lstrip('/')}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            token = await get_access_token(
                app_id=self.app_id, app_key=self.app_key, app_secret=self.app_secret
            )
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    res = await client.request(method, url, params=query, headers=headers, json=json)
            except httpx.HTTPError as exc:
                last_error = DingTalkError(f"连接钉钉失败：{exc}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise last_error from exc

            if res.status_code in _RETRY_STATUS and attempt < self.max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue

            try:
                return self._parse(res)
            except DingTalkError as exc:
                raise _with_scope_hint(exc, path) from None

        raise last_error or DingTalkError("请求钉钉失败")

    @staticmethod
    def _parse(res: httpx.Response) -> Any:
        try:
            body = res.json()
        except ValueError:
            if res.status_code < 400:
                return None
            raise DingTalkError(
                f"钉钉返回了非 JSON 内容（HTTP {res.status_code}）",
                http_status=res.status_code,
            ) from None

        if res.status_code < 400:
            errcode = body.get("errcode") if isinstance(body, dict) else None
            if errcode not in (None, 0):
                raise DingTalkError(
                    str(body.get("errmsg") or "钉钉接口返回错误"),
                    errcode=int(errcode) if isinstance(errcode, int) else None,
                    http_status=res.status_code,
                )
            return body

        code = body.get("code") if isinstance(body, dict) else None
        message = (
            body.get("message") or body.get("errmsg") or f"HTTP {res.status_code}"
            if isinstance(body, dict)
            else f"HTTP {res.status_code}"
        )
        errcode = body.get("errcode") if isinstance(body, dict) else None
        raise DingTalkError(
            str(message),
            code=str(code) if code else None,
            errcode=int(errcode) if isinstance(errcode, int) else None,
            http_status=res.status_code,
        )

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def oapi(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        "老版 oapi 接口：access_token 放在查询参数里，地址是 oapi.dingtalk.com。"
        url = f"{settings.dingtalk_oauth_base.rstrip('/')}/{path.lstrip('/')}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            token = await get_access_token(
                app_id=self.app_id, app_key=self.app_key, app_secret=self.app_secret
            )
            query = {**(params or {}), "access_token": token}
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    res = await client.request(method, url, params=query, json=json)
            except httpx.HTTPError as exc:
                last_error = DingTalkError(f"连接钉钉失败：{exc}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise last_error from exc

            if res.status_code in _RETRY_STATUS and attempt < self.max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue

            try:
                return self._parse(res)
            except DingTalkError as exc:
                raise _with_scope_hint(exc, path) from None

        raise last_error or DingTalkError("请求钉钉失败")


def client_for(app: Any, *, operator_id: str | None = None) -> DingTalkClient:
    """从库里的应用记录造一个客户端。AppSecret 在这里解密，其他地方拿不到明文。"""
    secret = decrypt_secret(app.app_secret_enc).get("app_secret", "")
    return DingTalkClient(
        app_id=int(app.id),
        app_key=str(app.app_key),
        app_secret=str(secret),
        operator_id=operator_id or app.default_operator_union_id,
    )
