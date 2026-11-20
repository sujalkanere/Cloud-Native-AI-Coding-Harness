"""
Dev Auth Provider for Cloud-Native AI Coding Harness.
Implements IAuthProvider returning a fixed user entity.
Refused when HARNESS_ENV=production.
Adheres strictly to Spec §3.2, §3.5, §7.
"""
from __future__ import annotations

from typing import Any

from backend.app.domain.interfaces import IAuthProvider
from backend.app.domain.models import AuthenticatedUser


class DevAuthProvider(IAuthProvider):
    """Development authentication provider returning a deterministic user."""

    def __init__(
        self,
        user_id: str = "user_dev_001",
        username: str = "dev_user",
        email: str = "dev@example.com",
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.email = email

    async def authenticate(self, request: Any) -> AuthenticatedUser:
        """Returns the fixed developer user regardless of headers or query parameters."""
        return AuthenticatedUser(
            id=self.user_id,
            username=self.username,
            email=self.email,
        )
