"""
Fake Sandbox Test Support for Cloud-Native AI Coding Harness.
Implements ISandboxEnvironment and ISandboxProvider adhering strictly to Spec §3.2, §5.
Provides a fully substitutable local filesystem and subprocess execution sandbox for tests.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from backend.app.application.archive import create_archive, extract_archive
from backend.app.domain.errors import PathTraversalError
from backend.app.domain.interfaces import ISandboxEnvironment, ISandboxProvider
from backend.app.domain.models import ExecEvent, LogEvent, SandboxSpec


class FakeSandbox(ISandboxEnvironment):
    """
    Substitutable test sandbox running locally using a temporary directory.
    Satisfies ISandboxEnvironment (IExecutionTerminal, IFileAccess, ILogStreamer).
    """

    def __init__(self, spec: SandboxSpec | None = None, sandbox_id: str | None = None) -> None:
        self._id = sandbox_id or f"fake-{uuid.uuid4().hex[:8]}"
        self.spec = spec or SandboxSpec()
        self._temp_dir: str | None = None
        self._workspace: Path | None = None
        self._is_running: bool = False
        self._current_process: asyncio.subprocess.Process | None = None
        self._log_history: list[LogEvent] = []
        self._subscribers: set[asyncio.Queue[LogEvent]] = set()

    @property
    def id(self) -> str:
        return self._id

    async def start(self) -> None:
        """Initializes the temporary directory representing the sandbox filesystem."""
        if not self._is_running:
            self._temp_dir = tempfile.mkdtemp(prefix=f"harness_sandbox_{self._id}_")
            self._workspace = Path(self._temp_dir) / "workspace"
            self._workspace.mkdir(parents=True, exist_ok=True)
            self._is_running = True

    async def stop(self) -> None:
        """Idempotently tears down the temporary sandbox environment."""
        self._is_running = False
        await self.cancel_current()
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except OSError:
                pass
            self._temp_dir = None
            self._workspace = None

    def _resolve_workspace_path(self, path: str) -> Path:
        """
        Resolves path against /workspace and strictly checks against directory traversal.
        Raises PathTraversalError if path escapes /workspace boundary.
        """
        if not self._workspace:
            raise RuntimeError("Sandbox environment has not been started.")

        if not path or "\0" in path:
            raise PathTraversalError("Path cannot be empty or contain null bytes.")

        # Normalize virtual path
        # If absolute path outside /workspace, reject
        clean_path = path.replace("\\", "/")
        if clean_path.startswith("/"):
            if not clean_path.startswith("/workspace"):
                raise PathTraversalError(f"Absolute path '{path}' is outside /workspace")
            rel = clean_path[len("/workspace"):].lstrip("/")
        else:
            rel = clean_path

        # Resolve relative to actual workspace directory
        resolved = (self._workspace / rel).resolve()
        workspace_resolved = self._workspace.resolve()

        try:
            resolved.relative_to(workspace_resolved)
        except ValueError as exc:
            raise PathTraversalError(f"Path '{path}' escapes workspace boundary") from exc

        return resolved

    # ================= IFileAccess =================

    async def read_file(self, path: str) -> str:
        if not self._is_running:
            await self.start()
        target = self._resolve_workspace_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        if not self._is_running:
            await self.start()
        target = self._resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")

    async def list_dir(self, path: str = ".") -> list[str]:
        if not self._is_running:
            await self.start()
        target = self._resolve_workspace_path(path)
        if not target.is_dir():
            raise FileNotFoundError(f"Directory not found: {path}")

        def _scan() -> list[str]:
            entries = []
            for item in sorted(target.iterdir()):
                entries.append(item.name)
            return entries

        return await asyncio.to_thread(_scan)

    async def upload_workspace(self, tar_gz: bytes) -> None:
        if not self._is_running:
            await self.start()
        assert self._workspace is not None
        # Uses extract_archive to validate tarbomb & traversal safety
        await asyncio.to_thread(extract_archive, tar_gz, self._workspace)

    async def download_workspace(self) -> bytes:
        if not self._is_running:
            await self.start()
        assert self._workspace is not None
        return await asyncio.to_thread(create_archive, self._workspace)

    # ================= IExecutionTerminal =================

    async def run(
        self,
        command: str,
        cwd: str = "/workspace",
        timeout: float | None = None,
    ) -> AsyncIterator[ExecEvent]:
        if not self._is_running:
            await self.start()

        target_cwd = self._resolve_workspace_path(cwd)

        # On Windows, normalize python execution to active interpreter
        exec_cmd = command
        if sys.platform == "win32" and (exec_cmd.startswith("python ") or exec_cmd == "python"):
            exec_cmd = f'"{sys.executable}"' + exec_cmd[6:]

        # Launch process
        proc = await asyncio.create_subprocess_shell(
            exec_cmd,
            cwd=str(target_cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "HOME": str(self._workspace),
                "TMPDIR": str(self._workspace),
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self._current_process = proc

        queue: asyncio.Queue[ExecEvent | None] = asyncio.Queue()

        async def _stream_reader(stream: asyncio.StreamReader, stream_name: str) -> None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                event = ExecEvent(stream=stream_name, data=text)
                await queue.put(event)
                self._emit_log(stream_name, text)

        stdout_task = asyncio.create_task(_stream_reader(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(_stream_reader(proc.stderr, "stderr"))

        async def _waiter() -> int:
            await asyncio.gather(stdout_task, stderr_task)
            return await proc.wait()

        timed_out = False
        try:
            if timeout is not None:
                exit_code = await asyncio.wait_for(_waiter(), timeout=timeout)
            else:
                exit_code = await _waiter()
        except TimeoutError:
            timed_out = True
            await self.cancel_current()
            exit_code = 124
        finally:
            self._current_process = None

        # Drain queued events
        while not queue.empty():
            ev = queue.get_nowait()
            if ev is not None:
                yield ev

        if timed_out:
            timeout_msg = f"Command timed out after {timeout} seconds\n"
            yield ExecEvent(stream="stderr", data=timeout_msg)
            self._emit_log("stderr", timeout_msg)

        exit_event = ExecEvent(stream="exit", exit_code=exit_code)
        yield exit_event
        self._emit_log("system", f"Process exited with code {exit_code}\n")

    async def cancel_current(self) -> None:
        proc = self._current_process
        if proc and proc.returncode is None:
            pid = proc.pid
            if os.name == "nt":
                # Kill process tree on Windows
                try:
                    await asyncio.to_thread(os.system, f"taskkill /F /T /PID {pid} >nul 2>&1")
                except OSError:

                    pass
            try:
                proc.terminate()
                await asyncio.sleep(0.02)
                if proc.returncode is None:
                    proc.kill()
            except OSError:
                pass
            self._current_process = None



    # ================= ILogStreamer =================

    def _emit_log(self, stream: str, data: str) -> None:
        log_event = LogEvent(stream=stream, data=data)
        self._log_history.append(log_event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(log_event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[LogEvent]:
        # First yield past logs from history
        for ev in list(self._log_history):
            yield ev

        q: asyncio.Queue[LogEvent] = asyncio.Queue()
        self._subscribers.add(q)
        try:
            while self._is_running:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue
        finally:
            self._subscribers.discard(q)


class FakeSandboxProvider(ISandboxProvider):
    """Substitutable fake sandbox provider for testing."""

    def __init__(self) -> None:
        self.acquired: list[FakeSandbox] = []

    async def acquire(self, spec: SandboxSpec) -> ISandboxEnvironment:
        sandbox = FakeSandbox(spec=spec)
        await sandbox.start()
        self.acquired.append(sandbox)
        return sandbox
