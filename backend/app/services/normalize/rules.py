"按规则改数据：**跳过整行** 或者 **替换掉某个格子的值**。"

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.normalize.headers import header_key

__all__ = ["RuleHit", "apply_rules", "parse_rules"]

_ACTIONS = {"skip", "replace"}


@dataclass
class RuleHit:
    """命中的一条规则干了什么 —— 拿它写日志、计数。"""

    row_no: int
    column: str
    match: str
    action: str
    before: str
    after: str = ""

    index: int = -1


@dataclass
class RuleResult:
    rows: list[list[str]] = field(default_factory=list)
    hits: list[RuleHit] = field(default_factory=list)

    @property
    def skipped_rows(self) -> list[int]:
        return sorted({hit.row_no for hit in self.hits if hit.action == "skip"})

    @property
    def replaced_cells(self) -> int:
        return sum(1 for hit in self.hits if hit.action == "replace")


def parse_rules(raw: Any) -> list[dict[str, Any]]:
    "把界面传来的规则过一遍，丢掉不成立的。"
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        match = str(item.get("match") or "")
        if action not in _ACTIONS or not match:
            continue
        out.append(
            {
                "column": str(item.get("column") or "").strip(),
                "match": match,
                "action": action,
                "value": str(item.get("value") if item.get("value") is not None else ""),
            }
        )
    return out


def apply_rules(
    rows: list[list[str]],
    header: list[str],
    rules: list[dict[str, Any]] | None,
    *,
    first_row: int = 1,
) -> RuleResult:
    "逐格套规则。``rows`` 是字符串网格，``first_row`` 是它的第 0 行对应原表第几行。"
    result = RuleResult()
    usable = parse_rules(rules)
    if not usable:
        result.rows = [list(row) for row in rows]
        return result

    for offset, row in enumerate(rows):
        row_no = first_row + offset
        cells = list(row)

        if any(_matches(cells, header, rule) for rule in usable if rule["action"] == "skip"):
            hit_rule = next(
                rule for rule in usable if rule["action"] == "skip" and _matches(cells, header, rule)
            )
            result.hits.append(
                RuleHit(
                    row_no=row_no,
                    column=hit_rule["column"] or "任意列",
                    match=hit_rule["match"],
                    action="skip",
                    before=_first_match(cells, header, hit_rule),
                )
            )
            continue

        for rule in usable:
            if rule["action"] != "replace":
                continue
            for index, cell in enumerate(cells):
                if rule["column"] and header_key(_header_at(header, index)) != header_key(rule["column"]):
                    continue
                if rule["match"] not in str(cell):
                    continue
                result.hits.append(
                    RuleHit(
                        row_no=row_no,
                        column=_header_at(header, index) or f"第{index + 1}列",
                        match=rule["match"],
                        action="replace",
                        before=str(cell),
                        after=rule["value"],
                        index=index,
                    )
                )
                cells[index] = rule["value"]

        result.rows.append(cells)

    return result


def _header_at(header: list[str], index: int) -> str:
    return str(header[index]) if index < len(header) else ""


def _matches(cells: list[str], header: list[str], rule: dict[str, Any]) -> bool:
    """这条跳过规则在这行命中了吗。"""
    for index, cell in enumerate(cells):
        if rule["column"] and header_key(_header_at(header, index)) != header_key(rule["column"]):
            continue
        if rule["match"] in str(cell):
            return True
    return False


def _first_match(cells: list[str], header: list[str], rule: dict[str, Any]) -> str:
    """命中时是哪一格 —— 写进日志，用户好核对。"""
    for index, cell in enumerate(cells):
        if rule["column"] and header_key(_header_at(header, index)) != header_key(rule["column"]):
            continue
        if rule["match"] in str(cell):
            return str(cell)
    return ""
