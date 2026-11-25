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
from backend.app.application.diff import _run_command_simple, compute_diff, parse_diff_files
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
    SandboxSpec,
)
from backend.app.infrastructure.storage.s3 import S3ObjectStorage
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


class ExecuteCommandRequest(BaseModel):
    command: str


class UpdateFileContentRequest(BaseModel):
    path: str
    content: str


class AgentChatRequest(BaseModel):
    message: str
    model: str | None = None
    agent: str | None = None
    files: list[dict[str, str]] | None = None
    history: list[dict[str, str]] | None = None


class InstallPackagesRequest(BaseModel):
    packages: list[str]


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

    # Multi-agent parallel swarm mode
    if created_run.options.multi_agent:
        from backend.app.application.multi_agent import start_swarm_task

        start_swarm_task(created_run, container)
        return created_run

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
    from backend.app.application.multi_agent import cancel_swarm_task

    if await cancel_swarm_task(id, container, reason=reason):
        return {"action": "terminated", "changed": True}

    if container.concurrency_manager is not None:
        result = await container.concurrency_manager.terminate_run(
            id, user_id=current_user.id, reason=reason
        )
        return {"action": result.action, "changed": result.changed}

    raise HTTPException(status_code=500, detail="Concurrency manager not available")


@router.delete("/{id}", response_model=dict[str, Any])
async def delete_run(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """Deletes a run record (terminating any active sandbox first)."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    if run.status in ("QUEUED", "PREPARING", "RUNNING", "PAUSED") and container.concurrency_manager is not None:
        try:
            await container.concurrency_manager.terminate_run(
                id, user_id=current_user.id, reason="Session deleted"
            )
        except Exception:
            pass

    deleted = await container.run_repository.delete(id, user_id=current_user.id)
    if not deleted:
        raise EntityNotFoundError(f"Run '{id}' not found")
    return {"deleted": True, "id": id}


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
        if handle and getattr(handle.control, "sandbox", None) and run.baseline_sha:
            try:
                diff_bytes = await compute_diff(handle.control.sandbox, run.baseline_sha)
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


@router.get("/{id}/files", response_model=list[dict[str, Any]])
async def list_run_files(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> list[dict[str, Any]]:
    """Lists all files created or present in the run workspace."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    file_paths: set[str] = set()

    # 1. Try listing files from live sandbox
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            try:
                entries = await handle.control.sandbox.list_dir(".")
                for e in entries:
                    if not e.startswith(".git"):
                        file_paths.add(e)
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                pass

    # 2. Replay write_file tool calls from events
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
            if p and not p.startswith(".git"):
                file_paths.add(p)

    # 3. Fall back to files parsed from diff
    if not file_paths:
        diffs = await get_run_diff(id=id, current_user=current_user, container=container)
        for d in diffs:
            if d.status != "deleted" and not d.path.startswith(".git"):
                file_paths.add(d.path)

    return [{"path": p, "name": p.split("/")[-1]} for p in sorted(file_paths)]


@router.get("/{id}/files/content", response_model=dict[str, str])
async def get_run_file_content(
    id: str,
    path: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """Reads text content of a specific file in the run workspace."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    # 1. Try reading from active sandbox
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            try:
                content = await handle.control.sandbox.read_file(path)
                if content:
                    return {"path": path, "content": content}
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                pass

    # 2. Check recorded write_file events in run repository
    events = await container.run_repository.list_events(id)
    for ev in reversed(events):
        if ev.type == "tool_call" and ev.payload.get("name") == "write_file":
            args = ev.payload.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if args.get("path") == path and args.get("content") is not None:
                return {"path": path, "content": args.get("content", "")}

    # 3. Fallback to extracting from diff patch if file was added
    diffs = await get_run_diff(id=id, current_user=current_user, container=container)
    for d in diffs:
        if d.path == path and d.diff_patch:
            lines = []
            for line in d.diff_patch.splitlines():
                if line.startswith("+") and not line.startswith("+++") or line.startswith(" "):
                    lines.append(line[1:])
            content = "\n".join(lines)
            if content:
                return {"path": path, "content": content}

    return {"path": path, "content": ""}


@router.put("/{id}/files/content", response_model=dict[str, str])
async def update_run_file_content(
    id: str,
    body: UpdateFileContentRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """Updates or creates a file in the run workspace and persists the edit event."""
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    clean_path = body.path.strip().replace("\\", "/")
    if not clean_path or clean_path.startswith("/") or ".." in clean_path.split("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            try:
                await handle.control.sandbox.write_file(clean_path, body.content)
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                pass

    payload = {
        "type": "tool_call",
        "payload": {
            "id": f"user_edit_{uuid.uuid4().hex[:8]}",
            "name": "write_file",
            "arguments": {"path": clean_path, "content": body.content},
        },
    }
    if container.concurrency_manager is not None:
        await container.concurrency_manager.publish_event(id, payload)
    else:
        await container.run_repository.append_event(id, payload)

    return {"path": clean_path, "content": body.content}


_AGENT_PERSONAS: dict[str, str] = {
    "designer": (
        "You are a senior product & UI/UX designer at Meta. Audit layout, typography, "
        "spacing, color hierarchy, and accessibility, and provide concrete code improvements."
    ),
    "tester": (
        "You are a staff QA & test engineer. Write thorough pytest/vitest unit tests, "
        "edge-case assertions, and verification steps for the workspace code."
    ),
    "architect": (
        "You are a principal systems architect. Analyze module boundaries, data flow, "
        "state management, and propose clean, minimal refactors."
    ),
    "reviewer": (
        "You are a senior code reviewer. Check for security issues, race conditions, "
        "error handling gaps, and edge cases."
    ),
    "debugger": (
        "You are a root-cause debugger. Analyze stack traces, failure modes, and logs, "
        "and provide exact minimal fixes."
    ),
}


@router.post("/{id}/chat", response_model=dict[str, str])
async def chat_with_agent(
    id: str,
    body: AgentChatRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """Direct interactive chat with a selectable model and slash-command agent persona."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    from backend.app.config import get_settings
    from backend.app.domain.interfaces import LLMMessage
    from backend.app.infrastructure.llm.openai import OpenAIProvider

    settings = get_settings()

    chosen_model = (body.model or settings.effective_llm_model or "openai/gpt-oss-120b").strip()
    agent_key = (body.agent or "").strip().lower()
    persona_prompt = _AGENT_PERSONAS.get(
        agent_key,
        "You are an expert AI coding assistant embedded in a cloud-native sandbox IDE. Be concise, accurate, and practical.",
    )

    context_parts = [f"Run ID: {run.id}", f"Run Task: {run.task}", f"Run Status: {run.status}"]
    if body.files:
        for f in body.files[:6]:
            p = f.get("path", "")
            c = f.get("content", "")
            if p and c:
                context_parts.append(f"--- {p} ---\n{c[:4000]}")

    system_msg = f"{persona_prompt}\n\nWorkspace context:\n" + "\n\n".join(context_parts)
    messages: list[LLMMessage] = [LLMMessage(role="system", content=system_msg)]
    for item in (body.history or [])[-8:]:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append(LLMMessage(role=role, content=content))
    messages.append(LLMMessage(role="user", content=body.message.strip()))

    # Resolve API key & base URL for selected model
    api_key = settings.GROQ_API_KEY or settings.APINEX_API_KEY or settings.OPENAI_API_KEY
    base_url = settings.GROQ_BASE_URL if settings.GROQ_API_KEY else (
        settings.APINEX_BASE_URL if settings.APINEX_API_KEY else settings.OPENAI_BASE_URL
    )
    if chosen_model in ("gpt-4o", "claude-3.5-sonnet") and settings.APINEX_API_KEY:
        api_key = settings.APINEX_API_KEY
        base_url = settings.APINEX_BASE_URL
    elif settings.GROQ_API_KEY and chosen_model not in ("gpt-4o", "claude-3.5-sonnet"):
        api_key = settings.GROQ_API_KEY
        base_url = settings.GROQ_BASE_URL

    if not api_key:
        raise HTTPException(status_code=503, detail="No LLM API key configured on backend")

    provider = OpenAIProvider(api_key=api_key, model=chosen_model, base_url=base_url)
    try:
        response = await provider.complete(messages=messages, tools=[])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    return {
        "reply": response.content or "(No response returned)",
        "model": chosen_model,
        "agent": agent_key or "assistant",
    }


@router.post("/{id}/packages/install", response_model=dict[str, Any])
async def install_session_packages(
    id: str,
    body: InstallPackagesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Downloads user-confirmed PyPI packages on the host and installs them offline
    into /tmp/pylibs inside the session's isolated sandbox (ephemeral for this session).
    """
    import asyncio
    import io
    import re
    import sys
    import tarfile
    import tempfile
    from pathlib import Path

    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    if not body.packages:
        return {"installed": [], "output": "No packages requested."}

    pkg_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    clean_packages: list[str] = []
    for raw in body.packages[:20]:
        pkg = raw.strip()
        if not pkg_pattern.fullmatch(pkg):
            raise HTTPException(status_code=400, detail=f"Invalid package name: '{raw}'")
        clean_packages.append(pkg)

    sandbox = None
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            sandbox = handle.control.sandbox

    acquired_temp_sandbox = False
    if sandbox is None:
        if container.sandbox_provider is None:
            raise HTTPException(status_code=503, detail="Sandbox provider not available")
        sandbox = await container.sandbox_provider.acquire(SandboxSpec(network_mode="none"))
        acquired_temp_sandbox = True

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            wheels_dir = Path(tmpdir) / "wheels"
            wheels_dir.mkdir(parents=True, exist_ok=True)

            # 1. Stage Linux-compatible wheels on host while keeping sandbox network_mode=none
            cmd = [
                sys.executable, "-m", "pip", "download",
                "--only-binary=:all:", "--python-version", "3.12",
                "--platform", "manylinux2014_x86_64",
                "-d", str(wheels_dir),
                *clean_packages,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            dl_out, _ = await proc.communicate()
            if proc.returncode != 0:
                # Fallback for pure-python / platform-agnostic packages
                fallback_cmd = [
                    sys.executable, "-m", "pip", "download",
                    "--no-binary=:none:",
                    "-d", str(wheels_dir),
                    *clean_packages,
                ]
                proc2 = await asyncio.create_subprocess_exec(
                    *fallback_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                dl_out, _ = await proc2.communicate()
                if proc2.returncode != 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to download packages: {dl_out.decode(errors='replace')[-500:]}",
                    )

            # 2. Stream wheels into /tmp/wheels inside isolated container
            if hasattr(sandbox, "container"):
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    tar.add(str(wheels_dir), arcname="wheels")
                buf.seek(0)
                await asyncio.to_thread(sandbox.container.put_archive, "/tmp", buf.getvalue())

            # 3. Install offline inside container to ephemeral /tmp/pylibs
            pkgs_joined = " ".join(clean_packages)
            install_cmd = (
                f"mkdir -p /tmp/pylibs && "
                f"pip install --no-index --find-links=/tmp/wheels --target /tmp/pylibs {pkgs_joined}"
            )
            chunks: list[str] = []
            exit_code = 0
            async for ev in sandbox.run(install_cmd, timeout=90.0):
                if ev.stream in ("stdout", "stderr"):
                    chunks.append(ev.data)
                elif ev.stream == "exit" and ev.exit_code is not None:
                    exit_code = ev.exit_code

            output_text = "".join(chunks)
            if exit_code != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Sandbox pip install failed: {output_text[-500:]}",
                )

            return {"installed": clean_packages, "output": output_text}
    finally:
        if acquired_temp_sandbox and container.sandbox_provider is not None:
            await container.sandbox_provider.release(sandbox)


@router.post("/{id}/orchestrate", response_model=dict[str, str])
async def orchestrate_multi_agent(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """Triggers the 5-agent parallel swarm on an existing run."""
    from backend.app.application.multi_agent import start_swarm_task

    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    start_swarm_task(run, container)
    return {"status": "orchestrating", "run_id": id}


@router.post("/{id}/execute", response_model=dict[str, Any])
async def execute_command_in_run(
    id: str,
    body: ExecuteCommandRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Executes a shell command inside the run sandbox (or throwaway workspace if terminated),
    streaming output events to repository/terminal.
    """
    run = await container.run_repository.get(id, user_id=current_user.id)
    if run is None:
        raise EntityNotFoundError(f"Run '{id}' not found")

    sandbox = None
    if container.concurrency_manager is not None:
        handle = container.concurrency_manager.get_handle(id)
        if handle and getattr(handle.control, "sandbox", None):
            sandbox = handle.control.sandbox

    output_chunks: list[str] = []
    exit_code = 0

    async def _emit_chunk(stream: str, data: str) -> None:
        output_chunks.append(data)
        payload = {"type": "terminal_output", "payload": {"stream": stream, "data": data}}
        if container.concurrency_manager is not None:
            await container.concurrency_manager.publish_event(id, payload)
        else:
            await container.run_repository.append_event(id, payload)

    if sandbox is not None:
        async for ev in sandbox.run(body.command, timeout=15.0):
            if ev.stream in ("stdout", "stderr"):
                await _emit_chunk(ev.stream, ev.data)
            elif ev.stream == "exit" and ev.exit_code is not None:
                exit_code = ev.exit_code
    else:
        # Acquire throwaway sandbox from provider to execute command on workspace
        spec = SandboxSpec(network_mode="none")
        box = await container.sandbox_provider.acquire(spec)
        try:
            await box.start()
            if run.baseline_sha:
                baseline_key = S3ObjectStorage.build_artifact_key(run.user_id, run.id, "baseline_snapshot.tar.gz")
                try:
                    tar_gz = await container.storage.get(baseline_key)
                    if tar_gz:
                        await box.upload_workspace(tar_gz)
                except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                    pass

                patch_key = S3ObjectStorage.build_artifact_key(run.user_id, run.id, "patch.diff")
                try:
                    patch_bytes = await container.storage.get(patch_key)
                    if patch_bytes:
                        await box.write_file(".patch.diff", patch_bytes.decode("utf-8", errors="replace"))
                        await _run_command_simple(box, "git apply .patch.diff")
                except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                    pass

            # Replay all write_file events to guarantee files are physically present
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
                            await box.write_file(p, c)
                        except (OSError, RuntimeError, ValueError, KeyError, AttributeError):
                            pass

            async for ev in box.run(body.command, timeout=15.0):
                if ev.stream in ("stdout", "stderr"):
                    await _emit_chunk(ev.stream, ev.data)
                elif ev.stream == "exit" and ev.exit_code is not None:
                    exit_code = ev.exit_code
        finally:
            await box.stop()

    return {
        "command": body.command,
        "exit_code": exit_code,
        "output": "".join(output_chunks),
    }
