"""
Git Diff and Isolated Patch Validation for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §4, §8, and PROJECT.md:
- Baseline git commit created in PREPARING with author 'AI Coding Harness <harness@local>'.
- Baseline SHA recorded in DB; clean tarball stored in S3 at artifacts/{user_id}/{run_id}/baseline_snapshot.tar.gz.
- Binary git diffs computed against recorded baseline SHA (git diff --binary <baseline_sha>), never against HEAD.
- Patches generated and stored in S3 for all terminal states (SUCCEEDED, FAILED, TERMINATED) where changes exist.
- Isolated patch validation executes `git apply --check` inside an isolated throwaway network=none sandbox.
"""
from __future__ import annotations

import logging
import re
import uuid

from backend.app.domain.interfaces import (
    IObjectStorage,
    IRunRepository,
    ISandboxEnvironment,
    ISandboxProvider,
)
from backend.app.domain.models import FileDiff, Run, SandboxSpec
from backend.app.infrastructure.storage.s3 import S3ObjectStorage

logger = logging.getLogger(__name__)


async def _run_command_simple(sandbox: ISandboxEnvironment, command: str) -> tuple[int, str]:
    """Helper to run a shell command inside sandbox and capture exit code + stdout."""
    stdout_chunks: list[str] = []
    exit_code = 0
    async for event in sandbox.run(command):
        if event.stream == "stdout":
            stdout_chunks.append(event.data)
        elif event.stream == "exit" and event.exit_code is not None:
            exit_code = event.exit_code
    return exit_code, "".join(stdout_chunks)


async def create_baseline(
    sandbox: ISandboxEnvironment,
    run: Run,
    storage: IObjectStorage,
    repo: IRunRepository | None = None,
) -> str:
    """
    Initializes git repository in sandbox workspace, creates baseline commit with author
    'AI Coding Harness <harness@local>', records baseline SHA in database, and stores
    clean tarball in S3. Returns baseline_sha.
    """
    # 1. Initialize git and configure harness author
    await _run_command_simple(sandbox, "git init")
    await _run_command_simple(sandbox, 'git config user.name "AI Coding Harness"')
    await _run_command_simple(sandbox, 'git config user.email "harness@local"')

    # 2. Stage all existing files and create baseline commit
    await _run_command_simple(sandbox, "git add -A")
    await _run_command_simple(
        sandbox,
        'git commit --allow-empty -m "baseline snapshot" --author="AI Coding Harness <harness@local>"',
    )

    # 3. Extract baseline SHA
    _code, sha_out = await _run_command_simple(sandbox, "git rev-parse HEAD")
    baseline_sha = sha_out.strip()
    if not baseline_sha or len(baseline_sha) < 40:
        raise RuntimeError(f"Failed to extract valid baseline commit SHA: {sha_out}")

    # 4. Download clean baseline tarball and store in S3
    tarball_bytes = await sandbox.download_workspace()
    baseline_key = S3ObjectStorage.build_artifact_key(run.user_id, run.id, "baseline_snapshot.tar.gz")
    await storage.put(baseline_key, tarball_bytes, content_type="application/gzip")

    # 5. Persist baseline SHA in DB if repository provided
    if repo is not None:
        await repo.update_status(run.id, status=run.status, baseline_sha=baseline_sha)

    return baseline_sha


async def compute_diff(
    sandbox: ISandboxEnvironment,
    baseline_sha: str,
) -> bytes:
    """
    Computes binary git diff against baseline commit SHA.
    Stages untracked files with `git add -N .` to ensure new files are captured.
    Returns binary diff bytes (empty bytes if no changes exist).
    """
    if not baseline_sha:
        return b""

    # Stage untracked and modified files so git diff captures everything
    await _run_command_simple(sandbox, "git add -A")

    # Execute binary diff against baseline SHA
    _code, diff_out = await _run_command_simple(sandbox, f"git diff --binary {baseline_sha}")
    if not diff_out or not diff_out.strip():
        return b""

    return diff_out.encode("utf-8")


def parse_diff_files(diff_content: str | bytes) -> list[FileDiff]:
    """
    Parses unified git diff output into structured FileDiff domain models for diff viewer.
    Captures modified, added, deleted, renamed, and binary files.
    """
    text = diff_content.decode("utf-8", errors="replace") if isinstance(diff_content, bytes) else diff_content
    if not text.strip():
        return []

    file_diffs: list[FileDiff] = []
    # Split on diff --git boundaries
    chunks = [c for c in re.split(r"(?=^diff --git )", text, flags=re.MULTILINE) if c.strip().startswith("diff --git ")]

    for chunk in chunks:
        lines = chunk.splitlines()
        header = lines[0]
        m = re.match(r"diff --git a/(.*) b/(.*)", header)
        if not m:
            continue
        old_path, new_path = m.group(1), m.group(2)

        status = "modified"
        if "new file mode" in chunk:
            status = "added"
        elif "deleted file mode" in chunk:
            status = "deleted"
        elif "rename from" in chunk:
            status = "renamed"
        elif "GIT binary patch" in chunk or "Binary files" in chunk:
            status = "binary"

        additions = 0
        deletions = 0
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        file_diffs.append(
            FileDiff(
                path=new_path if status != "deleted" else old_path,
                status=status,
                additions=additions,
                deletions=deletions,
                diff_patch=chunk,
            )
        )

    return file_diffs


async def validate_patch(
    sandbox_provider: ISandboxProvider,
    patch: bytes,
    baseline_tar_gz: bytes,
) -> bool:
    """
    Validates patch by running `git apply --check` inside an isolated throwaway
    sandbox container with network=none. Never executes on host or backend process.
    Returns True if git apply --check exits with code 0.
    """
    if not patch or not patch.strip():
        return True

    # 1. Acquire throwaway sandbox with network=none
    throwaway_spec = SandboxSpec(network_mode="none")
    box = await sandbox_provider.acquire(throwaway_spec)

    try:
        await box.start()
        # 2. Upload clean baseline snapshot
        await box.upload_workspace(baseline_tar_gz)

        # 3. Write patch file to workspace with non-colliding name
        patch_filename = f".harness_patch_{uuid.uuid4().hex[:8]}.diff"
        patch_str = patch.decode("utf-8", errors="replace")
        await box.write_file(patch_filename, patch_str)

        # 4. Execute git apply --check in sandbox
        exit_code, _ = await _run_command_simple(box, f"git apply --check {patch_filename}")
        return exit_code == 0
    except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("Patch validation encountered error: %s", exc)
        return False
    finally:
        # 5. Guaranteed cleanup of throwaway container
        await box.stop()


async def store_patch_artifact(
    storage: IObjectStorage,
    user_id: str,
    run_id: str,
    patch: bytes,
) -> str:
    """Stores patch diff in S3 at artifacts/{user_id}/{run_id}/patch.diff."""
    patch_key = S3ObjectStorage.build_artifact_key(user_id, run_id, "patch.diff")
    await storage.put(patch_key, patch, content_type="text/x-diff")
    return patch_key
