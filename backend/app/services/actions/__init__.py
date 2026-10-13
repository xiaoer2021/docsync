"后置动作：落库完成之后要触发什么。"

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.mask import mask_text
from app.models.action import (
    ACT_FAILED,
    ACT_SUCCESS,
    ACTION_DINGTALK_ROBOT,
    ACTION_WEBHOOK,
    ON_ALWAYS,
    ON_FAILURE,
    ON_MODE_LABELS,
    ON_NOT_SUCCESS,
    ON_PARTIAL,
    ON_SUCCESS,
    DdAction,
    channels_of,
)
from app.models.run import RUN_PARTIAL, RUN_SUCCESS, DdRunAction
from app.models.task import DdTask

logger = logging.getLogger(__name__)

DIGEST_LIMIT = 2000
DEFAULT_TIMEOUT = 15.0

TEMPLATE_FIELDS = (
    "task_name",
    "task_code",
    "target_table",
    "datasource",
    "status",
    "status_label",
    "read",
    "inserted",
    "updated",
    "unchanged",
    "failed",
    "duration_sec",
    "started_at",
    "finished_at",
    "error",
    "run_id",
)

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULT_ROBOT_CONTENT = (
    "【数据同步】{task_name}\n"
    "结果：{status_label}\n"
    "写入 {target_table}：新增 {inserted}、更新 {updated}、未变 {unchanged}\n"
    "耗时 {duration_sec} 秒　{finished_at}"
)


@dataclass(slots=True)
class ActionOutcome:
    ok: bool
    http_status: int | None = None
    detail: str = ""
    request_digest: str = ""
    error: str | None = None


def _clip(value: Any, limit: int = DIGEST_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[:limit] + f"…（共 {len(text)} 字，已截断）"
    return mask_text(text)


def render(template: str, ctx: dict[str, Any]) -> str:
    "把 ``{task_name}`` 这类变量换成真值。"
    return _PLACEHOLDER.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), template)


def preview(channel: dict[str, Any], ctx: dict[str, Any]) -> str:
    """给界面用的「发出去大概长什么样」。不真发。"""
    kind = str(channel.get("kind") or "")
    config = channel.get("config") or {}
    if kind == ACTION_DINGTALK_ROBOT:
        return render(str(config.get("content") or DEFAULT_ROBOT_CONTENT), ctx)
    url, method, _, body = _build(channel, ctx)
    if body is None:
        return f"{method} {url}"
    return f"{method} {url}\n\n{body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)}"


def _signed_robot_url(webhook: str, secret: str | None) -> str:
    """钉钉机器人加签。没配密钥就原样返回。"""
    secret = (secret or "").strip()
    if not secret:
        return webhook
    stamp = str(round(time.time() * 1000))
    payload = f"{stamp}\n{secret}".encode()
    digest = hmac.new(secret.encode(), payload, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode())
    joiner = "&" if "?" in webhook else "?"
    return f"{webhook}{joiner}timestamp={stamp}&sign={sign}"


def _build(channel: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, str, dict, Any]:
    """按 channel 拼出 (url, method, headers, body)。"""
    kind = str(channel.get("kind") or "")
    config = channel.get("config") or {}
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if kind == ACTION_DINGTALK_ROBOT:
        webhook = str(config.get("webhook") or "")
        url = _signed_robot_url(webhook, config.get("secret"))
        content = render(str(config.get("content") or DEFAULT_ROBOT_CONTENT), ctx)
        body: dict[str, Any] = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"isAtAll": bool(config.get("at_all"))},
        }
        return url, "POST", headers, body

    if kind == ACTION_WEBHOOK:
        return render(str(config.get("url") or ""), ctx), "GET", {}, None

    headers.update({str(k): render(str(v), ctx) for k, v in (config.get("headers") or {}).items()})
    url = render(str(config.get("url") or ""), ctx)
    method = str(config.get("method") or "POST").upper()
    raw = config.get("body")
    body = render(raw, ctx) if isinstance(raw, str) and raw.strip() else raw
    return url, method, headers, body


