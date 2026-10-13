"脏表验收：30 种真实会遇到的脏法，跑一遍整条管线，断言系统该有的行为。"

from __future__ import annotations

from typing import Any

from app.services.normalize.coercions import infer_transform, infer_type
from app.services.normalize.headers import compose_header, infer_header_row, normalize_headers
from app.services.normalize.rowfilter import drop_skipped_rows
from app.services.normalize.rules import apply_rules
from app.services.normalize.splitter import detect_split_columns, expand_rows, separator_indexes
from app.services.runner.prepare import build_specs, prepare_rows
from app.services.sources.data import SourceData
from app.services.sources.layout import detect_layout


def _source(grid: list[list[Any]], header_row: int = 1, data_start: int | None = None) -> SourceData:
    """把一块网格拼成 SourceData（跟平台读进来之后的形状一致）。"""
    start = data_start or header_row + 1
    header = normalize_headers(grid[header_row - 1], width=len(grid[header_row - 1]))
    rows = [(start + i, list(row)) for i, row in enumerate(grid[start - 1 :])]
    return SourceData(header=header, rows=rows)


def _norm(cells: list[Any]) -> list[Any]:
    return [None if (c is None or str(c).strip() == "") else c for c in cells]


def _body(prepared: Any) -> list[list[Any]]:
    """prepare 之后的「数据本体」部分（去掉来源子表和指纹那几列）。"""
    width = len(prepared.columns) - len(prepared.insert_only or []) - 1
    return [list(row[1][:width]) for row in _rows(prepared)]


def _rows(prepared: Any) -> list[tuple]:
    """prepare_rows 的产物是 dict 行 —— 这里还原成「按目标列顺序的列表」方便断言。"""
    cols = prepared.columns
    out = []
    for item in prepared.rows:
        out.append((0, [item.get(c) for c in cols]))
    return out


def test_01_title_above_header():
    "第 1 行是标题（只占一格），表头在第 3 行 —— 标题行不能被当表头。"
    grid = [
        ["2026 年经营数据（内部）", None, None],
        [None, None, None],
        ["月份", "科目", "金额"],
        ["1月", "收入", "100"],
        ["2月", "收入", "200"],
    ]
    assert infer_header_row(grid, start_row=1) == 3
    layout = detect_layout(grid, start_row=1)
    assert layout.orientation == "vertical"
    assert layout.header_row == 3
    assert layout.data_start_row == 4


def test_02_blank_rows_inside_header_area():
    """表头上方有整行空白 —— 空行不该被当表头（宽度门槛把它挡掉）。"""
    grid = [
        [None, None, None],
        ["", "", ""],
        ["月份", "科目", "金额"],
        ["1月", "收入", "100"],
    ]
    assert infer_header_row(grid, start_row=1) == 3


def test_03_header_not_row_one_with_notes():
    """表头前是「单位：元」「数据截止 9/30」这类说明行。"""
    grid = [
        ["单位：元", None, None, None],
        ["数据截止 2026-09-30", None, None, None],
        ["月份", "科目", "金额", "备注"],
        ["1月", "收入", "100", "正常"],
    ]
    assert infer_header_row(grid, start_row=1) == 3


def test_04_two_row_header_dimension_then_months():
    "**表头分段**：前面维度取第 1 行、后面月份取第 2 行。"
    grid = [
        ["店铺", "国家", "品类", "单品", "2026年", None, None],
        [None, None, None, None, "1月", "2月", "3月"],
        ["SHOP1", "US", "3C", "A1", "1200", "1350", "980"],
        ["SHOP2", "JP", "家居", "B2", "800", "900", "1100"],
    ]
    segments = [
        {"col_start": "A", "col_end": "D", "row": 1},
        {"col_start": "E", "row": 2},
    ]
    values, max_row = compose_header(grid, segments, first_row=1, width=7)
    assert values == ["店铺", "国家", "品类", "单品", "1月", "2月", "3月"]
    assert "2026年" not in values
    assert max_row == 2


