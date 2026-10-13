"""钉钉应用凭证与人员缓存。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

DOC_TYPE_SHEET = "sheet"
DOC_TYPE_AITABLE = "aitable"

DOC_TYPE_WEBPAGE = "webpage"
DOC_TYPES = (DOC_TYPE_SHEET, DOC_TYPE_AITABLE, DOC_TYPE_WEBPAGE)

DOC_TYPE_LABELS = {
    DOC_TYPE_SHEET: "在线表格",
    DOC_TYPE_AITABLE: "多维表",
    DOC_TYPE_WEBPAGE: "网页表格",
}

DOC_TYPE_LABELS_BY_PLATFORM: dict[str, dict[str, str]] = {
    "dingtalk": {DOC_TYPE_SHEET: "钉钉表格", DOC_TYPE_AITABLE: "多维表"},
    "feishu": {DOC_TYPE_SHEET: "飞书电子表格", DOC_TYPE_AITABLE: "飞书多维表格"},
    "wps": {DOC_TYPE_WEBPAGE: "WPS 表格"},
    "wps_api": {DOC_TYPE_SHEET: "WPS 表格"},
}


def doc_type_label(doc_type: str | None, platform: str | None = None) -> str:
    "文档类型的中文名。**按平台给**。"
    if not doc_type:
        return ""
    table = DOC_TYPE_LABELS_BY_PLATFORM.get(platform or "")
    if table and doc_type in table:
        return table[doc_type]
    return DOC_TYPE_LABELS.get(doc_type, doc_type)


class DdApp(BaseModel):
    "对接平台上的应用凭证（现在只实现了钉钉企业内部应用）。"

    __tablename__ = "dd_app"

    platform: Mapped[str] = mapped_column(String(16), default="dingtalk", nullable=False)

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    app_key: Mapped[str] = mapped_column(String(128), nullable=False)
    app_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)

    default_operator_union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_operator_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    token_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_token_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_token_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="enabled", nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    recipe: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DdContact(BaseModel):
    "人员缓存：unionId ↔ 姓名 ↔ 手机号 ↔ 部门。"

    __tablename__ = "dd_contact"
    __table_args__ = (UniqueConstraint("app_id", "union_id", name="uq_dd_contact_app_union"),)

    app_id: Mapped[int] = mapped_column(nullable=False)
    union_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dept: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="mobile", nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
