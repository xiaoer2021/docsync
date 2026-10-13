"""执行记录不应把数据库批量参数回显到页面。"""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.api.v1.runs import _public_log, _to_out
from app.models.run import DdRun
from app.services.runner.orchestrator import safe_run_error


def test_sql_error_hides_bound_parameters():
    error = OperationalError("INSERT INTO t VALUES (:v)", {"v": "private-value"}, Exception("bad type"))
    message = safe_run_error(error)
    assert "private-value" not in message
    assert "INSERT INTO" not in message
    run = DdRun(
        id=1,
        task_id=1,
        trigger_type="manual",
        status="failed",
        error_message=str(error),
        rows_read=0,
        rows_written=0,
        rows_inserted=0,
        rows_updated=0,
        rows_unchanged=0,
        rows_failed=0,
        batches=0,
        dry_run=False,
    )
    assert "private-value" not in (_to_out(run).error_message or "")
    assert "private-value" not in _public_log(f"执行失败：{error}")
