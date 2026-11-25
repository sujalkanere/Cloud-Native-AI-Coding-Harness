"""
Parallel Multi-Agent Orchestrator for Cloud-Native AI Coding Harness.

Invokes 5 specialized sub-agents in parallel phases inside a single shared session,
with shared context board and peer-to-peer inter-agent discussion:
1. Planner: Creates a task list for each sub-agent.
2. Research Agent: Researches domain benchmarks and successful examples.
3. Design Agent: Crafts the visual design system, layout, and UX.
4. Architect: Decides tech stack & architecture, discusses with Design Agent.
5. System Designer: Synthesizes system design, discusses with Architect & Research Agent,
   and implements the deliverable files into the shared workspace.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from backend.app.config import get_settings
from backend.app.domain.interfaces import LLMMessage
from backend.app.domain.models import Run, RunStatus
from backend.app.infrastructure.llm.openai import OpenAIProvider

if TYPE_CHECKING:
    from backend.app.bootstrap import AppContainer

logger = logging.getLogger(__name__)

_ACTIVE_SWARM_TASKS: dict[str, asyncio.Task[None]] = {}


def start_swarm_task(run: Run, container: AppContainer) -> asyncio.Task[None]:
    """Starts and tracks the 5-agent swarm background task for cancellation support."""
    existing = _ACTIVE_SWARM_TASKS.get(run.id)
    if existing and not existing.done():
        existing.cancel()
    task = asyncio.create_task(run_multi_agent_swarm(run, container))
    _ACTIVE_SWARM_TASKS[run.id] = task
    task.add_done_callback(lambda _t: _ACTIVE_SWARM_TASKS.pop(run.id, None))
    return task


async def cancel_swarm_task(run_id: str, container: AppContainer, reason: str = "User terminated") -> bool:
    """Cancels an active multi-agent swarm task and updates status to TERMINATED."""
    task = _ACTIVE_SWARM_TASKS.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await container.run_repository.update_status(run_id, RunStatus.TERMINATED, error_reason=reason)
    await _emit(
        container,
        run_id,
        "status_change",
        {"old_status": "RUNNING", "new_status": "TERMINATED", "reason": reason},
    )
    return True


AGENT_DEFS = [
    ("planner", "Planner", "Breaks down the objective into parallel sub-agent tasks"),
    ("researcher", "Research Agent", "Researches domain benchmarks and successful examples"),
    ("designer", "Design Agent", "Creates visual system, layout, typography, and UX"),
    ("architect", "Architect", "Selects tech stack & architecture; aligns with Design Agent"),
    ("system_designer", "System Designer", "Aligns with Architect & Research Agent and implements code"),
]


def _get_llm_provider() -> OpenAIProvider:
    settings = get_settings()
    api_key = settings.GROQ_API_KEY or settings.APINEX_API_KEY or settings.OPENAI_API_KEY
    base_url = (
        settings.GROQ_BASE_URL
        if settings.GROQ_API_KEY
        else (settings.APINEX_BASE_URL if settings.APINEX_API_KEY else settings.OPENAI_BASE_URL)
    )
    model = settings.effective_llm_model or "openai/gpt-oss-120b"
    if not api_key:
        raise RuntimeError("No LLM API key configured for multi-agent orchestration")
    return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)


async def _emit(container: AppContainer, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    ev = {"type": event_type, "payload": payload}
    if container.concurrency_manager is not None:
        await container.concurrency_manager.publish_event(run_id, ev)
    else:
        await container.run_repository.append_event(run_id, ev)


def _compact_shared_context(shared_board: list[str] | None, max_chars: int = 5500) -> str:
    """Formats shared session entries within a safe token/payload budget."""
    if not shared_board:
        return ""
    per_entry_limit = max(350, max_chars // max(1, len(shared_board)))
    compact_entries: list[str] = []
    for entry in shared_board:
        if len(entry) > per_entry_limit:
            compact_entries.append(entry[:per_entry_limit].rstrip() + "\n...(truncated)")
        else:
            compact_entries.append(entry)
    joined = "\n\n".join(compact_entries)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return "\n\n=== SHARED SESSION CONTEXT ===\n" + joined


async def _ask_llm(
    provider: OpenAIProvider,
    system_prompt: str,
    user_prompt: str,
    shared_board: list[str] | None = None,
) -> str:
    budgets = (5500, 2200, 0)
    last_exc: Exception | None = None
    for idx, budget in enumerate(budgets):
        context_block = _compact_shared_context(shared_board, max_chars=budget) if budget > 0 else ""
        try:
            resp = await provider.complete(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=f"{user_prompt}{context_block}"),
                ],
                tools=[],
            )
            return (resp.content or "").strip()
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            if idx < len(budgets) - 1 and ("413" in err_str or "429" in err_str or "too large" in err_str.lower()):
                await asyncio.sleep(1.5)
                continue
            raise
    if last_exc:
        raise last_exc
    return ""


def _extract_files(text: str) -> list[tuple[str, str]]:
    """Extracts ```file:path ... ``` blocks, fenced HTML, or raw/unclosed HTML documents."""
    files: list[tuple[str, str]] = []
    pattern = re.compile(r"```file:\s*([^\r\n`]+)\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(text):
        path = match.group(1).strip().lstrip("./")
        content = match.group(2).strip()
        if path and content:
            files.append((path, content))

    if not files:
        unclosed_file = re.search(r"```file:\s*([^\r\n`]+)\r?\n([\s\S]+)$", text, re.IGNORECASE)
        if unclosed_file:
            path = unclosed_file.group(1).strip().lstrip("./")
            content = unclosed_file.group(2).strip()
            if path and content:
                files.append((path, content))

    if not files:
        html_match = re.search(r"```(?:html|htm)?\r?\n([\s\S]*?<html[\s\S]*?</html>)\s*```", text, re.IGNORECASE)
        if html_match:
            files.append(("index.html", html_match.group(1).strip()))

    if not files:
        raw_html = re.search(r"(?:<!DOCTYPE\s+html[\s\S]*?|)<html[\s\S]*?(?:</html>|$)", text, re.IGNORECASE)
        if raw_html:
            content = raw_html.group(0).replace("```", "").strip()
            if content:
                if "</html>" not in content.lower():
                    content += "\n</html>"
                files.append(("index.html", content))

    if not files:
        code_blocks = re.findall(r"```([A-Za-z0-9_.-]+)\r?\n(.*?)```", text, re.DOTALL)
        for idx, (lang, code) in enumerate(code_blocks):
            ext = {"python": "py", "py": "py", "javascript": "js", "js": "js", "css": "css", "html": "html"}.get(lang.lower())
            if ext and code.strip():
                fname = "index.html" if ext == "html" else (f"main.{ext}" if idx == 0 else f"module_{idx}.{ext}")
                files.append((fname, code.strip()))

    return files


async def run_multi_agent_swarm(run: Run, container: AppContainer) -> None:
    """Executes the 5-agent parallel orchestration pipeline inside a single shared session."""
    run_id = run.id
    shared_sandbox = None
    shared_board: list[str] = []
    try:
        await container.run_repository.update_status(run_id, RunStatus.RUNNING)
        await _emit(
            container,
            run_id,
            "status_change",
            {"old_status": run.status.value, "new_status": "RUNNING"},
        )

        # Acquire a single shared sandbox for all 5 agents if available
        if container.sandbox_provider is not None:
            try:
                from backend.app.domain.models import SandboxSpec
                shared_sandbox = await container.sandbox_provider.acquire(SandboxSpec(network_mode="none"))
                await shared_sandbox.start()
            except Exception as sb_exc:
                logger.debug("Shared sandbox unavailable for swarm %s: %s", run_id, sb_exc)
                shared_sandbox = None

        # Initialize all 5 agent windows inside this single session
        for agent_id, label, role_desc in AGENT_DEFS:
            await _emit(
                container,
                run_id,
                "agent_status",
                {"agent": agent_id, "label": label, "role": role_desc, "status": "waiting", "session_id": run_id},
            )

        provider = _get_llm_provider()

        # ------------------------------------------------------------------
        # Phase 1: Planner creates task list for each sub-agent
        # ------------------------------------------------------------------
        await _emit(container, run_id, "agent_status", {"agent": "planner", "status": "working"})
        plan_text = await _ask_llm(
            provider,
            (
                "You are strictly the PLANNER in a 5-agent software swarm. Do not use emoji or markdown tables. "
                "Stay under 120 words total. Write 1-2 crisp bullet assignments strictly for: "
                "1) Research Agent, 2) Design Agent, 3) Architect, 4) System Designer."
            ),
            f"Project prompt: {run.task}",
        )
        await _emit(
            container,
            run_id,
            "agent_message",
            {"agent": "planner", "content": plan_text},
        )
        shared_board.append(f"[Planner Task List]\n{plan_text}")
        await _emit(container, run_id, "agent_status", {"agent": "planner", "status": "done"})

        # ------------------------------------------------------------------
        # Phase 2: Parallel execution — Research, Design, Architect (sharing session context)
        # ------------------------------------------------------------------
        async def run_researcher() -> str:
            await _emit(container, run_id, "agent_status", {"agent": "researcher", "status": "working"})
            out = await _ask_llm(
                provider,
                (
                    "You are strictly the RESEARCH AGENT (never act as Planner). Do not use emoji or markdown tables. Keep response under 150 words. "
                    "Execute ONLY the Research Agent assignment: analyze successful real-world examples, domain copy, and UX benchmarks."
                ),
                f"Deliver ONLY Research Agent findings for: {run.task}",
                shared_board=shared_board,
            )
            shared_board.append(f"[Research Agent Findings]\n{out}")
            await _emit(container, run_id, "agent_message", {"agent": "researcher", "content": out})
            return out

        async def run_designer() -> str:
            await _emit(container, run_id, "agent_status", {"agent": "designer", "status": "working"})
            out = await _ask_llm(
                provider,
                (
                    "You are strictly the DESIGN AGENT (never act as Planner). Do not use emoji or markdown tables. Keep response under 150 words. "
                    "Execute ONLY the Design Agent assignment: specify exact hex colors, typography pairing, spacing scale, hero composition, and interactive states."
                ),
                f"Deliver ONLY Design Agent visual specification for: {run.task}",
                shared_board=shared_board,
            )
            shared_board.append(f"[Design Agent Spec]\n{out}")
            await _emit(container, run_id, "agent_message", {"agent": "designer", "content": out})
            return out

        async def run_architect() -> str:
            await _emit(container, run_id, "agent_status", {"agent": "architect", "status": "working"})
            out = await _ask_llm(
                provider,
                (
                    "You are strictly the ARCHITECT (never act as Planner). Do not use emoji or markdown tables. Keep response under 150 words. "
                    "Execute ONLY the Architect assignment: define tech stack, file/component structure, state flow, and responsive layout strategy."
                ),
                f"Deliver ONLY Architect technical plan for: {run.task}",
                shared_board=shared_board,
            )
            shared_board.append(f"[Architect Plan]\n{out}")
            await _emit(container, run_id, "agent_message", {"agent": "architect", "content": out})
            return out

        await asyncio.gather(
            run_researcher(),
            run_designer(),
            run_architect(),
        )

        # ------------------------------------------------------------------
        # Phase 3: Peer-to-peer discussions across all agents in parallel
        # ------------------------------------------------------------------
        async def discuss_arch_design() -> None:
            await _emit(container, run_id, "agent_status", {"agent": "architect", "status": "discussing"})
            await _emit(container, run_id, "agent_status", {"agent": "designer", "status": "discussing"})
            arch_note = await _ask_llm(
                provider,
                "You are the Architect directly messaging the Design Agent. No emoji. Keep under 100 words. Confirm concretely how HTML/CSS/JS will implement Design Agent's tokens and layout.",
                "Write a short engineering handoff message to @designer referencing their spec from the shared session context.",
                shared_board=shared_board,
            )
            shared_board.append(f"[Architect -> Design Agent]\n{arch_note}")
            await _emit(
                container,
                run_id,
                "agent_message",
                {"agent": "architect", "to_agent": "designer", "content": arch_note},
            )
            design_reply = await _ask_llm(
                provider,
                "You are the Design Agent replying directly to the Architect. No emoji. Keep under 100 words. Confirm alignment and note 2 critical visual details.",
                f"Reply to Architect's message:\n{arch_note}",
                shared_board=shared_board,
            )
            shared_board.append(f"[Design Agent -> Architect]\n{design_reply}")
            await _emit(
                container,
                run_id,
                "agent_message",
                {"agent": "designer", "to_agent": "architect", "content": design_reply},
            )
            await _emit(container, run_id, "agent_status", {"agent": "designer", "status": "done"})

        async def discuss_system_research_arch() -> None:
            await _emit(container, run_id, "agent_status", {"agent": "system_designer", "status": "discussing"})
            await _emit(container, run_id, "agent_status", {"agent": "researcher", "status": "discussing"})
            sys_note = await _ask_llm(
                provider,
                "You are the System Designer directly messaging Architect and Research Agent. No emoji. Keep under 120 words. Outline the integrated system design and confirm domain requirements.",
                "Synthesize the shared session context from Planner, Research Agent, Design Agent, and Architect into your system design proposal.",
                shared_board=shared_board,
            )
            shared_board.append(f"[System Designer -> Architect, Research Agent]\n{sys_note}")
            await _emit(
                container,
                run_id,
                "agent_message",
                {"agent": "system_designer", "to_agent": "architect, researcher", "content": sys_note},
            )
            research_reply = await _ask_llm(
                provider,
                "You are the Research Agent replying directly to System Designer. No emoji. Keep under 100 words. Confirm domain copy, edge cases, and checklist before build.",
                f"Reply to System Designer's concept:\n{sys_note}",
                shared_board=shared_board,
            )
            shared_board.append(f"[Research Agent -> System Designer]\n{research_reply}")
            await _emit(
                container,
                run_id,
                "agent_message",
                {"agent": "researcher", "to_agent": "system_designer", "content": research_reply},
            )
            await _emit(container, run_id, "agent_status", {"agent": "researcher", "status": "done"})
            await _emit(container, run_id, "agent_status", {"agent": "architect", "status": "done"})

        await asyncio.gather(
            discuss_arch_design(),
            discuss_system_research_arch(),
        )

        # ------------------------------------------------------------------
        # Phase 4: System Designer implements deliverable files
        # ------------------------------------------------------------------
        await _emit(container, run_id, "agent_status", {"agent": "system_designer", "status": "working"})
        impl_text = await _ask_llm(
            provider,
            (
                "You are the System Designer writing the final deliverable code from the shared session context. "
                "Do NOT write a plan, essay, or summary—write actual source code ONLY. "
                "Start your response directly with ```file:index.html (or another ```file:path) containing complete, clean HTML/CSS/JS (~100-180 lines) and end with ```."
            ),
            f"Write complete working deliverable files for: {run.task}",
            shared_board=shared_board,
        )

        extracted = _extract_files(impl_text)
        for path, content in extracted:
            if shared_sandbox is not None:
                try:
                    await shared_sandbox.write_file(path, content)
                except Exception:
                    pass
            await _emit(
                container,
                run_id,
                "tool_call",
                {
                    "id": f"swarm_{uuid.uuid4().hex[:8]}",
                    "name": "write_file",
                    "arguments": {"path": path, "content": content},
                },
            )

        summary = (
            f"Implemented {len(extracted)} file(s): {', '.join(p for p, _ in extracted)}"
            if extracted
            else impl_text
        )
        await _emit(
            container,
            run_id,
            "agent_message",
            {"agent": "system_designer", "content": summary},
        )
        await _emit(container, run_id, "agent_status", {"agent": "system_designer", "status": "done"})

        await container.run_repository.update_status(run_id, RunStatus.SUCCEEDED)
        await _emit(
            container,
            run_id,
            "status_change",
            {"old_status": "RUNNING", "new_status": "SUCCEEDED"},
        )
    except asyncio.CancelledError:
        logger.info("Multi-agent swarm cancelled for run %s", run_id)
        raise
    except Exception as exc:
        logger.exception("Multi-agent swarm failed for run %s", run_id)
        err_msg = f"Multi-agent error: {exc}"
        await container.run_repository.update_status(run_id, RunStatus.FAILED, error_reason=err_msg[:250])
        await _emit(
            container,
            run_id,
            "status_change",
            {"old_status": "RUNNING", "new_status": "FAILED", "reason": err_msg[:250]},
        )
    finally:
        if shared_sandbox is not None and container.sandbox_provider is not None:
            try:
                await container.sandbox_provider.release(shared_sandbox)
            except Exception:
                pass
