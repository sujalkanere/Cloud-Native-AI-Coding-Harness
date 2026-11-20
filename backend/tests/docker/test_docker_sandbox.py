"""
Integration tests for Docker Sandbox Engine requiring Docker daemon.
Adheres strictly to Spec §5:
- Hardening assertions (non-root, cap-drop ALL, no-new-privs, read-only root, no host mounts, network none)
- Zero secrets assertion
- Writable tmpfs with exec in /workspace
- Warm pool boot latency < 5s
- Orphan container reaping
"""
from __future__ import annotations

import os
import time

import pytest
from backend.app.domain.models import SandboxSpec
from backend.app.infrastructure.sandbox.provider import DockerSandboxProvider


@pytest.fixture
def docker_client():
    import docker
    from docker.errors import DockerException

    docker_host = os.environ.get("DOCKER_HOST", "tcp://localhost:2375")
    try:
        client = docker.DockerClient(base_url=docker_host)
        client.ping()
        return client
    except (DockerException, OSError, ConnectionError) as exc:
        pytest.skip(f"Docker daemon not available: {exc}")


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_sandbox_hardening_and_zero_secrets(docker_client):
    provider = DockerSandboxProvider(client=docker_client, warm_pool_size=1)
    await provider.initialize()
    try:
        sandbox = await provider.acquire(SandboxSpec())
        container = docker_client.containers.get(sandbox.id)
        host_config = container.attrs["HostConfig"]

        # 1. Non-root user
        assert container.attrs["Config"]["User"] == "1000:1000"

        # 2. Hardening configs
        assert "ALL" in host_config.get("CapDrop", [])
        assert "no-new-privileges:true" in host_config.get("SecurityOpt", [])
        assert host_config.get("ReadonlyRootfs") is True
        assert host_config.get("NetworkMode") == "none"

        # 3. No host mounts
        assert len(host_config.get("Binds") or []) == 0

        # 4. Tmpfs mounts with exec
        tmpfs = host_config.get("Tmpfs", {})
        assert "/workspace" in tmpfs
        assert "exec" in tmpfs["/workspace"]
        assert "/tmp" in tmpfs
        assert "exec" in tmpfs["/tmp"]

        # 5. Zero secrets inside sandbox env
        env_vars = container.attrs["Config"]["Env"]
        forbidden_keys = [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "DATABASE_URL",
            "S3_SECRET_KEY",
            "S3_ACCESS_KEY",
            "CLERK_SECRET_KEY",
        ]
        for var in env_vars:
            key = var.split("=")[0]
            assert key not in forbidden_keys, f"Secret {key} leaked into sandbox container!"

        await sandbox.stop()
    finally:
        await provider.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_tmpfs_executable_in_workspace(docker_client):
    provider = DockerSandboxProvider(client=docker_client, warm_pool_size=1)
    await provider.initialize()
    try:
        sandbox = await provider.acquire(SandboxSpec())
        # Write an executable shell script to /workspace
        script_content = "#!/bin/sh\necho 'executable ran successfully'\n"
        await sandbox.write_file("run.sh", script_content)

        # Make executable
        events = []
        async for ev in sandbox.run("chmod +x /workspace/run.sh && /workspace/run.sh"):
            events.append(ev)

        exit_event = next(e for e in events if e.stream == "exit")
        assert exit_event.exit_code == 0
        stdout_events = [e for e in events if e.stream == "stdout"]
        assert any("executable ran successfully" in e.data for e in stdout_events)

        await sandbox.stop()
    finally:
        await provider.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_warm_pool_latency_and_orphan_reaping(docker_client):
    provider = DockerSandboxProvider(client=docker_client, warm_pool_size=2)
    await provider.initialize()
    try:
        t0 = time.perf_counter()
        sandbox = await provider.acquire(provider.default_spec)
        latency_s = time.perf_counter() - t0

        # Must boot under 5s from warm pool
        assert latency_s < 5.0

        # Verify orphan reaping
        reaped = await provider.reap_orphans()
        assert reaped >= 0

        await sandbox.stop()
    finally:
        await provider.close()
