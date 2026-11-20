"""
Unit tests for Configuration and Bootstrap Composition Root.
Adheres strictly to Spec §3.1, §3.6, §7, §9.1.
Validates:
- Headroom validation on Settings
- Provider selection rules (explicit, inferred, conflict, missing)
- Environment integrity guards (production dev auth / scripted LLM rejection)
- Bootstrap adapter wiring and container assembly
"""
from __future__ import annotations

import pytest
from backend.app.bootstrap import AppContainer, bootstrap
from backend.app.config import Settings
from backend.app.domain.errors import HeadroomValidationError
from backend.app.domain.interfaces import (
    IAuthProvider,
    ILLMProvider,
    IObjectStorage,
    IRunRepository,
    ISandboxProvider,
)


def test_shipped_defaults_pass_headroom_validation():
    """Spec §3.6 & §9.1: Unit test asserts shipped defaults pass headroom validation."""
    settings = Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
        SANDBOX_WORKSPACE_SIZE="384m",
        SANDBOX_TMP_SIZE="128m",
        SANDBOX_MEM_LIMIT="1g",
    )
    assert settings.SANDBOX_WORKSPACE_SIZE == "384m"
    assert settings.SANDBOX_TMP_SIZE == "128m"
    assert settings.SANDBOX_MEM_LIMIT == "1g"
    assert settings.effective_llm_provider == "scripted"


def test_headroom_validation_failure():
    """Spec §3.6: Tmpfs exceeding 60% of memory limit must fail fast with HeadroomValidationError."""
    with pytest.raises(HeadroomValidationError, match="Tmpfs memory headroom exceeded"):
        Settings(
            HARNESS_ENV="test",
            LLM_PROVIDER="scripted",
            SANDBOX_WORKSPACE_SIZE="512m",
            SANDBOX_TMP_SIZE="256m",  # 768m of 1g = 75% > 60%
            SANDBOX_MEM_LIMIT="1g",
        )


def test_provider_selection_explicit_anthropic():
    settings = Settings(
        HARNESS_ENV="development",
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="sk-ant-test-key",
    )
    assert settings.effective_llm_provider == "anthropic"
    assert settings.effective_llm_model == "claude-3-5-sonnet-20241022"


def test_provider_selection_inferred_openai():
    settings = Settings(
        HARNESS_ENV="development",
        LLM_PROVIDER=None,
        OPENAI_API_KEY="sk-openai-test-key",
        ANTHROPIC_API_KEY=None,
    )
    assert settings.effective_llm_provider == "openai"
    assert settings.effective_llm_model == "gpt-4o"


def test_provider_selection_conflict_fails_fast():
    """Spec §3.6: Both keys set and LLM_PROVIDER unset fails fast."""
    with pytest.raises(ValueError, match="Both ANTHROPIC_API_KEY and OPENAI_API_KEY are configured"):
        Settings(
            HARNESS_ENV="development",
            LLM_PROVIDER=None,
            ANTHROPIC_API_KEY="sk-ant-123",
            OPENAI_API_KEY="sk-openai-123",
        )


def test_provider_selection_neither_fails_fast():
    """Spec §3.6: Neither key set fails fast naming both keys."""
    with pytest.raises(ValueError, match="No LLM API keys provided"):
        Settings(
            HARNESS_ENV="development",
            LLM_PROVIDER=None,
            ANTHROPIC_API_KEY=None,
            OPENAI_API_KEY=None,
        )


def test_integrity_guard_refuse_dev_auth_in_production():
    """Spec §3.6, §7: In HARNESS_ENV=production, AUTH_PROVIDER=dev is refused."""
    with pytest.raises(ValueError, match="AUTH_PROVIDER='dev' is refused in production"):
        Settings(
            HARNESS_ENV="production",
            AUTH_PROVIDER="dev",
            ANTHROPIC_API_KEY="sk-ant-123",
        )


def test_integrity_guard_refuse_scripted_llm_in_production():
    """Spec §3.6, §7: In HARNESS_ENV=production, LLM_PROVIDER=scripted is refused."""
    with pytest.raises(ValueError, match="forbidden in production"):
        Settings(
            HARNESS_ENV="production",
            AUTH_PROVIDER="clerk",
            CLERK_JWKS_URL="https://clerk.test/.well-known/jwks.json",
            CLERK_ISSUER="https://clerk.test",
            LLM_PROVIDER="scripted",
        )


def test_integrity_guard_refuse_scripted_outside_test():
    """Spec §3.6: LLM_PROVIDER=scripted accepted only when HARNESS_ENV=test."""
    with pytest.raises(ValueError, match="refused unless HARNESS_ENV='test'"):
        Settings(
            HARNESS_ENV="development",
            LLM_PROVIDER="scripted",
        )


def test_clerk_auth_missing_jwks_or_issuer():
    with pytest.raises(ValueError, match="CLERK_JWKS_URL and CLERK_ISSUER must be configured"):
        Settings(
            HARNESS_ENV="development",
            AUTH_PROVIDER="clerk",
            CLERK_JWKS_URL=None,
            ANTHROPIC_API_KEY="sk-ant-123",
        )


def test_bootstrap_composition_root():
    settings = Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
        AUTH_PROVIDER="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )

    container = bootstrap(settings)
    assert isinstance(container, AppContainer)
    assert isinstance(container.auth_provider, IAuthProvider)
    assert isinstance(container.llm_provider, ILLMProvider)
    assert isinstance(container.storage, IObjectStorage)
    assert isinstance(container.run_repository, IRunRepository)
    assert isinstance(container.sandbox_provider, ISandboxProvider)
