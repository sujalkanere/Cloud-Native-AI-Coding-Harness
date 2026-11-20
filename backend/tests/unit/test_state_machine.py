"""
Unit tests for RunStateMachine lifecycle transition manager.

Adheres strictly to Spec §3.4:
- Full state transition matrix tests.
- Control idempotency tests (repeating same control returns 200/no-op).
- Conflicting control tests (raises InvalidStateTransitionError / HTTP 409).
- Boundary pause (is_pausing=True) and pause cancellation via resume.
- Immediate pause (mode="now").
- Terminal state immutability.
"""

from __future__ import annotations

import pytest
from backend.app.application.state_machine import RunStateMachine
from backend.app.domain.errors import InvalidStateTransitionError
from backend.app.domain.models import Run, RunStatus


def test_initial_state_defaults() -> None:
    sm = RunStateMachine()
    assert sm.status == RunStatus.QUEUED
    assert sm.current_status == RunStatus.QUEUED
    assert not sm.is_pausing
    assert not sm.is_terminal


def test_initial_state_from_run_model() -> None:
    run = Run(
        id="run-1",
        user_id="user-1",
        task="Test task",
        status=RunStatus.RUNNING,
        is_pausing=True,
    )
    sm = RunStateMachine(run)
    assert sm.status == RunStatus.RUNNING
    assert sm.is_pausing is True


# --- State Transition Matrix Tests ---


def test_queued_valid_transitions() -> None:
    # QUEUED -> PREPARING
    sm1 = RunStateMachine(RunStatus.QUEUED)
    res = sm1.transition_to(RunStatus.PREPARING)
    assert res.status == RunStatus.PREPARING
    assert sm1.status == RunStatus.PREPARING

    # QUEUED -> TERMINATED
    sm2 = RunStateMachine(RunStatus.QUEUED)
    res = sm2.transition_to(RunStatus.TERMINATED)
    assert res.status == RunStatus.TERMINATED


@pytest.mark.parametrize(
    "invalid_target",
    [
        RunStatus.RUNNING,
        RunStatus.PAUSED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
    ],
)
def test_queued_invalid_transitions(invalid_target: RunStatus) -> None:
    sm = RunStateMachine(RunStatus.QUEUED)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(invalid_target)


def test_preparing_valid_transitions() -> None:
    # PREPARING -> RUNNING
    sm1 = RunStateMachine(RunStatus.PREPARING)
    res = sm1.transition_to(RunStatus.RUNNING)
    assert res.status == RunStatus.RUNNING

    # PREPARING -> TERMINATED
    sm2 = RunStateMachine(RunStatus.PREPARING)
    res = sm2.transition_to(RunStatus.TERMINATED)
    assert res.status == RunStatus.TERMINATED


@pytest.mark.parametrize(
    "invalid_target",
    [
        RunStatus.QUEUED,
        RunStatus.PAUSED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
    ],
)
def test_preparing_invalid_transitions(invalid_target: RunStatus) -> None:
    sm = RunStateMachine(RunStatus.PREPARING)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(invalid_target)


def test_running_valid_transitions() -> None:
    for target in [
        RunStatus.PAUSED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    ]:
        sm = RunStateMachine(RunStatus.RUNNING)
        res = sm.transition_to(target)
        assert res.status == target
        assert sm.status == target


@pytest.mark.parametrize("invalid_target", [RunStatus.QUEUED, RunStatus.PREPARING])
def test_running_invalid_transitions(invalid_target: RunStatus) -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(invalid_target)


def test_paused_valid_transitions() -> None:
    # PAUSED -> RUNNING
    sm1 = RunStateMachine(RunStatus.PAUSED)
    res = sm1.transition_to(RunStatus.RUNNING)
    assert res.status == RunStatus.RUNNING

    # PAUSED -> TERMINATED
    sm2 = RunStateMachine(RunStatus.PAUSED)
    res = sm2.transition_to(RunStatus.TERMINATED)
    assert res.status == RunStatus.TERMINATED


@pytest.mark.parametrize(
    "invalid_target",
    [
        RunStatus.QUEUED,
        RunStatus.PREPARING,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
    ],
)
def test_paused_invalid_transitions(invalid_target: RunStatus) -> None:
    sm = RunStateMachine(RunStatus.PAUSED)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(invalid_target)


@pytest.mark.parametrize(
    "terminal_state",
    [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TERMINATED],
)
def test_terminal_states_cannot_transition(terminal_state: RunStatus) -> None:
    sm = RunStateMachine(terminal_state)
    assert sm.is_terminal is True
    for any_state in RunStatus:
        if any_state != terminal_state:
            with pytest.raises(InvalidStateTransitionError):
                sm.transition_to(any_state)


# --- Control Idempotency Tests ---


