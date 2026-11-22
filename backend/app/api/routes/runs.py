"""
Run Management and Control REST Routes for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.4, §3.5, §8:
- POST /api/runs: JSON / multipart upload with 50MB limit (MAX_UPLOAD_MB=50), SSRF validation.
- GET /api/runs: List runs for current authenticated user.
- GET /api/runs/{id}: Get run details including is_pausing: bool.
- POST /api/runs/{id}/pause: boundary vs now pause, 409 in PREPARING, idempotent 200 in PAUSED.
- POST /api/runs/{id}/resume: clears is_pausing on cancel, 409 in QUEUED/terminal, idempotent 200 in RUNNING.
- POST /api/runs/{id}/terminate: halts run, destroys sandbox, idempotent 200 on TERMINATED.
- POST /api/runs/{id}/guidance: injects guidance event.
- GET /api/runs/{id}/events?after=seq: sequential event retrieval strictly > after.
- GET /api/runs/{id}/artifacts: presigned S3 URLs (artifacts/{user_id}/{run_id}/...).
- GET /api/runs/{id}/diff: per-file before/after diff for viewer.
- Strict per-user isolation: returns 404 EntityNotFoundError for any run not owned by current user.
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any, Literal

from backend.app.api.middleware import get_container, get_current_user
from backend.app.application.diff import compute_diff, parse_diff_files
from backend.app.application.ssrf import validate_repo_url
from backend.app.bootstrap import AppContainer
from backend.app.domain.errors import EntityNotFoundError
from backend.app.domain.models import (
    AuthenticatedUser,
    FileDiff,
    Run,
    RunEvent,
    RunOptions,
    RunStatus,
)
from backend.app.infrastructure.storage.s3 import S3ObjectStorage
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


class PauseRequest(BaseModel):
    mode: Literal["boundary", "now"] = "boundary"


class GuidanceRequest(BaseModel):
    message: str


class TerminateRequest(BaseModel):
    reason: str = "User terminated"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Run)
async def create_run(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> Run:
    """
    Submits a new run.
    Accepts JSON body or multipart/form-data with optional archive upload.
    Enforces MAX_UPLOAD_MB limit (50 MB) and SSRF repo_url validation.
    """
    content_type = request.headers.get("content-type", "")
    max_upload_bytes = container.settings.MAX_UPLOAD_MB * 1024 * 1024

    task: str = ""
    repo_url: str | None = None
    options: RunOptions = RunOptions()
    archive_bytes: bytes | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        task_val = form.get("task")
        if not task_val or not str(task_val).strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'task' is required",
            )
        task = str(task_val)

        repo_val = form.get("repo_url")
        if repo_val and str(repo_val).strip():
            repo_url = str(repo_val).strip()

        options_val = form.get("options")
        if options_val:
            try:
                opts_dict = json.loads(str(options_val))
                options = RunOptions.model_validate(opts_dict)
            except (json.JSONDecodeError, ValueError, KeyError) as opt_err:
                logger.debug("Failed parsing options from form: %s", opt_err)

        archive_field = form.get("archive")
        if archive_field is not None and hasattr(archive_field, "read"):
            archive_bytes = await archive_field.read()
    else:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON: {exc}",
            )

        task_val = body.get("task")
        if not task_val or not str(task_val).strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'task' is required",
            )
        task = str(task_val)

        repo_val = body.get("repo_url")
        if repo_val and str(repo_val).strip():
            repo_url = str(repo_val).strip()

        if "options" in body and body["options"] is not None:
            options = RunOptions.model_validate(body["options"])

        if body.get("archive"):
            try:
                archive_bytes = base64.b64decode(body["archive"])
            except (ValueError, KeyError) as b64_err:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid base64 archive data: {b64_err}",
                )

    # Size limit validation
    if archive_bytes is not None and len(archive_bytes) > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archive size exceeds maximum limit of {container.settings.MAX_UPLOAD_MB} MB",
        )

    # SSRF guard on repository URL
    if repo_url is not None:
        validate_repo_url(repo_url)

    run_id = f"run_{uuid.uuid4().hex[:12]}"

    run = Run(
        id=run_id,
        user_id=current_user.id,
        task=task,
        repo_url=repo_url,
        options=options,
        status=RunStatus.QUEUED,
    )

    created_run = await container.run_repository.create(run)

    # Submit to concurrency manager
    if container.concurrency_manager is not None:
        created_run = await container.concurrency_manager.enqueue_or_start(
            created_run, archive_bytes=archive_bytes
        )

    return created_run


@router.get("", response_model=list[Run])
async def list_runs(
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> list[Run]:
    """Lists all runs belonging to current authenticated user."""
    runs = await container.run_repository.list(user_id=current_user.id)
    if container.concurrency_manager is not None:
        for r in runs:
            handle = container.concurrency_manager.get_handle(r.id)
            if handle is not None:
                r.is_pausing = handle.state_machine.is_pausing
                r.status = handle.state_machine.current_status
    return runs


@router.get("/{id}", response_model=Run)
async def get_run(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> Run:
    """Gets run details by ID. Strictly returns 404 if not found or owned by another user."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle is not None:
            run.is_pausing = handle.state_machine.is_pausing
            run.status = handle.state_machine.current_status

    return run


