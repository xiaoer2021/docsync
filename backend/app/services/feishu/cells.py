"飞书单元格的拍平。"

from __future__ import annotations

import json
from typing import Any

__all__ = ["flatten"]


def flatten(value: Any) -> Any:
    "把飞书的带类型单元格压成一个普通标量。"
    if value is None or value == "" or value == []:
        return None

    if isinstance(value, bool | int | float):
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("text", "name", "link"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found

        for found in value.values():
            if isinstance(found, list) and found:
                flattened = flatten(found)
                if flattened is not None:
                    return flattened
        return _json_fallback(value)

    if isinstance(value, list | tuple):
        items = list(value)
        if not items:
            return None

        if all(isinstance(x, dict) for x in items):
            parts: list[str] = []
            saw_text = False
            for item in items:
                for key in ("text", "name", "link"):
                    found = item.get(key)
                    if isinstance(found, str) and found:
                        parts.append(found)
                        if key == "text":
                            saw_text = True
                        break
            if parts:
                return "".join(parts) if saw_text else "、".join(parts)
            return _json_fallback(items)

        if all(not isinstance(x, dict | list | tuple) for x in items):
            texts = [str(x) for x in items if x is not None and x != ""]
            if not texts:
                return None
            return "、".join(texts) if len(texts) > 1 else texts[0]

        texts = [str(flatten(x)) for x in items if flatten(x) is not None]
        return "、".join(texts) if texts else None

    return str(value)


def _json_fallback(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
