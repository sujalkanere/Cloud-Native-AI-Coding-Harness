"""
Docker Sandbox Environment for Cloud-Native AI Coding Harness.
Implements ISandboxEnvironment (IExecutionTerminal, IFileAccess, ILogStreamer) via docker SDK.
Adheres strictly to Spec §3.2, §5.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Any

from backend.app.domain.errors import DomainError, PathTraversalError
from backend.app.domain.interfaces import ISandboxEnvironment
from backend.app.domain.models import ExecEvent, LogEvent
from backend.app.infrastructure.sandbox.transfer import SandboxTransferManager

logger = logging.getLogger(__name__)


class DockerSandboxEnvironment(ISandboxEnvironment):
    """
    Concrete sandbox environment wrapping a Docker container.
    Satisfies ISandboxEnvironment protocol.
    """

    def __init__(self, client: Any, container: Any) -> None:
        self._client = client
        self._container = container
        self._id = container.id if hasattr(container, "id") else str(container)
        self._is_stopped = False
        self._current_exec_id: str | None = None
        self._log_history: list[LogEvent] = []
        self._subscribers: set[asyncio.Queue[LogEvent]] = set()

    @property
    def id(self) -> str:
        return self._id

    async def start(self) -> None:
        """Starts container if not already running."""
        def _start() -> None:
            container = self._client.containers.get(self._id)
            if container.status != "running":
                container.start()
        await asyncio.to_thread(_start)

    async def stop(self) -> None:
        """Idempotently stops and removes the container."""
        if self._is_stopped:
            return
        self._is_stopped = True

        def _teardown() -> None:
            try:
                container = self._client.containers.get(self._id)
                container.remove(force=True)
            except (OSError, KeyError, AttributeError, DomainError) as exc:
                logger.debug("Container %s already removed: %s", self._id, exc)


        await asyncio.to_thread(_teardown)

    def _validate_workspace_path(self, path: str) -> str:
        """
        Validates path within /workspace, rejecting directory traversal attempts.
        Returns normalized absolute POSIX path under /workspace.
        """
        if not path or "\0" in path:
            raise PathTraversalError("Path cannot be empty or contain null bytes.")

        # Convert backslashes
        posix = PurePosixPath(path.replace("\\", "/"))

        # If absolute, must begin with /workspace
        if posix.is_absolute():
            parts = posix.parts
            if len(parts) < 2 or parts[1] != "workspace":
                raise PathTraversalError(f"Absolute path '{path}' is outside /workspace")
            rel_parts = parts[2:]
        else:
            rel_parts = posix.parts

        # Check for traversal components
        resolved_parts: list[str] = []
        for part in rel_parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved_parts:
                    raise PathTraversalError(f"Path '{path}' escapes /workspace boundary")
                resolved_parts.pop()
            else:
                resolved_parts.append(part)

        return "/workspace" + ("/" + "/".join(resolved_parts) if resolved_parts else "")

    # ================= IFileAccess =================

    async def read_file(self, path: str) -> str:
        valid_path = self._validate_workspace_path(path)

        def _read() -> str:
            exec_res = self._client.api.exec_create(
                container=self._id,
                cmd=["cat", valid_path],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            out = self._client.api.exec_start(exec_id, detach=False)
            inspect_res = self._client.api.exec_inspect(exec_id)
            if inspect_res.get("ExitCode", 0) != 0:
                raise FileNotFoundError(f"File not found: {path}")
            return out.decode("utf-8") if isinstance(out, bytes) else str(out)

        return await asyncio.to_thread(_read)

    async def write_file(self, path: str, content: str) -> None:
        valid_path = self._validate_workspace_path(path)
        parent_dir = str(PurePosixPath(valid_path).parent)
        content_bytes = content.encode("utf-8")
        b64_str = base64.b64encode(content_bytes).decode("ascii")

        def _write() -> None:
            # 1. Create parent dir
            self._client.api.exec_create(
                container=self._id,
                cmd=["mkdir", "-p", parent_dir],
                user="1000:1000",
            )
            # 2. Write file via base64 decode
            exec_res = self._client.api.exec_create(
                container=self._id,
                cmd=["sh", "-c", 'printf "%s" "$1" | base64 -d > "$2"', "_", b64_str, valid_path],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            out = self._client.api.exec_start(exec_id, detach=False)
            inspect_res = self._client.api.exec_inspect(exec_id)
            if inspect_res.get("ExitCode", 0) != 0:
                raise DomainError(f"Failed to write file {path}: {out}")

        await asyncio.to_thread(_write)

    async def list_dir(self, path: str = ".") -> list[str]:
        valid_path = self._validate_workspace_path(path) if path not in (".", "") else "/workspace"

        def _list() -> list[str]:
            exec_res = self._client.api.exec_create(
                container=self._id,
                cmd=["sh", "-c", 'find "$1" -maxdepth 1 -mindepth 1 -printf "%f\\n" | sort', "_", valid_path],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            out = self._client.api.exec_start(exec_id, detach=False)
            inspect_res = self._client.api.exec_inspect(exec_id)
            if inspect_res.get("ExitCode", 0) != 0:
                raise FileNotFoundError(f"Directory not found: {path}")
            text = out.decode("utf-8") if isinstance(out, bytes) else str(out)
            return [line.strip() for line in text.splitlines() if line.strip()]

        return await asyncio.to_thread(_list)

    async def upload_workspace(self, tar_gz: bytes) -> None:
        await SandboxTransferManager.upload_tarball_to_workspace(
            client=self._client,
            container_id=self._id,
            tar_gz_bytes=tar_gz,
        )

    async def download_workspace(self) -> bytes:
        return await SandboxTransferManager.download_workspace_tarball(
            client=self._client,
            container_id=self._id,
        )

    # ================= IExecutionTerminal =================

    async def run(
        self,
        command: str,
        cwd: str = "/workspace",
        timeout: float | None = None,
    ) -> AsyncIterator[ExecEvent]:
        valid_cwd = self._validate_workspace_path(cwd)

        # Wrap command to record PID for cancellation
        wrapped_command = f"echo $$ > /tmp/.exec.pid && exec {command}"

        exec_res = await asyncio.to_thread(
            self._client.api.exec_create,
            container=self._id,
            cmd=["sh", "-c", wrapped_command],
            workdir=valid_cwd,
            user="1000:1000",
            stdout=True,
            stderr=True,
        )
        exec_id = exec_res["Id"]
        self._current_exec_id = exec_id

        queue: asyncio.Queue[ExecEvent | None] = asyncio.Queue()

        def _stream_output() -> None:
            # stream=True, demux=True yields (stdout_chunk, stderr_chunk)
            stream_gen = self._client.api.exec_start(exec_id, stream=True, demux=True)
            for stdout_data, stderr_data in stream_gen:
                if stdout_data:
                    text = stdout_data.decode("utf-8", errors="replace")
                    queue.put_nowait(ExecEvent(stream="stdout", data=text))
                    self._emit_log("stdout", text)
                if stderr_data:
                    text = stderr_data.decode("utf-8", errors="replace")
                    queue.put_nowait(ExecEvent(stream="stderr", data=text))
                    self._emit_log("stderr", text)

        stream_task = asyncio.to_thread(_stream_output)

        timed_out = False
        try:
            if timeout is not None:
                await asyncio.wait_for(stream_task, timeout=timeout)
            else:
                await stream_task
        except TimeoutError:
            timed_out = True
            await self.cancel_current()
        finally:
            self._current_exec_id = None

        # Inspect exit code
        if timed_out:
            exit_code = 124
            timeout_msg = f"Command timed out after {timeout} seconds\n"
            yield ExecEvent(stream="stderr", data=timeout_msg)
            self._emit_log("stderr", timeout_msg)
        else:
            inspect_res = await asyncio.to_thread(self._client.api.exec_inspect, exec_id)
            exit_code = inspect_res.get("ExitCode", 0)

        # Drain queue
        while not queue.empty():
            ev = queue.get_nowait()
            if ev is not None:
                yield ev

        exit_event = ExecEvent(stream="exit", exit_code=exit_code)
        yield exit_event
        self._emit_log("system", f"Process exited with code {exit_code}\n")

    async def cancel_current(self) -> None:
        """Cancels in-flight exec process in container."""
        def _cancel() -> None:
            try:
                # Read pid and kill process group
                self._client.api.exec_create(
                    container=self._id,
                    cmd=["sh", "-c", "kill -TERM -$(cat /tmp/.exec.pid 2>/dev/null) 2>/dev/null || true"],
                    user="1000:1000",
                )
            except (OSError, KeyError, AttributeError, DomainError) as exc:
                logger.debug("Failed sending cancel signal: %s", exc)


        await asyncio.to_thread(_cancel)

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
        for ev in list(self._log_history):
            yield ev

        q: asyncio.Queue[LogEvent] = asyncio.Queue()
        self._subscribers.add(q)
        try:
            while not self._is_stopped:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue
        finally:
            self._subscribers.discard(q)
