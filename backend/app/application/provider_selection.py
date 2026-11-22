"""
LLM Provider Selection and Validation for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.6 and PROJECT.md:
- Provider selection (single source of truth):
  - LLM_PROVIDER set explicitly: use it; its key must be present (scripted needs none).
  - LLM_PROVIDER unset and exactly one of ANTHROPIC_API_KEY / OPENAI_API_KEY set: use that provider.
  - Both keys set and LLM_PROVIDER unset: fail fast asking the user to set LLM_PROVIDER.
  - No key set (and not scripted): fail fast naming both key variables (ANTHROPIC_API_KEY, OPENAI_API_KEY).
- Model default: if LLM_MODEL is unset, each provider uses a pinned default model.
- Startup rules: LLM_PROVIDER=scripted is refused unless HARNESS_ENV=test.
  In HARNESS_ENV=production, LLM_PROVIDER=scripted is strictly refused.
"""

from __future__ import annotations

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o",
    "apinex": "free/qwen-3.8-max",
    "groq": "openai/gpt-oss-120b",
    "scripted": "mock-scripted-model",
}

VALID_PROVIDERS = set(DEFAULT_MODELS.keys())


def resolve_llm_provider(
    llm_provider: str | None = None,
    anthropic_key: str | None = None,
    openai_key: str | None = None,
    harness_env: str = "development",
    model: str | None = None,
    apinex_key: str | None = None,
    groq_key: str | None = None,
) -> tuple[str, str]:
    """
    Resolves and validates the LLM provider and default model.

    Returns (provider_name, model_name).
    Raises ValueError on invalid configurations, missing keys, or environment violations.
    """
    env = (harness_env or "development").strip().lower()
    provider = (
        llm_provider.strip().lower()
        if (llm_provider and llm_provider.strip())
        else None
    )
    has_anthropic = bool(anthropic_key and anthropic_key.strip())
    has_openai = bool(openai_key and openai_key.strip())
    has_apinex = bool(apinex_key and apinex_key.strip())
    has_groq = bool(groq_key and groq_key.strip())

    # Environment integrity checks
    if env == "production" and provider == "scripted":
        raise ValueError(
            "LLM_PROVIDER='scripted' is strictly forbidden in production (HARNESS_ENV=production)."
        )

    if provider == "scripted" and env != "test":
        raise ValueError(
            f"LLM_PROVIDER='scripted' is refused unless HARNESS_ENV='test' (current HARNESS_ENV='{env}')."
        )

    # Explicit provider selection
    if provider is not None:
        if provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid LLM_PROVIDER '{provider}'. Supported providers: "
                f"{', '.join(sorted(VALID_PROVIDERS))}."
            )

        if provider == "anthropic":
            if not has_anthropic:
                raise ValueError(
                    "LLM_PROVIDER is set to 'anthropic' but ANTHROPIC_API_KEY is not configured."
                )
            return ("anthropic", model or DEFAULT_MODELS["anthropic"])

        if provider == "openai":
            if not has_openai:
                raise ValueError(
                    "LLM_PROVIDER is set to 'openai' but OPENAI_API_KEY is not configured."
                )
            return ("openai", model or DEFAULT_MODELS["openai"])

        if provider == "apinex":
            if not has_apinex and not has_openai:
                raise ValueError(
                    "LLM_PROVIDER is set to 'apinex' but APINEX_API_KEY is not configured."
                )
            return ("apinex", model or DEFAULT_MODELS["apinex"])

        if provider == "groq":
            if not has_groq and not has_openai:
                raise ValueError(
                    "LLM_PROVIDER is set to 'groq' but GROQ_API_KEY is not configured."
                )
            return ("groq", model or DEFAULT_MODELS["groq"])

        if provider == "scripted":
            return ("scripted", model or DEFAULT_MODELS["scripted"])

    # Unset provider inference
    configured_keys = [
        ("anthropic", has_anthropic),
        ("openai", has_openai),
        ("apinex", has_apinex),
        ("groq", has_groq),
    ]
    active_providers = [name for name, has_key in configured_keys if has_key]

    if has_anthropic and has_openai and len(active_providers) == 2:
        raise ValueError(
            "Both ANTHROPIC_API_KEY and OPENAI_API_KEY are configured, but LLM_PROVIDER is unset. "
            "Please explicitly set LLM_PROVIDER to 'anthropic' or 'openai'."
        )

    if len(active_providers) > 1:
        raise ValueError(
            f"Multiple LLM API keys configured ({', '.join(active_providers)}), but LLM_PROVIDER is unset. "
            f"Please explicitly set LLM_PROVIDER."
        )

    if has_anthropic:
        return ("anthropic", model or DEFAULT_MODELS["anthropic"])

    if has_openai:
        return ("openai", model or DEFAULT_MODELS["openai"])

    if has_apinex:
        return ("apinex", model or DEFAULT_MODELS["apinex"])

    if has_groq:
        return ("groq", model or DEFAULT_MODELS["groq"])

    # Neither key present and provider unset
    raise ValueError(
        "No LLM API keys provided. Please configure ANTHROPIC_API_KEY or OPENAI_API_KEY, "
        "or set LLM_PROVIDER=scripted with HARNESS_ENV=test."
    )
