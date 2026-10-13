"列的变化检测：新增 / 消失 / **疑似改名** / **同一列名但性质变了**。"

from __future__ import annotations

from app.services.doc_registry import column_drift_text, drift_in_kind, guess_renames


class TestDriftInKind:
    def test_number_column_became_text(self):
        """「数量」原来记件数，后来有人写成「约 10 件」。"""
        notes = drift_in_kind({"数量": "数值"}, {"数量": "文本"})
        assert len(notes) == 1
        assert "数量" in notes[0] and "数值" in notes[0] and "文本" in notes[0]

    def test_unchanged_is_not_reported(self):
        assert drift_in_kind({"数量": "数值"}, {"数量": "数值"}) == []

    def test_new_column_is_not_drift(self):
        assert drift_in_kind({}, {"数量": "数值"}) == []

    def test_column_missing_before_is_not_drift(self):
        """上次是空的（没判出性质），这次有了也不算漂移。"""
        assert drift_in_kind({"备注": ""}, {"备注": "文本"}) == []

    def test_removed_column_is_not_drift(self):
        assert drift_in_kind({"数量": "数值"}, {}) == []

    def test_int_to_float_is_not_drift(self):
        """都归到同一个家族了，所以整数变小不会误报。"""
        assert drift_in_kind({"数量": "数值"}, {"数量": "数值"}) == []


class TestGuessRenames:
    def test_nearby_same_kind_is_a_rename(self):
        before = ["产品编码", "数量", "单价"]
        after = ["产品编码", "件数", "单价"]
        notes = guess_renames(before, after, {"数量": "数值"}, {"件数": "数值"})
        assert notes == ["数量 → 件数"]

    def test_different_kind_is_not_a_rename(self):
        """「订单号」（数值）不会变成「备注」（文本）—— 性质不一致就不敢配。"""
        before = ["订单号", "金额"]
        after = ["备注", "金额"]
        notes = guess_renames(before, after, {"订单号": "文本"}, {"备注": "文本"})

        assert notes == ["订单号 → 备注"]

    def test_kind_mismatch_blocks_pairing(self):
        before = ["订单号", "金额"]
        after = ["备注", "金额"]
        assert guess_renames(before, after, {"订单号": "数值"}, {"备注": "文本"}) == []

    def test_far_apart_is_not_a_rename(self):
        """位置差太远就不配 —— 在线表格插一列会让后面整体位移，纯按位置配会配错。"""
        before = ["甲", "乙", "丙", "丁", "戊", "己"]
        after = ["乙", "丙", "丁", "戊", "己", "庚"]

        assert guess_renames(before, after, {"甲": "文本"}, {"庚": "文本"}) == []

    def test_pure_addition_is_not_a_rename(self):
        before = ["甲", "乙"]
        after = ["甲", "乙", "丙"]
        assert guess_renames(before, after, {}, {"丙": "文本"}) == []

    def test_one_added_column_used_once(self):
        """一个新增列不能同时配给两个消失列。"""
        before = ["甲", "乙"]
        after = ["丙"]
        notes = guess_renames(before, after, {"甲": "文本", "乙": "文本"}, {"丙": "文本"})
        assert len(notes) == 1


class TestDriftText:
    def test_plain_add_remove(self):
        assert column_drift_text(["新列"], ["旧列"]) == "新增 新列；消失 旧列"

    def test_rename_is_called_a_guess(self):
        """改名只是猜测，措辞上必须带「疑似」—— 用户要自己去确认。"""
        text = column_drift_text([], [], renames=["数量 → 件数"])
        assert text is not None and "疑似改名" in text

    def test_kind_shift_is_called_out_loudly(self):
        text = column_drift_text([], [], shifted=["数量（数值 → 文本）"])
        assert text is not None
        assert "性质变了" in text

    def test_nothing_changed(self):
        assert column_drift_text([], []) is None