def test_05_header_segment_window_offset():
    "只读 E 列往右时，段里写「E」指的是**窗口第一格**，不是原表第 5 格。"
    window = [
        ["基准", "单位", "2026年"],
        [None, None, "1月"],
    ]
    segments = [{"col_start": "E", "col_end": "F", "row": 1}, {"col_start": "G", "row": 2}]
    values, max_row = compose_header(window, segments, first_row=1, width=3, col_start_index=4)
    assert values == ["基准", "单位", "1月"]
    assert max_row == 2


def test_06_blank_header_cell_gets_placeholder():
    "表头中间有个空格子 —— 补成「列D」而不是留空。"
    header = normalize_headers(["月份", "", "金额", None], width=4)
    assert header == ["月份", "列B", "金额", "列D"]


def test_07_duplicate_header_names_get_suffix():
    """两个列都叫「金额」—— 重名的加后缀，否则按名字取值会拿错一列。"""
    header = normalize_headers(["月份", "金额", "金额"], width=3)
    assert header == ["月份", "金额", "金额_1"]


def test_08_header_with_units_and_spaces():
    """表头带单位、前后有空格、全角括号 —— 只去装饰，不改字面。"""
    header = normalize_headers([" 月份 ", "金额（元）", "数量*"], width=3)
    assert header == ["月份", "金额（元）", "数量*"]


def test_09_no_header_at_all_falls_back():
    "整块都是数据、没有表头 —— 返回第 1 行当表头（**不猜**），"
    grid = [["1", "2", "3"], ["4", "5", "6"]]
    header_row = infer_header_row(grid, start_row=1)
    assert header_row == 1


def test_10_wide_data_row_does_not_win():
    """数据比表头「更满」时，不能把数据行当表头（历史上出过这个故障）。"""
    grid = [
        ["部门销售", None, None, None, None, None],
        ["部门", "一月", "二月", "三月", "四月", "五月"],
        [1, 2, 3, 4, 5, 6],
    ]
    assert infer_header_row(grid, start_row=1) == 2


def test_11_total_row_by_keyword():
    "「月度总计」这种行 —— 子串匹配要命中（表里不会只写「总计」两个字）。"
    rows = [(1, ["1月", "收入", "100"]), (2, ["1月", "月度总计", "100"])]
    kept, dropped = drop_skipped_rows(rows, skip_words=["总计"])
    assert len(kept) == 1
    assert kept[0][0] == 1
    assert any("2" in note for note in dropped)


def test_12_total_row_by_row_number():
    """按**行号**点掉 —— 小计行的写法每月都在变，光靠关键词不够。"""
    rows = [(1, ["a"]), (2, ["b"]), (3, ["c"])]
    kept, _ = drop_skipped_rows(rows, skip_rows={2})
    assert [r[0] for r in kept] == [1, 3]


def test_13_keyword_in_any_column():
    """关键词出现在哪一列都算 —— 不限定列时全行扫。"""
    rows = [(1, ["合计", "x"]), (2, ["y", "备注：合计口径见附注"])]
    kept, _ = drop_skipped_rows(rows, skip_words=["合计"])
    assert kept == []


def test_14_replaced_placeholder_with_zero():
    "`-` / `N/A` 当空用 —— 规则把它换成 0，而不是留成文本。"
    rows = [["1月", "收入", "-", "正常"], ["2月", "收入", "N/A", ""]]
    rules = [
        {"column": "金额", "match": "-", "action": "replace", "value": "0"},
        {"column": "金额", "match": "N/A", "action": "replace", "value": "0"},
    ]
    result = apply_rules(rows, ["月份", "科目", "金额", "备注"], rules, first_row=1)
    assert result.rows[0][2] == "0"
    assert result.rows[1][2] == "0"
    assert result.replaced_cells == 2


