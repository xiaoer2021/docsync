"平台无关的表格工具。"

from app.services.tabular.align import (
    align_headers,
    expand_row,
    is_placeholder_header,
    missing_expected_headers,
)
from app.services.tabular.geometry import (
    CELL_SAFETY,
    MAX_CELLS,
    RangeTooLarge,
    a1_address,
    assert_range_ok,
    cell_is_empty,
    col_to_index,
    cols_per_read,
    column_count,
    index_to_col,
    row_has_data,
    rows_per_read,
)

__all__ = [
    "CELL_SAFETY",
    "MAX_CELLS",
    "RangeTooLarge",
    "a1_address",
    "align_headers",
    "assert_range_ok",
    "cell_is_empty",
    "col_to_index",
    "cols_per_read",
    "column_count",
    "expand_row",
    "index_to_col",
    "is_placeholder_header",
    "missing_expected_headers",
    "row_has_data",
    "rows_per_read",
]
