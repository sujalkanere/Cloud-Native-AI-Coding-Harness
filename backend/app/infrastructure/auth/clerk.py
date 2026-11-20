"""
Clerk Auth Provider for Cloud-Native AI Coding Harness.
Implements IAuthProvider verifying RS256 JWT tokens against Clerk JWKS and issuer.
Adheres strictly to Spec §3.2, §3.5, §7.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import jwt
from backend.app.domain.errors import AuthenticationError
from backend.app.domain.interfaces import IAuthProvider
from backend.app.domain.models import AuthenticatedUser
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger(__name__)


class ClerkAuthProvider(IAuthProvider):
    """
    Clerk JWT Authentication Provider.
    Extracts Bearer token from headers or 'token' query parameter (for WebSocket connections).
    Validates token signature against JWKS and issuer claims.
    """

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer
        self._client = client
        self._public_keys: dict[str, Any] = {}

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _extract_token(self, request: Any) -> str:
        """Extracts JWT token from Authorization header or 'token' query param."""
        # 1. Check Authorization header
        auth_header = None
        if hasattr(request, "headers"):
            auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        elif isinstance(request, dict):
            headers = request.get("headers", {})
            auth_header = headers.get("Authorization") or headers.get("authorization")

        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        # 2. Check query param 'token' (Spec §3.5: WebSocket connections)
        query_token = None
        if hasattr(request, "query_params"):
            query_token = request.query_params.get("token")
        elif isinstance(request, dict):
            query = request.get("query_params") or request.get("params") or {}
            query_token = query.get("token")

        if query_token:
            return str(query_token).strip()

        raise AuthenticationError("Missing authentication token in Authorization header or query parameter")

    async def _fetch_jwks(self) -> None:
        """Fetches public keys from JWKS endpoint and caches them."""
        client = self._get_http_client()
        try:
            resp = await client.get(self.jwks_url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            raise AuthenticationError(f"Failed to fetch JWKS from {self.jwks_url}: {exc}") from exc


        keys = data.get("keys", [])
        new_keys: dict[str, Any] = {}
        for key_dict in keys:
            kid = key_dict.get("kid")
            if kid and key_dict.get("kty") == "RSA":
                try:
                    pub_key = RSAAlgorithm.from_jwk(key_dict)
                    new_keys[kid] = pub_key
                except (ValueError, KeyError, TypeError) as exc:
                    logger.debug("Failed parsing JWK %s: %s", kid, exc)


        self._public_keys = new_keys

    async def authenticate(self, request: Any) -> AuthenticatedUser:
        token = self._extract_token(request)

        # 1. Read unverified header for kid
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid token header: {exc}") from exc

        if not kid:
            raise AuthenticationError("Token missing 'kid' header parameter")

        # 2. Lookup public key in cache, refresh if not found
        if kid not in self._public_keys:
            await self._fetch_jwks()

        if kid not in self._public_keys:
            raise AuthenticationError(f"Unknown signing key id '{kid}'")

        pub_key = self._public_keys[kid]

        # 3. Verify signature, issuer, expiration
        try:
            payload = jwt.decode(
                token,
                pub_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError(f"Invalid token issuer: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            if "Subject" in str(exc) or "sub" in str(exc):
                raise AuthenticationError("Token missing 'sub' claim") from exc
            raise AuthenticationError(f"Invalid token signature: {exc}") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid token signature: {exc}") from exc


        sub = payload.get("sub")
        if not sub:
            raise AuthenticationError("Token missing 'sub' claim")

        email = payload.get("email")
        username = payload.get("username") or payload.get("name") or payload.get("preferred_username")

        return AuthenticatedUser(
            id=sub,
            username=username,
            email=email,
        )