def test_15_skip_beats_replace():
    "同一行既该跳过、又有格要替换 —— 跳过优先。"
    rows = [["合计", "-", "-"]]
    rules = [
        {"match": "合计", "action": "skip"},
        {"match": "-", "action": "replace", "value": "0"},
    ]
    result = apply_rules(rows, ["a", "b", "c"], rules, first_row=3)
    assert result.rows == []
    assert result.skipped_rows == [3]
    assert result.replaced_cells == 0


def test_16_half_filled_rule_is_dropped_not_fatal():
    """界面上刚点「加一条」还没填完的半截规则 —— 丢掉，不能让整表读不出来。"""
    rows = [["1月", "收入", "100"]]
    rules = [{"column": "金额", "match": "", "action": "replace", "value": "0"}, {"match": "总计"}]
    result = apply_rules(rows, ["月份", "科目", "金额"], rules, first_row=1)
    assert result.rows == [["1月", "收入", "100"]]


def test_17_split_two_codes():
    """`9158xxxx,9262xxxx` —— 两个单号，要拆成两行。"""
    rows = [["订单1", "9158,9262"], ["订单2", "9270,9281"], ["订单3", "9300,9310"]]
    detected = detect_split_columns(["订单号", "单品编码"], rows)
    assert detected == {1: ",，"}


def test_18_thousand_separator_is_not_split():
    """`1,234.56` 是**一个数**，不是两个值 —— 拆了金额就错了。"""
    rows = [["1,234.56"], ["2,345.67"], ["3,456.78"]]
    assert detect_split_columns(["金额"], rows) == {}


def test_19_inconsistent_parts_not_split():
    """份数不一致就不拆 —— 那是备注里的逗号，不是多值。"""
    rows = [["a,b"], ["今天下雨，没发货"], ["c,d,e"]]
    assert detect_split_columns(["备注"], rows) == {}


def test_20_explicit_split_expands_and_keeps_others():
    """显式指定拆哪列时：按分隔符展开，其它列原样复制。"""
    rows = [["A", "x,y", "1"]]
    separators = separator_indexes(["品名", "编码", "数量"], {"编码": "comma"})
    out = expand_rows(rows, separators)
    assert out == [["A", "x", "1"], ["A", "y", "1"]]


def test_21_leading_zero_kept():
    """单号 `0012` 不能变成 12 —— 前导零是有意义的。"""
    assert infer_type(["0012", "0034"]) == "text"


def test_22_mixed_percent_detected_as_percent():
    "同一列里 0.15 和 15% 混着写 —— 要判成百分比整列换算。"
    assert infer_transform([0.15, "15%", 0.2, "18%"]) == "percent"
    assert infer_transform([0.15, 0.2]) is None


def test_23_number_with_unit_is_suggested():
    "`5 个`、`12 台` —— 去单位留数字。**这是验收时发现的缺口，现在补上了。**"
    assert infer_transform(["5 个", "12 台", "3 个"]) == "strip_unit"
    assert infer_type(["5 个", "12 台"]) == "text"


def test_23b_unit_number_never_eats_dates_or_percent():
    "**这条比上一条重要**：单位判断不能误伤日期和百分比。"
    from app.services.normalize.coercions import to_unit_number

    assert to_unit_number("5 个") == 5
    assert to_unit_number("12 台") == 12
    assert to_unit_number("1,234.56 元") == 1234.56

    assert to_unit_number("1月") is None
    assert to_unit_number("2026年") is None
    assert to_unit_number("3 日") is None
    assert to_unit_number("15:30") is None

    assert to_unit_number("15%") is None

    assert to_unit_number("abc") is None
    assert to_unit_number("个") is None
    assert to_unit_number("") is None

    assert infer_transform(["1月", "2月", "3月"]) != "strip_unit"


