"""
Unit tests for Git Diff and Isolated Patch Validation.
"""
from backend.app.application.diff import (
    compute_diff,
    create_baseline,
    parse_diff_files,
    store_patch_artifact,
    validate_patch,
)
from backend.app.domain.models import Run, RunStatus
from backend.test_support.fake_sandbox import FakeSandbox, FakeSandboxProvider


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.files[key] = data

    async def get(self, key: str) -> bytes:
        return self.files[key]

    async def presigned_url(self, key: str, ttl_seconds: int = 3600) -> str:
        return f"https://s3.local/{key}"


async def test_create_baseline_and_compute_diff() -> None:
    sandbox = FakeSandbox()
    await sandbox.start()
    storage = FakeStorage()

    run = Run(id="run-test", user_id="user-test", task="test task", status=RunStatus.PREPARING)

    # Initial file
    await sandbox.write_file("main.py", "print('hello')\n")

    # Create baseline
    sha = await create_baseline(sandbox, run, storage)
    assert len(sha) == 40
    assert "artifacts/user-test/run-test/baseline_snapshot.tar.gz" in storage.files

    # Modify file and add new file
    await sandbox.write_file("main.py", "print('hello world')\n")
    await sandbox.write_file("new.py", "x = 1\n")

    diff = await compute_diff(sandbox, sha)
    diff_text = diff.decode("utf-8")
    assert "main.py" in diff_text
    assert "new.py" in diff_text

    # Parse diff
    file_diffs = parse_diff_files(diff)
    assert len(file_diffs) == 2
    paths = {f.path for f in file_diffs}
    assert "main.py" in paths
    assert "new.py" in paths

    # Store patch artifact
    key = await store_patch_artifact(storage, run.user_id, run.id, diff)
    assert key == "artifacts/user-test/run-test/patch.diff"
    assert storage.files[key] == diff

    await sandbox.stop()


async def test_validate_patch_in_throwaway_sandbox() -> None:
    sandbox = FakeSandbox()
    await sandbox.start()
    storage = FakeStorage()
    run = Run(id="run-val", user_id="user-val", task="test task", status=RunStatus.PREPARING)
    await sandbox.write_file("calc.py", "def add(a, b): return a - b\n")

    sha = await create_baseline(sandbox, run, storage)
    baseline_tar = storage.files["artifacts/user-val/run-val/baseline_snapshot.tar.gz"]

    # Modify
    await sandbox.write_file("calc.py", "def add(a, b): return a + b\n")
    valid_patch = await compute_diff(sandbox, sha)

    provider = FakeSandboxProvider()
    is_valid = await validate_patch(provider, valid_patch, baseline_tar)
    assert is_valid is True

    # Check invalid patch
    invalid_patch = b"diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,1 +1,1 @@\n-nonexistent line\n+bad\n"
    is_invalid = await validate_patch(provider, invalid_patch, baseline_tar)
    assert is_invalid is False

    await sandbox.stop()
