"""
Security test conftest: overrides clerk_setup to pre-seed JWKS keys synchronously.

Root cause of original hang:
  When TestClient opens a WebSocket, the ASGI app runs in a background thread.
  ClerkAuthProvider.authenticate() calls `await self._fetch_jwks()` using an
  httpx.AsyncClient whose event loop belongs to a different thread, causing a
  deadlock on the WebSocket test.

Fix:
  1. Patch `ClerkAuthProvider._fetch_jwks` to a no-op via autouse fixture.
  2. Override the `clerk_setup` fixture to pre-seed `_public_keys` synchronously
     before returning, so authenticate() never calls _fetch_jwks at all.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from backend.app.api.main import create_app
from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.application.redaction import SecretRedactor
from backend.app.bootstrap import AppContainer
from backend.app.domain.interfaces import IObjectStorage, IRunRepository
from backend.app.infrastructure.auth.clerk import ClerkAuthProvider
from backend.test_support.fake_sandbox import FakeSandboxProvider
from backend.test_support.jwks_helper import JWKSHelper
from backend.test_support.scripted_llm import ScriptedLLMProvider
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm


def _build_public_keys(helper: JWKSHelper) -> dict:
    """Synchronously build the public-key dict that _fetch_jwks would populate."""
    result = {}
    for key_dict in helper.get_jwks().get("keys", []):
        kid = key_dict.get("kid")
        if kid and key_dict.get("kty") == "RSA":
            result[kid] = RSAAlgorithm.from_jwk(key_dict)
    return result


@pytest.fixture(autouse=True)
def patch_clerk_no_jwks_fetch():
    """
    Autouse: replace _fetch_jwks with a no-op for every test in this directory.
    Public keys are pre-seeded in clerk_setup below, so the fetch is unnecessary.
    """
    async def _noop(self: ClerkAuthProvider) -> None:
        return

    with patch.object(ClerkAuthProvider, "_fetch_jwks", _noop):
        yield


@pytest.fixture
def clerk_setup(
    test_settings,
    in_memory_repo: IRunRepository,
    in_memory_storage: IObjectStorage,
    fake_sandbox_provider: FakeSandboxProvider,
    scripted_llm: ScriptedLLMProvider,
):
    """
    Overrides root clerk_setup: same interface but pre-seeds _public_keys so
    authenticate() never triggers _fetch_jwks (which deadlocks in WS tests).
    """
    helper = JWKSHelper(kid="test-clerk-key-1", issuer="https://clerk.test")
    jwks_data = helper.get_jwks()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jwks.json"):
            return httpx.Response(200, json=jwks_data)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)

    clerk_auth = ClerkAuthProvider(
        jwks_url="https://clerk.test/.well-known/jwks.json",
        issuer="https://clerk.test",
        client=http_client,
    )
    # Pre-seed keys — prevents any async _fetch_jwks call during tests
    clerk_auth._public_keys = _build_public_keys(helper)

    concurrency_mgr = RunConcurrencyManager(
        repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        settings=test_settings,
    )
    container = AppContainer(
        settings=test_settings,
        redactor=SecretRedactor(secrets=[]),
        auth_provider=clerk_auth,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        run_repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        session_factory=None,  # type: ignore[arg-type]
        concurrency_manager=concurrency_mgr,
    )
    app = create_app(settings=test_settings, container=container, skip_migrations=True)
    client = TestClient(app)
    return helper, container, app, client
