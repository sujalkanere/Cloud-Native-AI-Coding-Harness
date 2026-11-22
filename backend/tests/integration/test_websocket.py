"""
Integration Tests for WebSocket Streaming, Historical Replay, and Reconnection Deduplication.

Adheres strictly to Spec §3.5, §7, §8:
- WS /api/runs/{id}/stream?after=seq&token=...
- Query param token authentication via configured IAuthProvider.
- Replay of historical events with seq > after.
- Real-time live event streaming from publish_event.
- Reconnection deduplication.
"""
from __future__ import annotations

import json

import pytest
from backend.app.domain.models import Run
from starlette.websockets import WebSocketDisconnect


def test_websocket_dev_auth_connect(test_client, in_memory_repo):
    """Asserts dev auth connects to WebSocket without requiring token."""
    user_id = "user_dev_001"
    run = Run(id="run_ws_dev", user_id=user_id, task="dev ws task")
    # Pre-populate run
    import asyncio
    asyncio.run(in_memory_repo.create(run))

    with test_client.websocket_connect(f"/api/runs/{run.id}/stream") as ws:
        # Connection succeeds and remains open
        assert ws is not None


def test_websocket_clerk_auth_valid_token(clerk_setup):
    """Asserts Clerk authentication succeeds when valid JWT is supplied in query string."""
    helper, container, _app, client = clerk_setup

    token = helper.generate_token(user_id="user_carol")
    run = Run(id="run_ws_clerk", user_id="user_carol", task="clerk ws task")

    import asyncio
    asyncio.run(container.run_repository.create(run))

    with client.websocket_connect(f"/api/runs/{run.id}/stream?token={token}") as ws:
        assert ws is not None


def test_websocket_invalid_token_rejected(clerk_setup):
    """Asserts connection with invalid token is rejected with close code 4401."""
    _helper, container, _app, client = clerk_setup

    run = Run(id="run_ws_bad", user_id="user_david", task="bad token task")
    import asyncio
    asyncio.run(container.run_repository.create(run))

    try:
        with client.websocket_connect(f"/api/runs/{run.id}/stream?token=invalid.garbage.jwt") as ws:
            ws.receive_text()
            pytest.fail("WebSocket should have been rejected with 4401")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401


def test_websocket_replay_historical_events(test_client, in_memory_repo):
    """Asserts WebSocket replays past events with seq > after in order."""
    user_id = "user_dev_001"
    run = Run(id="run_ws_replay", user_id=user_id, task="replay task")

    import asyncio
    async def prep_events():
        await in_memory_repo.create(run)
        for i in range(1, 6):
            await in_memory_repo.append_event(
                run.id,
                {"type": "step", "payload": {"step_num": i}},
            )
    asyncio.run(prep_events())

    # Connect with after=2 -> Expect events 3, 4, 5
    with test_client.websocket_connect(f"/api/runs/{run.id}/stream?after=2") as ws:
        ev3 = json.loads(ws.receive_text())
        assert ev3["seq"] == 3
        assert ev3["payload"]["step_num"] == 3

        ev4 = json.loads(ws.receive_text())
        assert ev4["seq"] == 4
        assert ev4["payload"]["step_num"] == 4

        ev5 = json.loads(ws.receive_text())
        assert ev5["seq"] == 5
        assert ev5["payload"]["step_num"] == 5


@pytest.mark.asyncio
async def test_websocket_live_event_streaming_and_reconnect_dedup(test_container, test_app):
    """
    Asserts live events published via publish_event are streamed over WebSocket,
    and client reconnecting with after=last_seq receives only new events with no duplicates.
    """
    from starlette.testclient import TestClient
    client = TestClient(test_app)

    user_id = "user_dev_001"
    run = Run(id="run_ws_live", user_id=user_id, task="live stream task")
    await test_container.run_repository.create(run)

    # Publish 2 events before connection
    await test_container.concurrency_manager.publish_event(
        run.id,
        {"type": "pre_event", "payload": {"index": 1}},
    )
    await test_container.concurrency_manager.publish_event(
        run.id,
        {"type": "pre_event", "payload": {"index": 2}},
    )

    # 1. Connect first time with after=0
    with client.websocket_connect(f"/api/runs/{run.id}/stream?after=0") as ws1:
        e1 = json.loads(ws1.receive_text())
        assert e1["seq"] == 1
        e2 = json.loads(ws1.receive_text())
        assert e2["seq"] == 2

        # Publish a live event while connected
        await test_container.concurrency_manager.publish_event(
            run.id,
            {"type": "live_event", "payload": {"message": "hello live"}},
        )
        e3 = json.loads(ws1.receive_text())
        assert e3["seq"] == 3
        assert e3["payload"]["message"] == "hello live"

    # 2. Client reconnects with after=3 (reconnection deduplication)
    # Publish event 4 before and event 5 after reconnect
    await test_container.concurrency_manager.publish_event(
        run.id,
        {"type": "post_event", "payload": {"index": 4}},
    )

    with client.websocket_connect(f"/api/runs/{run.id}/stream?after=3") as ws2:
        e4 = json.loads(ws2.receive_text())
        assert e4["seq"] == 4, "Client should receive event 4, never re-receiving 1..3"

        # Publish live event 5
        await test_container.concurrency_manager.publish_event(
            run.id,
            {"type": "post_event", "payload": {"index": 5}},
        )
        e5 = json.loads(ws2.receive_text())
        assert e5["seq"] == 5
