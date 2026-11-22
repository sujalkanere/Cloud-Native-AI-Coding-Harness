"""
OpenAI LLM Provider for Cloud-Native AI Coding Harness.
Implements ILLMProvider adhering strictly to Spec §3.2, §4, §7.
Supports OpenAI Chat Completions API, custom OPENAI_BASE_URL,
exponential backoff retry on 429/5xx, and secret redaction.
"""
from __future__ import annotations

import asyncio
import json
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


class OpenAIProvider(ILLMProvider):
    """OpenAI Chat Completions API provider with retry backoff and secret redaction."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        redactor: SecretRedactor | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.redactor = redactor
        self._client = client
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    def _redact_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        if self.redactor:
            return self.redactor.redact(text)
        return text

    def _format_payload(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> dict[str, Any]:
        openai_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": self._redact_text(msg.content or "") or "",
                })
            elif msg.role == "assistant":
                item: dict[str, Any] = {
                    "role": "assistant",
                    "content": self._redact_text(msg.content),
                }
                if msg.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                openai_messages.append(item)
            else:  # system or user
                openai_messages.append({
                    "role": msg.role,
                    "content": self._redact_text(msg.content or "") or "",
                })

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
        }

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        return payload

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        client = self._get_client()
        payload = self._format_payload(messages, tools)
        endpoint = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                return self._parse_response(data)
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                if 400 <= status_code < 500 and status_code != 429:
                    raise

                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(
                        "OpenAI request failed (%s). Retrying in %.2fs (attempt %d/%d)...",
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
        raise RuntimeError("Unexpected failure in OpenAIProvider complete")

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content=None, tool_calls=[])

        msg = choices[0].get("message", {})
        raw_content = msg.get("content")
        reasoning = msg.get("reasoning")
        if not raw_content and reasoning:
            raw_content = f"{reasoning}"
        content = self._redact_text(raw_content)

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    args = {"raw": raw_args}

            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=name,
                    arguments=args,
                )
            )

        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