def test_transition_to_self_is_idempotent() -> None:
    for state in RunStatus:
        sm = RunStateMachine(state)
        res = sm.transition_to(state)
        assert res.status == state
        assert res.action == "noop"
        assert not res.changed


def test_pause_on_paused_is_idempotent() -> None:
    sm = RunStateMachine(RunStatus.PAUSED)
    res = sm.pause()
    assert res.status == RunStatus.PAUSED
    assert res.action == "noop"
    assert not res.changed


def test_resume_on_running_is_idempotent() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    res = sm.resume()
    assert res.status == RunStatus.RUNNING
    assert res.action == "noop"
    assert not res.changed


def test_terminate_on_terminated_is_idempotent() -> None:
    sm = RunStateMachine(RunStatus.TERMINATED)
    res = sm.terminate()
    assert res.status == RunStatus.TERMINATED
    assert res.action == "noop"
    assert not res.changed


# --- Boundary Pause & Pause Cancellation Tests ---


def test_boundary_pause_sets_is_pausing_flag() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    res = sm.pause(mode="boundary")
    assert res.status == RunStatus.RUNNING
    assert res.is_pausing is True
    assert sm.is_pausing is True
    assert res.action == "boundary_pause_requested"
    assert res.changed is True

    # Repeated boundary pause while already pausing is idempotent no-op
    res2 = sm.pause(mode="boundary")
    assert res2.status == RunStatus.RUNNING
    assert res2.is_pausing is True
    assert res2.action == "noop"
    assert res2.changed is False


def test_boundary_pause_cancellation_via_resume() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    sm.pause(mode="boundary")
    assert sm.is_pausing is True

    # Resume while is_pausing cancels the pending boundary pause
    res = sm.resume()
    assert res.status == RunStatus.RUNNING
    assert res.is_pausing is False
    assert sm.is_pausing is False
    assert res.action == "pause_cancelled"
    assert res.changed is True


def test_complete_boundary_pause_transitions_to_paused() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    sm.pause(mode="boundary")
    assert sm.is_pausing is True

    res = sm.complete_boundary_pause()
    assert res.status == RunStatus.PAUSED
    assert res.is_pausing is False
    assert sm.status == RunStatus.PAUSED
    assert not sm.is_pausing


def test_complete_boundary_pause_when_not_pausing_fails() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        sm.complete_boundary_pause()


def test_immediate_pause_now() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    res = sm.pause(mode="now")
    assert res.status == RunStatus.PAUSED
    assert res.is_pausing is False
    assert sm.status == RunStatus.PAUSED


def test_invalid_pause_mode_raises_value_error() -> None:
    sm = RunStateMachine(RunStatus.RUNNING)
    with pytest.raises(ValueError, match="Invalid pause mode"):
        sm.pause(mode="unsupported")


# --- Conflicting Control Tests ---


def test_pause_on_preparing_raises_conflict() -> None:
    sm = RunStateMachine(RunStatus.PREPARING)
    with pytest.raises(InvalidStateTransitionError, match="Pause is valid only from RUNNING"):
        sm.pause()


def test_pause_on_queued_raises_conflict() -> None:
    sm = RunStateMachine(RunStatus.QUEUED)
    with pytest.raises(InvalidStateTransitionError):
        sm.pause()


def test_resume_on_queued_raises_conflict() -> None:
    sm = RunStateMachine(RunStatus.QUEUED)
    with pytest.raises(InvalidStateTransitionError):
        sm.resume()


def test_resume_on_preparing_raises_conflict() -> None:
    sm = RunStateMachine(RunStatus.PREPARING)
    with pytest.raises(InvalidStateTransitionError):
        sm.resume()


@pytest.mark.parametrize(
    "terminal_state",
    [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TERMINATED],
)
def test_pause_on_terminal_raises_conflict(terminal_state: RunStatus) -> None:
    sm = RunStateMachine(terminal_state)
    with pytest.raises(InvalidStateTransitionError, match="Cannot pause terminal run"):
        sm.pause()


@pytest.mark.parametrize(
    "terminal_state",
    [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TERMINATED],
)
def test_resume_on_terminal_raises_conflict(terminal_state: RunStatus) -> None:
    sm = RunStateMachine(terminal_state)
    with pytest.raises(InvalidStateTransitionError, match="Cannot resume terminal run"):
        sm.resume()


@pytest.mark.parametrize("terminal_state", [RunStatus.SUCCEEDED, RunStatus.FAILED])
def test_terminate_on_succeeded_or_failed_raises_conflict(
    terminal_state: RunStatus,
) -> None:
    sm = RunStateMachine(terminal_state)
    with pytest.raises(InvalidStateTransitionError, match="Cannot terminate run already in terminal state"):
        sm.terminate()
