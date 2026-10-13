"同名不同义：两个子表有同名的列，但其实是两种东西。"

from __future__ import annotations

from app.services.sources.merge_check import (
    family_of,
    find_same_name_conflicts,
    sample_row,
)

HEADER = ["产品编码", "数量", "备注"]
NAMES = {"s1": "店铺1", "s2": "店铺2"}


class TestFamilyOf:
    def test_numbers(self):
        assert family_of([1, 2, 3, 4]) == "数值"

    def test_numeric_strings(self):
        assert family_of(["1", "2", "3"]) == "数值"

    def test_text(self):
        assert family_of(["杯子", "碟子", "托盘"]) == "文本"

    def test_dates(self):
        assert family_of(["2026-10-01", "2026-10-02", "2026-10-03"]) == "日期"

    def test_too_few_samples_is_unknown(self):
        """样本太少就不判 —— 那样猜类型本身就是碰运气，会带来误报。"""
        assert family_of([1, 2]) == ""
        assert family_of([]) == ""

    def test_int_and_float_same_family(self):
        """整数和小数是同一种东西，不能算冲突。"""
        assert family_of([1, 2, 3]) == family_of([1.5, 2.5, 3.5])


class TestFindConflicts:
    def test_same_kind_is_not_a_conflict(self):
        """两边都是数字 —— 正常的合表，不该报。"""
        samples = {
            "s1": {1: [1, 2, 3]},
            "s2": {1: [4, 5, 6]},
        }
        assert find_same_name_conflicts(samples, HEADER, NAMES) == []

    def test_disjoint_text_values_are_not_a_conflict(self):
        """**这条很关键**：两个店铺的店铺名不重叠，那是正常的，不能误报。"""
        samples = {
            "s1": {2: ["天猫订单", "天猫退款", "天猫咨询"]},
            "s2": {2: ["京东订单", "京东退款", "京东咨询"]},
        }
        assert find_same_name_conflicts(samples, HEADER, NAMES) == []

    def test_number_vs_text_is_a_conflict(self):
        """一个记件数（数字）、一个记规格说明（文字）—— 合并就混了。"""
        samples = {
            "s1": {1: [10, 20, 30]},
            "s2": {1: ["约 10 件", "约 20 件", "约 30 件"]},
        }
        notes = find_same_name_conflicts(samples, HEADER, NAMES)
        assert len(notes) == 1
        assert "数量" in notes[0]
        assert "店铺1" in notes[0] and "店铺2" in notes[0]

        assert "改掉" in notes[0]

    def test_date_vs_text_is_a_conflict(self):
        samples = {
            "s1": {1: ["2026-10-01", "2026-10-02", "2026-10-03"]},
            "s2": {1: ["十月初", "十月中", "十月底"]},
        }
        assert len(find_same_name_conflicts(samples, HEADER, NAMES)) == 1

    def test_single_sheet_never_conflicts(self):
        """只有一张表，谈不上「同名不同义」。"""
        samples = {"s1": {1: [1, 2, 3]}}
        assert find_same_name_conflicts(samples, HEADER, NAMES) == []

    def test_one_side_empty_is_not_a_conflict(self):
        """一边是空的（某张表没填这一列）不算冲突 —— 那只是没数据。"""
        samples = {
            "s1": {1: [1, 2, 3]},
            "s2": {1: []},
        }
        assert find_same_name_conflicts(samples, HEADER, NAMES) == []

    def test_reports_each_conflicting_column_once(self):
        samples = {
            "s1": {1: [1, 2, 3], 2: ["A", "B", "C"]},
            "s2": {1: ["a", "b", "c"], 2: [1, 2, 3]},
        }
        assert len(find_same_name_conflicts(samples, HEADER, NAMES)) == 2


class TestSampleRow:
    def test_collects_by_column(self):
        bucket: dict = {}
        sample_row(bucket, "s1", ["A001", 10, None])
        sample_row(bucket, "s1", ["A002", 20, "备注"])
        assert bucket["s1"][0] == ["A001", "A002"]
        assert bucket["s1"][1] == [10, 20]

        assert bucket["s1"][2] == ["备注"]

    def test_separate_sheets_separate_buckets(self):
        bucket: dict = {}
        sample_row(bucket, "s1", [1])
        sample_row(bucket, "s2", [2])
        assert bucket["s1"][0] == [1]
        assert bucket["s2"][0] == [2]

    def test_limits_samples_per_column(self):
        bucket: dict = {}
        for i in range(200):
            sample_row(bucket, "s1", [i])
        assert len(bucket["s1"][0]) == 30, "采满就不再采，免得把整表都留在内存里"
