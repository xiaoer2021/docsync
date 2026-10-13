"表格摆法识别的测试。"

from __future__ import annotations

from app.services.sources.layout import detect_layout


def _month_row(start_month: int = 1, count: int = 12) -> list:
    """造一行 `1月 2月 …`，前面空 6 格（对应真实表里 A~F 列是空的）。"""
    return [None] * 6 + [f"{((start_month - 1 + i) % 12) + 1}月" for i in range(count)]


def test_month_cross_tab():
    """用户那张真实表：标题 + 左右两段表头 + 月份轴。"""
    rows = [
        [None, "💰 2026 全年销售目标计划表", None, None, None, None, None],
        [None, None, None, None, None, None, None],
        [None, "部门", "全年计划", "员工人数", "人均目标", "单月计划", "实际完成情况"],
        _month_row().copy(),
        [None, "A 部门", 800, 11, 72.7, 66.7, 45, 44, 51, 54, 57, 62, 70, 75, 80, 85, 90, 95],
        [None, "B 部门", 300, 6, 50, 25, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
    ]

    found = detect_layout(rows)

    assert found.orientation == "matrix"
    assert found.header_row == 4
    assert found.data_start_row == 5
    assert found.field_col == "B"
    assert found.date_start_col == "G"
    assert found.axis_kind == "month"
    assert found.axis_count == 12

    assert found.reasons
    assert "月份" in found.reasons[0]


def test_day_cross_tab():
    rows = [
        [None, "科目", "10-01", "10-02", "10-03", "10-04", "10-05"],
        [None, "实际销售额", 100, 120, 90, 110, 130],
        [None, "成本", 60, 70, 50, 65, 80],
    ]
    found = detect_layout(rows)
    assert found.orientation == "matrix"
    assert found.axis_kind == "day"
    assert found.date_start_col == "C"
    assert found.field_col == "B"
    assert found.header_row == 1


def test_vertical_table_stays_vertical():
    rows = [
        [None, "2026 年货品表", None],
        ["产品编码", "产品名", "数量"],
        ["A1", "杯子", 10],
        ["A2", "碟子", 20],
    ]
    found = detect_layout(rows)
    assert found.orientation == "vertical"
    assert found.header_row == 2
    assert found.data_start_row == 3


def test_two_months_is_not_a_cross_tab():
    """只有两个月不算 —— 那更可能是一张普通的两列表，不能因为「看着像」就换读法。"""
    rows = [
        ["部门", "1月", "2月"],
        ["A 部门", 10, 20],
        ["B 部门", 30, 40],
    ]
    found = detect_layout(rows)
    assert found.orientation == "vertical"


def test_empty_sheet():
    found = detect_layout([])
    assert found.orientation == "vertical"
    assert found.confidence == "low"


def test_axis_row_itself_is_the_header_row():
    """交叉表的「表头行」就是轴那一行 —— 跟 matrix 读法的约定对齐。"""
    rows = [
        [None, "科目", "10-01", "10-02", "10-03", "10-04"],
        [None, "销售额", 1, 2, 3, 4],
    ]
    found = detect_layout(rows)
    assert found.header_row == 1

    assert found.data_start_row == 2


def test_start_row_offset_respected():
    """探测区不一定从第 1 行开始 —— 行号要按实际位置算。"""
    rows = [
        [None, "科目", "10-01", "10-02", "10-03", "10-04"],
        [None, "销售额", 1, 2, 3, 4],
    ]
    found = detect_layout(rows, start_row=7)
    assert found.header_row == 7
    assert found.data_start_row == 8
