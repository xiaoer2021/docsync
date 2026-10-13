"飞书 HTTP 客户端与 tenant_access_token 缓存。"

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.feishu.errors import FeishuError, is_permission_error

_TOKEN_CACHE: dict[int, tuple[str, float]] = {}
_LOCKS: dict[int, asyncio.Lock] = {}

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _lock_for(key: int) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def forget_token(app_id: int) -> None:
    _TOKEN_CACHE.pop(app_id, None)


async def fetch_tenant_access_token(
    app_id: str, app_secret: str, *, timeout: float | None = None
) -> tuple[str, int]:
    "换 tenant_access_token。返回 (token, 有效秒数)。"
    url = f"{settings.feishu_api_base.rstrip('/')}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.feishu_timeout_seconds) as client:
            res = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise FeishuError(f"连接飞书失败：{exc}") from exc

    try:
        body = res.json()
    except ValueError as exc:
        raise FeishuError(
            f"飞书返回了非 JSON 内容（HTTP {res.status_code}）", http_status=res.status_code
        ) from exc

    code = body.get("code") if isinstance(body, dict) else None
    if code not in (0, None):
        raise FeishuError(
            str(body.get("msg") or "换取访问凭证失败"),
            errcode=int(code) if isinstance(code, int) else None,
            http_status=res.status_code,
        )

    token = body.get("tenant_access_token")
    if not token:
        raise FeishuError(
            f"飞书没有返回 tenant_access_token（HTTP {res.status_code}）",
            http_status=res.status_code,
        )

    return str(token), int(body.get("expire") or 7200)


async def get_tenant_access_token(*, app_id: int, app_key: str, app_secret: str, force: bool = False) -> str:
    """带缓存地取 token。并发调用同一个应用只会换一次。"""
    now = time.time()
    cached = _TOKEN_CACHE.get(app_id)
    if not force and cached and cached[1] > now:
        return cached[0]

    async with _lock_for(app_id):
        cached = _TOKEN_CACHE.get(app_id)
        if not force and cached and cached[1] > time.time():
            return cached[0]

        token, expires_in = await fetch_tenant_access_token(app_key, app_secret)
        expires_at = time.time() + expires_in - settings.feishu_token_refresh_margin_seconds
        _TOKEN_CACHE[app_id] = (token, expires_at)
        return token


class FeishuClient:
    "飞书开放接口客户端。"

    def __init__(
        self,
        *,
        app_id: int,
        app_key: str,
        app_secret: str,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = timeout or settings.feishu_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.feishu_max_retries

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{settings.feishu_api_base.rstrip('/')}/{path.lstrip('/')}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            token = await get_tenant_access_token(
                app_id=self.app_id, app_key=self.app_key, app_secret=self.app_secret
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    res = await client.request(method, url, params=query, headers=headers, json=json)
            except httpx.HTTPError as exc:
                last_error = FeishuError(f"连接飞书失败：{exc}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise last_error from exc

            if res.status_code in _RETRY_STATUS and attempt < self.max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue

            try:
                return self._parse(res)
            except FeishuError as exc:
                if exc.errcode in (99991663, 99991664) and attempt < self.max_retries - 1:
                    forget_token(self.app_id)
                    continue
                raise

        raise last_error or FeishuError("请求飞书失败")

    @staticmethod
    def _parse(res: httpx.Response) -> Any:
        "解飞书的响应。"
        try:
            body = res.json()
        except ValueError:
            if res.status_code < 400:
                return None
            raise FeishuError(
                f"飞书返回了非 JSON 内容（HTTP {res.status_code}）",
                http_status=res.status_code,
            ) from None

        if not isinstance(body, dict):
            return body

        code = body.get("code")
        if code not in (0, None):
            raise FeishuError(
                str(body.get("msg") or "飞书接口返回错误"),
                errcode=int(code) if isinstance(code, int) else None,
                http_status=res.status_code,
            )

        if res.status_code >= 400:
            raise FeishuError(
                str(body.get("msg") or f"HTTP {res.status_code}"),
                http_status=res.status_code,
            )

        return body

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)


def data_of(body: Any) -> dict[str, Any]:
    "取 ``data``。飞书的业务数据都在这一层，缺了当空 dict 处理。"
    if not isinstance(body, dict):
        return {}
    value = body.get("data")
    return value if isinstance(value, dict) else {}


def is_permission_failure(exc: FeishuError) -> bool:
    return is_permission_error(exc)
