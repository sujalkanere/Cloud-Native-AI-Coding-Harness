"""
Integration Tests for REST Endpoints, Controls, Idempotency, and Readiness Probes.

Adheres strictly to Spec §3.4, §3.5, §7, §8:
- POST /api/runs: JSON and multipart upload with 50MB limit (MAX_UPLOAD_MB), SSRF guard.
- Control state transitions and idempotency:
    - Pause: 409 in PREPARING, 200 in RUNNING (boundary sets is_pausing, now sets PAUSED), 200 in PAUSED.
    - Resume: 200 cancels boundary pause, 200 resumes PAUSED, 200 on RUNNING, 409 on QUEUED/terminal.
    - Terminate: 200 on RUNNING/PAUSED/QUEUED, idempotent 200 on TERMINATED, 409 on SUCCEEDED/FAILED.
    - Guidance: 200 on active, 422 on empty, 409 on terminal.
- GET /api/runs/{id}/events: filtered polling after=seq.
- GET /api/runs/{id}/artifacts: presigned URLs with user-namespaced keys.
- GET /api/runs/{id}/diff: per-file before/after diff parsing.
- Health: /healthz 200 OK, /readyz 503 until healthy.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import botocore.exceptions
import pytest
import sqlalchemy.exc
from backend.app.domain.models import Run, RunStatus


def test_create_run_json_success(test_client):
    """Asserts JSON payload creates run returning 201 Created."""
    resp = test_client.post(
        "/api/runs",
        json={"task": "Fix calculator bug", "repo_url": "https://github.com/example/repo.git"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["task"] == "Fix calculator bug"
    assert data["repo_url"] == "https://github.com/example/repo.git"
    assert data["status"] in ("QUEUED", "PREPARING")


def test_create_run_multipart_success(test_client):
    """Asserts multipart/form-data upload creates run returning 201 Created."""
    archive_content = b"fake tarball archive bytes"
    files = {"archive": ("workspace.tar.gz", io.BytesIO(archive_content), "application/gzip")}
    data = {"task": "Multipart task upload", "repo_url": "https://github.com/example/repo2.git"}

    resp = test_client.post("/api/runs", data=data, files=files)
    assert resp.status_code == 201
    res = resp.json()
    assert res["task"] == "Multipart task upload"
    assert res["id"].startswith("run_")


def test_create_run_upload_limit_413(test_client, test_container):
    """Asserts archive exceeding MAX_UPLOAD_MB is rejected with HTTP 413."""
    # Temporarily set MAX_UPLOAD_MB to 1 MB for testing
    old_limit = test_container.settings.MAX_UPLOAD_MB
    test_container.settings.MAX_UPLOAD_MB = 1
    try:
        oversized = b"x" * (2 * 1024 * 1024)  # 2MB
        files = {"archive": ("large.tar.gz", io.BytesIO(oversized), "application/gzip")}
        resp = test_client.post("/api/runs", data={"task": "Oversized upload"}, files=files)
        assert resp.status_code == 413
        assert "exceeds maximum limit" in resp.json()["detail"].lower()
    finally:
        test_container.settings.MAX_UPLOAD_MB = old_limit


def test_create_run_ssrf_guard_400(test_client):
    """Asserts private/loopback repo URLs are rejected with HTTP 400 Bad Request."""
    resp = test_client.post(
        "/api/runs",
        json={"task": "SSRF attack", "repo_url": "https://127.0.0.1/malicious.git"},
    )
    assert resp.status_code == 400
    assert (
        "disallowed" in resp.json()["detail"].lower()
        or "loopback" in resp.json()["detail"].lower()
        or "ssrf" in resp.json()["detail"].lower()
    )

    resp2 = test_client.post(
        "/api/runs",
        json={"task": "SSRF attack private", "repo_url": "https://192.168.1.1/malicious.git"},
    )
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_control_idempotency_and_conflicts(test_client, in_memory_repo, test_container):
    """
    Tests pause, resume, terminate, and guidance endpoints:
    - State transition validity
    - Control idempotency (matching state returns 200 OK)
    - Conflicting transitions return 409 Conflict
    """
    user_id = "user_dev_001"  # DevAuthProvider default user

    # 1. PREPARING run: pause must return 409 Conflict
    run_prep = Run(id="run_prep", user_id=user_id, task="prep task", status=RunStatus.PREPARING)
    await in_memory_repo.create(run_prep)
    resp = test_client.post(f"/api/runs/{run_prep.id}/pause", json={"mode": "boundary"})
    assert resp.status_code == 409

    # 2. RUNNING run: boundary pause sets is_pausing=True (returns 200 OK)
    run_running = Run(id="run_run", user_id=user_id, task="running task", status=RunStatus.RUNNING)
    await in_memory_repo.create(run_running)
    resp_pause = test_client.post(f"/api/runs/{run_running.id}/pause", json={"mode": "boundary"})
    assert resp_pause.status_code == 200
    # Verify is_pausing updated
    run_state = (await in_memory_repo.get(run_running.id))
    assert run_state.is_pausing is True

    # 3. Resume while is_pausing=True cancels boundary pause (returns 200 OK)
    resp_resume = test_client.post(f"/api/runs/{run_running.id}/resume")
    assert resp_resume.status_code == 200
    run_state = (await in_memory_repo.get(run_running.id))
    assert run_state.is_pausing is False

    # 4. Now pause on RUNNING enters PAUSED
    resp_now = test_client.post(f"/api/runs/{run_running.id}/pause", json={"mode": "now"})
    assert resp_now.status_code == 200
    run_state = (await in_memory_repo.get(run_running.id))
    assert run_state.status == RunStatus.PAUSED

    # 5. Idempotent pause on PAUSED returns 200 OK
    resp_pause_idempotent = test_client.post(f"/api/runs/{run_running.id}/pause", json={"mode": "now"})
    assert resp_pause_idempotent.status_code == 200

    # 6. Resume from PAUSED transitions back to RUNNING
    resp_resume_paused = test_client.post(f"/api/runs/{run_running.id}/resume")
    assert resp_resume_paused.status_code == 200
    run_state = (await in_memory_repo.get(run_running.id))
    assert run_state.status == RunStatus.RUNNING

    # 7. Idempotent resume on RUNNING returns 200 OK
    resp_resume_idempotent = test_client.post(f"/api/runs/{run_running.id}/resume")
    assert resp_resume_idempotent.status_code == 200

    # 8. Resume on QUEUED returns 409 Conflict
    run_queued = Run(id="run_queued", user_id=user_id, task="queued task", status=RunStatus.QUEUED)
    await in_memory_repo.create(run_queued)
    resp_resume_queued = test_client.post(f"/api/runs/{run_queued.id}/resume")
    assert resp_resume_queued.status_code == 409

    # 9. Terminate on QUEUED / RUNNING returns 200 OK
    resp_term_queued = test_client.post(f"/api/runs/{run_queued.id}/terminate")
    assert resp_term_queued.status_code == 200
    assert (await in_memory_repo.get(run_queued.id)).status == RunStatus.TERMINATED

    # 10. Idempotent terminate on TERMINATED returns 200 OK
    resp_term_idempotent = test_client.post(f"/api/runs/{run_queued.id}/terminate")
    assert resp_term_idempotent.status_code == 200

    # 11. Terminate on SUCCEEDED or FAILED returns 409 Conflict
    run_succ = Run(id="run_succ", user_id=user_id, task="done", status=RunStatus.SUCCEEDED)
    await in_memory_repo.create(run_succ)
    resp_term_succ = test_client.post(f"/api/runs/{run_succ.id}/terminate")
    assert resp_term_succ.status_code == 409


@pytest.mark.asyncio
async def test_guidance_endpoint(test_client, in_memory_repo, test_container):
    """Asserts guidance injection validation and status handling."""
    user_id = "user_dev_001"
    run = Run(id="run_guide", user_id=user_id, task="guidance task", status=RunStatus.RUNNING)
    await in_memory_repo.create(run)

    # Empty message returns 422
    resp_empty = test_client.post(f"/api/runs/{run.id}/guidance", json={"message": "   "})
    assert resp_empty.status_code == 422

    # Terminal run guidance returns 409 Conflict
    run_term = Run(id="run_t", user_id=user_id, task="term task", status=RunStatus.TERMINATED)
    await in_memory_repo.create(run_term)
    resp_term = test_client.post(f"/api/runs/{run_term.id}/guidance", json={"message": "too late"})
    assert resp_term.status_code == 409


@pytest.mark.asyncio
async def test_events_polling_filter(test_client, in_memory_repo):
    """Asserts GET /api/runs/{id}/events?after=seq returns events strictly > after."""
    user_id = "user_dev_001"
    run = Run(id="run_ev", user_id=user_id, task="event poll task")
    await in_memory_repo.create(run)

    for i in range(1, 6):
        await in_memory_repo.append_event(run.id, {"type": f"event_{i}", "payload": {"n": i}})

    resp = test_client.get(f"/api/runs/{run.id}/events?after=2")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 3
    assert [e["seq"] for e in events] == [3, 4, 5]


@pytest.mark.asyncio
async def test_artifacts_presigned_urls(test_client, in_memory_repo):
    """Asserts GET /api/runs/{id}/artifacts returns presigned S3 URLs."""
    user_id = "user_dev_001"
    run = Run(id="run_art", user_id=user_id, task="artifact task")
    await in_memory_repo.create(run)

    resp = test_client.get(f"/api/runs/{run.id}/artifacts")
    assert resp.status_code == 200
    data = resp.json()
    assert "patch_url" in data
    assert "logs_url" in data
    assert "transcript_url" in data
    assert f"artifacts/{user_id}/{run.id}/patch.diff" in data["patch_url"]


@pytest.mark.asyncio
async def test_diff_endpoint(test_client, in_memory_repo, in_memory_storage):
    """Asserts GET /api/runs/{id}/diff parses unified diff into FileDiff list."""
    user_id = "user_dev_001"
    run = Run(id="run_diff", user_id=user_id, task="diff task", baseline_sha="abcd" * 10)
    await in_memory_repo.create(run)

    # Store a sample unified diff in S3
    patch_text = (
        "diff --git a/calc.py b/calc.py\n"
        "index 123..456 100644\n"
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def add(a, b): return a - b\n"
        "+def add(a, b): return a + b\n"
    )
    patch_key = f"artifacts/{user_id}/{run.id}/patch.diff"
    await in_memory_storage.put(patch_key, patch_text.encode("utf-8"))

    resp = test_client.get(f"/api/runs/{run.id}/diff")
    assert resp.status_code == 200
    diffs = resp.json()
    assert len(diffs) == 1
    assert diffs[0]["path"] == "calc.py"
    assert diffs[0]["status"] == "modified"
    assert diffs[0]["additions"] == 1
    assert diffs[0]["deletions"] == 1


def test_health_and_readiness_probes(test_client, test_container):
    """Asserts /healthz returns 200 OK and /readyz checks all 4 dependencies."""
    # 1. Liveness probe
    resp_liveness = test_client.get("/healthz")
    assert resp_liveness.status_code == 200
    assert resp_liveness.json() == {"status": "ok"}

    # 2. Readiness probe (with test container, dependencies report healthy)
    resp_readiness = test_client.get("/readyz")
    assert resp_readiness.status_code == 200
    assert resp_readiness.json()["status"] == "ready"
    assert "database" in resp_readiness.json()["dependencies"]
    assert "storage" in resp_readiness.json()["dependencies"]
    assert "docker_proxy" in resp_readiness.json()["dependencies"]
    assert "sandbox_image" in resp_readiness.json()["dependencies"]


def test_readiness_probe_db_operational_error(test_client, test_container):
    """Asserts /readyz returns 503 Service Unavailable when DB raises OperationalError."""

    class FailingSessionContext:
        async def __aenter__(self):
            raise sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception("Connection refused"))

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    test_container.session_factory = FailingSessionContext
    try:
        resp = test_client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert "unhealthy" in data["dependencies"]["database"]
        assert "Connection refused" in data["dependencies"]["database"]
    finally:
        test_container.session_factory = None


def test_readiness_probe_storage_connection_error(test_client, test_container):
    """Asserts /readyz returns 503 Service Unavailable when storage raises EndpointConnectionError."""
    old_ensure = getattr(test_container.storage, "ensure_bucket_exists", None)
    test_container.storage.ensure_bucket_exists = AsyncMock(
        side_effect=botocore.exceptions.EndpointConnectionError(endpoint_url="https://s3.local")
    )
    try:
        resp = test_client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert "unhealthy" in data["dependencies"]["storage"]
        assert "Could not connect to the endpoint URL" in data["dependencies"]["storage"]
    finally:
        if old_ensure is not None:
            test_container.storage.ensure_bucket_exists = old_ensure


def test_readiness_probe_docker_image_not_found_error(test_client, test_container):
    """Asserts /readyz returns 503 Service Unavailable when docker image lookup fails."""

    class MockDockerClient:
        def ping(self):
            return True

        @property
        def images(self):
            mock_images = MagicMock()
            mock_images.get.side_effect = Exception("Image 'harness-sandbox:latest' not found")
            return mock_images

    class MockDockerProvider:
        def _get_client(self):
            return MockDockerClient()

    old_provider = test_container.sandbox_provider
    test_container.sandbox_provider = MockDockerProvider()
    try:
        resp = test_client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert data["dependencies"]["docker_proxy"] == "healthy"
        assert "unhealthy" in data["dependencies"]["sandbox_image"]
        assert "Image 'harness-sandbox:latest' not found" in data["dependencies"]["sandbox_image"]
    finally:
        test_container.sandbox_provider = old_provider

