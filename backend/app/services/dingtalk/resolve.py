"""文档探测：判定是钉钉表格还是多维表，并列出子表。"""

from __future__ import annotations

from app.models.app import DOC_TYPE_AITABLE, DOC_TYPE_SHEET
from app.services.dingtalk import aitable_reader, sheet_reader
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.errors import DingTalkError

_TYPE_MISMATCH_CODES = {
    "invalidRequest.resource.notWorkbook",
    "invalidRequest.document.typeIllegal",
    "invalidRequest.resource.notFound",
    "invalidRequest.document.notFound",
}

from app.services.sources.base import ProbeResult as ProbeResult  # noqa: E402
from app.services.sources.base import SubItem as SubItem  # noqa: E402


async def _probe_sheet(client: DingTalkClient, node_id: str) -> list[SubItem]:
    sheets = await sheet_reader.list_sheets(client, node_id)
    return [SubItem(id=s.id, name=s.name, kind="worksheet") for s in sheets]


async def _probe_aitable(client: DingTalkClient, node_id: str) -> list[SubItem]:
    tables = await aitable_reader.list_tables(client, node_id)
    out: list[SubItem] = []
    for table in tables:
        try:
            field_count: int | None = len(await aitable_reader.list_fields(client, node_id, table.id))
        except DingTalkError:
            field_count = None
        out.append(SubItem(id=table.id, name=table.name, kind="aitable_table", field_count=field_count))
    return out


async def probe_doc(
    client: DingTalkClient, node_id: str, *, preferred_type: str | None = None
) -> ProbeResult:
    "探测文档类型并列出子表。"
    if preferred_type in (DOC_TYPE_SHEET, DOC_TYPE_AITABLE):
        order = [preferred_type]
    else:
        order = [DOC_TYPE_SHEET, DOC_TYPE_AITABLE]

    attempts: list[dict[str, str]] = []
    first_error: DingTalkError | None = None

    for doc_type in order:
        label = "钉钉表格" if doc_type == DOC_TYPE_SHEET else "多维表"
        try:
            items = (
                await _probe_sheet(client, node_id)
                if doc_type == DOC_TYPE_SHEET
                else await _probe_aitable(client, node_id)
            )
            return ProbeResult(ok=True, doc_type=doc_type, sub_items=items, attempts=attempts)
        except DingTalkError as exc:
            attempts.append(
                {
                    "doc_type": doc_type,
                    "label": label,
                    "code": exc.code or (f"errcode={exc.errcode}" if exc.errcode else ""),
                    "message": exc.message,
                }
            )
            if first_error is None:
                first_error = exc
            if len(order) == 1 or exc.code not in _TYPE_MISMATCH_CODES:
                break

    if first_error is not None:
        return ProbeResult(
            ok=False,
            error=first_error.message,
            hint=first_error.hint,
            code=first_error.code,
            http_status=first_error.http_status,
            attempts=attempts,
        )
    return ProbeResult(ok=False, error="探测失败，没有可用的读取方式")
