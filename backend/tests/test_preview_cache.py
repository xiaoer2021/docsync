"预览缓存。"

from __future__ import annotations

import time

from app.api.v1.tasks import (
    _PREVIEW_CACHE,
    PREVIEW_TTL,
    _cache_get,
    _cache_put,
    _preview_key,
)

CFG = {"orientation": "vertical", "header_row": 1, "col_start": "A", "col_end": "Z"}


def setup_function() -> None:
    _PREVIEW_CACHE.clear()


class TestPreviewKey:
    def test_same_inputs_same_key(self):
        a = _preview_key(1, "s1", CFG, 200, ["s2", "s3"])
        b = _preview_key(1, "s1", CFG, 200, ["s2", "s3"])
        assert a == b

    def test_merge_order_does_not_matter(self):
        """合并子表的顺序不影响缓存命中 —— 它只是同一批表。"""
        a = _preview_key(1, "s1", CFG, 200, ["s2", "s3"])
        b = _preview_key(1, "s1", CFG, 200, ["s3", "s2"])
        assert a == b

    def test_config_change_busts_cache(self):
        """改了表头行就是另一份预览。命中旧的话用户会以为「改了没反应」。"""
        a = _preview_key(1, "s1", CFG, 200, [])
        b = _preview_key(1, "s1", {**CFG, "header_row": 3}, 200, [])
        assert a != b

    def test_different_sheet_different_key(self):
        assert _preview_key(1, "s1", CFG, 200, []) != _preview_key(1, "s2", CFG, 200, [])


class TestCacheGetPut:
    def test_roundtrip(self):
        key = "k1"
        _cache_put(key, {"ok": True, "header": ["a"]})
        got = _cache_get(key)
        assert got == {"ok": True, "header": ["a"]}

    def test_miss_returns_none(self):
        assert _cache_get("nope") is None

    def test_failures_are_not_cached(self):
        """失败的预览不缓存：多半是权限或限流，缓存住会让「重试也没用」。"""
        _cache_put("bad", {"ok": False, "error": "没权限"})
        assert _cache_get("bad") is None

    def test_expired_entry_is_gone(self):
        key = "old"
        _PREVIEW_CACHE[key] = (time.time() - PREVIEW_TTL - 1, {"ok": True})
        assert _cache_get(key) is None
        assert key not in _PREVIEW_CACHE

    def test_returned_value_is_a_copy(self):
        """调用方（和各层序列化）会碰这个字典，给引用迟早被改花。"""
        _cache_put("c", {"ok": True, "header": ["a"]})
        first = _cache_get("c")
        first["header"].append("被改坏了")
        assert _cache_get("c")["header"] == ["a"]

    def test_stored_value_is_a_copy(self):
        payload = {"ok": True, "header": ["a"]}
        _cache_put("c2", payload)
        payload["header"].append("外面改了")
        assert _cache_get("c2")["header"] == ["a"]
