"""
Unit tests for AnthropicProvider, OpenAIProvider, and ScriptedLLMProvider.
Adheres strictly to Spec §3.2, §4, §7, §9.1.
Validates:
- Message and tool formatting
- Exponential backoff retry on 429/5xx and fail-fast on 4xx
- Secret redaction on inputs and outputs
- Scripted replay of buggy-calculator fixture
"""
from __future__ import annotations

import httpx
import pytest
from backend.app.application.redaction import SecretRedactor
from backend.app.domain.interfaces import ILLMProvider
from backend.app.domain.models import (
    LLMMessage,
    ToolDefinition,
)
from backend.app.infrastructure.llm.anthropic import AnthropicProvider
from backend.app.infrastructure.llm.openai import OpenAIProvider
from backend.test_support.scripted_llm import ScriptedLLMProvider


def test_protocol_conformance():
    anthropic = AnthropicProvider(api_key="test-key")
    assert isinstance(anthropic, ILLMProvider)

    openai = OpenAIProvider(api_key="test-key")
    assert isinstance(openai, ILLMProvider)

    scripted = ScriptedLLMProvider()
    assert isinstance(scripted, ILLMProvider)


# ================= Anthropic Provider Tests =================


@pytest.mark.asyncio
async def test_anthropic_provider_complete():
    secret_key = "secret_key_12345"
    redactor = SecretRedactor(secrets=[secret_key])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "sk-ant-test"
        payload = request.read().decode("utf-8")
        assert secret_key not in payload, "Secret must be redacted from payload"
        assert "[REDACTED]" in payload

        response_data = {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": f"Thought with secret {secret_key}"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {"path": "calculator.py"},
                },
            ],
            "usage": {"input_tokens": 50, "output_tokens": 25},
        }
        return httpx.Response(200, json=response_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        redactor=redactor,
        client=client,
    )

    messages = [
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content=f"Hello with {secret_key}"),
    ]
    tools = [
        ToolDefinition(
            name="read_file",
            description="Read file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]

    res = await provider.complete(messages, tools)
    assert "[REDACTED]" in res.content
    assert secret_key not in res.content
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "read_file"
    assert res.prompt_tokens == 50
    assert res.completion_tokens == 25
    assert res.total_tokens == 75


@pytest.mark.asyncio
async def test_anthropic_retry_backoff():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"error": "rate_limited"})
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Success after retries"}],
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        client=client,
        max_retries=3,
        base_delay=0.01,
    )

    res = await provider.complete([LLMMessage(role="user", content="Hi")], [])
    assert attempts == 3
    assert res.content == "Success after retries"


@pytest.mark.asyncio
async def test_anthropic_non_retryable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_api_key"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(api_key="bad-key", client=client, max_retries=3, base_delay=0.01)

    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete([LLMMessage(role="user", content="Hi")], [])


# ================= OpenAI Provider Tests =================


@pytest.mark.asyncio
async def test_openai_provider_complete():
    secret_key = "openai_secret_token_999"
    redactor = SecretRedactor(secrets=[secret_key])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = request.read().decode("utf-8")
        assert secret_key not in payload, "Secret must be redacted"
        assert "[REDACTED]" in payload

        response_data = {
            "id": "chatcmpl_01",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": f"Here is secret: {secret_key}",
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "pytest", "purpose": "test"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
        }
        return httpx.Response(200, json=response_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider(
        api_key="sk-openai-test",
        base_url="https://api.openai.com/v1/",
        redactor=redactor,
        client=client,
    )

    messages = [LLMMessage(role="user", content=f"Run command {secret_key}")]
    res = await provider.complete(messages, [])

    assert "[REDACTED]" in res.content
    assert secret_key not in res.content
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "run_command"
    assert res.tool_calls[0].arguments == {"command": "pytest", "purpose": "test"}
    assert res.total_tokens == 60


@pytest.mark.asyncio
async def test_openai_retry_backoff():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(503, json={"error": "service_unavailable"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Recovered"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider(
        api_key="sk-test",
        client=client,
        max_retries=3,
        base_delay=0.01,
    )

    res = await provider.complete([LLMMessage(role="user", content="Ping")], [])
    assert attempts == 2
    assert res.content == "Recovered"


# ================= Scripted LLM Provider Tests =================


@pytest.mark.asyncio
async def test_scripted_llm_provider_replay():
    provider = ScriptedLLMProvider()
    assert provider.total_steps == 5

    # Step 1: read_file
    res1 = await provider.complete([], [])
    assert len(res1.tool_calls) == 1
    assert res1.tool_calls[0].name == "read_file"
    assert res1.tool_calls[0].arguments["path"] == "calculator.py"

    # Step 2: run_command pytest test_calculator.py
    res2 = await provider.complete([], [])
    assert len(res2.tool_calls) == 1
    assert res2.tool_calls[0].name == "run_command"
    assert "pytest" in res2.tool_calls[0].arguments["command"]

    # Step 3: write_file calculator.py
    res3 = await provider.complete([], [])
    assert len(res3.tool_calls) == 1
    assert res3.tool_calls[0].name == "write_file"
    assert res3.tool_calls[0].arguments["path"] == "calculator.py"

    # Step 4: run_command pytest test_calculator.py
    res4 = await provider.complete([], [])
    assert len(res4.tool_calls) == 1
    assert res4.tool_calls[0].name == "run_command"

    # Step 5: finish
    res5 = await provider.complete([], [])
    assert len(res5.tool_calls) == 1
    assert res5.tool_calls[0].name == "finish"
    assert "Fixed calculator bug" in res5.tool_calls[0].arguments["summary"]

    # Step 6: exhaustion raises RuntimeError
    with pytest.raises(RuntimeError, match="exhausted"):
        await provider.complete([], [])

    # Reset
    provider.reset()
    assert provider.current_step_index == 0
    res_reset = await provider.complete([], [])
    assert res_reset.tool_calls[0].name == "read_file"
