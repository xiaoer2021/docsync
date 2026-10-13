from app.models.run import RUN_PARTIAL, RUN_SUCCESS
from app.services.runner.safety import (
    assess_write_safety,
    run_status,
    validate_quality_policy,
)


def assess(**overrides):
    params = dict(
        mode="full_replace",
        source_rows=1000,
        output_rows=1000,
        previous_rows=1000,
        row_limited=False,
        incremental=False,
        source_cap_reached=False,
        skipped_required=0,
        critical_cells=0,
        retyped_columns=0,
    )
    params.update(overrides)
    return assess_write_safety(**params)


def test_clean_full_replace_is_allowed():
    assert assess().can_write


def test_full_replace_stops_on_incomplete_or_dirty_source():
    result = assess(row_limited=True, skipped_required=2, critical_cells=3, retyped_columns=1)
    assert not result.can_write
    assert len(result.blockers) == 4


def test_ordinary_dirty_cells_do_not_block_full_replace():
    "普通列的异常格不该拦整表重写 —— 原文搬进「原始值_未识别」，数据没丢。"
    assert assess(critical_cells=0).can_write


def test_critical_column_cells_still_block():
    """关键列（主键/必填）的身份证坏了，就该停下 —— 清空重写风险太大。"""
    result = assess(critical_cells=3)
    assert not result.can_write
    assert any("关键格" in b for b in result.blockers)


def test_full_replace_stops_on_large_drop_unless_explicitly_disabled():
    assert not assess(source_rows=100, output_rows=100).can_write
    assert assess(source_rows=100, output_rows=100, minimum_row_ratio=0).can_write


def test_partition_replace_rejects_incomplete_source_without_global_ratio():
    assert not assess(mode="replace_partition", incremental=True).can_write
    assert assess(mode="replace_partition", source_rows=100, output_rows=100).can_write


def test_non_destructive_modes_do_not_apply_overwrite_gate():
    assert assess(mode="upsert", critical_cells=4, source_rows=10, output_rows=10).can_write


def test_quality_policy_requires_numeric_notes_to_use_float_and_text_note_column():
    columns = [{"target": "金额", "type": "float"}, {"target": "备注", "type": "text"}]
    assert validate_quality_policy(columns, {"numeric_note_columns": ["金额"], "note_column": "备注"}) is None
    assert validate_quality_policy(columns, {"numeric_note_columns": ["备注"]})
    assert validate_quality_policy(columns, {"numeric_note_columns": ["金额"], "note_column": "金额"})
    assert validate_quality_policy(columns, {"minimum_row_ratio": 2})


def status(**overrides):
    params = dict(failed_rows=0, retyped_columns=0, blockers=())
    params.update(overrides)
    return run_status(**params)


def test_clean_run_is_success():
    assert status() == RUN_SUCCESS


def test_handled_dirty_cells_still_count_as_success():
    "普通列的异常格**不该**把执行标成「部分成功」。"
    assert status() == RUN_SUCCESS


def test_skipped_rows_make_it_partial():
    assert status(failed_rows=2) == RUN_PARTIAL


def test_auto_retyped_columns_make_it_partial():
    """列类型被自动改过说明配置写错了，值得标黄。"""
    assert status(retyped_columns=1) == RUN_PARTIAL


def test_formula_error_cells_do_not_make_it_partial():
    "源表里的 `#DIV/0!` 那种格子现在按 0 写入，数据是完整的。"
    assert status() == RUN_SUCCESS


def test_safety_blockers_make_it_partial():
    assert status(blockers=("本次只读取了部分源数据",)) == RUN_PARTIAL
