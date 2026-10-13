"钉盘 / 文档搜索。"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.dingtalk.client import DingTalkClient

MAX_PAGE_SIZE = 50


@dataclass(slots=True)
class DentryHit:
    uuid: str
    name: str
    creator: str | None = None
    modifier: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "creator": self.creator,
            "modifier": self.modifier,
        }


def _person(value: Any) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name else None
    return None


async def search_dentries(
    client: DingTalkClient,
    keyword: str,
    *,
    next_token: str | None = None,
    max_results: int = 20,
) -> tuple[list[DentryHit], str | None]:
    """按关键词搜文档。返回 (结果, 下一页游标)，游标为空表示没有更多。"""
    option: dict[str, Any] = {"maxResults": min(max(int(max_results), 1), MAX_PAGE_SIZE)}
    if next_token:
        option["nextToken"] = next_token

    body = await client.post(
        "/v2.0/storage/dentries/search",
        json={"keyword": keyword.strip(), "option": option},
    )
    body = body or {}

    hits: list[DentryHit] = []
    for item in body.get("items") or []:
        if not isinstance(item, dict):
            continue
        uuid = item.get("dentryUuid")
        if not uuid:
            continue
        hits.append(
            DentryHit(
                uuid=str(uuid),
                name=str(item.get("name") or ""),
                creator=_person(item.get("creator")),
                modifier=_person(item.get("modifier")),
            )
        )

    token = body.get("nextToken")
    return hits, (str(token) if token else None)
