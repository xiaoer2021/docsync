"通讯录：把手机号或姓名换成 operatorId（unionId）。"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError


@dataclass(slots=True)
class Contact:
    user_id: str | None = None
    union_id: str | None = None
    name: str | None = None
    mobile: str | None = None
    dept: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "union_id": self.union_id,
            "name": self.name,
            "mobile": self.mobile,
            "dept": self.dept,
        }


def _dept_text(row: dict[str, Any]) -> str | None:
    names = row.get("dept_name_list") or row.get("dept_names")
    if isinstance(names, list) and names:
        return " / ".join(str(n) for n in names)
    dept_id_list = row.get("dept_id_list")
    if isinstance(dept_id_list, list) and dept_id_list:
        return ",".join(str(d) for d in dept_id_list)
    return None


def _to_contact(row: dict[str, Any]) -> Contact:
    return Contact(
        user_id=str(row["userid"]) if row.get("userid") else None,
        union_id=str(row["unionid"]) if row.get("unionid") else None,
        name=str(row.get("name")) if row.get("name") else None,
        mobile=str(row.get("mobile")) if row.get("mobile") else None,
        dept=_dept_text(row),
    )


def _result(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        inner = body.get("result")
        if isinstance(inner, dict):
            return inner
        return body
    return {}


async def user_detail(client: DingTalkClient, user_id: str) -> Contact:
    "用 **userId** 换完整信息（含 unionId）。"
    body = await client.oapi("POST", "/topapi/v2/user/get", json={"userid": user_id, "language": "zh_CN"})
    return _to_contact(_result(body))


async def user_id_by_unionid(client: DingTalkClient, union_id: str) -> str | None:
    "unionId → userId。"
    body = await client.oapi("POST", "/topapi/user/getbyunionid", json={"unionid": union_id.strip()})
    data = _result(body)
    user_id = data.get("userid")
    return str(user_id) if user_id else None


async def contact_by_union_id(client: DingTalkClient, union_id: str) -> Contact | None:
    """unionId → 人员信息。查不到返回 None。"""
    user_id = await user_id_by_unionid(client, union_id)
    if not user_id:
        return None
    contact = await user_detail(client, user_id)
    contact.union_id = contact.union_id or union_id
    return contact


async def user_id_by_mobile(client: DingTalkClient, mobile: str) -> str | None:
    body = await client.oapi("POST", "/topapi/v2/user/getbymobile", json={"mobile": mobile.strip()})
    data = _result(body)
    user_id = data.get("userid")
    return str(user_id) if user_id else None


async def resolve_by_mobile(client: DingTalkClient, mobile: str) -> Contact | None:
    """手机号 → userId → unionId。查不到返回 None（比如人已离职）。"""
    user_id = await user_id_by_mobile(client, mobile)
    if not user_id:
        return None
    contact = await user_detail(client, user_id)
    contact.mobile = contact.mobile or mobile.strip()
    return contact


async def list_department_users(
    client: DingTalkClient, *, dept_id: int = 1, keyword: str | None = None, limit: int = 100
) -> list[Contact]:
    "列某个部门下的人。"
    size = min(max(limit, 1), 100)
    body = await client.oapi(
        "POST", "/topapi/v2/user/list", json={"dept_id": dept_id, "cursor": 0, "size": size}
    )
    rows = _result(body).get("list") or []
    contacts = [_to_contact(row) for row in rows if isinstance(row, dict)]

    need_detail = [c for c in contacts if c.user_id and not c.union_id]
    for contact in need_detail[:size]:
        try:
            detail = await user_detail(client, contact.user_id or "")
        except DingTalkError:
            continue
        contact.union_id = detail.union_id
        contact.mobile = contact.mobile or detail.mobile
        contact.dept = contact.dept or detail.dept

    if keyword:
        text = keyword.strip()
        contacts = [c for c in contacts if (c.name and text in c.name) or (c.mobile and text in c.mobile)]

    return contacts[:limit]
