"飞书对接的纯逻辑测试。"

from __future__ import annotations

import pytest

from app.services.feishu.bitable_reader import flatten
from app.services.feishu.errors import FeishuError, lookup_hint
from app.services.feishu.urls import (
    DOC_TYPE_AITABLE,
    DOC_TYPE_SHEET,
    DOC_TYPE_WIKI,
    DocRefError,
    doc_url,
    parse_doc_ref,
)


class TestParseDocRef:
    def test_sheet_link(self):
        ref = parse_doc_ref("https://acme.feishu.cn/sheets/shtcnABC123")
        assert ref.node_id == "shtcnABC123"
        assert ref.doc_type == DOC_TYPE_SHEET
        assert ref.is_url

    def test_bitable_link(self):
        ref = parse_doc_ref("https://acme.feishu.cn/base/bascnXYZ789")
        assert ref.node_id == "bascnXYZ789"
        assert ref.doc_type == DOC_TYPE_AITABLE

    def test_wiki_link_needs_resolve(self):
        ref = parse_doc_ref("https://acme.feishu.cn/wiki/wikcnQWE456")
        assert ref.doc_type == DOC_TYPE_WIKI

        assert ref.needs_resolve

    def test_lark_domain_also_works(self):
        """国际版域名不同，但不该影响解析 —— 路径段才是关键。"""
        ref = parse_doc_ref("https://acme.larksuite.com/sheets/shtcnINTL")
        assert ref.doc_type == DOC_TYPE_SHEET
        assert ref.node_id == "shtcnINTL"

    def test_query_hint_extracted(self):
        ref = parse_doc_ref("https://acme.feishu.cn/sheets/shtcnA?sheet=abc123")
        assert ref.sub_id_hint == "abc123"

    def test_table_hint_for_base(self):
        ref = parse_doc_ref("https://acme.feishu.cn/base/bascnB?table=tbl999")
        assert ref.sub_id_hint == "tbl999"

    def test_link_embedded_in_text(self):
        """用户经常连着一句话一起粘进来，要把链接抠出来。"""
        ref = parse_doc_ref("链接在这 https://acme.feishu.cn/sheets/shtcnC 你看下")
        assert ref.node_id == "shtcnC"

    def test_bare_token_guesses_bitable_by_prefix(self):
        ref = parse_doc_ref("bascnBARE123")
        assert ref.doc_type == DOC_TYPE_AITABLE

    def test_bare_token_guesses_sheet_by_prefix(self):
        ref = parse_doc_ref("shtcnBARE456")
        assert ref.doc_type == DOC_TYPE_SHEET

    def test_unknown_path_rejected(self):
        with pytest.raises(DocRefError):
            parse_doc_ref("https://acme.feishu.cn/search?q=hello")

    def test_empty_rejected(self):
        with pytest.raises(DocRefError):
            parse_doc_ref("   ")

    def test_doc_url_roundtrip(self):
        for kind in (DOC_TYPE_SHEET, DOC_TYPE_AITABLE):
            assert parse_doc_ref(doc_url("tok123", kind)).doc_type == kind


class TestFlatten:
    def test_text_cell_joins_text_segments(self):
        """飞书的文本是 [{"text": ...}]，不是字符串。"""
        assert flatten([{"text": "上海", "type": "text"}]) == "上海"

    def test_rich_text_segments_concatenated(self):
        assert flatten([{"text": "上海"}, {"text": " "}, {"text": "仓"}]) == "上海 仓"

    def test_person_cell_uses_name(self):
        assert flatten([{"id": "ou_1", "name": "张三"}]) == "张三"

    def test_multiple_people_joined(self):
        assert flatten([{"name": "张三"}, {"name": "李四"}]) == "张三、李四"

    def test_hyperlink_prefers_text(self):
        assert flatten({"link": "https://x.com", "text": "点这里"}) == "点这里"

    def test_hyperlink_without_text_falls_back_to_link(self):
        assert flatten({"link": "https://x.com"}) == "https://x.com"

    def test_number_and_bool_pass_through(self):
        assert flatten(42.5) == 42.5
        assert flatten(True) is True

    def test_multi_select_joined(self):
        assert flatten(["A", "B"]) == "A、B"

    def test_single_select_scalar(self):
        assert flatten("选项甲") == "选项甲"

    def test_empty_variants_become_none(self):
        for empty in (None, "", []):
            assert flatten(empty) is None

    def test_unknown_shape_degrades_to_readable_text(self):
        "认不出的形状要退化成**可读文本**，不能是 [object Object]。"
        weird = {"unknown_key": {"nested": 1, "deep": 2}}
        out = flatten(weird)
        assert out is not None
        assert "object Object" not in out

    def test_dict_wrapping_a_list_is_unwrapped(self):
        '**包了一层的要拆开**：飞书的人员是 ``{"users": [...]}``。'
        assert flatten({"users": [{"name": "张小力", "id": "ou_x"}]}) == "张小力"
        assert flatten({"link_record_ids": [{"text": "关联记录"}]}) == "关联记录"

    def test_dict_with_empty_list_falls_back(self):
        out = flatten({"users": []})
        assert out is not None and "object Object" not in out

    def test_attachment_uses_name(self):
        assert flatten([{"file_token": "box_1", "name": "报表.pdf"}]) == "报表.pdf"


