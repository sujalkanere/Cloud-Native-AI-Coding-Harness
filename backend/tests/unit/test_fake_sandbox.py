"""Unit tests for FakeSandbox and FakeSandboxProvider."""
import asyncio
import io
import tarfile

import pytest
from backend.app.domain.errors import PathTraversalError
from backend.app.domain.interfaces import ISandboxEnvironment, ISandboxProvider
from backend.app.domain.models import SandboxSpec
from backend.test_support.fake_sandbox import FakeSandbox, FakeSandboxProvider


def test_protocol_conformance():
    sandbox = FakeSandbox()
    assert isinstance(sandbox, ISandboxEnvironment)

    provider = FakeSandboxProvider()
    assert isinstance(provider, ISandboxProvider)


@pytest.mark.asyncio
async def test_fake_sandbox_lifecycle():
    sandbox = FakeSandbox()
    assert sandbox.id.startswith("fake-")

    await sandbox.start()
    assert sandbox._is_running is True

    # Stop idempotency
    await sandbox.stop()
    assert sandbox._is_running is False
    await sandbox.stop()


@pytest.mark.asyncio
async def test_file_crud_and_traversal_guards():
    sandbox = FakeSandbox()
    await sandbox.start()
    try:
        # Write and read
        await sandbox.write_file("sub/hello.txt", "Hello World!")
        content = await sandbox.read_file("sub/hello.txt")
        assert content == "Hello World!"

        # List dir
        items = await sandbox.list_dir("sub")
        assert items == ["hello.txt"]

        # Traversal guards
        with pytest.raises(PathTraversalError):
            await sandbox.read_file("../escape.txt")

        with pytest.raises(PathTraversalError):
            await sandbox.write_file("/etc/passwd", "malicious")

        with pytest.raises(PathTraversalError):
            await sandbox.read_file("")

        with pytest.raises(PathTraversalError):
            await sandbox.read_file("bad\0file")

        with pytest.raises(FileNotFoundError):
            await sandbox.read_file("missing.txt")
    finally:
        await sandbox.stop()


@pytest.mark.asyncio
async def test_workspace_upload_and_download():
    sandbox = FakeSandbox()
    await sandbox.start()
    try:
        # Create sample tarball
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"archive content here"
            ti = tarfile.TarInfo(name="archived_file.txt")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        tar_gz = buf.getvalue()

        await sandbox.upload_workspace(tar_gz)

        # Verify uploaded file exists
        read_back = await sandbox.read_file("archived_file.txt")
        assert read_back == "archive content here"

        # Download workspace
        downloaded_bytes = await sandbox.download_workspace()
        assert len(downloaded_bytes) > 0

        # Inspect downloaded tarball
        buf2 = io.BytesIO(downloaded_bytes)
        with tarfile.open(fileobj=buf2, mode="r:gz") as tar2:
            names = tar2.getnames()
            assert any("archived_file.txt" in n for n in names)
    finally:
        await sandbox.stop()


@pytest.mark.asyncio
async def test_execution_terminal_and_timeout():
    sandbox = FakeSandbox()
    await sandbox.start()
    try:
        # Normal execution
        events = []
        async for ev in sandbox.run('python -c "import sys; sys.stdout.write(\'out\\n\'); sys.stderr.write(\'err\\n\'); sys.exit(0)"'):
            events.append(ev)

        assert any(e.stream == "stdout" and "out" in e.data for e in events)
        assert any(e.stream == "stderr" and "err" in e.data for e in events)
        assert any(e.stream == "exit" and e.exit_code == 0 for e in events)
    finally:
        await sandbox.stop()


@pytest.mark.asyncio
async def test_execution_terminal_command():
    sandbox = FakeSandbox()
    await sandbox.start()
    try:
        events = []
        async for ev in sandbox.run('python -c "print(1 + 2)"'):
            events.append(ev)

        exit_events = [e for e in events if e.stream == "exit"]
        stdout_events = [e for e in events if e.stream == "stdout"]
        assert len(exit_events) == 1
        assert exit_events[0].exit_code == 0
        assert any("3" in e.data for e in stdout_events)

        # Command with timeout
        timeout_events = []
        async for ev in sandbox.run('python -c "import time; time.sleep(5)"', timeout=0.2):
            timeout_events.append(ev)

        exit_timeout = [e for e in timeout_events if e.stream == "exit"]
        assert len(exit_timeout) == 1
        assert exit_timeout[0].exit_code == 124
    finally:
        await sandbox.stop()


@pytest.mark.asyncio
async def test_cancellation():
    sandbox = FakeSandbox()
    await sandbox.start()
    try:
        run_task = asyncio.create_task(
            _collect_run(sandbox, 'python -c "import time; time.sleep(10)"')
        )
        await asyncio.sleep(0.1)
        await sandbox.cancel_current()
        events = await run_task
        exit_events = [e for e in events if e.stream == "exit"]
        assert len(exit_events) == 1
    finally:
        await sandbox.stop()


async def _collect_run(sandbox, cmd):
    events = []
    async for ev in sandbox.run(cmd):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_fake_sandbox_provider():
    provider = FakeSandboxProvider()
    spec = SandboxSpec(mem_limit="2g")
    box = await provider.acquire(spec)
    assert box.spec.mem_limit == "2g"
    assert len(provider.acquired) == 1
    await box.stop()
