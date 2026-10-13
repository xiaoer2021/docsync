"网页取数：不依赖真浏览器的部分。"

from __future__ import annotations

import pytest

from app.services.webflow.actions import Box, parse_tsv, tsv_to_grid
from app.services.webflow.cdp import CdpError, find_browser


class TestBoxPoint:
    """点哪儿 —— 影刀里那个「锚点 + 自定义偏移」就是这段。"""

    def test_center_is_default(self):
        box = Box(x=100, y=200, w=40, h=20, visible=True)
        assert box.point() == (120, 210)

    def test_topleft_with_offset(self):
        """右键必须落在选区内时用这个（默认点中心会被别的图层挡掉）。"""
        box = Box(x=100, y=200, w=400, h=300, visible=True)
        assert box.point("topleft", (160, 100)) == (260, 300)

    def test_negative_coords_are_kept(self):
        """元素被滚出视口时坐标会是负的 —— 原样返回，让调用方去判断。"""
        box = Box(x=-30, y=-10, w=10, h=10, visible=True)
        assert box.point("topleft") == (-30, -10)


class TestParseTsv:
    """剪贴板里拿到的是 Excel 那套 TSV —— 只拆，不判断表头在第几行。"""

    def test_header_and_rows(self):
        header, rows = parse_tsv("月份\t金额\n1月\t100\n2月\t200")
        assert header == ["月份", "金额"]
        assert rows == [["1月", "100"], ["2月", "200"]]

    def test_blank_lines_dropped(self):
        header, rows = parse_tsv("月份\t金额\n\n1月\t100\n\n")
        assert header == ["月份", "金额"]
        assert rows == [["1月", "100"]]

    def test_crlf(self):
        header, rows = parse_tsv("a\tb\r\n1\t2\r\n")
        assert header == ["a", "b"]
        assert rows == [["1", "2"]]

    def test_empty(self):
        assert parse_tsv("") == ([], [])
        assert parse_tsv("\n\n") == ([], [])

    def test_no_header_mode(self):
        header, rows = parse_tsv("1\t2\n3\t4", has_header=False)
        assert header == []
        assert rows == [["1", "2"], ["3", "4"]]

    def test_ragged_rows_are_kept(self):
        "列数不齐**照样留着** —— 那是脏数据，交给后面的管线去判断，"
        header, rows = parse_tsv("a\tb\tc\n1\t2\n3\t4\t5\t6")
        assert rows == [["1", "2"], ["3", "4", "5", "6"]]

    def test_tsv_to_grid_round_trip(self):
        header, rows = parse_tsv("月份\t金额\n1月\t100")
        assert tsv_to_grid(header, rows) == [["月份", "金额"], ["1月", "100"]]
        assert tsv_to_grid([], rows) == rows


class TestToSourceData:
    """剪贴板文本 → SourceData（接进现有管线的那一层）。"""

    def test_builds_source_data_with_row_numbers(self):
        from app.services.webflow.source import to_source_data

        source = to_source_data("月份\t金额\n1月\t100\n2月\t200")
        assert source.header == ["月份", "金额"]

        assert source.rows == [(2, ["1月", "100"]), (3, ["2月", "200"])]

    def test_headers_are_normalized_like_other_platforms(self):
        """空表头补「列X」、重名加后缀 —— 不规整会串列，字段映射直接失效。"""
        from app.services.webflow.source import to_source_data

        source = to_source_data("月份\t\t月份\n1月\t2\t3")
        assert source.header == ["月份", "列B", "月份_1"]

    def test_empty_clipboard_raises_instead_of_empty_table(self):
        "**取不到必须报错，不能给空表** —— 空表进库下游看起来「今天没数据」，"
        from app.services.sources.base import SourceError
        from app.services.webflow.source import to_source_data

        with pytest.raises(SourceError) as exc:
            to_source_data("")
        assert "登录" in (exc.value.hint or "")

    def test_header_only_still_usable(self):
        from app.services.webflow.source import to_source_data

        source = to_source_data("月份\t金额")
        assert source.header == ["月份", "金额"]
        assert source.rows == []

    def test_ragged_rows_survive(self):
        from app.services.webflow.source import to_source_data

        source = to_source_data("a\tb\tc\n1\t2\n3\t4\t5\t6")
        assert [row for _, row in source.rows] == [["1", "2"], ["3", "4", "5", "6"]]


