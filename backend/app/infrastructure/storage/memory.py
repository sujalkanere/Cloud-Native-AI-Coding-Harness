"""
In-Memory Object Storage Adapter for Cloud-Native AI Coding Harness.
Implements IObjectStorage for local development and offline environments.
"""
from __future__ import annotations

import logging

from backend.app.domain.interfaces import IObjectStorage

logger = logging.getLogger(__name__)


class InMemoryObjectStorage(IObjectStorage):
    """In-memory object storage adapter for local development testing."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(f"Storage key '{key}' not found in in-memory storage.")
        return self.objects[key]

    def presigned_url(self, key: str, ttl: int = 3600) -> str:
        return f"/api/artifacts/download?key={key}"

    async def ensure_bucket_exists(self) -> None:
        pass
