"""
Unit tests for Domain Protocol interfaces.

Asserts that all 9 protocols in backend.app.domain.interfaces:
- Are @runtime_checkable typing.Protocol classes.
- Support duck typing verification with conformant and non-conformant implementations.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator
from typing import Any, Protocol

import pytest

from backend.app.domain.interfaces import (
    IAuthProvider,
    IExecutionTerminal,
    IFileAccess,
    ILLMProvider,
    ILogStreamer,
    IObjectStorage,
    IRunRepository,
    ISandboxEnvironment,
    ISandboxProvider,
)
from backend.app.domain.models import (
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

ALL_PROTOCOLS = [
    IExecutionTerminal,
    IFileAccess,
    ILogStreamer,
    ISandboxEnvironment,
    ISandboxProvider,
    ILLMProvider,
    IObjectStorage,
    IRunRepository,
    IAuthProvider,
]


@pytest.mark.parametrize("protocol_cls", ALL_PROTOCOLS)
def test_all_protocols_are_runtime_checkable_protocols(protocol_cls: type) -> None:
    """Verifies that all 9 domain contracts are runtime_checkable typing.Protocol subclasses."""
    assert issubclass(protocol_cls, Protocol)
    # typing._is_runtime_protocol flag is set by @runtime_checkable
    assert getattr(protocol_cls, "_is_runtime_protocol", False) is True


def test_execution_terminal_duck_typing() -> None:
    class DummyExecutionTerminal:
        def run(
            self, command: str, cwd: str = "/workspace", timeout: float | None = None
        ) -> AsyncIterator[ExecEvent]:
            async def _gen() -> AsyncIterator[ExecEvent]:
                yield ExecEvent(stream="stdout", data="ok")
            return _gen()

        async def cancel_current(self) -> None:
            pass

    class NonConformant:
        pass

    assert isinstance(DummyExecutionTerminal(), IExecutionTerminal)
    assert not isinstance(NonConformant(), IExecutionTerminal)


def test_file_access_duck_typing() -> None:
    class DummyFileAccess:
        async def read_file(self, path: str) -> str:
            return ""

        async def write_file(self, path: str, content: str) -> None:
            pass

        async def list_dir(self, path: str = ".") -> list[str]:
            return []

        async def upload_workspace(self, tar_gz: bytes) -> None:
            pass

        async def download_workspace(self) -> bytes:
            return b""

    class MissingMethods:
        async def read_file(self, path: str) -> str:
            return ""

    assert isinstance(DummyFileAccess(), IFileAccess)
    assert not isinstance(MissingMethods(), IFileAccess)


def test_log_streamer_duck_typing() -> None:
    class DummyLogStreamer:
        def subscribe(self) -> AsyncIterator[LogEvent]:
            async def _gen() -> AsyncIterator[LogEvent]:
                yield LogEvent(stream="stdout", data="line")
            return _gen()

    class IncompleteLogStreamer:
        pass

    assert isinstance(DummyLogStreamer(), ILogStreamer)
    assert not isinstance(IncompleteLogStreamer(), ILogStreamer)


def test_sandbox_environment_duck_typing() -> None:
    class DummySandboxEnvironment:
        @property
        def id(self) -> str:
            return "sbx-123"

        def run(
            self, command: str, cwd: str = "/workspace", timeout: float | None = None
        ) -> AsyncIterator[ExecEvent]:
            async def _gen() -> AsyncIterator[ExecEvent]:
                yield ExecEvent(stream="stdout", data="")
            return _gen()

        async def cancel_current(self) -> None:
            pass

        async def read_file(self, path: str) -> str:
            return ""

        async def write_file(self, path: str, content: str) -> None:
            pass

        async def list_dir(self, path: str = ".") -> list[str]:
            return []

        async def upload_workspace(self, tar_gz: bytes) -> None:
            pass

        async def download_workspace(self) -> bytes:
            return b""

        def subscribe(self) -> AsyncIterator[LogEvent]:
            async def _gen() -> AsyncIterator[LogEvent]:
                yield LogEvent(stream="stdout", data="")
            return _gen()

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class NonConformantSandbox:
        @property
        def id(self) -> str:
            return "sbx-invalid"

    sbx = DummySandboxEnvironment()
    assert isinstance(sbx, ISandboxEnvironment)
    assert isinstance(sbx, IExecutionTerminal)
    assert isinstance(sbx, IFileAccess)
    assert isinstance(sbx, ILogStreamer)
    assert not isinstance(NonConformantSandbox(), ISandboxEnvironment)


def test_sandbox_provider_duck_typing() -> None:
    class DummySandboxProvider:
        async def acquire(self, spec: SandboxSpec) -> ISandboxEnvironment:
            raise NotImplementedError

    class IncompleteProvider:
        pass

    assert isinstance(DummySandboxProvider(), ISandboxProvider)
    assert not isinstance(IncompleteProvider(), ISandboxProvider)


def test_llm_provider_duck_typing() -> None:
    class DummyLLMProvider:
        async def complete(
            self, messages: list[LLMMessage], tools: list[ToolDefinition]
        ) -> LLMResponse:
            return LLMResponse(content="done")

    class IncompleteLLMProvider:
        pass

    assert isinstance(DummyLLMProvider(), ILLMProvider)
    assert not isinstance(IncompleteLLMProvider(), ILLMProvider)


def test_object_storage_duck_typing() -> None:
    class DummyObjectStorage:
        async def put(
            self, key: str, data: bytes, content_type: str = "application/octet-stream"
        ) -> None:
            pass

        async def get(self, key: str) -> bytes:
            return b""

        def presigned_url(self, key: str, ttl: int = 3600) -> str:
            return "https://storage.example.com/item"

    class MissingStorageGet:
        async def put(self, key: str, data: bytes) -> None:
            pass

    assert isinstance(DummyObjectStorage(), IObjectStorage)
    assert not isinstance(MissingStorageGet(), IObjectStorage)


def test_run_repository_duck_typing() -> None:
    class DummyRunRepository:
        async def create(self, run: Run) -> Run:
            return run

        async def get(self, run_id: str, user_id: str | None = None) -> Run | None:
            return None

        async def list(self, user_id: str | None = None) -> builtins.list[Run]:
            return []

        async def update_status(
            self,
            run_id: str,
            status: RunStatus,
            error_reason: str | None = None,
            is_pausing: bool | None = None,
        ) -> Run:
            raise NotImplementedError

        async def append_event(self, run_id: str, event_data: dict[str, Any]) -> RunEvent:
            raise NotImplementedError

        async def list_events(
            self, run_id: str, after_seq: int | None = None
        ) -> builtins.list[RunEvent]:
            return []

    class EmptyRepo:
        pass

    assert isinstance(DummyRunRepository(), IRunRepository)
    assert not isinstance(EmptyRepo(), IRunRepository)


def test_auth_provider_duck_typing() -> None:
    class DummyAuthProvider:
        async def authenticate(self, request: Any) -> AuthenticatedUser:
            return AuthenticatedUser(id="user-1")

    class EmptyAuth:
        pass

    assert isinstance(DummyAuthProvider(), IAuthProvider)
    assert not isinstance(EmptyAuth(), IAuthProvider)