def _verify(kind: str, config: dict[str, Any], status_code: int, text: str) -> ActionOutcome:
    """判断这次调用算不算成功。"""
    if not (200 <= status_code < 300):
        return ActionOutcome(
            ok=False, http_status=status_code, error=f"HTTP {status_code}：{_clip(text, 300)}"
        )

    if kind == ACTION_DINGTALK_ROBOT or config.get("check_errcode"):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            code = payload.get("errcode", payload.get("code"))
            if code not in (None, 0, "0", "success"):
                return ActionOutcome(
                    ok=False,
                    http_status=status_code,
                    error=f"接口返回业务错误：{_clip(payload, 300)}",
                )
    return ActionOutcome(ok=True, http_status=status_code)


async def execute(channel: dict[str, Any], ctx: dict[str, Any]) -> ActionOutcome:
    """跑一个 channel。任何异常都吞掉转成失败结果 —— 不能连累主任务。"""
    kind = str(channel.get("kind") or "")
    config = channel.get("config") or {}
    url, method, headers, body = _build(channel, ctx)
    if not url:
        return ActionOutcome(ok=False, error="没配地址")

    timeout = float(config.get("timeout_sec") or DEFAULT_TIMEOUT)
    if body is None:
        payload: bytes | None = None
    elif isinstance(body, str):
        payload = body.encode("utf-8")
    else:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    request_digest = _clip({"method": method, "url": url, "body": body})

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(method, url, headers=headers, content=payload)
    except httpx.TimeoutException:
        return ActionOutcome(ok=False, error=f"请求超过 {timeout:g} 秒没返回", request_digest=request_digest)
    except httpx.HTTPError as exc:
        return ActionOutcome(
            ok=False, error=f"请求发不出去：{mask_text(str(exc))}", request_digest=request_digest
        )

    outcome = _verify(kind, config, response.status_code, response.text)
    outcome.detail = _clip(response.text)
    outcome.request_digest = request_digest
    return outcome


def _should_run(on: str, status: str) -> bool:
    "这次执行该不该跑这个动作。"
    if on == ON_ALWAYS:
        return True
    if on == ON_SUCCESS:
        return status == RUN_SUCCESS
    if on == ON_PARTIAL:
        return status == RUN_PARTIAL
    if on == ON_NOT_SUCCESS:
        return status != RUN_SUCCESS
    if on == ON_FAILURE:
        return status not in (RUN_SUCCESS, RUN_PARTIAL)
    return False


STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "partial": "部分成功",
    "canceled": "已取消",
    "timeout": "超时",
    "running": "运行中",
}


async def _load_actions(session, task: DdTask) -> list[tuple[DdAction, str]]:
    specs = task.post_actions or []
    ids = [int(s["action_id"]) for s in specs if s.get("action_id")]
    if not ids:
        return []
    rows = (
        (await session.execute(select(DdAction).where(DdAction.id.in_(ids), DdAction.enabled.is_(True))))
        .scalars()
        .all()
    )
    by_id = {row.id: row for row in rows}
    result: list[tuple[DdAction, str]] = []
    for spec in specs:
        action = by_id.get(int(spec.get("action_id") or 0))
        if action is not None:
            result.append((action, str(spec.get("on") or ON_SUCCESS)))
    return result


def build_context(task: DdTask, run, *, datasource: str = "") -> dict[str, Any]:
    """模板变量。界面上的「预览」和真跑用的是同一份，免得对不上。"""

    def stamp(value: Any) -> str:
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value)

    return {
        "task_name": task.name,
        "task_code": task.code,
        "target_table": task.target_table,
        "datasource": datasource,
        "status": run.status,
        "status_label": STATUS_LABELS.get(run.status, run.status),
        "read": run.rows_read,
        "inserted": run.rows_inserted,
        "updated": run.rows_updated,
        "unchanged": run.rows_unchanged,
        "failed": run.rows_failed,
        "duration_sec": round((run.duration_ms or 0) / 1000, 1),
        "started_at": stamp(run.started_at),
        "finished_at": stamp(run.finished_at),
        "error": run.error_message or "",
        "run_id": run.id,
    }


