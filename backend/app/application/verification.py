"""
Fresh Verification Evaluator for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §4 and PROJECT.md:
- verification="required": finish transitions to SUCCEEDED only if:
  1. At least one test command (purpose="test") was executed.
  2. The most recent test command exited with code 0.
  3. No write_file tool call occurred after that passing test.
- If write_file occurred after last passing test -> FAILED(reason="finish_without_fresh_verification").
- If finish called without running tests or while tests are failing -> FAILED(reason="finish_with_failing_tests").
- verification="none": finish transitions to SUCCEEDED unconditionally.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.models import Run, RunEvent, RunStatus, VerificationMode


@dataclass(frozen=True)
class FreshVerificationResult:
    """Represents the outcome of a fresh verification evaluation."""

    is_valid: bool
    target_status: RunStatus
    error_reason: str | None = None
    message: str = ""


class FreshVerificationTracker:
    """Stateful tracker for live verification state in the agent loop."""

    def __init__(self, mode: VerificationMode = VerificationMode.REQUIRED) -> None:
        self.mode = mode
        self.has_test_executed: bool = False
        self.last_test_passed: bool = False
        self.last_test_exit_code: int | None = None
        self.wrote_file_after_last_test: bool = False
        self.total_tests: int = 0
        self.total_writes: int = 0

    def record_command(self, command: str, purpose: str = "other", exit_code: int = 0) -> None:
        """Records command execution and updates verification state if purpose is test."""
        clean_purpose = purpose.strip().lower() if purpose else "other"
        if clean_purpose == "test":
            self.has_test_executed = True
            self.total_tests += 1
            self.last_test_exit_code = exit_code
            if exit_code == 0:
                self.last_test_passed = True
                self.wrote_file_after_last_test = False
            else:
                self.last_test_passed = False

    def record_write_file(self, path: str, success: bool = True) -> None:
        """Records file write and flags violation if occurring after a passing test."""
        if success:
            self.total_writes += 1
            if self.has_test_executed and self.last_test_passed:
                self.wrote_file_after_last_test = True

    def evaluate_finish(self) -> FreshVerificationResult:
        """Evaluates whether finish can transition to SUCCEEDED."""
        if self.mode == VerificationMode.NONE:
            return FreshVerificationResult(
                is_valid=True,
                target_status=RunStatus.SUCCEEDED,
                error_reason=None,
                message="Verification mode is 'none'; finish accepted unconditionally.",
            )

        if not self.has_test_executed:
            return FreshVerificationResult(
                is_valid=False,
                target_status=RunStatus.FAILED,
                error_reason="finish_with_failing_tests",
                message="Finish rejected: No test command was executed during the run.",
            )

        if not self.last_test_passed:
            return FreshVerificationResult(
                is_valid=False,
                target_status=RunStatus.FAILED,
                error_reason="finish_with_failing_tests",
                message=f"Finish rejected: Last test command failed with exit code {self.last_test_exit_code}.",
            )

        if self.wrote_file_after_last_test:
            return FreshVerificationResult(
                is_valid=False,
                target_status=RunStatus.FAILED,
                error_reason="finish_without_fresh_verification",
                message="Finish rejected: write_file was called after the last passing test without fresh verification.",
            )

        return FreshVerificationResult(
            is_valid=True,
            target_status=RunStatus.SUCCEEDED,
            error_reason=None,
            message="Fresh verification satisfied: passing test executed with no subsequent file writes.",
        )


def evaluate_verification(run: Run, events: list[RunEvent]) -> FreshVerificationResult:
    """
    Stateless evaluator reconstructing verification state from monotonic event history.
    Useful for audit verification and post-restart evaluation.
    """
    mode = run.options.verification
    tracker = FreshVerificationTracker(mode=mode)

    sorted_events = sorted(events, key=lambda e: e.seq)

    for event in sorted_events:
        payload = event.payload or {}
        if event.type == "tool_result":
            tool_name = payload.get("name") or payload.get("tool_name")
            if tool_name == "run_command":
                purpose = payload.get("purpose", "other")
                exit_code = payload.get("exit_code", 0)
                tracker.record_command(command=payload.get("command", ""), purpose=purpose, exit_code=exit_code)
            elif tool_name == "write_file":
                is_error = payload.get("is_error", False)
                if not is_error:
                    tracker.record_write_file(path=payload.get("path", ""), success=True)

    return tracker.evaluate_finish()
