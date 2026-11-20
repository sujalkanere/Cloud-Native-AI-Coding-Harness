"""
Lifecycle State Machine for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.4 and PROJECT.md:
- Enforces valid transitions across the 7 lifecycle states:
  QUEUED, PREPARING, RUNNING, PAUSED, SUCCEEDED, FAILED, TERMINATED.
- Boundary pause: sets is_pausing = True while completing the current step in RUNNING.
- Boundary pause cancellation: calling resume while is_pausing=True clears is_pausing
  and remains in RUNNING (returns 200).
- Control idempotency: repeating the same control action matching current state returns 200
  as a no-op (e.g. terminate on TERMINATED, pause on PAUSED, resume on RUNNING).
- Conflicting controls: calling a different control on a terminal run or any invalid transition
  raises typed InvalidStateTransitionError (maps to HTTP 409 Conflict).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.errors import InvalidStateTransitionError
from backend.app.domain.models import Run, RunStatus

_VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.PREPARING, RunStatus.TERMINATED},
    RunStatus.PREPARING: {RunStatus.RUNNING, RunStatus.TERMINATED},
    RunStatus.RUNNING: {
        RunStatus.PAUSED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.TERMINATED,
    },
    RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.TERMINATED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.TERMINATED: set(),
}

TERMINAL_STATES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TERMINATED}


@dataclass(frozen=True)
class ActionResult:
    """Represents the outcome of a state transition or control command."""

    status: RunStatus
    is_pausing: bool = False
    action: str = ""
    message: str = ""
    success: bool = True
    changed: bool = False


class RunStateMachine:
    """Lifecycle transition manager enforcing Spec §3.4 constraints."""

    def __init__(
        self,
        current_status: RunStatus | Run = RunStatus.QUEUED,
        is_pausing: bool = False,
    ) -> None:
        if isinstance(current_status, Run):
            self._status = current_status.status
            self._is_pausing = current_status.is_pausing
        else:
            self._status = current_status
            self._is_pausing = is_pausing

    @property
    def status(self) -> RunStatus:
        """Current lifecycle state."""
        return self._status

    @property
    def current_status(self) -> RunStatus:
        """Alias for status."""
        return self._status

    @property
    def is_pausing(self) -> bool:
        """True when a boundary pause is pending."""
        return self._is_pausing

    @property
    def is_terminal(self) -> bool:
        """True if the current state is a terminal state."""
        return self._status in TERMINAL_STATES

    def can_transition_to(self, target: RunStatus) -> bool:
        """Checks if a transition to target is valid without mutating state."""
        if target == self._status:
            return True
        return target in _VALID_TRANSITIONS.get(self._status, set())

    def transition_to(
        self, target: RunStatus, reason: str | None = None
    ) -> ActionResult:
        """
        Transitions the run to target state.
        Raises InvalidStateTransitionError if the transition is prohibited.
        """
        # Idempotent no-op
        if target == self._status:
            return ActionResult(
                status=self._status,
                is_pausing=self._is_pausing,
                action="noop",
                message=f"Run is already in state {self._status.value}",
                changed=False,
            )

        if self.is_terminal:
            raise InvalidStateTransitionError(
                f"Cannot transition terminal run from {self._status.value} to {target.value}"
            )

        allowed = _VALID_TRANSITIONS.get(self._status, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid state transition from {self._status.value} to {target.value}"
            )

        self._status = target
        if target != RunStatus.RUNNING:
            self._is_pausing = False

        msg = f"Transitioned to {target.value}"
        if reason:
            msg += f": {reason}"

        return ActionResult(
            status=self._status,
            is_pausing=self._is_pausing,
            action="transition",
            message=msg,
            changed=True,
        )

    def pause(self, mode: str = "boundary") -> ActionResult:
        """
        Executes a pause control.

        - If mode == 'boundary': sets is_pausing = True while in RUNNING.
        - If mode == 'now': immediately transitions RUNNING to PAUSED.
        - Calling pause while in PAUSED is an idempotent no-op (200).
        - Calling pause in PREPARING, QUEUED, or terminal states raises InvalidStateTransitionError (409).
        """
        if self.is_terminal:
            raise InvalidStateTransitionError(
                f"Cannot pause terminal run in state {self._status.value}"
            )

        if self._status == RunStatus.PAUSED:
            return ActionResult(
                status=self._status,
                is_pausing=False,
                action="noop",
                message="Run is already paused",
                changed=False,
            )

        if self._status != RunStatus.RUNNING:
            raise InvalidStateTransitionError(
                f"Pause is valid only from RUNNING, but current state is {self._status.value}"
            )

        if mode == "boundary":
            if self._is_pausing:
                return ActionResult(
                    status=self._status,
                    is_pausing=True,
                    action="noop",
                    message="Boundary pause is already requested",
                    changed=False,
                )
            self._is_pausing = True
            return ActionResult(
                status=self._status,
                is_pausing=True,
                action="boundary_pause_requested",
                message="Boundary pause requested; will halt at step boundary",
                changed=True,
            )
        elif mode == "now":
            self._status = RunStatus.PAUSED
            self._is_pausing = False
            return ActionResult(
                status=self._status,
                is_pausing=False,
                action="paused_now",
                message="Run paused immediately",
                changed=True,
            )
        else:
            raise ValueError(f"Invalid pause mode '{mode}'. Must be 'boundary' or 'now'.")

    def resume(self) -> ActionResult:
        """
        Executes a resume control.

        - Calling resume while is_pausing=True cancels pending boundary pause (clears is_pausing, returns 200).
        - Calling resume in PAUSED transitions to RUNNING.
        - Calling resume in RUNNING (without pending pause) is an idempotent no-op (200).
        - Calling resume in QUEUED, PREPARING, or terminal states raises InvalidStateTransitionError (409).
        """
        if self.is_terminal:
            raise InvalidStateTransitionError(
                f"Cannot resume terminal run in state {self._status.value}"
            )

        if self._status == RunStatus.RUNNING:
            if self._is_pausing:
                # Pause cancellation: cancel pending boundary pause
                self._is_pausing = False
                return ActionResult(
                    status=self._status,
                    is_pausing=False,
                    action="pause_cancelled",
                    message="Pending boundary pause cancelled; run remains RUNNING",
                    changed=True,
                )
            # Idempotent resume on RUNNING
            return ActionResult(
                status=self._status,
                is_pausing=False,
                action="noop",
                message="Run is already running",
                changed=False,
            )

        if self._status == RunStatus.PAUSED:
            self._status = RunStatus.RUNNING
            self._is_pausing = False
            return ActionResult(
                status=self._status,
                is_pausing=False,
                action="resumed",
                message="Run resumed to RUNNING",
                changed=True,
            )

        raise InvalidStateTransitionError(
            f"Resume is valid only from PAUSED or pending pause, but current state is {self._status.value}"
        )

    def complete_boundary_pause(self) -> ActionResult:
        """Completes a pending boundary pause when the in-flight step finishes."""
        if self._status != RunStatus.RUNNING or not self._is_pausing:
            raise InvalidStateTransitionError(
                f"No boundary pause pending to complete (status={self._status.value}, is_pausing={self._is_pausing})"
            )

        self._status = RunStatus.PAUSED
        self._is_pausing = False
        return ActionResult(
            status=self._status,
            is_pausing=False,
            action="paused",
            message="Boundary pause completed; run is now PAUSED",
            changed=True,
        )

    def terminate(self, reason: str | None = None) -> ActionResult:
        """
        Executes a terminate control.

        - Repeating terminate on TERMINATED is an idempotent no-op (200).
        - Terminating a run in SUCCEEDED or FAILED raises InvalidStateTransitionError (409).
        - Valid from QUEUED, PREPARING, RUNNING, PAUSED -> transitions to TERMINATED.
        """
        if self._status == RunStatus.TERMINATED:
            return ActionResult(
                status=self._status,
                is_pausing=False,
                action="noop",
                message="Run is already terminated",
                changed=False,
            )

        if self._status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            raise InvalidStateTransitionError(
                f"Cannot terminate run already in terminal state {self._status.value}"
            )

        self._status = RunStatus.TERMINATED
        self._is_pausing = False
        msg = "Run terminated"
        if reason:
            msg += f": {reason}"

        return ActionResult(
            status=self._status,
            is_pausing=False,
            action="terminated",
            message=msg,
            changed=True,
        )
