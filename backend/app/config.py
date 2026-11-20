"""
Configuration Management for Cloud-Native AI Coding Harness.
Implements Pydantic Settings declaring all environment variables from .env.example
and fail-fast validators adhering strictly to Spec §3.6, §7.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from backend.app.application.headroom import validate_tmpfs_headroom
from backend.app.application.provider_selection import resolve_llm_provider
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file with fail-fast validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 1. Environment Mode
    HARNESS_ENV: Literal["development", "test", "production"] = "development"

    # 2. LLM Provider Configuration
    LLM_PROVIDER: str | None = None
    LLM_MODEL: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None

    # Effective values populated by provider selection validator
    effective_llm_provider: str = Field(default="", init=False)
    effective_llm_model: str = Field(default="", init=False)

    # 3. Authentication Configuration
    AUTH_PROVIDER: Literal["dev", "clerk"] = "dev"
    CLERK_JWKS_URL: str | None = None
    CLERK_ISSUER: str | None = None

    # 4. Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/harness"

    # 5. Object Storage Configuration
    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_PUBLIC_ENDPOINT_URL: str = "http://127.0.0.1:9000"
    S3_BUCKET: str = "harness-artifacts"
    S3_ACCESS_KEY: str | None = "minioadmin"
    S3_SECRET_KEY: str | None = "minioadmin"
    S3_REGION: str = "us-east-1"

    # 6. Docker Proxy Connection
    DOCKER_HOST: str = "tcp://docker-proxy:2375"

    # 7. Sandbox Container Specification & Hardening
    SANDBOX_IMAGE: str = "harness-sandbox:latest"
    SANDBOX_NETWORK_MODE: str = "none"
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_MEM_LIMIT: str = "1g"
    SANDBOX_PIDS_LIMIT: int = 256
    SANDBOX_WARM_POOL_SIZE: int = 2
    SANDBOX_WORKSPACE_SIZE: str = "384m"
    SANDBOX_TMP_SIZE: str = "128m"

    # 8. Orchestration & Concurrency Limits
    MAX_CONCURRENT_RUNS: int = 4
    AGENT_MAX_STEPS: int = 40
    AGENT_MAX_TOKENS: int = 200000
    AGENT_MAX_CONSECUTIVE_FAILURES: int = 5
    COMMAND_TIMEOUT_SECONDS: int = 120
    MAX_UPLOAD_MB: int = 50
    MAX_OUTPUT_BYTES_PER_RUN: int = 5242880
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    )

    @model_validator(mode="after")
    def validate_all(self) -> Settings:
        # 1. Headroom validation (Spec §3.6): total tmpfs <= 60% of memory limit
        validate_tmpfs_headroom(
            workspace_size=self.SANDBOX_WORKSPACE_SIZE,
            tmp_size=self.SANDBOX_TMP_SIZE,
            mem_limit=self.SANDBOX_MEM_LIMIT,
            max_ratio=0.60,
        )

        # 2. Environment integrity guards (Spec §3.6, §7)
        if self.HARNESS_ENV == "production" and self.AUTH_PROVIDER == "dev":
            raise ValueError("AUTH_PROVIDER='dev' is refused in production mode (HARNESS_ENV=production).")

        if self.AUTH_PROVIDER == "clerk" and (not self.CLERK_JWKS_URL or not self.CLERK_ISSUER):
            raise ValueError(
                "CLERK_JWKS_URL and CLERK_ISSUER must be configured when AUTH_PROVIDER='clerk'."
            )


        # 3. Provider selection logic (Spec §3.6)
        provider, model = resolve_llm_provider(
            llm_provider=self.LLM_PROVIDER,
            anthropic_key=self.ANTHROPIC_API_KEY,
            openai_key=self.OPENAI_API_KEY,
            harness_env=self.HARNESS_ENV,
            model=self.LLM_MODEL,
        )
        object.__setattr__(self, "effective_llm_provider", provider)
        object.__setattr__(self, "effective_llm_model", model)

        return self

    def get_secrets(self) -> list[str]:
        """Returns non-empty secret keys configured for redacting sensitive values."""
        secrets: list[str] = []
        for val in [
            self.ANTHROPIC_API_KEY,
            self.OPENAI_API_KEY,
            self.S3_SECRET_KEY,
            self.S3_ACCESS_KEY,
        ]:
            if val and len(val.strip()) > 3:
                secrets.append(val.strip())
        return secrets


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns singleton cached instance of validated application settings."""
    return Settings()
