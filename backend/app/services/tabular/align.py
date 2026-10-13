"多子表按列名对齐。"

from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"^列[A-Z]+$")


def is_placeholder_header(name: str) -> bool:
    "这个名字是不是「本来就没表头，被补出来的」。"
    return bool(_PLACEHOLDER_RE.match((name or "").strip()))


def align_headers(headers: list[list[str]]) -> tuple[list[str], list[list[int]]]:
    "把多张表的表头**按列名**对齐到同一个列序上。"
    union: list[str] = []
    index_of: dict[str, int] = {}

    def take(name: str) -> bool:
        if is_placeholder_header(name) or not (name or "").strip():
            return False
        if name in index_of:
            return False
        index_of[name] = len(union)
        union.append(name)
        return True

    for name in headers[0]:
        take(name)
    for hdr in headers[1:]:
        for name in hdr:
            take(name)

    maps = [[index_of.get(name, -1) for name in hdr] for hdr in headers]
    return union, maps


def expand_row(values: list, slot: list[int], width: int) -> list:
    """把某张表的一行按落位表摊到合并列序上，没有的列留空。"""
    out: list = [None] * width
    for i, value in enumerate(values):
        target = slot[i] if i < len(slot) else -1
        if target >= 0:
            out[target] = value
    return out


def missing_expected_headers(expected: list[str], actual: list[str]) -> list[str]:
    "表头校验：``expected`` 里哪些列在 ``actual`` 里找不到。"
    from app.services.normalize.headers import header_key

    exact = set(actual)
    loose: dict[str, int] = {}
    for name in actual:
        key = header_key(name)
        if key:
            loose[key] = loose.get(key, 0) + 1
    return [name for name in expected if name not in exact and loose.get(header_key(name), 0) != 1]
