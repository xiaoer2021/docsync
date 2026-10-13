"""Safety rules for destructive synchronization modes."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from app.services.loader.writer import WRITE_FULL_REPLACE, WRITE_REPLACE_PARTITION


@dataclass(frozen=True, slots=True)
class WriteSafety:
    blockers: tuple[str, ...]
    previous_rows: int | None
    source_rows: int
    output_rows: int

    @property
    def can_write(self) -> bool:
        return not self.blockers


def validate_quality_policy(
    columns: list[dict[str, Any]] | None, target: dict[str, Any] | None
) -> str | None:
    """Validate user-facing quality rules before storing a task."""
    target = target or {}
    mapped = {str(col.get("target")): str(col.get("type")) for col in (columns or []) if col.get("target")}
    note_columns = target.get("numeric_note_columns") or []
    if not isinstance(note_columns, list) or any(not isinstance(name, str) for name in note_columns):
        return "金额说明列必须是列名列表"
    if any(mapped.get(name) != "float" for name in note_columns):
        return "金额说明列必须是已映射的数值（double）列"
    note_column = str(target.get("note_column") or "备注").strip()
    if note_columns and (
        not note_column or note_column in note_columns or mapped.get(note_column) not in (None, "text")
    ):
        return "备注列必须是独立的文本列"
    ratio = target.get("minimum_row_ratio")
    if ratio is not None:
        try:
            number = float(ratio)
        except (TypeError, ValueError):
            return "行数保护比例必须是 0 到 1 之间的数值"
        if not isfinite(number) or not 0 <= number <= 1:
            return "行数保护比例必须是 0 到 1 之间的数值"
    return None


def run_status(
    *,
    failed_rows: int,
    retyped_columns: int,
    blockers: tuple[str, ...] = (),
) -> str:
    "这次执行该记「成功」还是「部分成功」。"
    from app.models.run import RUN_PARTIAL, RUN_SUCCESS

    if failed_rows or retyped_columns or blockers:
        return RUN_PARTIAL
    return RUN_SUCCESS


def assess_write_safety(
    *,
    mode: str,
    source_rows: int,
    output_rows: int,
    previous_rows: int | None,
    row_limited: bool,
    incremental: bool,
    source_cap_reached: bool,
    skipped_required: int,
    critical_cells: int,
    retyped_columns: int,
    minimum_row_ratio: float = 0.5,
) -> WriteSafety:
    "Reject a destructive write when the source is incomplete or unexpectedly changed."
    if not 0 <= minimum_row_ratio <= 1:
        raise ValueError("minimum_row_ratio must be between 0 and 1")
    if mode not in (WRITE_FULL_REPLACE, WRITE_REPLACE_PARTITION):
        return WriteSafety((), previous_rows, source_rows, output_rows)
    blockers: list[str] = []
    if row_limited:
        blockers.append("本次只读取了部分源数据")
    if incremental:
        blockers.append("增量窗口不能用于覆盖写入")
    if source_cap_reached:
        blockers.append("源数据达到读取上限，可能尚未读完")
    if skipped_required:
        blockers.append(f"有 {skipped_required} 行因必填值缺失被跳过")
    if critical_cells:
        blockers.append(f"有 {critical_cells} 个关键格没通过")
    if retyped_columns:
        blockers.append(f"有 {retyped_columns} 列发生自动类型调整")
    if not output_rows:
        blockers.append("没有可写入的行")
    if (
        mode == WRITE_FULL_REPLACE
        and previous_rows is not None
        and previous_rows >= 100
        and minimum_row_ratio > 0
        and output_rows < previous_rows * minimum_row_ratio
    ):
        blockers.append(
            f"本次只有 {output_rows} 行，少于目标表原有 {previous_rows} 行的" f" {minimum_row_ratio:.0%}"
        )
    return WriteSafety(tuple(blockers), previous_rows, source_rows, output_rows)
