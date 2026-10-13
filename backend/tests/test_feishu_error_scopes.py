"""飞书报错要说清「缺哪个权限点」。"""

from __future__ import annotations

from app.services.feishu.errors import (
    FeishuError,
    lookup_hint,
    missing_scopes,
    scope_names,
)


class TestMissingScopes:
    def test_extracts_from_real_feishu_message(self):
        """飞书的原文长这样 —— 缺什么就写在里面，这是唯一具体的信息。"""
        msg = "Access denied. One of the following scopes is required: " "[sheets:spreadsheet, drive:drive]"
        assert missing_scopes(msg) == ["sheets:spreadsheet", "drive:drive"]

    def test_three_part_scope(self):
        msg = "scope [bitable:app:readonly] is required"
        assert missing_scopes(msg) == ["bitable:app:readonly"]

    def test_ignores_ordinary_words(self):
        """只有「a:b」这种形状才算权限点，别把句子里的词抠出来。"""
        assert missing_scopes("Access denied for this app") == []

    def test_empty(self):
        assert missing_scopes(None) == []
        assert missing_scopes("") == []

    def test_dedupes(self):
        assert missing_scopes("[x:y, x:y]") == ["x:y"]


class TestScopeNames:
    def test_known_scope_gets_chinese_name(self):
        assert "电子表格读权限" in scope_names(["sheets:spreadsheet:readonly"])

    def test_unknown_scope_is_shown_as_is(self):
        """**不猜** —— 认不出就原样列出。猜错比不说更糟（用户会去开错开关）。"""
        assert scope_names(["weird:thing:x"]) == "weird:thing:x"


class TestHintCarriesTheScope:
    def test_permission_error_names_the_scope(self):
        """用户报的：无权限报错看不出要开什么。现在要能一眼看到。"""
        exc = FeishuError(
            "Access denied. One of the following scopes is required: [sheets:spreadsheet]",
            errcode=99991672,
        )
        assert "sheets:spreadsheet" in (exc.hint or "")
        assert "电子表格读权限" in (exc.hint or "")

        assert "创建版本并发布" in (exc.hint or "")

    def test_hint_without_scopes_is_unchanged(self):
        """报错里没写 scope 时别硬编一段。"""
        hint = lookup_hint(errcode=99991672, message="Access denied")
        assert hint is not None
        assert "缺这个权限" not in hint