class TestSheetCellFlatten:
    "电子表格的单元格也要拍平 —— 这条是真机数据逼出来的。"

    def test_read_range_flattens_rich_text_cells(self):
        import asyncio

        from app.services.feishu import sheet_reader

        class _FakeClient:
            async def get(self, path, **kwargs):
                return {
                    "code": 0,
                    "data": {
                        "valueRange": {
                            "values": [
                                [
                                    [{"text": "创建人："}, {"name": "黄泡泡", "type": "mention"}],
                                    "普通文本",
                                    42,
                                ]
                            ]
                        }
                    },
                }

        rows = asyncio.run(sheet_reader.read_range(_FakeClient(), "shtcnX", "sid1", "sid1!A1:C1"))
        assert rows == [["创建人：黄泡泡", "普通文本", 42]]

    def test_empty_response_gives_empty_list(self):
        import asyncio

        from app.services.feishu import sheet_reader

        class _FakeClient:
            async def get(self, path, **kwargs):
                return {"code": 0, "data": {}}

        assert asyncio.run(sheet_reader.read_range(_FakeClient(), "t", "s", "s!A1:B2")) == []


class TestSourceDispatch:
    """`sources` 那层的平台分派 —— 接新平台时最容易改漏的地方。"""

    def test_feishu_link_parsed_through_dispatcher(self):
        from app.services.sources import parse_doc_link

        ref = parse_doc_link("feishu", "https://a.feishu.cn/base/bascnX")
        assert ref.node_id == "bascnX"

        assert ref.doc_type == DOC_TYPE_AITABLE

    def test_dingtalk_link_has_no_doc_type(self):
        """钉钉的类型靠探测反推，解析阶段不该编一个出来。"""
        from app.services.sources import parse_doc_link

        ref = parse_doc_link("dingtalk", "https://alidocs.dingtalk.com/i/nodes/abc123XYZ")
        assert ref.node_id == "abc123XYZ"
        assert ref.doc_type is None

    def test_bad_link_raises_platform_neutral_error(self):
        """两家的 DocRefError 都要被换成 DocLinkError，调用方只捕一个类型。"""
        from app.services.sources import DocLinkError, parse_doc_link

        for platform in ("dingtalk", "feishu"):
            with pytest.raises(DocLinkError):
                parse_doc_link(platform, "这不是链接也不是ID！！！")

    def test_feishu_needs_no_operator_for_build_source(self):
        "飞书按应用自己的权限读文档，不该要 operatorId。"
        from app.services.sources import build_source

        class _App:
            id = 1
            platform = "feishu"
            app_key = "cli_x"

        src = build_source(_App(), None, secret="s")
        assert src.platform == "feishu"

    def test_pending_platform_reports_not_ready_not_unknown(self):
        """「还没接入」和「名字拼错」要给不同的话 —— 拼错的人不该以为自己只是来得早。"""
        from app.services.sources import RunAborted, build_source

        class _Pending:
            platform = "google"

        class _Bogus:
            platform = "wpsx"

        with pytest.raises(RunAborted) as pending:
            build_source(_Pending(), None, secret="s")
        assert "接入中" in str(pending.value)

        with pytest.raises(RunAborted) as bogus:
            build_source(_Bogus(), None, secret="s")
        assert "不认识" in str(bogus.value)


class TestErrorHints:
    def test_permission_code_gets_hint(self):
        exc = FeishuError("no permission", errcode=99991672)
        assert exc.hint

        assert "发布" in exc.hint

    def test_unknown_code_falls_back_to_message(self):
        """错误码**不认识**时才回头看文案（已知码优先，见 lookup_hint 的说明）。"""
        exc = FeishuError("Forbidden: not a collaborator", errcode=424242424)
        assert exc.hint
        assert "分享" in exc.hint or "协作者" in exc.hint

    def test_known_code_wins_over_ambiguous_message(self):
        "「no permission」这句话两种情况下都会出现，所以已知码必须优先。"
        exc = FeishuError("no permission", errcode=99991672)
        assert "发布" in exc.hint

    def test_token_message_hint(self):
        assert lookup_hint(message="invalid token") is not None

    def test_unknown_code_has_no_hint(self):
        assert lookup_hint(errcode=123456789) is None

    def test_string_is_human_readable(self):
        exc = FeishuError("失败了", code="1310213")
        text = str(exc)
        assert "失败了" in text
        assert "1310213" in text

    def test_to_dict_shape_matches_dingtalk(self):
        """两个平台错误都喂给同一套界面，字段必须一致。"""
        exc = FeishuError("x", errcode=99991672, http_status=403)
        data = exc.to_dict()
        assert set(data) == {"message", "code", "errcode", "http_status", "hint"}

    def test_feishu_error_is_source_error(self):
        from app.services.sources import SourceError

        assert isinstance(FeishuError("x"), SourceError)
