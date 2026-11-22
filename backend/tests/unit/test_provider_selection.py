"""
Unit tests for LLM Provider Selection and Startup Validation.

Adheres strictly to Spec §3.6:
- Provider selection (single source of truth):
  - Explicit provider: validates provider and checks corresponding API key is present.
  - Unset provider & exactly one key present: select that provider.
  - Both keys present & unset provider: fail fast asking user to set LLM_PROVIDER.
  - Neither key present & unset provider: fail fast naming both key variables.
  - Scripted provider refused if HARNESS_ENV != "test".
  - Scripted provider refused in HARNESS_ENV == "production".
- Model defaults pinned per provider.
"""

from __future__ import annotations

import pytest
from backend.app.application.provider_selection import (
    DEFAULT_MODELS,
    resolve_llm_provider,
)


def test_explicit_anthropic_with_key_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="anthropic",
        anthropic_key="sk-ant-testkey",
        openai_key=None,
    )
    assert provider == "anthropic"
    assert model == DEFAULT_MODELS["anthropic"]


def test_explicit_anthropic_with_custom_model_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="anthropic",
        anthropic_key="sk-ant-testkey",
        model="claude-3-7-sonnet-20250219",
    )
    assert provider == "anthropic"
    assert model == "claude-3-7-sonnet-20250219"


def test_explicit_anthropic_without_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not configured"):
        resolve_llm_provider(
            llm_provider="anthropic",
            anthropic_key="",
        )


def test_explicit_openai_with_key_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="openai",
        anthropic_key=None,
        openai_key="sk-open-testkey",
    )
    assert provider == "openai"
    assert model == DEFAULT_MODELS["openai"]


def test_explicit_openai_without_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not configured"):
        resolve_llm_provider(
            llm_provider="openai",
            openai_key="",
        )


def test_explicit_scripted_in_test_env_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="scripted",
        anthropic_key=None,
        openai_key=None,
        harness_env="test",
    )
    assert provider == "scripted"
    assert model == DEFAULT_MODELS["scripted"]


def test_explicit_scripted_outside_test_env_fails_fast() -> None:
    with pytest.raises(ValueError, match="refused unless HARNESS_ENV='test'"):
        resolve_llm_provider(
            llm_provider="scripted",
            harness_env="development",
        )


def test_explicit_scripted_in_production_env_strictly_refused() -> None:
    with pytest.raises(ValueError, match="strictly forbidden in production"):
        resolve_llm_provider(
            llm_provider="scripted",
            harness_env="production",
        )


def test_invalid_explicit_provider_name_fails_fast() -> None:
    with pytest.raises(ValueError, match="Invalid LLM_PROVIDER 'unsupported'"):
        resolve_llm_provider(
            llm_provider="unsupported",
            anthropic_key="sk-ant-key",
        )


def test_unset_provider_infers_anthropic_when_only_anthropic_key_present() -> None:
    provider, model = resolve_llm_provider(
        llm_provider=None,
        anthropic_key="sk-ant-key",
        openai_key=None,
    )
    assert provider == "anthropic"
    assert model == DEFAULT_MODELS["anthropic"]


def test_unset_provider_infers_openai_when_only_openai_key_present() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="",
        anthropic_key=None,
        openai_key="sk-openai-key",
    )
    assert provider == "openai"
    assert model == DEFAULT_MODELS["openai"]


def test_unset_provider_with_both_keys_present_fails_fast() -> None:
    with pytest.raises(
        ValueError,
        match="Both ANTHROPIC_API_KEY and OPENAI_API_KEY are configured, but LLM_PROVIDER is unset",
    ):
        resolve_llm_provider(
            llm_provider=None,
            anthropic_key="sk-ant-key",
            openai_key="sk-open-key",
        )


def test_unset_provider_with_neither_key_present_fails_fast_naming_variables() -> None:
    with pytest.raises(ValueError) as exc_info:
        resolve_llm_provider(
            llm_provider=None,
            anthropic_key=None,
            openai_key=None,
        )

    msg = str(exc_info.value)
    # Must name both key variables
    assert "ANTHROPIC_API_KEY" in msg
    assert "OPENAI_API_KEY" in msg


def test_explicit_apinex_with_key_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="apinex",
        apinex_key="sk-apx-test",
    )
    assert provider == "apinex"
    assert model == DEFAULT_MODELS["apinex"]


def test_explicit_groq_with_key_succeeds() -> None:
    provider, model = resolve_llm_provider(
        llm_provider="groq",
        groq_key="gsk-groq-test",
    )
    assert provider == "groq"
    assert model == DEFAULT_MODELS["groq"]


def test_explicit_apinex_without_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="APINEX_API_KEY is not configured"):
        resolve_llm_provider(
            llm_provider="apinex",
            apinex_key="",
        )


def test_explicit_groq_without_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY is not configured"):
        resolve_llm_provider(
            llm_provider="groq",
            groq_key="",
        )
