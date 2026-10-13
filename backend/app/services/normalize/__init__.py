"""归一化层：类型转换、表头推断、列映射、去重与指纹。"""

from app.services.normalize.coercions import ConvertError, convert, is_empty
from app.services.normalize.headers import infer_header_row, normalize_headers
from app.services.normalize.mapping import (
    ColumnSpec,
    ResolvedColumn,
    RowResult,
    dedupe_rows,
    map_row,
    resolve_columns,
    row_fingerprint,
)

__all__ = [
    "ColumnSpec",
    "ConvertError",
    "ResolvedColumn",
    "RowResult",
    "convert",
    "dedupe_rows",
    "infer_header_row",
    "is_empty",
    "map_row",
    "normalize_headers",
    "resolve_columns",
    "row_fingerprint",
]
