"后置动作：模板渲染、加签、渠道拼装、成功判定。"

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.parse

from app.api.v1.actions import _kind_label, _merge_channels, _merge_config
from app.models.action import (
    ACTION_DINGTALK_ROBOT,
    ACTION_INTERFACE,
    ACTION_WEBHOOK,
    DdAction,
    channels_of,
)
from app.services.actions import (
    DEFAULT_ROBOT_CONTENT,
    _build,
    _signed_robot_url,
    _verify,
    render,
    sample_context,
)


def channel(kind: str, **config) -> dict:
    return {"kind": kind, "config": config}


class TestRender:
    def test_placeholders(self):
        ctx = {"task_name": "亚马逊线下", "inserted": 100}
        assert render("{task_name} 新增 {inserted} 行", ctx) == "亚马逊线下 新增 100 行"

    def test_unknown_placeholder_is_left_alone(self):
        assert render("{不认识}", {}) == "{不认识}"

    def test_json_braces_survive(self):
        """请求体里写 JSON 花括号太常见了，绝不能因此炸掉。"""
        body = '{"text": "{task_name}", "n": {"a": 1}}'
        out = render(body, {"task_name": "X"})
        assert '"X"' in out
        assert '{"a": 1}' in out

    def test_unbalanced_braces_do_not_raise(self):
        assert render('{"a": ', {}) == '{"a": '

    def test_default_robot_template_renders(self):
        text = render(DEFAULT_ROBOT_CONTENT, sample_context())
        assert "示例：亚马逊线下日常费用" in text
        assert "成功" in text
        assert "{" not in text


class TestSigning:
    def test_no_secret_no_sign(self):
        assert _signed_robot_url("https://x/y?access_token=t", "") == "https://x/y?access_token=t"

    def test_sign_appended_with_ampersand_when_query_exists(self):
        url = _signed_robot_url("https://x/y?access_token=t", "SEC")
        assert "&timestamp=" in url and "&sign=" in url

    def test_signature_matches_dingtalk_algorithm(self):
        """钉钉加签 = base64(hmac_sha256(secret, "时间戳\\n密钥")) 再 urlencode。"""
        url = _signed_robot_url("https://x/y", "SEC")
        query = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        expected = base64.b64encode(
            hmac.new(b"SEC", f"{query['timestamp']}\nSEC".encode(), hashlib.sha256).digest()
        ).decode()
        assert query["sign"] == expected


class TestBuild:
    def test_webhook_is_just_a_get(self):
        """「Webhook 调度」的用途就是通知一声 —— 不该逼用户选方法、写请求头。"""
        url, method, headers, body = _build(channel(ACTION_WEBHOOK, url="https://h"), {})
        assert url == "https://h"
        assert method == "GET"
        assert body is None
        assert "Content-Type" not in headers

    def test_interface_keeps_method_and_body(self):
        got = channel(ACTION_INTERFACE, url="https://i", method="put", body="x=1")
        url, method, headers, body = _build(got, {})
        assert url == "https://i"
        assert method == "PUT"
        assert body == "x=1"
        assert headers["Content-Type"] == "application/json"

    def test_interface_url_and_headers_render_variables(self):
        got = channel(
            ACTION_INTERFACE,
            url="https://i/{task_code}",
            headers={"X-Task": "{task_name}"},
        )
        url, _, headers, _ = _build(got, {"task_code": "abc", "task_name": "甲"})
        assert url == "https://i/abc"
        assert headers["X-Task"] == "甲"

    def test_robot_body(self):
        got = channel(ACTION_DINGTALK_ROBOT, webhook="https://x/y", content="【{task_name}】{inserted}")
        url, method, _, body = _build(got, {"task_name": "T", "inserted": 3})
        assert method == "POST"
        assert body["msgtype"] == "text"
        assert body["text"]["content"] == "【T】3"
        assert "atMobiles" not in body["at"]

    def test_robot_uses_default_content_when_blank(self):
        _, _, _, body = _build(channel(ACTION_DINGTALK_ROBOT, webhook="https://x"), sample_context())
        assert "示例：亚马逊线下日常费用" in body["text"]["content"]

    def test_robot_at_all(self):
        got = channel(ACTION_DINGTALK_ROBOT, webhook="https://x", at_all=True)
        _, _, _, body = _build(got, {})
        assert body["at"]["isAtAll"] is True


