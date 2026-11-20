"""
Scripted LLM Provider for Cloud-Native AI Coding Harness.
Implements ILLMProvider replaying scripted_run.json fixtures.
Lives strictly in test_support package and is refused in production.
Adheres strictly to Spec §3.2, §7, §9.1.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.domain.interfaces import ILLMProvider
from backend.app.domain.models import LLMMessage, LLMResponse, ToolCall, ToolDefinition


class ScriptedLLMProvider(ILLMProvider):
    """
    Test provider replaying pre-recorded LLM steps from a JSON script.
    Used for reproducible integration and E2E testing without real LLM API calls.
    """

    def __init__(self, script_path: str | Path | None = None) -> None:
        if script_path is None:
            # Default to samples/buggy-calculator/scripted_run.json
            repo_root = Path(__file__).resolve().parents[2]
            script_path = repo_root / "samples" / "buggy-calculator" / "scripted_run.json"

        self.script_path = Path(script_path)
        if not self.script_path.is_file():
            raise FileNotFoundError(f"Scripted run file not found at {self.script_path}")

        data = json.loads(self.script_path.read_text(encoding="utf-8"))
        self._steps: list[dict[str, Any]] = data.get("steps", [])
        self._step_index: int = 0

    @property
    def total_steps(self) -> int:
        return len(self._steps)

    @property
    def current_step_index(self) -> int:
        return self._step_index

    def reset(self) -> None:
        """Resets replay step pointer to the beginning."""
        self._step_index = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """Replays the next sequential step from the scripted fixture."""
        if self._step_index >= len(self._steps):
            raise RuntimeError(
                f"Scripted run steps exhausted (executed {self._step_index} of {len(self._steps)} steps)"
            )

        step = self._steps[self._step_index]
        self._step_index += 1

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

        # Simulated deterministic token counts
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
