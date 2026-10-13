"写入前按主键去重。"

from __future__ import annotations

from app.services.loader.writer import dedupe_by_key


def row(**kw) -> dict:
    return dict(kw)


class TestDedupeByKey:
    def test_no_duplicates_keeps_everything(self):
        rows = [row(id=1, v="a"), row(id=2, v="b")]
        kept, dropped = dedupe_by_key(rows, ["id"])
        assert len(kept) == 2
        assert dropped == 0

    def test_duplicate_keys_collapse(self):
        rows = [row(id=1, v="a"), row(id=1, v="b"), row(id=2, v="c")]
        kept, dropped = dedupe_by_key(rows, ["id"])
        assert len(kept) == 2
        assert dropped == 1

    def test_last_one_wins(self):
        """同步是「源文档当前的样子说了算」—— 留第一条会把后来的修改丢掉。"""
        rows = [row(id=1, v="旧"), row(id=1, v="新")]
        kept, _ = dedupe_by_key(rows, ["id"])
        assert kept[0]["v"] == "新"

    def test_multi_column_key(self):
        rows = [
            row(d="2026-01-01", shop="A", amount=100),
            row(d="2026-01-01", shop="A", amount=200),
            row(d="2026-01-01", shop="A", amount=100),
        ]
        kept, dropped = dedupe_by_key(rows, ["d", "shop", "amount"])
        assert len(kept) == 2
        assert dropped == 1

    def test_number_and_string_are_the_same_key(self):
        """源里读回来是数字 45511，另一处可能是字符串 '45511' —— 得算同一个身份证。"""
        rows = [row(id=45511, v="a"), row(id="45511", v="b")]
        kept, dropped = dedupe_by_key(rows, ["id"])
        assert len(kept) == 1
        assert dropped == 1

    def test_none_and_empty_are_the_same_key(self):
        rows = [row(id=None, v="a"), row(id="", v="b")]
        kept, dropped = dedupe_by_key(rows, ["id"])
        assert len(kept) == 1
        assert dropped == 1

    def test_no_keys_is_a_noop(self):
        rows = [row(id=1), row(id=1)]
        kept, dropped = dedupe_by_key(rows, [])
        assert len(kept) == 2
        assert dropped == 0

    def test_empty_input(self):
        assert dedupe_by_key([], ["id"]) == ([], 0)
