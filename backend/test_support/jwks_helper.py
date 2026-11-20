"""
JWKS and JWT Test Support Helper for Cloud-Native AI Coding Harness.
Generates local RSA keypairs, exports RFC 7517 JWKS, and signs RS256 JWTs for testing.
Adheres strictly to Spec §7, §9.1.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


class JWKSHelper:
    """Offline RSA keypair and JWKS/JWT generator for ClerkAuthProvider tests."""

    def __init__(
        self,
        kid: str = "test-key-01",
        issuer: str = "https://clerk.example.com",
    ) -> None:
        self.kid = kid
        self.issuer = issuer
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.public_key = self.private_key.public_key()

    def get_jwks(self) -> dict[str, Any]:
        """Exports RFC 7517 JWKS dictionary containing public RSA key."""
        public_numbers = self.public_key.public_numbers()

        def int_to_b64(val: int) -> str:
            # Big-endian bytes
            b = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
            return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

        jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": int_to_b64(public_numbers.n),
            "e": int_to_b64(public_numbers.e),
        }
        return {"keys": [jwk]}

    def generate_token(
        self,
        user_id: str,
        email: str | None = None,
        username: str | None = None,
        expires_in: int = 3600,
        issuer: str | None = None,
        kid: str | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Signs an RS256 JWT for the given user."""
        now = datetime.now(UTC)
        payload = {
            "sub": user_id,
            "iss": issuer or self.issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        }
        if email:
            payload["email"] = email
        if username:
            payload["username"] = username
        if extra_claims:
            for k, v in extra_claims.items():
                if v is None and k in payload:
                    del payload[k]
                else:
                    payload[k] = v


        headers = {
            "kid": kid or self.kid,
            "alg": "RS256",
        }

        return jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers=headers,
        )
