"文档列表要显示的那些「一句话说明」。"

from __future__ import annotations

from app.api.v1.docs import _post_actions_label
from app.models.action import (
    ACTION_DINGTALK_ROBOT,
    ACTION_INTERFACE,
    ACTION_WEBHOOK,
    DdAction,
)
from app.models.task import DdTask


def make_task(**post_actions) -> DdTask:
    return DdTask(
        name="测试任务",
        code="TEST",
        doc_id=1,
        sheet_id="s1",
        engine="sheet",
        post_actions=post_actions.get("specs"),
    )


class TestPostActionsLabel:
    def test_none_configured(self):
        assert _post_actions_label(make_task(specs=None), []) == "无"

    def test_shows_what_it_does_not_how_many(self):
        """要写「钉钉机器人」，不能写「1 个动作」。"""
        task = make_task(specs=[{"action_id": 1, "on": "success"}])
        action = DdAction(
            name="同步通知",
            channels=[{"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x"}}],
        )
        assert _post_actions_label(task, [action]) == "钉钉机器人"

    def test_combines_channels_of_one_action(self):
        task = make_task(specs=[{"action_id": 1, "on": "success"}])
        action = DdAction(
            name="同步完成",
            channels=[
                {"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x"}},
                {"kind": ACTION_WEBHOOK, "config": {"url": "https://h"}},
            ],
        )
        assert _post_actions_label(task, [action]) == "钉钉机器人 + Webhook 调度"

    def test_dedupes_repeated_kinds(self):
        task = make_task(specs=[{"action_id": 1}, {"action_id": 2}])
        actions = [
            DdAction(name="A", channels=[{"kind": ACTION_INTERFACE, "config": {}}]),
            DdAction(name="B", channels=[{"kind": ACTION_INTERFACE, "config": {}}]),
        ]
        assert _post_actions_label(task, actions) == "接口调度"

    def test_legacy_single_kind_action_still_labels(self):
        """老数据只有 kind/config，也要能读出标签。"""
        task = make_task(specs=[{"action_id": 1}])
        action = DdAction(name="老的", kind=ACTION_WEBHOOK, config={"url": "https://h"})
        assert _post_actions_label(task, [action]) == "Webhook 调度"

    def test_deleted_action_is_not_silent(self):
        """配了动作但动作被删了 —— 得说出来，不能显示成「无」。"""
        task = make_task(specs=[{"action_id": 9}])
        assert "动作可能被删了" in (_post_actions_label(task, []) or "")