def test_23c_infer_transform_never_raises_on_unit_like_text():
    "以单位字结尾、但前面不是数字的格子（`负责人`）**不能把预览带崩**。"

    assert infer_transform(["负责人", "负责人", "负责人"]) is None
    assert infer_transform(["5 个", "负责人"]) != "strip_unit"

    assert infer_transform(["5 个", "12 台"]) == "strip_unit"

    from app.services.normalize.coercions import ConvertError, to_unit_number

    try:
        to_unit_number("负责人")
    except ConvertError:
        pass
    else:  # pragma: no cover
        raise AssertionError("to_unit_number 对『负责人』应当抛 ConvertError（写库时算异常格）")


def test_24_date_variants():
    """多种日期写法都要认成日期（面板上要显示成日期列）。"""
    assert infer_type(["2026-01-05", "2026/01/06", "2026年1月7日"]) == "date"


def test_25_invisible_chars_cleaned():
    """零宽空格、BOM 混在值里 —— 清掉，否则「看起来一样」的两个值不相等。"""
    from app.services.normalize.coercions import clean_text

    assert clean_text("收\u200b入\ufeff") == "收入"


def test_26_cell_newline_becomes_space():
    """格内换行（多行填写）—— 归一成空格，别把一行数据拆断。"""
    from app.services.normalize.coercions import clean_text

    assert clean_text("第一行\r\n第二行") == "第一行 第二行"


def test_27_empty_column_is_dropped_by_suggestion():
    """整列是空的 —— 体检结果标成 drop，默认不勾。"""
    from app.services.sources.preview_util import profiles

    result = profiles(["月份", "空列"], [["1月", None], ["2月", None]])
    by_name = {item["name"]: item for item in result}
    assert by_name["空列"]["is_empty_column"] is True
    assert by_name["空列"]["suggestion"] == "drop"
    assert by_name["月份"]["suggestion"] != "drop"


def test_28_required_empty_drops_row():
    """必填列为空的行 —— 丢掉并**记账**（坏行留证），不能静默少一行。"""
    grid = [["月份", "金额"], ["1月", "100"], ["2月", None]]
    prepared = prepare_rows(
        _source(grid),
        build_specs(
            [
                {"source": "月份", "target": "月份", "type": "text"},
                {"source": "金额", "target": "金额", "type": "float", "required": True},
            ]
        ),
    )
    assert len(prepared.rows) == 1
    assert prepared.bad_rows >= 1


def test_29_upsert_fingerprint_is_stable():
    """同样的行跑两次，指纹一样 —— 靠它跳过没变的行（不然每次全量重写）。"""
    grid = [["月份", "金额"], ["1月", "100"]]
    specs = [
        {"source": "月份", "target": "月份", "type": "text"},
        {"source": "金额", "target": "金额", "type": "float"},
    ]
    first = prepare_rows(_source(grid), build_specs(specs))
    second = prepare_rows(_source(grid), build_specs(specs))
    key = first.fingerprint_column
    assert key
    assert first.rows[0].get(key) == second.rows[0].get(key)


def test_30_row_count_and_keys_survive_combined_dirt():
    "**混合脏**：表头前有标题、中间有小计行、某格写了两个值、空值用 `-`。"
    grid = [
        ["💡 月度经营表", None, None],
        ["月份", "科目", "金额"],
        ["1月", "收入", "100"],
        ["1月", "合计", "100"],
        ["2月", "收入,支出", "-"],
    ]
    source = _source(grid, header_row=2)
    kept, dropped = drop_skipped_rows(source.rows, skip_words=["合计"])
    assert len(kept) == 2
    assert len(dropped) == 1

    separators = separator_indexes(source.header, {"科目": "comma"})
    expanded = []
    for row_no, values in kept:
        for piece in expand_rows([list(values)], separators):
            expanded.append((row_no, piece))
    assert len(expanded) == 3
    assert [r[1][1] for r in expanded] == ["收入", "收入", "支出"]

    rules = [{"column": "金额", "match": "-", "action": "replace", "value": "0"}]
    fixed = apply_rules([list(r[1]) for r in expanded], source.header, rules, first_row=expanded[0][0])
    assert fixed.rows[-1][2] == "0"

    assert fixed.replaced_cells == 2