def sample_context() -> dict[str, Any]:
    """试发/预览用的一份样例数据。不会碰到任何真实数据。"""
    return {
        "task_name": "示例：亚马逊线下日常费用",
        "task_code": "SAMPLE",
        "target_table": "亚马逊_线下费用",
        "datasource": "BI数据库·sqlserver",
        "status": "success",
        "status_label": "成功",
        "read": 2152,
        "inserted": 2146,
        "updated": 4,
        "unchanged": 2,
        "failed": 0,
        "duration_sec": 3.2,
        "started_at": "2026-10-07 09:25:12",
        "finished_at": "2026-10-07 09:25:20",
        "error": "",
        "run_id": 12,
    }


async def _record(run_id: int, action: DdAction, on: str, item: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        session.add(
            DdRunAction(
                run_id=run_id,
                action_id=action.id,
                action_name=action.name,
                kind=item.get("kind"),
                trigger_on=on,
                status=item.get("status") or ACT_FAILED,
                duration_ms=item.get("duration_ms"),
                http_status=item.get("http_status"),
                request_digest=item.get("request_digest"),
                response_digest=item.get("response_digest"),
                error_message=item.get("error"),
            )
        )
        await session.commit()


async def run_post_actions(run_id: int, *, dry_run: bool = False) -> None:
    "在 run 结束之后跑它配的后置动作。"
    if dry_run:
        return

    async with SessionLocal() as session:
        from app.models.run import DdRun

        run = await session.get(DdRun, run_id)
        if run is None:
            return
        task = await session.get(DdTask, run.task_id)
        if task is None:
            return

        pairs = await _load_actions(session, task)
        if not pairs:
            return

        datasource = ""
        ds_id = (task.target or {}).get("datasource_id")
        if ds_id:
            from app.models.datasource import DdDatasource

            ds = await session.get(DdDatasource, int(ds_id))
            datasource = f"{ds.name}·{ds.db_type}" if ds else ""

        ctx = build_context(task, run, datasource=datasource)
        run_status = run.status
        jobs = [(a, on, ch) for a, on in pairs for ch in channels_of(a) if _should_run(on, run_status)]

        skipped = [(a, on, ch) for a, on in pairs for ch in channels_of(a) if not _should_run(on, run_status)]

    for action, on, channel in skipped:
        await _record(
            run_id,
            action,
            on,
            {
                "kind": str(channel.get("kind") or ""),
                "status": "skipped",
                "error": f"这次是{STATUS_LABELS.get(run_status, run_status)}，"
                f"动作设的是{ON_MODE_LABELS.get(on, on)}，所以没执行",
            },
        )

    if not jobs:
        return

    logger.info("开始跑后置动作：%s 个渠道", len(jobs))

    for action, on, channel in jobs:
        kind = str(channel.get("kind") or "")
        started = time.monotonic()
        try:
            outcome = await asyncio.wait_for(execute(channel, ctx), timeout=60.0)
        except asyncio.TimeoutError:
            outcome = ActionOutcome(ok=False, error="动作整体超时（60 秒）")
        except Exception as exc:  # noqa: BLE001 — 动作怎么炸都不能影响主流程
            outcome = ActionOutcome(ok=False, error=f"{type(exc).__name__}: {mask_text(str(exc))}")

        elapsed = int((time.monotonic() - started) * 1000)
        label = f"{action.name} / {kind}"
        if outcome.ok:
            logger.info(f"后置动作「{label}」成功（{elapsed} ms）")
        else:
            logger.warn(f"后置动作「{label}」失败：{outcome.error}")

        await _record(
            run_id,
            action,
            on,
            {
                "kind": kind,
                "status": ACT_SUCCESS if outcome.ok else ACT_FAILED,
                "duration_ms": elapsed,
                "http_status": outcome.http_status,
                "request_digest": outcome.request_digest or None,
                "response_digest": outcome.detail or None,
                "error": mask_text(outcome.error) if outcome.error else None,
            },
        )


__all__ = [
    "ActionOutcome",
    "TEMPLATE_FIELDS",
    "DEFAULT_ROBOT_CONTENT",
    "build_context",
    "channels_of",
    "execute",
    "preview",
    "render",
    "run_post_actions",
    "sample_context",
]
