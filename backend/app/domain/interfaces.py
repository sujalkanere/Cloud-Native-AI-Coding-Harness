"""
Domain Interface Contracts for Cloud-Native AI Coding Harness.

Fixed contracts adhering strictly to Spec §3.2:
- Dependencies point strictly inward.
- Defined as runtime-checkable typing.Protocol classes.
- All sandbox implementations, including FakeSandbox, must be substitutable.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from .models import (
    AuthenticatedUser,
    ExecEvent,
    LLMMessage,
    LLMResponse,
    LogEvent,
    Run,
    RunEvent,
    RunStatus,
    SandboxSpec,
    ToolDefinition,
)


@runtime_checkable
class IExecutionTerminal(Protocol):
    """Execution terminal contract for running commands and streaming output in the sandbox."""

    def run(
        self,
        command: str,
        cwd: str = "/workspace",
        timeout: float | None = None,
    ) -> AsyncIterator[ExecEvent]:
        """Runs a command inside the sandbox, yielding stdout/stderr events."""
        ...

    async def cancel_current(self) -> None:
        """Cancels the currently in-flight command in the sandbox."""
        ...


@runtime_checkable
class IFileAccess(Protocol):
    """File access contract for reading, writing, and transferring workspace files."""

    async def read_file(self, path: str) -> str:
        """Reads text content of a file within the sandbox /workspace."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Writes text content to a file in /workspace, creating intermediate directories."""
        ...

    async def list_dir(self, path: str = ".") -> list[str]:
        """Lists relative paths of entries within the given directory."""
        ...

    async def upload_workspace(self, tar_gz: bytes) -> None:
        """Unpacks a tar.gz archive into the /workspace directory."""
        ...

    async def download_workspace(self) -> bytes:
        """Packs the /workspace directory into a tar.gz archive and returns its bytes."""
        ...


@runtime_checkable
class ILogStreamer(Protocol):
    """Log streaming contract for telemetry, replaying from start then live."""

    def subscribe(self) -> AsyncIterator[LogEvent]:
        """Subscribes to execution logs, replaying past events from start, then streaming live."""
        ...


@runtime_checkable
class ISandboxEnvironment(IExecutionTerminal, IFileAccess, ILogStreamer, Protocol):
    """Unified sandbox contract combining terminal execution, file access, and log streaming."""

    @property
    def id(self) -> str:
        """Returns the unique identifier of the sandbox container."""
        ...

    async def start(self) -> None:
        """Starts or initializes the sandbox container environment."""
        ...

    async def stop(self) -> None:
        """Stops and tears down the sandbox container (idempotent)."""
        ...


@runtime_checkable
class ISandboxProvider(Protocol):
    """Sandbox provider contract for acquiring warmed or cold container environments."""

    async def acquire(self, spec: SandboxSpec) -> ISandboxEnvironment:
        """Acquires a sandbox environment matching the resource specification."""
        ...


@runtime_checkable
class ILLMProvider(Protocol):
    """LLM provider contract for chat completions with tool definitions."""

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Executes a chat completion call with retry and exponential backoff."""
        ...


@runtime_checkable
class IObjectStorage(Protocol):
    """Object storage contract for storing artifacts and generating presigned URLs."""

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Stores binary object data at the specified key."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieves binary object data from the specified key."""
        ...

    def presigned_url(self, key: str, ttl: int = 3600) -> str:
        """Generates a public presigned URL for downloading the artifact."""
        ...


@runtime_checkable
class IRunRepository(Protocol):
    """Run repository contract for persisting run state, status transitions, and events."""

    async def create(self, run: Run) -> Run:
        """Persists a newly created run."""
        ...

    async def get(self, run_id: str, user_id: str | None = None) -> Run | None:
        """Retrieves a run by ID, enforcing user isolation when user_id is provided."""
        ...

    async def list(self, user_id: str | None = None) -> builtins.list[Run]:
        """Lists runs scoped to user_id, or all runs if unauthenticated/admin."""
        ...

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_reason: str | None = None,
        is_pausing: bool | None = None,
    ) -> Run:
        """Updates lifecycle status, error reason, or is_pausing flag atomically."""
        ...

    async def append_event(self, run_id: str, event_data: dict[str, Any]) -> RunEvent:
        """Appends an event with a monotonically increasing, gap-free sequence number."""
        ...

    async def list_events(self, run_id: str, after_seq: int | None = None) -> builtins.list[RunEvent]:
        """Lists events for a run ordered by sequence number, optionally filtered after_seq."""
        ...


@runtime_checkable
class IAuthProvider(Protocol):
    """Authentication provider contract for request authentication."""

    async def authenticate(self, request: Any) -> AuthenticatedUser:
        """Authenticates a request and returns the authenticated user entity."""
        ...
