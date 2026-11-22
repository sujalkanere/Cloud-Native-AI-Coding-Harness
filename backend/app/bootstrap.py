"""
Composition Root for Cloud-Native AI Coding Harness.
Adheres strictly to Spec §3.1, §3.6, §7:
- Dependencies point strictly inward.
- Single composition root wiring concrete infrastructure adapters based on validated settings.
- ScriptedLLMProvider is imported dynamically only in test mode (never in production).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.application.redaction import SecretRedactor
from backend.app.config import Settings, get_settings
from backend.app.domain.interfaces import (
    IAuthProvider,
    ILLMProvider,
    IObjectStorage,
    IRunRepository,
    ISandboxProvider,
)
from backend.app.domain.models import SandboxSpec
from backend.app.infrastructure.auth.clerk import ClerkAuthProvider
from backend.app.infrastructure.auth.dev import DevAuthProvider
from backend.app.infrastructure.database.repository import PostgresRunRepository
from backend.app.infrastructure.llm.anthropic import AnthropicProvider
from backend.app.infrastructure.llm.openai import OpenAIProvider
from backend.app.infrastructure.sandbox.provider import DockerSandboxProvider
from backend.app.infrastructure.storage.s3 import S3ObjectStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


@dataclass
class AppContainer:
    """Dependency injection container holding instantiated application components."""

    settings: Settings
    redactor: SecretRedactor
    auth_provider: IAuthProvider
    llm_provider: ILLMProvider
    storage: IObjectStorage
    run_repository: IRunRepository
    sandbox_provider: ISandboxProvider
    session_factory: async_sessionmaker[AsyncSession]
    concurrency_manager: RunConcurrencyManager | None = None


def bootstrap(settings: Settings | None = None) -> AppContainer:
    """
    Wires and instantiates all application adapters according to validated settings.
    Sole composition root for backend application.
    """
    active_settings = settings or get_settings()

    # 1. Secret Redactor
    redactor = SecretRedactor(secrets=active_settings.get_secrets())

    # 2. Authentication Provider
    auth_provider: IAuthProvider
    if active_settings.AUTH_PROVIDER == "dev":
        auth_provider = DevAuthProvider()
    elif active_settings.AUTH_PROVIDER == "clerk":
        assert active_settings.CLERK_JWKS_URL is not None
        assert active_settings.CLERK_ISSUER is not None
        auth_provider = ClerkAuthProvider(
            jwks_url=active_settings.CLERK_JWKS_URL,
            issuer=active_settings.CLERK_ISSUER,
        )
    else:
        raise ValueError(f"Unsupported AUTH_PROVIDER: {active_settings.AUTH_PROVIDER}")

    # 3. LLM Provider
    llm_provider: ILLMProvider
    provider_name = active_settings.effective_llm_provider

    if provider_name == "anthropic":
        assert active_settings.ANTHROPIC_API_KEY is not None
        llm_provider = AnthropicProvider(
            api_key=active_settings.ANTHROPIC_API_KEY,
            model=active_settings.effective_llm_model,
            redactor=redactor,
        )
    elif provider_name == "openai":
        assert active_settings.OPENAI_API_KEY is not None
        llm_provider = OpenAIProvider(
            api_key=active_settings.OPENAI_API_KEY,
            model=active_settings.effective_llm_model,
            base_url=active_settings.OPENAI_BASE_URL,
            redactor=redactor,
        )
    elif provider_name == "apinex":
        api_key = active_settings.APINEX_API_KEY or active_settings.OPENAI_API_KEY
        assert api_key is not None
        llm_provider = OpenAIProvider(
            api_key=api_key,
            model=active_settings.effective_llm_model,
            base_url=active_settings.APINEX_BASE_URL or "https://api.apinex.bond/v1",
            redactor=redactor,
        )
    elif provider_name == "groq":
        api_key = active_settings.GROQ_API_KEY or active_settings.OPENAI_API_KEY
        assert api_key is not None
        llm_provider = OpenAIProvider(
            api_key=api_key,
            model=active_settings.effective_llm_model,
            base_url=active_settings.GROQ_BASE_URL or "https://api.groq.com/openai/v1",
            redactor=redactor,
        )
    elif provider_name == "scripted":
        # Dynamic import ensures test_support is never imported in production builds (Spec §7)
        from backend.test_support.scripted_llm import ScriptedLLMProvider

        llm_provider = ScriptedLLMProvider()
    else:
        raise ValueError(f"Unsupported LLM provider: {provider_name}")

    # 4. S3 Object Storage Adapter
    storage = S3ObjectStorage(
        endpoint_url=active_settings.S3_ENDPOINT_URL,
        public_endpoint_url=active_settings.S3_PUBLIC_ENDPOINT_URL,
        bucket=active_settings.S3_BUCKET,
        access_key=active_settings.S3_ACCESS_KEY,
        secret_key=active_settings.S3_SECRET_KEY,
        region=active_settings.S3_REGION,
    )

    # 5. Database Connection & Postgres Run Repository
    engine = create_async_engine(
        active_settings.DATABASE_URL,
        echo=False,
        future=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    run_repository = PostgresRunRepository(session_factory=session_factory)

    # 6. Docker Sandbox Provider
    default_spec = SandboxSpec(
        image=active_settings.SANDBOX_IMAGE,
        cpu_limit=active_settings.SANDBOX_CPU_LIMIT,
        mem_limit=active_settings.SANDBOX_MEM_LIMIT,
        pids_limit=active_settings.SANDBOX_PIDS_LIMIT,
        workspace_size=active_settings.SANDBOX_WORKSPACE_SIZE,
        tmp_size=active_settings.SANDBOX_TMP_SIZE,
        network_mode=active_settings.SANDBOX_NETWORK_MODE,
    )
    sandbox_provider = DockerSandboxProvider(
        docker_host=active_settings.DOCKER_HOST,
        warm_pool_size=active_settings.SANDBOX_WARM_POOL_SIZE,
        default_spec=default_spec,
    )

    concurrency_manager = RunConcurrencyManager(
        repository=run_repository,
        sandbox_provider=sandbox_provider,
        llm_provider=llm_provider,
        storage=storage,
        settings=active_settings,
    )

    return AppContainer(
        settings=active_settings,
        redactor=redactor,
        auth_provider=auth_provider,
        llm_provider=llm_provider,
        storage=storage,
        run_repository=run_repository,
        sandbox_provider=sandbox_provider,
        session_factory=session_factory,
        concurrency_manager=concurrency_manager,
    )