class TestVerify:
    def test_2xx_is_ok(self):
        assert _verify(ACTION_WEBHOOK, {}, 200, "ok").ok is True

    def test_500_is_not_ok(self):
        outcome = _verify(ACTION_WEBHOOK, {}, 500, "boom")
        assert outcome.ok is False and outcome.http_status == 500

    def test_robot_business_error_behind_http_200(self):
        """钉钉用 HTTP 200 包一个 errcode —— 只看状态码会把失败当成功。"""
        payload = json.dumps({"errcode": 310000, "errmsg": "sign not match"})
        outcome = _verify(ACTION_DINGTALK_ROBOT, {}, 200, payload)
        assert outcome.ok is False
        assert "业务错误" in (outcome.error or "")

    def test_robot_errcode_zero_is_ok(self):
        assert _verify(ACTION_DINGTALK_ROBOT, {}, 200, json.dumps({"errcode": 0})).ok is True


class TestChannels:
    def test_channels_of_legacy_single_kind(self):
        """老数据只有单个 kind + config，也要能读出来。"""
        action = DdAction(name="老的", kind=ACTION_WEBHOOK, config={"url": "https://h"})
        got = channels_of(action)
        assert got == [{"kind": ACTION_WEBHOOK, "config": {"url": "https://h"}}]

    def test_channels_of_new_shape(self):
        action = DdAction(
            name="新的",
            channels=[
                {"kind": ACTION_WEBHOOK, "config": {"url": "https://h"}},
                {"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x"}},
            ],
        )
        assert len(channels_of(action)) == 2

    def test_one_action_can_do_both(self):
        """跑完既发钉钉又调接口，是同一件事的两半，不该建成两个动作。"""
        action = DdAction(
            name="同步完成",
            channels=[
                {"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x"}},
                {"kind": ACTION_WEBHOOK, "config": {"url": "https://h"}},
            ],
        )
        assert _kind_label(channels_of(action)) == "钉钉机器人 + Webhook 调度"

    def test_masked_secret_is_not_saved_back(self):
        """回显的是 ``****abcd``，用户不改直接保存 —— 不能把真密钥存成星号。"""
        old = [{"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x", "secret": "REAL"}}]
        new = [{"kind": ACTION_DINGTALK_ROBOT, "config": {"webhook": "https://x", "secret": "****REAL"}}]
        merged = _merge_channels(old, new)
        assert merged[0]["config"]["secret"] == "REAL"

    def test_secret_kept_when_a_different_kind_is_added(self):
        old = [{"kind": ACTION_DINGTALK_ROBOT, "config": {"secret": "REAL"}}]
        new = [
            {"kind": ACTION_DINGTALK_ROBOT, "config": {}},
            {"kind": ACTION_WEBHOOK, "config": {"url": "https://h"}},
        ]
        merged = _merge_channels(old, new)
        assert merged[0]["config"]["secret"] == "REAL"
        assert merged[1]["config"]["url"] == "https://h"


class TestMergeConfig:
    def test_empty_secret_keeps_old(self):
        assert _merge_config({"secret": "REAL"}, {"secret": ""})["secret"] == "REAL"

    def test_new_secret_replaces(self):
        assert _merge_config({"token": "OLD"}, {"token": "NEW"})["token"] == "NEW"

    def test_none_clears_non_secret(self):
        merged = _merge_config({"url": "u", "method": "POST"}, {"method": None})
        assert "method" not in merged
        assert merged["url"] == "u"