@router.post("/{id}/pause")
async def pause_run(
    id: str,
    payload: PauseRequest | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Pauses an active run.
    mode='boundary': sets is_pausing=True while completing in-flight step.
    mode='now': cancels current command immediately and enters PAUSED.
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    mode = payload.mode if payload else "boundary"
    if container.concurrency_manager is not None:
        result = await container.concurrency_manager.pause_run(
            id, user_id=current_user.id, mode=mode
        )
        return {"action": result.action, "changed": result.changed}

    raise HTTPException(status_code=500, detail="Concurrency manager not available")


@router.post("/{id}/resume")
async def resume_run(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Resumes a paused run, or cancels a pending boundary pause.
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    if container.concurrency_manager is not None:
        result = await container.concurrency_manager.resume_run(id, user_id=current_user.id)
        return {"action": result.action, "changed": result.changed}

    raise HTTPException(status_code=500, detail="Concurrency manager not available")


@router.post("/{id}/terminate")
async def terminate_run(
    id: str,
    payload: TerminateRequest | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Terminates a run. Halts agent loop, extracts patch, and stops container.
    Idempotent 200 on TERMINATED; 409 on SUCCEEDED/FAILED.
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    reason = payload.reason if payload else "User terminated"
    if container.concurrency_manager is not None:
        result = await container.concurrency_manager.terminate_run(
            id, user_id=current_user.id, reason=reason
        )
        return {"action": result.action, "changed": result.changed}

    raise HTTPException(status_code=500, detail="Concurrency manager not available")


@router.post("/{id}/guidance")
async def inject_guidance(
    id: str,
    payload: GuidanceRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """Injects user steering guidance into active run."""
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Guidance message cannot be empty",
        )

    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    if container.concurrency_manager is not None:
        await container.concurrency_manager.inject_guidance(
            id, user_id=current_user.id, message=payload.message
        )
        return {"status": "guidance_injected"}

    raise HTTPException(status_code=500, detail="Concurrency manager not available")


@router.get("/{id}/events", response_model=list[RunEvent])
async def get_run_events(
    id: str,
    after: int = 0,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> list[RunEvent]:
    """Returns sequential event stream strictly with seq > after."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    events = await container.run_repository.list_events(id, after_seq=after)
    return events


@router.get("/{id}/artifacts")
async def get_run_artifacts(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str | None]:
    """
    Returns presigned S3 URLs for patch, logs, and transcript.
    Keys are strictly partitioned by artifacts/{user_id}/{run_id}/...
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    patch_key = S3ObjectStorage.build_artifact_key(current_user.id, id, "patch.diff")
    logs_key = S3ObjectStorage.build_artifact_key(current_user.id, id, "logs.txt")
    transcript_key = S3ObjectStorage.build_artifact_key(current_user.id, id, "transcript.json")

    patch_url = container.storage.presigned_url(patch_key, ttl=3600)
    logs_url = container.storage.presigned_url(logs_key, ttl=3600)
    transcript_url = container.storage.presigned_url(transcript_key, ttl=3600)

    return {
        "patch_url": patch_url,
        "logs_url": logs_url,
        "transcript_url": transcript_url,
    }


@router.get("/{id}/diff", response_model=list[FileDiff])
async def get_run_diff(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> list[FileDiff]:
    """
    Returns per-file before/after diff for diff viewer.
    Computes live diff from sandbox if run is active, or loads stored patch from S3.
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    diff_bytes = b""
    # 1. Try computing live diff from active sandbox if running
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and handle.control._sandbox and run.baseline_sha:
            try:
                diff_bytes = await compute_diff(handle.control._sandbox, run.baseline_sha)
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.debug("Live diff computation error: %s", exc)

    # 2. If no live diff, try retrieving stored patch from S3
    if not diff_bytes and run.baseline_sha:
        patch_key = S3ObjectStorage.build_artifact_key(current_user.id, id, "patch.diff")
        try:
            stored = await container.storage.get(patch_key)
            if stored:
                diff_bytes = stored
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError, FileNotFoundError) as exc:
            logger.debug("Stored patch retrieval: %s", exc)

    return parse_diff_files(diff_bytes)
