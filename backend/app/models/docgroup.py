"""业务分组。"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BigIntPK


class DdDocGroup(BaseModel):
    "业务分组（Coupang / 京东 / 独立站 …）。"

    __tablename__ = "dd_doc_group"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class DdDocGroupLink(BaseModel):
    "表单 ↔ 业务分组。**一个表单可以属于多个分组。**"

    __tablename__ = "dd_doc_group_link"
    __table_args__ = (UniqueConstraint("doc_id", "group_id", name="uq_doc_group_link"),)

    doc_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    group_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
