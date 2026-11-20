"""
Anthropic LLM Provider for Cloud-Native AI Coding Harness.
Implements ILLMProvider adhering strictly to Spec §3.2, §4, §7.
Supports Anthropic Messages API, tool calling via input_schema,
exponential backoff retry on 429/5xx, and secret redaction.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from backend.app.application.redaction import SecretRedactor
from backend.app.domain.interfaces import ILLMProvider
from backend.app.domain.models import (
    LLMMessage,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(ILLMProvider):
    """Anthropic Messages API provider with retry backoff and secret redaction."""

    API_URL: str = "https://api.anthropic.com/v1/messages"
    API_VERSION: str = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        redactor: SecretRedactor | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.redactor = redactor
        self._client = client
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    def _redact_text(self, text: str) -> str:
        if self.redactor:
            return self.redactor.redact(text)
        return text

    def _format_payload(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> dict[str, Any]:
        system_prompts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_prompts.append(self._redact_text(msg.content))
            elif msg.role == "tool":
                # Tool result block sent as a user message
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": self._redact_text(msg.content or ""),
                        }
                    ],
                })
            elif msg.role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({
                        "type": "text",
                        "text": self._redact_text(msg.content),
                    })
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                anthropic_messages.append({
                    "role": "assistant",
                    "content": content_blocks if content_blocks else [
                        {"type": "text", "text": ""}
                    ],
                })
            else:  # user
                anthropic_messages.append({
                    "role": "user",
                    "content": self._redact_text(msg.content or ""),
                })

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }

        if system_prompts:
            payload["system"] = "\n\n".join(system_prompts)

        if tools:
            anthropic_tools: list[dict[str, Any]] = []
            for t in tools:
                anthropic_tools.append({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                })
            payload["tools"] = anthropic_tools

        return payload

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        client = self._get_client()
        payload = self._format_payload(messages, tools)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()
                # 4xx errors fail immediately without retry
                resp.raise_for_status()
                data = resp.json()
                return self._parse_response(data)
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                # If non-retryable 4xx (e.g. 400 Bad Request, 401 Unauthorized), re-raise immediately
                if 400 <= status_code < 500 and status_code != 429:
                    raise

                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(
                        "Anthropic request failed (%s). Retrying in %.2fs (attempt %d/%d)...",
                        exc,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected failure in AnthropicProvider complete")

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    content_parts.append(self._redact_text(text))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
                    )
                )

        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
