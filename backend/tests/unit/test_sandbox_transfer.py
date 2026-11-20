"""Unit tests for SandboxTransferManager."""
import hashlib
import os
from unittest.mock import MagicMock

import pytest
from backend.app.domain.errors import DomainError
from backend.app.infrastructure.sandbox.transfer import SandboxTransferManager


def test_slice_into_base64_chunks():
    data = b"Hello, world! This is a test string." * 100
    chunks = SandboxTransferManager.slice_into_base64_chunks(data, chunk_size=64)

    assert len(chunks) > 1
    assert all(len(c) <= 64 for c in chunks)
    reassembled = SandboxTransferManager.reassemble_base64_chunks(chunks)
    assert reassembled == data


def test_slice_empty_bytes():
    chunks = SandboxTransferManager.slice_into_base64_chunks(b"")
    assert chunks == []
    reassembled = SandboxTransferManager.reassemble_base64_chunks(chunks)
    assert reassembled == b""


def test_compute_sha256():
    data = os.urandom(1024)
    expected = hashlib.sha256(data).hexdigest()
    assert SandboxTransferManager.compute_sha256(data) == expected


@pytest.mark.asyncio
async def test_chunked_base64_upload_mock_container():
    client = MagicMock()
    data = b"Some binary content to upload" * 50
    expected_sha = hashlib.sha256(data).hexdigest()

    # Track exec calls
    commands_executed = []

    def mock_exec_create(container, cmd, **kwargs):
        commands_executed.append(cmd)
        return {"Id": f"exec_{len(commands_executed)}"}

    def mock_exec_start(exec_id, **kwargs):
        # If running sha256sum, return expected sha
        last_cmd = commands_executed[-1]
        if "sha256sum" in " ".join(last_cmd):
            return f"{expected_sha}  /tmp/staging.bin\n".encode()
        return b""

    def mock_exec_inspect(exec_id):
        return {"ExitCode": 0}

    client.api.exec_create = mock_exec_create
    client.api.exec_start = mock_exec_start
    client.api.exec_inspect = mock_exec_inspect

    await SandboxTransferManager.chunked_base64_upload(
        client=client,
        container_id="c_123",
        dest_path="/workspace/file.bin",
        data=data,
    )

    # Assert initialization, chunk appends, decoding, sha256, moving, and cleanup happened
    cmds_str = [" ".join(c) for c in commands_executed]
    assert any("printf" in c for c in cmds_str)
    assert any("base64 -d" in c for c in cmds_str)
    assert any("sha256sum" in c for c in cmds_str)
    assert any("mv -f" in c for c in cmds_str)
    assert any("rm -f" in c for c in cmds_str)


@pytest.mark.asyncio
async def test_chunked_base64_upload_checksum_mismatch():
    client = MagicMock()
    data = b"Content"

    def mock_exec_create(container, cmd, **kwargs):
        return {"Id": "exec_1"}

    def mock_exec_start(exec_id, **kwargs):
        # Return wrong checksum
        return b"badchecksum00000000000000000000000000000000000000000000000000  /tmp/staging.bin\n"

    def mock_exec_inspect(exec_id):
        return {"ExitCode": 0}

    client.api.exec_create = mock_exec_create
    client.api.exec_start = mock_exec_start
    client.api.exec_inspect = mock_exec_inspect

    with pytest.raises(DomainError, match="Checksum mismatch"):
        await SandboxTransferManager.chunked_base64_upload(
            client=client,
            container_id="c_123",
            dest_path="/workspace/file.bin",
            data=data,
        )
