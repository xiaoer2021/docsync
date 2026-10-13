"读源的产物，以及读源的上限。"

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ROWS = 500_000


@dataclass(slots=True)
class SourceData:
    header: list[str]

    rows: list[tuple] = field(default_factory=list)
    skipped_formula_cells: int = 0

    sheet_columns: dict[str, list[str]] = field(default_factory=dict)

    sheet_column_types: dict[str, dict[str, str]] = field(default_factory=dict)
