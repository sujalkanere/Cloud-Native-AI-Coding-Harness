"""
Scripted LLM Provider for Cloud-Native AI Coding Harness.
Implements ILLMProvider replaying scripted_run.json fixtures or in-memory steps.
Lives strictly in test_support package and is refused in production.
Adheres strictly to Spec §3.2, §7, §9.1.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from backend.app.domain.interfaces import ILLMProvider
from backend.app.domain.models import LLMMessage, LLMResponse, ToolCall, ToolDefinition


class ScriptedLLMProvider(ILLMProvider):
    """
    Test provider replaying pre-recorded LLM steps from a JSON script or in-memory list.
    Used for reproducible integration, unit, and orchestration testing without real LLM API calls.
    """

    def __init__(
        self,
        script_path: str | Path | None = None,
        steps: list[dict[str, Any]] | None = None,
        default_tokens: int | None = None,
    ) -> None:
        self.default_tokens = default_tokens
        self.call_history: list[dict[str, Any]] = []

        if steps is not None:
            self.script_path: Path | None = None
            self._steps: list[dict[str, Any]] = list(steps)
        else:
            if script_path is None:
                # Default to samples/buggy-calculator/scripted_run.json
                repo_root = Path(__file__).resolve().parents[2]
                script_path = repo_root / "samples" / "buggy-calculator" / "scripted_run.json"

            self.script_path = Path(script_path)
            if not self.script_path.is_file():
                raise FileNotFoundError(f"Scripted run file not found at {self.script_path}")

            data = json.loads(self.script_path.read_text(encoding="utf-8"))
            self._steps = data.get("steps", [])

        self._step_index: int = 0

    @property
    def total_steps(self) -> int:
        return len(self._steps)

    @property
    def current_step_index(self) -> int:
        return self._step_index

    def reset(self) -> None:
        """Resets replay step pointer and call history."""
        self._step_index = 0
        self.call_history.clear()

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Replays the next sequential step from the scripted fixture or in-memory steps."""
        self.call_history.append({
            "messages": list(messages),
            "tools": list(tools),
            "step_index": self._step_index,
        })

        if self._step_index >= len(self._steps):
            raise RuntimeError(
                f"Scripted run steps exhausted (executed {self._step_index} of {len(self._steps)} steps)"
            )

        step = self._steps[self._step_index]
        self._step_index += 1

        # Optional delay or callback before returning response (e.g. for pause-during-call testing)
        delay = step.get("delay")
        if delay and isinstance(delay, (int, float)):
            await asyncio.sleep(delay)

        callback = step.get("callback")
        if callback and callable(callback):
            res = callback()
            if inspect.iscoroutine(res):
                await res

        thought = step.get("thought", "")
        tool_calls_data = step.get("tool_calls", [])

        # If legacy single tool_call is present and tool_calls is empty
        if not tool_calls_data and "tool_call" in step:
            tc = step["tool_call"]
            tool_calls_data = [{
                "id": f"call_{self._step_index}_{tc['name']}",
                "name": tc["name"],
                "arguments": tc.get("arguments", {}),
            }]

        tool_calls = [
            ToolCall(
                id=tc.get("id", f"call_{self._step_index}_{tc['name']}"),
                name=tc["name"],
                arguments=tc.get("arguments", {}),
            )
            for tc in tool_calls_data
        ]

        # Configurable token counts
        if step.get("total_tokens") is not None:
            total_tokens = int(step["total_tokens"])
            prompt_tokens = int(step.get("prompt_tokens", total_tokens // 2))
            completion_tokens = int(step.get("completion_tokens", total_tokens - prompt_tokens))
        elif step.get("tokens") is not None:
            total_tokens = int(step["tokens"])
            prompt_tokens = total_tokens // 2
            completion_tokens = total_tokens - prompt_tokens
        elif self.default_tokens is not None:
            total_tokens = self.default_tokens
            prompt_tokens = total_tokens // 2
            completion_tokens = total_tokens - prompt_tokens
        else:
            prompt_tokens = 100 + (self._step_index * 20)
            completion_tokens = 50 + len(thought)
            total_tokens = prompt_tokens + completion_tokens

        return LLMResponse(
            content=thought,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