class TestRowsEnvelope:
    """``SourceData`` → 任务向导的信封。**纯函数**，不碰浏览器。"""

    def _envelope(self, text: str, cfg: dict | None = None, limit: int | None = None):
        from app.services.webflow.preview import rows_envelope
        from app.services.webflow.source import to_source_data

        return rows_envelope(
            to_source_data(text),
            sheet_id="https://www.kdocs.cn/l/xxxx",
            sheet_name="www.kdocs.cn",
            cfg=cfg,
            limit=limit,
        )

    def test_shape_matches_wizard(self):
        out = self._envelope("月份\t金额\n1月\t100\n2月\t200")
        assert out["ok"] is True
        assert out["header"] == ["月份", "金额"]

        assert out["raw_rows"] == [["1月", "100"], ["2月", "200"]]
        assert [row[0] for row in out["rows"]] == ["1月", "2月"]

        assert out["row_numbers"] == [2, 3]

        assert out["raw_grid"][0] == ["月份", "金额"]
        assert out["raw_origin"] == {"row": 1, "col": "A"}

        for key in ("column_stats", "suggested_types", "suggested_transforms", "sheet_id"):
            assert key in out

    def test_skip_words_mark_rows_instead_of_dropping_them(self):
        """命中关键词的行**只标记不删** —— 用户要看得见，也才能改主意。"""
        out = self._envelope("月份\t金额\n1月\t100\n月度总计\t300", cfg={"skip_words": ["总计"]})
        assert out["total_preview"] == 2
        assert out["skipped_row_numbers"] == [3]

    def test_rules_replace_cells_like_the_loader(self):
        out = self._envelope(
            "月份\t金额\n1月\t-\n2月\t200",
            cfg={"rules": [{"column": "金额", "match": "-", "action": "replace", "value": "0"}]},
        )
        assert out["raw_rows"][0] == ["1月", "0"]

    def test_limit_caps_rows(self):
        out = self._envelope("月份\n1\n2\n3\n4", limit=2)
        assert out["total_preview"] == 2
        assert out["row_numbers"] == [2, 3]

    def test_unit_like_text_does_not_crash_the_envelope(self):
        "一列里有 `负责人`（以单位字 `人` 结尾、前面不是数字）时，"
        out = self._envelope("姓名\t数量\n负责人\t5 个")
        assert out["ok"] is True
        assert out["suggested_transforms"] == [None, "strip_unit"]


class TestWebRecipe:
    def test_default_recipe_matches_what_was_verified(self):
        from app.services.webflow.flow import parse_flow
        from app.services.webflow.source import DEFAULT_WPS_ELEMENTS, DEFAULT_WPS_STEPS

        actions = [s.action for s in parse_flow(DEFAULT_WPS_STEPS)]
        assert actions[0] == "wait"
        assert "if" in actions and "endif" in actions
        assert "select_used_range" in actions

        assert "协作邀请弹窗关闭按钮" in DEFAULT_WPS_ELEMENTS


class TestFindBrowser:
    def test_explicit_missing_path_says_where_to_configure(self):
        with pytest.raises(CdpError) as exc:
            find_browser(r"C:\nope\nope.exe")
        assert "不存在" in str(exc.value)

    def test_missing_browser_message_is_actionable(self):
        """找不到浏览器时**要说清怎么办** —— 不然只是一句「没找到」。"""
        from app.services.webflow import cdp

        original = cdp._CANDIDATES
        cdp._CANDIDATES = ("/definitely/not/here",)
        try:
            with pytest.raises(CdpError) as exc:
                find_browser()
            assert "DOCSYNC_BROWSER" in str(exc.value)
        finally:
            cdp._CANDIDATES = original


