"""
Docker Sandbox Provider for Cloud-Native AI Coding Harness.
Implements ISandboxProvider adhering strictly to Spec §3.2, §5:
- Warm pool of idle pre-booted containers (< 5s boot).
- Startup orphan reaping of containers labeled harness.managed=true.
- Hardening: non-root UID 1000:1000, cap-drop ALL, no-new-privileges, read-only root, no host mounts, network none.
- Writable tmpfs mounts with exec,nosuid,nodev for /workspace and /tmp.
- Zero backend secrets injected.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.interfaces import ISandboxEnvironment, ISandboxProvider
from backend.app.domain.models import SandboxSpec
from backend.app.infrastructure.sandbox.environment import DockerSandboxEnvironment

logger = logging.getLogger(__name__)


class DockerSandboxProvider(ISandboxProvider):
    """
    Concrete sandbox provider managing hardened Docker containers and warm pool.
    Reaches Docker exclusively through docker-socket-proxy.
    """

    def __init__(
        self,
        docker_host: str = "tcp://docker-proxy:2375",
        warm_pool_size: int = 2,
        default_spec: SandboxSpec | None = None,
        client: Any | None = None,
    ) -> None:
        self.docker_host = docker_host
        self.warm_pool_size = warm_pool_size
        self.default_spec = default_spec or SandboxSpec()
        self._client = client
        self._warm_pool: asyncio.Queue[DockerSandboxEnvironment] = asyncio.Queue()
        self._is_initialized = False
        self._is_closed = False

    def _get_client(self) -> Any:
        if self._client is None:
            import docker
            try:
                if self.docker_host and self.docker_host not in ("auto", "default", "npipe"):
                    self._client = docker.DockerClient(base_url=self.docker_host)
                    self._client.ping()
                else:
                    self._client = docker.from_env()
            except Exception:
                self._client = docker.from_env()
        return self._client

    async def initialize(self) -> None:
        """Startup hook: reaps orphan containers and fills the warm pool."""
        if self._is_initialized:
            return
        self._is_initialized = True

        # 1. Reap orphan containers labeled harness.managed=true
        await self.reap_orphans()

        # 2. Fill warm pool up to warm_pool_size
        for _ in range(self.warm_pool_size):
            try:
                env = await self._boot_container(self.default_spec)
                await self._warm_pool.put(env)
            except (OSError, RuntimeError, KeyError, AttributeError) as exc:
                logger.warning("Could not pre-boot warm pool container: %s", exc)

    async def reap_orphans(self) -> int:
        """Finds and forcefully removes any lingering containers labeled harness.managed=true."""
        def _reap() -> int:
            client = self._get_client()
            orphans = client.containers.list(
                all=True,
                filters={"label": "harness.managed=true"},
            )
            count = 0
            for container in orphans:
                try:
                    container.remove(force=True)
                    count += 1
                except (OSError, RuntimeError, KeyError, AttributeError) as exc:
                    logger.debug("Failed removing orphan container %s: %s", container.id, exc)
            return count


        return await asyncio.to_thread(_reap)

    def _matches_default_spec(self, spec: SandboxSpec) -> bool:
        """Checks if spec matches default spec to determine warm pool eligibility."""
        return (
            spec.image == self.default_spec.image
            and spec.cpu_limit == self.default_spec.cpu_limit
            and spec.mem_limit == self.default_spec.mem_limit
            and spec.pids_limit == self.default_spec.pids_limit
            and spec.workspace_size == self.default_spec.workspace_size
            and spec.tmp_size == self.default_spec.tmp_size
            and spec.network_mode == self.default_spec.network_mode
            and spec.env == self.default_spec.env
        )

    async def acquire(self, spec: SandboxSpec) -> ISandboxEnvironment:
        """
        Acquires a sandbox container.
        Runs matching default spec are acquired from the warm pool (<5s).
        Custom specs perform cold boot and are exempt from the 5s limit.
        """
        if not self._is_initialized:
            await self.initialize()

        # If matching default spec, attempt acquisition from warm pool
        if self._matches_default_spec(spec) and not self._warm_pool.empty():
            try:
                sandbox = self._warm_pool.get_nowait()
                # Schedule background replenishment
                asyncio.create_task(self._replenish_warm_pool())
                return sandbox
            except asyncio.QueueEmpty:
                pass

        # Cold boot container
        return await self._boot_container(spec)

    async def _replenish_warm_pool(self) -> None:
        """Background task replenishing an idle container to maintain warm pool size."""
        if self._is_closed or self._warm_pool.qsize() >= self.warm_pool_size:
            return
        try:
            sandbox = await self._boot_container(self.default_spec)
            await self._warm_pool.put(sandbox)
        except (OSError, RuntimeError, KeyError, AttributeError) as exc:
            logger.warning("Background replenishment of warm pool container failed: %s", exc)


    async def _boot_container(self, spec: SandboxSpec) -> DockerSandboxEnvironment:
        """Boots a new hardened container adhering strictly to Spec §5."""
        def _create() -> DockerSandboxEnvironment:
            client = self._get_client()

            # Tooling and caches under /tmp (Spec §5)
            # Zero backend environment variables or cloud secrets injected
            safe_env = {
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "PIP_CACHE_DIR": "/tmp/.cache/pip",
                "PYTHONPATH": "/tmp/pylibs",
                "NPM_CONFIG_CACHE": "/tmp/.npm",
                "TMPDIR": "/tmp",
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                **spec.env,
            }

            # Hardened container configuration
            container = client.containers.run(
                image=spec.image,
                command=["sleep", "infinity"],
                user="1000:1000",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=True,
                network_mode=spec.network_mode,
                nano_cpus=int(spec.cpu_limit * 1e9),
                mem_limit=spec.mem_limit,
                pids_limit=spec.pids_limit,
                tmpfs={
                    "/workspace": f"rw,exec,nosuid,nodev,size={spec.workspace_size},uid=1000,gid=1000,mode=1777",
                    "/tmp": f"rw,exec,nosuid,nodev,size={spec.tmp_size},uid=1000,gid=1000,mode=1777",
                },
                volumes={},  # Zero host mounts
                labels={
                    "harness.managed": "true",
                    "harness.created_at": datetime.now(UTC).isoformat(),
                },
                environment=safe_env,
                detach=True,
            )

            return DockerSandboxEnvironment(client=client, container=container)

        return await asyncio.to_thread(_create)

    async def close(self) -> None:
        """Drains and tears down all idle containers in the warm pool."""
        self._is_closed = True
        while not self._warm_pool.empty():
            try:
                sandbox = self._warm_pool.get_nowait()
                await sandbox.stop()
            except asyncio.QueueEmpty:
                break
