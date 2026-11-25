"""
WebSocket Real-Time Event Streaming for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.5, §7, §8:
- WS /api/runs/{id}/stream?after=seq&token=...
- Query param token authentication via configured IAuthProvider.
- Strict Per-User Isolation: cross-user access closes with code 4404 (strictly 404, never 403).
- Replays historical events with seq > after.
- Real-time live event streaming with reconnection deduplication.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading

from backend.app.api.middleware import authenticate_websocket, get_container
from backend.app.domain.errors import AuthenticationError
from backend.app.domain.models import RunEvent, SandboxSpec
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/runs/{id}/stream")
async def websocket_stream(
    websocket: WebSocket,
    id: str,
) -> None:
    """
    WebSocket endpoint streaming monotonic events for a run.
    Query parameters:
        token: Bearer JWT or dev token
        after: Sequence number for historical event replay (default 0)
    """
    container = get_container(websocket)

    # 1. Authenticate WebSocket connection
    try:
        current_user = await authenticate_websocket(websocket, container)
    except (AuthenticationError, OSError, RuntimeError, ValueError):
        # Connection already closed in authenticate_websocket with code 4401
        return

    # 2. Strict per-user isolation: return 4404 if run not found or belongs to another user
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        await websocket.close(code=4404, reason="Run not found")
        return

    # 3. Accept WebSocket connection
    await websocket.accept()

    # 4. Parse after sequence parameter
    after_seq_str = websocket.query_params.get("after", "0")
    try:
        after_seq = int(after_seq_str)
    except ValueError:
        after_seq = 0

    last_sent_seq = after_seq
    subscriber_queue: asyncio.Queue[RunEvent] | None = None

    try:
        # 5. Subscribe to live queue first to ensure zero events dropped
        if container.concurrency_manager is not None:
            subscriber_queue = await container.concurrency_manager.subscribe(id)

        # 6. Replay historical events
        past_events = await container.run_repository.list_events(id, after_seq=after_seq)
        for ev in past_events:
            await websocket.send_text(ev.model_dump_json())
            last_sent_seq = max(last_sent_seq, ev.seq)

        # 7. Live event streaming loop
        if subscriber_queue is not None:
            while True:
                live_event = await subscriber_queue.get()
                if live_event.seq > last_sent_seq:
                    await websocket.send_text(live_event.model_dump_json())
                    last_sent_seq = live_event.seq
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected from run %s stream.", id)
    except asyncio.CancelledError:
        logger.debug("WebSocket streaming task cancelled for run %s.", id)
    except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("Error in WebSocket streaming for run %s: %s", id, exc)
    finally:
        if subscriber_queue is not None and container.concurrency_manager is not None:
            container.concurrency_manager.unsubscribe(id, subscriber_queue)


@router.websocket("/runs/{id}/terminal")
async def websocket_terminal(
    websocket: WebSocket,
    id: str,
) -> None:
    """
    Bidirectional interactive PTY terminal WebSocket endpoint.
    Allows real-time stdin/stdout streaming for interactive CLI games, shells, and REPLs.
    """
    container = get_container(websocket)
    try:
        current_user = await authenticate_websocket(websocket, container)
    except (AuthenticationError, OSError, RuntimeError, ValueError):
        return

    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        await websocket.close(code=4404, reason="Run not found")
        return

    await websocket.accept()

    # Determine or acquire sandbox for interactive session
    sandbox = None
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            sandbox = handle.control.sandbox

    cleanup_box = False
    if sandbox is None:
        try:
            spec = SandboxSpec(network_mode="none")
            sandbox = await container.sandbox_provider.acquire(spec)
            await sandbox.start()
            cleanup_box = True
        except Exception as exc:
            await websocket.send_text(
                f"\r\n\x1b[33m[Sandbox terminal unavailable: {exc}]\x1b[0m\r\n"
            )
            await websocket.close(code=1011)
            return

        # Replay write_file events to populate workspace
        events = await container.run_repository.list_events(id)
        for ev in events:
            if ev.type == "tool_call" and ev.payload.get("name") == "write_file":
                args = ev.payload.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                p = args.get("path")
                c = args.get("content")
                if p and c is not None:
                    try:
                        await sandbox.write_file(p, c)
                    except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                        pass

    # Check if sandbox is DockerSandboxEnvironment
    is_docker = hasattr(sandbox, "_client") and hasattr(sandbox, "_id")

    if is_docker:
        client = sandbox._client
        container_id = sandbox._id
        exec_inst = client.api.exec_create(
            container_id,
            cmd=["/bin/bash"],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
            workdir="/workspace",
            user="1000:1000",
            environment={"TERM": "xterm-256color", "PYTHONUNBUFFERED": "1", "PS1": "\\u@sandbox:\\w$ "},
        )
        sock = client.api.exec_start(exec_inst["Id"], socket=True, tty=True)
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _socket_reader() -> None:
            while True:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    loop.call_soon_threadsafe(q.put_nowait, data)
                except Exception:
                    break
            loop.call_soon_threadsafe(q.put_nowait, None)

        reader_thread = threading.Thread(target=_socket_reader, daemon=True)
        reader_thread.start()

        async def _forward_to_ws() -> None:
            while True:
                data = await q.get()
                if data is None:
                    break
                await websocket.send_text(data.decode("utf-8", errors="replace"))

        async def _forward_from_ws() -> None:
            while True:
                msg = await websocket.receive_text()
                sock.send(msg.encode("utf-8"))

        forward_task = asyncio.create_task(_forward_to_ws())
        try:
            await _forward_from_ws()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            forward_task.cancel()
            try:
                sock.close()
            except Exception:
                pass
            if cleanup_box:
                await sandbox.stop()
    else:
        # Local subprocess shell
        exec_shell = "cmd.exe" if sys.platform == "win32" else "/bin/bash"
        proc = await asyncio.create_subprocess_shell(
            exec_shell,
            cwd=str(sandbox._workspace),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        async def _forward_to_ws_subproc() -> None:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await websocket.send_text(chunk.decode("utf-8", errors="replace"))

        async def _forward_from_ws_subproc() -> None:
            while True:
                msg = await websocket.receive_text()
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(msg.encode("utf-8"))
                    await proc.stdin.drain()

        forward_task = asyncio.create_task(_forward_to_ws_subproc())
        try:
            await _forward_from_ws_subproc()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            forward_task.cancel()
            try:
                proc.terminate()
            except Exception:
                pass
            if cleanup_box:
                await sandbox.stop()
