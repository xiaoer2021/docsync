"后置动作的触发口径。"

import pytest

from app.models.action import ON_ALWAYS, ON_FAILURE, ON_NOT_SUCCESS, ON_PARTIAL, ON_SUCCESS
from app.models.run import RUN_CANCELED, RUN_FAILED, RUN_PARTIAL, RUN_SUCCESS, RUN_TIMEOUT
from app.services.actions import _should_run

ALL_STATUSES = [RUN_SUCCESS, RUN_PARTIAL, RUN_FAILED, RUN_TIMEOUT, RUN_CANCELED]


def runs(mode: str) -> set[str]:
    return {s for s in ALL_STATUSES if _should_run(mode, s)}


def test_success_means_fully_successful_only():
    assert runs(ON_SUCCESS) == {RUN_SUCCESS}
    assert RUN_PARTIAL not in runs(ON_SUCCESS)


def test_partial_has_its_own_bucket():
    assert runs(ON_PARTIAL) == {RUN_PARTIAL}


def test_not_success_covers_partial_and_every_failure():
    assert runs(ON_NOT_SUCCESS) == {RUN_PARTIAL, RUN_FAILED, RUN_TIMEOUT, RUN_CANCELED}


def test_failure_excludes_partial():
    assert RUN_PARTIAL not in runs(ON_FAILURE)
    assert runs(ON_FAILURE) == {RUN_FAILED, RUN_TIMEOUT, RUN_CANCELED}


def test_always_covers_everything():
    assert runs(ON_ALWAYS) == set(ALL_STATUSES)


@pytest.mark.parametrize("mode", [ON_SUCCESS, ON_PARTIAL])
def test_partial_is_never_lumped_in_with_success(mode):
    "专挑两档能区分「部分成功」和「完全成功」的模式来盯。"
    assert _should_run(mode, RUN_PARTIAL) != _should_run(mode, RUN_SUCCESS)


@pytest.mark.parametrize("mode", [ON_NOT_SUCCESS, ON_ALWAYS])
def test_partial_is_not_lumped_in_with_failure_either(mode):
    """反过来也要盯：这两档里部分成功跟失败是**一起**发的。"""
    assert _should_run(mode, RUN_PARTIAL) == _should_run(mode, RUN_FAILED)


def test_unknown_mode_never_runs():
    """库里存了个没见过的 on 值（改过版本、手改过库）时，宁可不发也不乱发。"""
    assert not _should_run("something-stale", RUN_SUCCESS)
    assert not _should_run("something-stale", RUN_FAILED)
