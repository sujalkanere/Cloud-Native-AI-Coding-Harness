"""
Security and Multi-User Isolation Tests for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.5, §7, §8:
- Per-User Isolation: Cross-user run access strictly returns 404 (NEVER 403, preventing run ID existence leakage).
- WebSocket cross-user connection rejection with application close code 4404.
- User-scoped run listing (GET /api/runs returns only runs owned by authenticated user).
- S3 artifact keys strictly namespaced: artifacts/{user_id}/{run_id}/...
- Unauthenticated requests rejected with 401 Unauthorized / 4401 on WebSocket.
"""
from __future__ import annotations

import pytest
from backend.app.infrastructure.storage.s3 import S3ObjectStorage
from starlette.websockets import WebSocketDisconnect


def test_cross_user_run_isolation_returns_404(clerk_setup):
    """
    Asserts that if User A creates a run, User B receives HTTP 404 Not Found
    across all REST endpoints (GET /runs/{id}, POST /pause, POST /resume,
    POST /terminate, POST /guidance, GET /events, GET /artifacts, GET /diff).
    Asserts HTTP 403 is NEVER returned, strictly preventing run ID enumeration.
    """
    helper, _container, _app, client = clerk_setup

    alice_token = helper.generate_token(user_id="user_alice", email="alice@test.com")
    bob_token = helper.generate_token(user_id="user_bob", email="bob@test.com")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # 1. Alice creates a run
    resp = client.post(
        "/api/runs",
        json={"task": "Alice's secret task"},
        headers=alice_headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # 2. Bob attempts to access Alice's run across all endpoints
    # GET /api/runs/{id}
    resp_get = client.get(f"/api/runs/{run_id}", headers=bob_headers)
    assert resp_get.status_code == 404, "Cross-user GET must return 404, not 403 or 200"

    # POST /api/runs/{id}/pause
    resp_pause = client.post(f"/api/runs/{run_id}/pause", json={"mode": "boundary"}, headers=bob_headers)
    assert resp_pause.status_code == 404, "Cross-user pause must return 404"

    # POST /api/runs/{id}/resume
    resp_resume = client.post(f"/api/runs/{run_id}/resume", headers=bob_headers)
    assert resp_resume.status_code == 404, "Cross-user resume must return 404"

    # POST /api/runs/{id}/terminate
    resp_term = client.post(f"/api/runs/{run_id}/terminate", headers=bob_headers)
    assert resp_term.status_code == 404, "Cross-user terminate must return 404"

    # POST /api/runs/{id}/guidance
    resp_guide = client.post(
        f"/api/runs/{run_id}/guidance",
        json={"message": "malicious guidance"},
        headers=bob_headers,
    )
    assert resp_guide.status_code == 404, "Cross-user guidance must return 404"

    # GET /api/runs/{id}/events
    resp_events = client.get(f"/api/runs/{run_id}/events", headers=bob_headers)
    assert resp_events.status_code == 404, "Cross-user events must return 404"

    # GET /api/runs/{id}/artifacts
    resp_artifacts = client.get(f"/api/runs/{run_id}/artifacts", headers=bob_headers)
    assert resp_artifacts.status_code == 404, "Cross-user artifacts must return 404"

    # GET /api/runs/{id}/diff
    resp_diff = client.get(f"/api/runs/{run_id}/diff", headers=bob_headers)
    assert resp_diff.status_code == 404, "Cross-user diff must return 404"


def test_cross_user_websocket_rejected_with_4404(clerk_setup):
    """
    Asserts that if Bob attempts to open a WebSocket stream on Alice's run,
    the connection is rejected with close code 4404 (Run Not Found).
    """
    helper, _container, _app, client = clerk_setup

    alice_token = helper.generate_token(user_id="user_alice")
    bob_token = helper.generate_token(user_id="user_bob")

    # Alice creates a run
    resp = client.post(
        "/api/runs",
        json={"task": "Alice's stream task"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Bob attempts WebSocket connection with his own valid token
    try:
        with client.websocket_connect(f"/api/runs/{run_id}/stream?token={bob_token}") as ws:
            ws.receive_text()
            pytest.fail("WebSocket should have been closed with 4404")
    except WebSocketDisconnect as exc:
        assert exc.code == 4404, f"Expected close code 4404, got {exc.code}"


def test_user_run_listing_scoped(clerk_setup):
    """
    Asserts GET /api/runs returns only runs belonging to the authenticated user.
    """
    helper, _container, _app, client = clerk_setup

    alice_token = helper.generate_token(user_id="user_alice")
    bob_token = helper.generate_token(user_id="user_bob")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Alice creates 2 runs
    client.post("/api/runs", json={"task": "Alice task 1"}, headers=alice_headers)
    client.post("/api/runs", json={"task": "Alice task 2"}, headers=alice_headers)

    # Bob creates 1 run
    client.post("/api/runs", json={"task": "Bob task 1"}, headers=bob_headers)

    # Verify Alice's list
    alice_runs = client.get("/api/runs", headers=alice_headers).json()
    assert len(alice_runs) == 2
    for r in alice_runs:
        assert r["user_id"] == "user_alice"

    # Verify Bob's list
    bob_runs = client.get("/api/runs", headers=bob_headers).json()
    assert len(bob_runs) == 1
    assert bob_runs[0]["user_id"] == "user_bob"


def test_s3_artifact_keys_user_partitioned():
    """
    Asserts S3 artifact keys are strictly partitioned by user_id and run_id.
    """
    user_id = "user_victim_123"
    run_id = "run_abc_456"

    patch_key = S3ObjectStorage.build_artifact_key(user_id, run_id, "patch.diff")
    assert patch_key == f"artifacts/{user_id}/{run_id}/patch.diff"

    logs_key = S3ObjectStorage.build_artifact_key(user_id, run_id, "logs.txt")
    assert logs_key == f"artifacts/{user_id}/{run_id}/logs.txt"

    transcript_key = S3ObjectStorage.build_artifact_key(user_id, run_id, "transcript.json")
    assert transcript_key == f"artifacts/{user_id}/{run_id}/transcript.json"

    # Validate key prefix helper
    assert S3ObjectStorage.validate_artifact_key(patch_key, user_id, run_id) is True
    # Attempt cross-user access with same key
    assert S3ObjectStorage.validate_artifact_key(patch_key, "user_attacker", run_id) is False


def test_unauthenticated_request_rejected(clerk_setup):
    """
    Asserts unauthenticated requests return 401 Unauthorized or close code 4401.
    """
    _helper, _container, _app, client = clerk_setup

    # Unauthenticated HTTP GET
    resp = client.get("/api/runs")
    assert resp.status_code == 401

    # Unauthenticated WebSocket
    try:
        with client.websocket_connect("/api/runs/any_run_id/stream") as ws:
            ws.receive_text()
            pytest.fail("Unauthenticated WebSocket should have been rejected")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401
