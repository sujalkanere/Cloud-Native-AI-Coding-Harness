"""
Sandbox Transfer Manager for Cloud-Native AI Coding Harness.
Implements low-level hijacked socket attachment across docker-socket-proxy
and 64 KB base64 chunked transfer with SHA-256 verification after reassembly in container.
Adheres strictly to Spec §5 and M3.1.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import socket
import uuid
from typing import Any

from backend.app.domain.errors import DomainError

logger = logging.getLogger(__name__)


class SandboxTransferManager:
    """Manages workspace tarball and file transfers via socket streaming or 64KB base64 chunked fallback."""

    CHUNK_SIZE: int = 64 * 1024  # 64 KB = 65,536 bytes/chars

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Computes hex SHA-256 digest of data."""
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def slice_into_base64_chunks(cls, data: bytes, chunk_size: int | None = None) -> list[str]:
        """Encodes binary data into base64 and slices into chunks (default 64 KB)."""
        size = chunk_size or cls.CHUNK_SIZE
        b64_str = base64.b64encode(data).decode("ascii")
        if not b64_str:
            return []
        return [b64_str[i : i + size] for i in range(0, len(b64_str), size)]

    @classmethod
    def reassemble_base64_chunks(cls, chunks: list[str]) -> bytes:
        """Reassembles base64 chunks and decodes to binary."""
        joined = "".join(chunks)
        return base64.b64decode(joined.encode("ascii"))

    @classmethod
    async def chunked_base64_upload(
        cls,
        client: Any,
        container_id: str,
        dest_path: str,
        data: bytes,
    ) -> None:
        """
        Uploads data to container via 64 KB base64 chunked transfer with SHA-256 verification.
        Uses positional parameters in short exec calls to prevent shell escaping or ARG_MAX issues.
        """
        expected_sha = cls.compute_sha256(data)
        staging_id = uuid.uuid4().hex
        staging_b64 = f"/tmp/staging_{staging_id}.b64"
        staging_bin = f"/tmp/staging_{staging_id}.bin"

        chunks = cls.slice_into_base64_chunks(data)

        def _run_exec(cmd: list[str]) -> tuple[int, str]:
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=cmd,
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            output = client.api.exec_start(exec_id, detach=False)
            inspect_res = client.api.exec_inspect(exec_id)
            exit_code = inspect_res.get("ExitCode", 0)
            text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
            return exit_code, text

        try:
            # 1. Initialize staging file
            code, out = await asyncio.to_thread(
                _run_exec,
                ["sh", "-c", 'printf "" > "$1"', "_", staging_b64],
            )
            if code != 0:
                raise DomainError(f"Failed to initialize staging file: {out}")

            # 2. Append chunks via positional argument
            for chunk in chunks:
                code, out = await asyncio.to_thread(
                    _run_exec,
                    ["sh", "-c", 'printf "%s" "$1" >> "$2"', "_", chunk, staging_b64],
                )
                if code != 0:
                    raise DomainError(f"Failed appending chunk to container: {out}")

            # 3. Decode base64 in container
            code, out = await asyncio.to_thread(
                _run_exec,
                ["sh", "-c", 'base64 -d "$1" > "$2"', "_", staging_b64, staging_bin],
            )
            if code != 0:
                raise DomainError(f"Failed decoding base64 in container: {out}")

            # 4. Verify SHA-256 inside container
            code, out = await asyncio.to_thread(
                _run_exec,
                ["sh", "-c", 'sha256sum "$1"', "_", staging_bin],
            )
            if code != 0:
                raise DomainError(f"Failed running sha256sum in container: {out}")

            # Output format: "<checksum>  <path>\n"
            parts = out.strip().split()
            actual_sha = parts[0] if parts else ""
            if actual_sha.lower() != expected_sha.lower():
                raise DomainError(
                    f"Checksum mismatch after reassembly: expected {expected_sha}, got {actual_sha}"
                )

            # 5. Move verified binary to dest_path
            code, out = await asyncio.to_thread(
                _run_exec,
                ["sh", "-c", 'mv -f "$1" "$2"', "_", staging_bin, dest_path],
            )
            if code != 0:
                raise DomainError(f"Failed moving verified file to {dest_path}: {out}")

        finally:
            # Cleanup staging files
            await asyncio.to_thread(
                _run_exec,
                ["sh", "-c", 'rm -f "$1" "$2"', "_", staging_b64, staging_bin],
            )

    @classmethod
    async def upload_tarball_to_workspace(
        cls,
        client: Any,
        container_id: str,
        tar_gz_bytes: bytes,
        mode: str = "auto",
    ) -> None:
        """
        Uploads and unpacks a tarball into /workspace.
        Attempts hijacked socket streaming first; falls back to 64KB base64 chunked transfer with SHA-256.
        """
        if mode in ("auto", "socket"):
            try:
                success = await cls._stream_tarball_via_socket(client, container_id, tar_gz_bytes)
                if success:
                    return
            except Exception as exc:
                logger.warning(
                    "Socket streaming tarball failed (%s). Falling back to 64KB base64 chunked transfer.",
                    exc,
                )
                if mode == "socket":
                    raise

        # Fallback: 64 KB base64 chunked transfer + SHA-256 verification + unpacking
        staging_tar = f"/tmp/upload_{uuid.uuid4().hex}.tar.gz"
        await cls.chunked_base64_upload(client, container_id, staging_tar, tar_gz_bytes)

        # Unpack verified tarball into /workspace
        def _unpack() -> tuple[int, str]:
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=["tar", "-xzf", staging_tar, "-C", "/workspace"],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            out = client.api.exec_start(exec_id, detach=False)
            inspect_res = client.api.exec_inspect(exec_id)
            code = inspect_res.get("ExitCode", 0)
            text = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out)
            # Remove staging tar
            client.api.exec_create(container=container_id, cmd=["rm", "-f", staging_tar], user="1000:1000")
            return code, text

        code, out = await asyncio.to_thread(_unpack)
        if code != 0:
            raise DomainError(f"Failed to unpack tarball in /workspace: {out}")

    @classmethod
    async def _stream_tarball_via_socket(
        cls,
        client: Any,
        container_id: str,
        tar_gz_bytes: bytes,
    ) -> bool:
        """Low-level hijacked socket streaming to tar -xzf - -C /workspace."""
        def _stream() -> bool:
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=["tar", "-xzf", "-", "-C", "/workspace"],
                stdin=True,
                stdout=True,
                stderr=True,
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            # Attach socket
            sock = client.api.exec_start(exec_id, detach=False, socket=True)
            raw_sock = getattr(sock, "_sock", sock)

            try:
                raw_sock.sendall(tar_gz_bytes)
                if hasattr(raw_sock, "shutdown"):
                    try:
                        raw_sock.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
            finally:
                if hasattr(sock, "close"):
                    sock.close()

            inspect_res = client.api.exec_inspect(exec_id)
            return inspect_res.get("ExitCode", 0) == 0

        return await asyncio.to_thread(_stream)

    @classmethod
    async def download_workspace_tarball(
        cls,
        client: Any,
        container_id: str,
        mode: str = "auto",
    ) -> bytes:
        """
        Packs /workspace and retrieves it as tar.gz bytes.
        Supports direct stdout streaming or chunked base64 staging with SHA-256 verification.
        """
        staging_tar = f"/tmp/download_{uuid.uuid4().hex}.tar.gz"

        def _pack_and_read() -> bytes:
            # 1. Create tarball inside container
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=["tar", "-czf", staging_tar, "-C", "/workspace", "."],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            out = client.api.exec_start(exec_id, detach=False)
            code = client.api.exec_inspect(exec_id).get("ExitCode", 0)
            if code != 0:
                raise DomainError(f"Failed to archive /workspace: {out}")

            # 2. Get base64 string
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=["base64", staging_tar],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            b64_output = client.api.exec_start(exec_id, detach=False)
            code = client.api.exec_inspect(exec_id).get("ExitCode", 0)
            if code != 0:
                raise DomainError(f"Failed to read base64 archive: {b64_output}")

            # 3. Compute sha256 inside container
            exec_res = client.api.exec_create(
                container=container_id,
                cmd=["sha256sum", staging_tar],
                user="1000:1000",
            )
            exec_id = exec_res["Id"]
            sha_output = client.api.exec_start(exec_id, detach=False)
            sha_text = sha_output.decode("utf-8", errors="replace").strip().split()
            expected_sha = sha_text[0] if sha_text else ""

            # 4. Clean up staging tar
            client.api.exec_create(
                container=container_id,
                cmd=["rm", "-f", staging_tar],
                user="1000:1000",
            )

            # 5. Decode and verify locally
            b64_clean = b64_output.replace(b"\n", b"").replace(b"\r", b"")
            data = base64.b64decode(b64_clean)
            actual_sha = hashlib.sha256(data).hexdigest()

            if expected_sha and actual_sha.lower() != expected_sha.lower():
                raise DomainError(
                    f"Checksum mismatch on workspace download: expected {expected_sha}, got {actual_sha}"
                )

            return data

        return await asyncio.to_thread(_pack_and_read)
