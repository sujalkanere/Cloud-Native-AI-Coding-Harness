"""
Unit tests for Fresh Verification Evaluator.
"""
from backend.app.application.verification import (
    FreshVerificationTracker,
    evaluate_verification,
)
from backend.app.domain.models import Run, RunEvent, RunOptions, RunStatus, VerificationMode


def test_verification_none_succeeds_without_tests() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.NONE)
    tracker.record_write_file("foo.py")
    res = tracker.evaluate_finish()
    assert res.is_valid is True
    assert res.target_status == RunStatus.SUCCEEDED
    assert res.error_reason is None


def test_finish_without_tests_fails() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.REQUIRED)
    tracker.record_write_file("foo.py")
    res = tracker.evaluate_finish()
    assert res.is_valid is False
    assert res.target_status == RunStatus.FAILED
    assert res.error_reason == "finish_with_failing_tests"


def test_finish_with_failing_tests_fails() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.REQUIRED)
    tracker.record_command("pytest", purpose="test", exit_code=1)
    res = tracker.evaluate_finish()
    assert res.is_valid is False
    assert res.target_status == RunStatus.FAILED
    assert res.error_reason == "finish_with_failing_tests"


def test_finish_without_fresh_verification_fails() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.REQUIRED)
    tracker.record_command("pytest", purpose="test", exit_code=0)
    tracker.record_write_file("foo.py")
    res = tracker.evaluate_finish()
    assert res.is_valid is False
    assert res.target_status == RunStatus.FAILED
    assert res.error_reason == "finish_without_fresh_verification"


def test_fresh_verification_success_after_fix() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.REQUIRED)
    tracker.record_command("pytest", purpose="test", exit_code=1)
    tracker.record_write_file("foo.py")
    tracker.record_command("pytest", purpose="test", exit_code=0)
    res = tracker.evaluate_finish()
    assert res.is_valid is True
    assert res.target_status == RunStatus.SUCCEEDED
    assert res.error_reason is None


def test_purpose_other_does_not_satisfy_test() -> None:
    tracker = FreshVerificationTracker(mode=VerificationMode.REQUIRED)
    tracker.record_command("pytest", purpose="other", exit_code=0)
    res = tracker.evaluate_finish()
    assert res.is_valid is False
    assert res.target_status == RunStatus.FAILED
    assert res.error_reason == "finish_with_failing_tests"


def test_stateless_evaluate_verification() -> None:
    run = Run(
        id="run-1",
        user_id="user-1",
        task="task",
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    events = [
        RunEvent(seq=1, type="tool_result", payload={"name": "run_command", "purpose": "test", "exit_code": 1}),
        RunEvent(seq=2, type="tool_result", payload={"name": "write_file", "path": "app.py", "is_error": False}),
        RunEvent(seq=3, type="tool_result", payload={"name": "run_command", "purpose": "test", "exit_code": 0}),
    ]
    res = evaluate_verification(run, events)
    assert res.is_valid is True
    assert res.target_status == RunStatus.SUCCEEDED
