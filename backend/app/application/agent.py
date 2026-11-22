"""
Autonomous AI Coding Agent Execution Engine for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.4, §4, §8, §9.1:
- 5 JSON-Schema compliant tools: read_file, write_file, list_dir, run_command, finish.
- Fresh verification evaluation on finish.
- Monotonic gap-free sequencing for all events.
- Hard limits: AGENT_MAX_STEPS (40), AGENT_MAX_TOKENS (200000), AGENT_MAX_CONSECUTIVE_FAILURES (5).
- Output stream truncation at MAX_OUTPUT_BYTES_PER_RUN (5MB) with truncation_marker.
- Interactive controls: boundary pause, now pause, pause cancellation via resume, guidance injection, terminate.
- Binary git diff against baseline SHA for all terminal states (SUCCEEDED, FAILED, TERMINATED) with changes.
- Container destroyed within 5s after patch extraction on terminate.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.app.application.coalescing import TerminalCoalescer
from backend.app.application.diff import compute_diff, create_baseline, store_patch_artifact
from backend.app.application.state_machine import ActionResult, RunStateMachine
from backend.app.application.verification import FreshVerificationTracker
from backend.app.config import Settings, get_settings
from backend.app.domain.errors import DomainError
from backend.app.domain.interfaces import (
    ILLMProvider,
    IObjectStorage,
    IRunRepository,
    ISandboxEnvironment,
)
from backend.app.domain.models import (
    LLMMessage,
    Run,
    RunStatus,
    ToolDefinition,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    ToolDefinition(
        name="read_file",
        description="Reads text content of a file within /workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file relative to /workspace"}
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="write_file",
        description="Writes text content to a file in /workspace, creating intermediate directories.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file relative to /workspace"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        name="list_dir",
        description="Lists relative paths of entries within the given directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path relative to /workspace", "default": "."}
            },
        },
    ),
    ToolDefinition(
        name="run_command",
        description="Runs a shell command inside /workspace, streaming stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "purpose": {
                    "type": "string",
                    "enum": ["test", "other"],
                    "description": "Purpose of command",
                    "default": "other",
                },
            },
            "required": ["command"],
        },
    ),
    ToolDefinition(
        name="finish",
        description="Signals completion of the task and requests run finalization.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of changes made and verification outcome"}
            },
            "required": ["summary"],
        },
    ),
]


class AgentControl:
    """Control handle for external steering of an active agent run."""

    def __init__(
        self,
        run_id: str,
        repository: IRunRepository,
        state_machine: RunStateMachine | None = None,
        sandbox: ISandboxEnvironment | None = None,
    ) -> None:
        self.run_id = run_id
        self.repository = repository
        self.state_machine = state_machine or RunStateMachine(RunStatus.RUNNING)
        self.sandbox = sandbox
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._pending_guidance: list[str] = []
        self._is_terminated = False

    @property
    def is_pausing(self) -> bool:
        return self.state_machine.is_pausing

    @property
    def status(self) -> RunStatus:
        return self.state_machine.status

    def attach_state_machine(self, sm: RunStateMachine) -> None:
        self.state_machine = sm

    def attach_sandbox(self, sandbox: ISandboxEnvironment) -> None:
        self.sandbox = sandbox

    async def request_pause(
        self,
        mode: str = "boundary",
        sandbox: ISandboxEnvironment | None = None,
    ) -> ActionResult:
        """Requests run pause with boundary or now mode."""
        box = sandbox or self.sandbox
        action = self.state_machine.pause(mode=mode)
        if mode == "now":
            self._resume_event.clear()
            if box is not None:
                await box.cancel_current()
            await self.repository.update_status(
                self.run_id,
                status=RunStatus.PAUSED,
                is_pausing=False,
            )
            await self.repository.append_event(
                self.run_id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.PAUSED.value,
                        "error_reason": None,
                        "is_pausing": False,
                    },
                },
            )
        elif mode == "boundary" and action.changed:
            await self.repository.update_status(
                self.run_id,
                status=self.state_machine.status,
                is_pausing=True,
            )
            await self.repository.append_event(
                self.run_id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": self.state_machine.status.value,
                        "error_reason": None,
                        "is_pausing": True,
                    },
                },
            )
        return action

    async def request_resume(self) -> ActionResult:
        """Resumes run from PAUSED or cancels pending boundary pause."""
        action = self.state_machine.resume()
        if action.action == "pause_cancelled":
            await self.repository.update_status(
                self.run_id,
                status=RunStatus.RUNNING,
                is_pausing=False,
            )
            await self.repository.append_event(
                self.run_id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.RUNNING.value,
                        "error_reason": None,
                        "is_pausing": False,
                    },
                },
            )
        elif action.action == "resumed":
            self._resume_event.set()
            await self.repository.update_status(
                self.run_id,
                status=RunStatus.RUNNING,
                is_pausing=False,
            )
            await self.repository.append_event(
                self.run_id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.RUNNING.value,
                        "error_reason": None,
                        "is_pausing": False,
                    },
                },
            )
        return action

    async def inject_guidance(self, message: str) -> None:
        """Appends user guidance into event stream and queues for next LLM prompt."""
        self._pending_guidance.append(message)
        await self.repository.append_event(
            self.run_id,
            {"type": "guidance", "payload": {"message": message}},
        )

    async def request_terminate(
        self,
        sandbox: ISandboxEnvironment | None = None,
        reason: str | None = None,
    ) -> ActionResult:
        """Cancels in-flight actions and transitions to TERMINATED."""
        box = sandbox or self.sandbox
        action = self.state_machine.terminate(reason=reason)
        self._is_terminated = True
        self._resume_event.set()  # Unblock any pause wait

        if box is not None:
            await box.cancel_current()

        await self.repository.update_status(
            self.run_id,
            status=RunStatus.TERMINATED,
            error_reason=reason,
            is_pausing=False,
        )
        await self.repository.append_event(
            self.run_id,
            {
                "type": "status_change",
                "payload": {
                    "status": RunStatus.TERMINATED.value,
                    "error_reason": reason,
                    "is_pausing": False,
                },
            },
        )
        return action


class AgentRunner:
    """Coordinates the execution loop of an agent run."""

    def __init__(
        self,
        run: Run,
        repository: IRunRepository,
        sandbox: ISandboxEnvironment,
        llm_provider: ILLMProvider,
        storage: IObjectStorage,
        control: AgentControl | None = None,
        settings: Settings | None = None,
        coalescer: TerminalCoalescer | None = None,
    ) -> None:
        self.run = run
        self.repository = repository
        self.sandbox = sandbox
        self.llm_provider = llm_provider
        self.storage = storage
        if settings is not None:
            self.settings = settings
        else:
            try:
                self.settings = get_settings()
            except (ValidationError, ValueError, RuntimeError):
                self.settings = Settings(HARNESS_ENV="test", LLM_PROVIDER="scripted")

        self.state_machine = RunStateMachine(current_status=run.status, is_pausing=run.is_pausing)
        if control is None:
            self.control = AgentControl(
                run_id=run.id,
                repository=repository,
                state_machine=self.state_machine,
                sandbox=sandbox,
            )
        else:
            self.control = control
            self.control.attach_state_machine(self.state_machine)
            self.control.attach_sandbox(sandbox)

        if coalescer is not None:
            self.coalescer = coalescer
        else:
            self.coalescer = TerminalCoalescer(
                run_id=run.id,
                emit_callback=self.repository.append_event,
                max_bytes=self.settings.MAX_OUTPUT_BYTES_PER_RUN,
            )

        self.tracker = FreshVerificationTracker(mode=run.options.verification)
        self.step_count: int = 0
        self.total_tokens: int = 0
        self.consecutive_failures: int = 0
        self.total_output_bytes: int = 0
        self.truncation_emitted: bool = False
        self.patch_extracted_at: float | None = None
        self.container_destroyed_at: float | None = None

    async def _execute_tool_read_file(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        path = arguments.get("path", "")
        try:
            content = await self.sandbox.read_file(path)
            return content, False
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError, DomainError) as exc:
            return f"Error reading file '{path}': {exc}", True

    async def _execute_tool_write_file(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        try:
            await self.sandbox.write_file(path, content)
            self.tracker.record_write_file(path=path, success=True)
            return f"Successfully wrote {len(content)} bytes to {path}", False
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError, DomainError) as exc:
            self.tracker.record_write_file(path=path, success=False)
            return f"Error writing file '{path}': {exc}", True

    async def _execute_tool_list_dir(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        path = arguments.get("path", ".")
        try:
            items = await self.sandbox.list_dir(path)
            return "\n".join(items) if items else "(empty directory)", False
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError, DomainError) as exc:
            return f"Error listing directory '{path}': {exc}", True

    async def _execute_tool_run_command(self, arguments: dict[str, Any]) -> tuple[str, bool, int, str]:
        command = arguments.get("command", "")
        purpose = arguments.get("purpose", "other")
        clean_purpose = purpose.strip().lower() if purpose else "other"

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        exit_code = 0

        timeout = float(self.settings.COMMAND_TIMEOUT_SECONDS)

        async for ev in self.sandbox.run(command, cwd="/workspace", timeout=timeout):
            if ev.stream == "exit" and ev.exit_code is not None:
                exit_code = ev.exit_code
            elif ev.stream in ("stdout", "stderr"):
                data = ev.data
                await self.coalescer.feed(ev.stream, data)
                if ev.stream == "stdout":
                    stdout_chunks.append(data)
                else:
                    stderr_chunks.append(data)

        # Flush any coalesced output immediately upon command completion
        await self.coalescer.flush()
        self.total_output_bytes = self.coalescer.total_bytes_emitted
        self.truncation_emitted = self.coalescer.is_truncated

        # Track failure counts
        if exit_code != 0:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

        self.tracker.record_command(command=command, purpose=clean_purpose, exit_code=exit_code)

        combined_output = "".join(stdout_chunks) + "".join(stderr_chunks)
        summary = combined_output if combined_output else f"Command exited with code {exit_code}"
        is_error = exit_code != 0
        return summary, is_error, exit_code, clean_purpose

    async def _execute_tool_finish(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        summary = arguments.get("summary", "")
        verif_result = self.tracker.evaluate_finish()

        if verif_result.is_valid:
            # Pre-compute diff and store patch artifact before emitting SUCCEEDED event
            if self.run.baseline_sha:
                try:
                    patch_bytes = await compute_diff(self.sandbox, self.run.baseline_sha)
                    if patch_bytes:
                        await store_patch_artifact(
                            self.storage,
                            self.run.user_id,
                            self.run.id,
                            patch_bytes,
                        )
                except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                    logger.warning("Failed to extract or store patch diff in finish: %s", exc)

            self.state_machine.transition_to(RunStatus.SUCCEEDED)
            await self.repository.update_status(self.run.id, status=RunStatus.SUCCEEDED)
            await self.repository.append_event(
                self.run.id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.SUCCEEDED.value,
                        "error_reason": None,
                        "is_pausing": False,
                    },
                },
            )
            return f"Task completed successfully: {summary}", False
        else:
            self.state_machine.transition_to(RunStatus.FAILED, reason=verif_result.error_reason)
            await self.repository.update_status(
                self.run.id,
                status=RunStatus.FAILED,
                error_reason=verif_result.error_reason,
            )
            await self.repository.append_event(
                self.run.id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.FAILED.value,
                        "error_reason": verif_result.error_reason,
                        "is_pausing": False,
                    },
                },
            )
            return f"Finish verification rejected ({verif_result.error_reason}): {verif_result.message}", True

    async def run_loop(self) -> Run:
        """Executes the agent lifecycle loop."""
        # 1. Setup PREPARING -> baseline snapshot
        if self.state_machine.status in (RunStatus.QUEUED, RunStatus.PREPARING):
            if self.state_machine.status == RunStatus.QUEUED:
                self.state_machine.transition_to(RunStatus.PREPARING)
                await self.repository.update_status(self.run.id, status=RunStatus.PREPARING)
                await self.repository.append_event(
                    self.run.id,
                    {"type": "status_change", "payload": {"status": RunStatus.PREPARING.value}},
                )

            # Create baseline commit in git and upload snapshot
            if not self.run.baseline_sha:
                baseline_sha = await create_baseline(
                    self.sandbox,
                    self.run,
                    self.storage,
                    self.repository,
                )
                self.run.baseline_sha = baseline_sha

            # Transition to RUNNING
            self.state_machine.transition_to(RunStatus.RUNNING)
            await self.repository.update_status(
                self.run.id,
                status=RunStatus.RUNNING,
                baseline_sha=self.run.baseline_sha,
            )
            await self.repository.append_event(
                self.run.id,
                {
                    "type": "status_change",
                    "payload": {
                        "status": RunStatus.RUNNING.value,
                        "is_pausing": False,
                    },
                },
            )

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content="You are an autonomous AI coding agent."),
            LLMMessage(role="user", content=f"Task: {self.run.task}"),
        ]

        try:
            while not self.state_machine.is_terminal and not self.control._is_terminated:
                # Check boundary pause before starting new step
                if self.state_machine.is_pausing:
                    self.state_machine.complete_boundary_pause()
                    self.control._resume_event.clear()
                    await self.repository.update_status(
                        self.run.id,
                        status=RunStatus.PAUSED,
                        is_pausing=False,
                    )
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "status_change",
                            "payload": {
                                "status": RunStatus.PAUSED.value,
                                "error_reason": None,
                                "is_pausing": False,
                            },
                        },
                    )

                # Wait if paused
                if self.state_machine.status == RunStatus.PAUSED:
                    await self.control._resume_event.wait()
                    if self.control._is_terminated or self.state_machine.is_terminal:
                        break

                # Check max steps limit
                if self.step_count >= self.settings.AGENT_MAX_STEPS:
                    self.state_machine.transition_to(
                        RunStatus.FAILED,
                        reason="max_steps_exceeded",
                    )
                    await self.repository.update_status(
                        self.run.id,
                        status=RunStatus.FAILED,
                        error_reason="max_steps_exceeded",
                    )
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "status_change",
                            "payload": {
                                "status": RunStatus.FAILED.value,
                                "error_reason": "max_steps_exceeded",
                            },
                        },
                    )
                    break

                self.step_count += 1

                # Drain pending guidance messages into conversation context
                while self.control._pending_guidance:
                    guidance_msg = self.control._pending_guidance.pop(0)
                    messages.append(LLMMessage(role="user", content=f"User Guidance: {guidance_msg}"))

                # Invoke LLM completion
                response = await self.llm_provider.complete(messages, TOOL_DEFINITIONS)
                self.total_tokens += response.total_tokens

                # Check max tokens limit
                if self.total_tokens >= self.settings.AGENT_MAX_TOKENS:
                    self.state_machine.transition_to(
                        RunStatus.FAILED,
                        reason="max_tokens_exceeded",
                    )
                    await self.repository.update_status(
                        self.run.id,
                        status=RunStatus.FAILED,
                        error_reason="max_tokens_exceeded",
                    )
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "status_change",
                            "payload": {
                                "status": RunStatus.FAILED.value,
                                "error_reason": "max_tokens_exceeded",
                            },
                        },
                    )
                    break

                # Record reasoning event if present
                if response.content:
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "reasoning",
                            "payload": {
                                "thought": response.content,
                                "prompt_tokens": response.prompt_tokens,
                                "completion_tokens": response.completion_tokens,
                                "total_tokens": response.total_tokens,
                            },
                        },
                    )

                # Record token usage event if tokens were consumed
                if response.total_tokens > 0 or response.prompt_tokens > 0 or response.completion_tokens > 0:
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "token_usage",
                            "payload": {
                                "prompt_tokens": response.prompt_tokens,
                                "completion_tokens": response.completion_tokens,
                                "total_tokens": response.total_tokens,
                                "cumulative_total_tokens": self.total_tokens,
                            },
                        },
                    )

                # Check if paused now while LLM was in-flight (Spec §4: halt before tools)
                if self.state_machine.status == RunStatus.PAUSED:
                    await self.control._resume_event.wait()
                    if self.control._is_terminated or self.state_machine.is_terminal:
                        break

                # Append assistant message to conversation context
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )

                # Execute tool calls
                for tc in response.tool_calls:
                    if self.control._is_terminated or self.state_machine.is_terminal:
                        break

                    # Emit tool_call event
                    await self.repository.append_event(
                        self.run.id,
                        {
                            "type": "tool_call",
                            "payload": {
                                "id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        },
                    )

                    tool_result_str: str = ""
                    is_error: bool = False
                    extra_payload: dict[str, Any] = {}

                    if tc.name == "read_file":
                        tool_result_str, is_error = await self._execute_tool_read_file(tc.arguments)
                        extra_payload["path"] = tc.arguments.get("path", "")
                    elif tc.name == "write_file":
                        tool_result_str, is_error = await self._execute_tool_write_file(tc.arguments)
                        extra_payload["path"] = tc.arguments.get("path", "")
                    elif tc.name == "list_dir":
                        tool_result_str, is_error = await self._execute_tool_list_dir(tc.arguments)
                        extra_payload["path"] = tc.arguments.get("path", ".")
                    elif tc.name == "run_command":
                        (
                            tool_result_str,
                            is_error,
                            exit_code,
                            purpose,
                        ) = await self._execute_tool_run_command(tc.arguments)
                        extra_payload["command"] = tc.arguments.get("command", "")
                        extra_payload["exit_code"] = exit_code
                        extra_payload["purpose"] = purpose

                        # Check consecutive failures limit
                        if self.consecutive_failures >= self.settings.AGENT_MAX_CONSECUTIVE_FAILURES:
                            self.state_machine.transition_to(
                                RunStatus.FAILED,
                                reason="max_consecutive_failures_exceeded",
                            )
                            await self.repository.update_status(
                                self.run.id,
                                status=RunStatus.FAILED,
                                error_reason="max_consecutive_failures_exceeded",
                            )
                            await self.repository.append_event(
                                self.run.id,
                                {
                                    "type": "status_change",
                                    "payload": {
                                        "status": RunStatus.FAILED.value,
                                        "error_reason": "max_consecutive_failures_exceeded",
                                    },
                                },
                            )
                    elif tc.name == "finish":
                        tool_result_str, is_error = await self._execute_tool_finish(tc.arguments)
                        extra_payload["summary"] = tc.arguments.get("summary", "")
                    else:
                        tool_result_str = f"Unknown tool: '{tc.name}'"
                        is_error = True

                    # Emit tool_result event
                    result_payload: dict[str, Any] = {
                        "id": tc.id,
                        "name": tc.name,
                        "output": tool_result_str,
                        "is_error": is_error,
                    }
                    result_payload.update(extra_payload)
                    await self.repository.append_event(
                        self.run.id,
                        {"type": "tool_result", "payload": result_payload},
                    )

                    # Append tool result to conversation context
                    messages.append(
                        LLMMessage(
                            role="tool",
                            content=tool_result_str,
                            tool_call_id=tc.id,
                        )
                    )

                    # If finish was executed or terminal reached, break tool loop
                    if tc.name == "finish" or self.state_machine.is_terminal or self.control._is_terminated:
                        break

        finally:
            # 2. Extract git diff against baseline commit SHA if baseline exists
            loop = asyncio.get_running_loop()
            if self.run.baseline_sha:
                try:
                    patch_bytes = await compute_diff(self.sandbox, self.run.baseline_sha)
                    if patch_bytes:
                        await store_patch_artifact(
                            self.storage,
                            self.run.user_id,
                            self.run.id,
                            patch_bytes,
                        )
                except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                    logger.warning("Failed to extract or store patch diff: %s", exc)
                self.patch_extracted_at = loop.time()

            # 3. Destroy sandbox container (within 5 seconds per Spec §4, §9.1)
            try:
                await asyncio.wait_for(self.sandbox.stop(), timeout=5.0)
                self.container_destroyed_at = loop.time()
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError, TimeoutError) as exc:
                logger.warning("Error stopping sandbox container: %s", exc)

        # Refresh updated run state from repository
        updated_run = await self.repository.get(self.run.id, user_id=self.run.user_id)
        return updated_run or self.run


async def run_agent(
    run_id: str,
    repository: IRunRepository,
    sandbox: ISandboxEnvironment,
    llm_provider: ILLMProvider,
    storage: IObjectStorage,
    control: AgentControl | None = None,
    settings: Settings | None = None,
    coalescer: TerminalCoalescer | None = None,
) -> Run:
    """Entry point to execute an agent run."""
    run = await repository.get(run_id)
    if run is None:
        raise ValueError(f"Run '{run_id}' not found")

    runner = AgentRunner(
        run=run,
        repository=repository,
        sandbox=sandbox,
        llm_provider=llm_provider,
        storage=storage,
        control=control,
        settings=settings,
        coalescer=coalescer,
    )
    return await runner.run_loop()