class TestClearStaleLocks:
    "启动前要清掉上次残留的端口文件与单实例锁。"

    def test_removes_port_file_and_singleton_links(self, tmp_path):
        from app.services.webflow.cdp import _clear_stale_locks

        (tmp_path / "DevToolsActivePort").write_text("12345\n/devtools/browser/x\n")
        (tmp_path / "SingletonLock").write_text("dead-host-42")
        (tmp_path / "SingletonCookie").write_text("123456")
        (tmp_path / "SingletonSocket").write_text("/tmp/gone/SingletonSocket")

        (tmp_path / "Preferences").write_text("keep me")

        _clear_stale_locks(str(tmp_path))

        names = {p.name for p in tmp_path.iterdir()}
        assert "DevToolsActivePort" not in names
        assert "SingletonLock" not in names
        assert "SingletonCookie" not in names
        assert "SingletonSocket" not in names
        assert (tmp_path / "Preferences").read_text() == "keep me"

    def test_missing_dir_is_fine(self, tmp_path):
        from app.services.webflow.cdp import _clear_stale_locks

        _clear_stale_locks(str(tmp_path / "does-not-exist"))


class TestXpathLiteral:
    """工作表名要能安全塞进 XPath —— 用户起的名字里可能带引号。"""

    def test_plain(self):
        from app.services.webflow.actions import xpath_literal

        assert xpath_literal("T+1导出") == '"T+1导出"'

    def test_single_quote_only(self):
        from app.services.webflow.actions import xpath_literal

        assert xpath_literal("it's") == '"it\'s"'

    def test_double_quote_only(self):
        from app.services.webflow.actions import xpath_literal

        assert xpath_literal('say "hi"') == "'say \"hi\"'"

    def test_both_quotes_use_concat(self):
        from app.services.webflow.actions import xpath_literal

        out = xpath_literal("a\"b'c")
        assert out.startswith("concat(")

        assert "concat(" in out and '"' in out and "'" in out


class TestApplyLayout:
    """整块网格 → SourceData：表头行 / 数据起始行按配置切。"""

    _WITH_TITLE = "标题\n月份\t金额\n1月\t100\n2月\t200"

    def test_default_is_first_row_header(self):
        from app.services.webflow.source import apply_layout, to_grid

        out = apply_layout(to_grid("月份\t金额\n1月\t100\n2月\t200"))
        assert out.header == ["月份", "金额"]

        assert out.rows == [(2, ["1月", "100"]), (3, ["2月", "200"])]

    def test_header_row_from_cfg(self):
        """标题行占第 1 行时，把表头指到第 2 行 —— 这就是「读取控件」的作用。"""
        from app.services.webflow.source import apply_layout, to_grid

        out = apply_layout(to_grid(self._WITH_TITLE), {"header_row": 2, "data_start_row": 3})
        assert out.header == ["月份", "金额"]
        assert out.rows == [(3, ["1月", "100"]), (4, ["2月", "200"])]

    def test_only_vertical_supported(self):
        """横向 / 交叉表还没做 —— 必须明确报错，不能猜（猜错就是静默写错数据）。"""
        import pytest

        from app.services.sources.base import SourceError
        from app.services.webflow.source import apply_layout, to_grid

        with pytest.raises(SourceError) as exc:
            apply_layout(to_grid(self._WITH_TITLE), {"orientation": "horizontal"})
        assert "纵向" in str(exc.value)

    def test_header_row_out_of_range_reports_clearly(self):
        import pytest

        from app.services.sources.base import SourceError
        from app.services.webflow.source import apply_layout, to_grid

        with pytest.raises(SourceError) as exc:
            apply_layout(to_grid("a\tb"), {"header_row": 9})
        assert "表头在第 9 行" in str(exc.value)


class TestWpsLoginSessions:
    """扫码登录的会话表：没有活会话时必须告诉前端「重新开一个」，不能抛。"""

    async def test_poll_without_session_is_expired(self):
        from app.services.webflow import login as svc

        class _App:
            id = 4242

        svc._SESSIONS.pop(4242, None)
        assert await svc.poll_login(_App()) == {"status": "expired"}

    async def test_close_without_session_is_safe(self):
        from app.services.webflow import login as svc

        class _App:
            id = 4243

        svc._SESSIONS.pop(4243, None)
        await svc.close_login(_App())
        assert 4243 not in svc._SESSIONS
