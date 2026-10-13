"写入统计的累加规则。"

from __future__ import annotations

from app.services.loader.writer import WriteStats


class TestMerge:
    def test_read_is_not_doubled(self):
        """核心：合并之后「读到」还是源文档那个数，不能翻倍。"""
        stats = WriteStats(read=2152)
        stats.merge(WriteStats(read=2152, inserted=2146, written=2150))
        assert stats.read == 2152, "读到行数被加了两遍"

    def test_other_counters_accumulate(self):
        stats = WriteStats(read=100)
        stats.merge(WriteStats(inserted=60, updated=30, unchanged=10, written=100, batches=3))
        assert (stats.inserted, stats.updated, stats.unchanged) == (60, 30, 10)
        assert stats.written == 100
        assert stats.batches == 3

    def test_merge_is_additive_for_batches(self):
        stats = WriteStats()
        stats.merge(WriteStats(batches=5))
        stats.merge(WriteStats(batches=7))
        assert stats.batches == 12

    def test_duplicates_and_deleted_accumulate(self):
        stats = WriteStats()
        stats.merge(WriteStats(duplicates=91, deleted=3))
        stats.merge(WriteStats(duplicates=9, deleted=2))
        assert stats.duplicates == 100
        assert stats.deleted == 5

    def test_issues_are_concatenated(self):
        stats = WriteStats()
        stats.merge(WriteStats(issues=[{"a": 1}]))
        stats.merge(WriteStats(issues=[{"b": 2}]))
        assert stats.issues == [{"a": 1}, {"b": 2}]

    def test_merge_of_empty_stats_changes_nothing(self):
        stats = WriteStats(read=42, inserted=7)
        stats.merge(WriteStats())
        assert stats.read == 42
        assert stats.inserted == 7
