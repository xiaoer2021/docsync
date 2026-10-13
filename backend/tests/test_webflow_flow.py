"步骤解释器：不依赖真浏览器的部分（解析、IF 跳转、元素库）。"

from __future__ import annotations

import pytest

from app.services.webflow.flow import ElementLibrary, FlowError, _matching_endif, parse_flow


class TestParseFlow:
    def test_keeps_known_actions(self):
        steps = parse_flow(
            [
                {"action": "goto", "url": "https://x"},
                {"action": "wait", "element": "弹窗", "output": "r"},
                {"action": "if", "var": "r"},
                {"action": "click", "element": "弹窗"},
                {"action": "endif"},
            ]
        )
        assert [s.action for s in steps] == ["goto", "wait", "if", "click", "endif"]
        assert [s.index for s in steps] == [1, 2, 3, 4, 5]

    def test_unknown_action_is_skipped_not_fatal(self):
        """配置是给人编辑的 —— 拼错一个动词不该让整个取数读不出来。"""
        steps = parse_flow([{"action": "goto"}, {"action": "乱写的"}, {"action": "endif"}])
        assert [s.action for s in steps] == ["goto", "endif"]

    def test_junk_entries_ignored(self):
        assert parse_flow(None) == []
        assert parse_flow([None, "x", 1]) == []  # type: ignore[list-item]

    def test_empty_action_ignored(self):
        assert parse_flow([{"action": "  "}, {}]) == []


class TestMatchingEndif:
    """条件不成立时要跳到配对的 endif —— 嵌套也要对。"""

    def _steps(self, actions: list[str]):
        return parse_flow([{"action": a} for a in actions])

    def test_simple_pair(self):
        steps = self._steps(["if", "click", "endif", "click"])
        assert _matching_endif(steps, 0) == 3

    def test_nested_pair(self):
        """嵌套时「跳到第一个 endif」是错的 —— 会跳进内层里面。"""
        steps = self._steps(["if", "if", "click", "endif", "click", "endif", "click"])
        assert _matching_endif(steps, 0) == 6
        assert _matching_endif(steps, 1) == 4

    def test_unclosed_if_runs_to_end(self):
        steps = self._steps(["if", "click"])
        assert _matching_endif(steps, 0) == 2


class TestElementLibrary:
    def test_lookup(self):
        lib = ElementLibrary({"BI使用页签": "//div[@role='option']"})
        assert lib.xpath("BI使用页签") == "//div[@role='option']"

    def test_lookup_is_lenient_about_spaces(self):
        """手抄 XPath 的人很容易多打空格 —— 为此报「元素不存在」太苛刻。"""
        lib = ElementLibrary({"名称框_2": "//input[@class='edit-box']"})
        assert lib.xpath(" 名称框_2 ") == "//input[@class='edit-box']"

    def test_missing_element_lists_what_exists(self):
        """报错要把**现有元素列出来** —— 不然改配置的人不知道库里有什么。"""
        lib = ElementLibrary({"A": "//a", "B": "//b"})
        with pytest.raises(KeyError) as exc:
            lib.xpath("C")
        assert "A" in str(exc.value)
        assert "B" in str(exc.value)

    def test_empty_library(self):
        with pytest.raises(KeyError) as exc:
            ElementLibrary(None).xpath("任何")
        assert "空的" in str(exc.value)


class TestFlowError:
    def test_error_says_which_step(self):
        """报错必须带「第几步、什么动作」—— 只说「没找到元素」等于没说。"""
        err = FlowError(7, "click", "没找到元素：//div")
        assert "第 7 步" in err.message
        assert "click" in err.message
        assert err.hint
