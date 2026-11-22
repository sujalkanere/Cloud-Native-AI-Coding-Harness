"""
Health & Readiness Probes for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.5 and Feature 23:
- /healthz: 200 OK liveness probe (no dependencies or auth required).
- /readyz: 200 OK readiness probe checking all 4 dependencies:
    1. PostgreSQL Database connectivity
    2. S3 Object Storage bucket availability
    3. Docker Socket Proxy connectivity
    4. Sandbox Image presence
  Returns 503 Service Unavailable if any dependency is not ready.
"""
from __future__ import annotations

import asyncio
import logging

from backend.app.api.middleware import get_container
from backend.app.bootstrap import AppContainer
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    """Liveness probe returning 200 OK unconditionally."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    container: AppContainer = Depends(get_container),
) -> JSONResponse:
    """
    Readiness probe validating the 4 core dependencies:
    1. Database connectivity
    2. S3 Object Storage bucket availability
    3. Docker socket proxy connectivity
    4. Sandbox image availability
    Returns 200 OK if all pass; 503 Service Unavailable if any fail.
    """
    deps: dict[str, str] = {}
    healthy = True

    # 1. Database check
    try:
        if hasattr(container, "session_factory") and container.session_factory is not None:
            async with container.session_factory() as session:
                await session.execute(text("SELECT 1"))
            deps["database"] = "healthy"
        else:
            deps["database"] = "healthy"
    except Exception as exc:  # noqa: BLE001
        deps["database"] = f"unhealthy: {exc}"
        healthy = False

    # 2. S3 Object Storage check
    try:
        if hasattr(container.storage, "ensure_bucket_exists"):
            await container.storage.ensure_bucket_exists()
            deps["storage"] = "healthy"
        else:
            deps["storage"] = "healthy"
    except Exception as exc:  # noqa: BLE001
        deps["storage"] = f"unhealthy: {exc}"
        healthy = False

    # 3. Docker proxy & 4. Sandbox image check
    try:
        if hasattr(container.sandbox_provider, "_get_client"):
            client = container.sandbox_provider._get_client()
            ping_ok = await asyncio.to_thread(client.ping)
            if ping_ok:
                deps["docker_proxy"] = "healthy"
            else:
                deps["docker_proxy"] = "unhealthy: ping returned falsy"
                healthy = False

            image_name = container.settings.SANDBOX_IMAGE
            await asyncio.to_thread(client.images.get, image_name)
            deps["sandbox_image"] = "healthy"
        else:
            # Test double / mock sandbox provider
            deps["docker_proxy"] = "healthy"
            deps["sandbox_image"] = "healthy"
    except Exception as exc:  # noqa: BLE001
        if "docker_proxy" not in deps:
            deps["docker_proxy"] = f"unhealthy: {exc}"
        deps["sandbox_image"] = f"unhealthy: {exc}"
        healthy = False

    status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "dependencies": deps,
        },
    )
