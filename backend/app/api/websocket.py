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
import logging

from backend.app.api.middleware import authenticate_websocket, get_container
from backend.app.domain.errors import AuthenticationError
from backend.app.domain.models import RunEvent
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
