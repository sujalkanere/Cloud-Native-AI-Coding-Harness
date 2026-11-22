"""
Run Concurrency Manager and Run Control Registry for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.1, §3.3, §3.4, §3.5, §3.6:
- Enforces MAX_CONCURRENT_RUNS (default 4; excess runs remain in QUEUED status).
- In-memory RunControlRegistry holding ActiveRunHandle instances.
- Automatic FIFO queue dispatching when active runs complete or terminate.
- Event broadcasting to active WebSocket subscriber queues upon event creation.
- Control endpoints coordination with state machine and agent loop.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.app.application.agent import AgentControl, run_agent
from backend.app.application.coalescing import TerminalCoalescer
from backend.app.application.state_machine import ActionResult, RunStateMachine
from backend.app.config import Settings
from backend.app.domain.errors import EntityNotFoundError, InvalidStateTransitionError
from backend.app.domain.interfaces import (
    ILLMProvider,
    IObjectStorage,
    IRunRepository,
    ISandboxProvider,
)
from backend.app.domain.models import Run, RunEvent, RunStatus, SandboxSpec

logger = logging.getLogger(__name__)


@dataclass
class ActiveRunHandle:
    """Represents an actively executing or paused run holding an execution slot."""

    run_id: str
    user_id: str
    control: AgentControl
    state_machine: RunStateMachine
    task: asyncio.Task[Any] | None = None
    coalescer: TerminalCoalescer | None = None
    subscribers: set[asyncio.Queue[RunEvent]] = field(default_factory=set)


class RunConcurrencyManager:
    """
    Manages active run concurrency slots, queued runs, and real-time event broadcasting.
    Single-replica backend design per Spec §3.1.
    """

    def __init__(
        self,
        repository: IRunRepository,
        sandbox_provider: ISandboxProvider,
        llm_provider: ILLMProvider,
        storage: IObjectStorage,
        settings: Settings,
        worker_fn: Any = None,
    ) -> None:
        self.repository = repository
        self.sandbox_provider = sandbox_provider
        self.llm_provider = llm_provider
        self.storage = storage
        self.settings = settings
        self.max_concurrent_runs = settings.MAX_CONCURRENT_RUNS
        self._worker_fn = worker_fn or run_agent

        self._active_runs: dict[str, ActiveRunHandle] = {}
        self._queued_run_ids: list[str] = []
        self._queued_archives: dict[str, bytes] = {}
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = {}
        self._is_shutting_down: bool = False
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        """Returns the number of active runs currently occupying execution slots."""
        return len(self._active_runs)

    @property
    def queued_count(self) -> int:
        """Returns the number of runs currently waiting in the FIFO queue."""
        return len(self._queued_run_ids)

    def get_handle(self, run_id: str) -> ActiveRunHandle | None:
        """Retrieves active run handle if run is currently active."""
        return self._active_runs.get(run_id)

    def get_control(self, run_id: str) -> AgentControl | None:
        """Retrieves AgentControl handle if run is currently active."""
        handle = self._active_runs.get(run_id)
        return handle.control if handle else None

    async def enqueue_or_start(self, run: Run, archive_bytes: bytes | None = None) -> Run:
        """
        Submits a new run.
        If active count < MAX_CONCURRENT_RUNS:
            Allocates an execution slot, transitions to PREPARING, and starts background execution.
        If active count >= MAX_CONCURRENT_RUNS:
            Adds to FIFO queue in QUEUED status.
        """
        async with self._lock:
            if len(self._active_runs) < self.max_concurrent_runs:
                # Slot is immediately available: transition to PREPARING and launch
                state_machine = RunStateMachine(current_status=RunStatus.PREPARING)
                await self.repository.update_status(run.id, status=RunStatus.PREPARING)
                await self.publish_event(
                    run.id,
                    {
                        "type": "status_change",
                        "payload": {
                            "old_status": RunStatus.QUEUED.value,
                            "new_status": RunStatus.PREPARING.value,
                        },
                    },
                )
                run.status = RunStatus.PREPARING

                control = AgentControl(
                    run_id=run.id,
                    repository=self.repository,
                    state_machine=state_machine,
                )
                handle = ActiveRunHandle(
                    run_id=run.id,
                    user_id=run.user_id,
                    control=control,
                    state_machine=state_machine,
                )
                self._active_runs[run.id] = handle

                # Transfer any pre-registered subscribers for this run
                if run.id in self._subscribers:
                    handle.subscribers.update(self._subscribers[run.id])

                handle.task = asyncio.create_task(
                    self._run_worker(run=run, handle=handle, archive_bytes=archive_bytes)
                )
                return run
            else:
                # Concurrency limit reached: keep in QUEUED status
                self._queued_run_ids.append(run.id)
                if archive_bytes:
                    self._queued_archives[run.id] = archive_bytes
                return run

    async def _run_worker(
        self,
        run: Run,
        handle: ActiveRunHandle,
        archive_bytes: bytes | None = None,
    ) -> None:
        """Background execution worker for an active run."""
        sandbox = None
        try:
            # 1. Acquire sandbox environment
            spec = SandboxSpec(
                image=self.settings.SANDBOX_IMAGE,
                cpu_limit=self.settings.SANDBOX_CPU_LIMIT,
                mem_limit=self.settings.SANDBOX_MEM_LIMIT,
                pids_limit=self.settings.SANDBOX_PIDS_LIMIT,
                workspace_size=self.settings.SANDBOX_WORKSPACE_SIZE,
                tmp_size=self.settings.SANDBOX_TMP_SIZE,
                network_mode=self.settings.SANDBOX_NETWORK_MODE,
            )
            sandbox = await self.sandbox_provider.acquire(spec)
            handle.control.attach_sandbox(sandbox)

            # 2. Upload archive if provided
            if archive_bytes:
                await sandbox.upload_workspace(archive_bytes)

            # 3. Create TerminalCoalescer connected to publish_event
            coalescer = TerminalCoalescer(
                run_id=run.id,
                emit_callback=self.publish_event,
                max_bytes=self.settings.MAX_OUTPUT_BYTES_PER_RUN,
            )
            handle.coalescer = coalescer

            # 4. Execute the agent run
            await self._worker_fn(
                run_id=run.id,
                repository=self.repository,
                sandbox=sandbox,
                llm_provider=self.llm_provider,
                storage=self.storage,
                control=handle.control,
                settings=self.settings,
                coalescer=coalescer,
            )
        except asyncio.CancelledError:
            logger.info("Worker for run %s was cancelled.", run.id)
        except Exception as exc:
            logger.exception("Unexpected error in worker for run %s", run.id)
            current_run = await self.repository.get(run.id)
            if current_run and not current_run.status.is_terminal:
                await self.repository.update_status(
                    run.id,
                    status=RunStatus.FAILED,
                    error_reason=f"Worker exception: {exc}",
                )
                await self.publish_event(
                    run.id,
                    {
                        "type": "status_change",
                        "payload": {
                            "old_status": current_run.status.value,
                            "new_status": RunStatus.FAILED.value,
                            "reason": f"Worker exception: {exc}",
                        },
                    },
                )
        finally:
            if handle.coalescer is not None:
                try:
                    await handle.coalescer.close()
                except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                    logger.warning("Error closing coalescer for run %s: %s", run.id, exc)

            await self._on_run_finished(run.id)

    async def _on_run_finished(self, run_id: str) -> None:
        """Cleans up finished run and dispatches next queued run from FIFO queue."""
        async with self._lock:
            self._active_runs.pop(run_id, None)

            if self._is_shutting_down:
                return

            # Dispatch next available queued run
            while self._queued_run_ids:
                next_id = self._queued_run_ids.pop(0)
                next_archive = self._queued_archives.pop(next_id, None)

                next_run = await self.repository.get(next_id)
                # Ensure the run is still in QUEUED (was not terminated while queued)
                if next_run is not None and next_run.status == RunStatus.QUEUED:
                    state_machine = RunStateMachine(current_status=RunStatus.PREPARING)
                    await self.repository.update_status(next_run.id, status=RunStatus.PREPARING)
                    await self.publish_event(
                        next_run.id,
                        {
                            "type": "status_change",
                            "payload": {
                                "old_status": RunStatus.QUEUED.value,
                                "new_status": RunStatus.PREPARING.value,
                            },
                        },
                    )
                    next_run.status = RunStatus.PREPARING

                    control = AgentControl(
                        run_id=next_run.id,
                        repository=self.repository,
                        state_machine=state_machine,
                    )
                    handle = ActiveRunHandle(
                        run_id=next_run.id,
                        user_id=next_run.user_id,
                        control=control,
                        state_machine=state_machine,
                    )
                    self._active_runs[next_run.id] = handle

                    if next_run.id in self._subscribers:
                        handle.subscribers.update(self._subscribers[next_run.id])

                    handle.task = asyncio.create_task(
                        self._run_worker(
                            run=next_run,
                            handle=handle,
                            archive_bytes=next_archive,
                        )
                    )
                    break

    async def pause_run(
        self,
        run_id: str,
        user_id: str,
        mode: Literal["boundary", "now"] = "boundary",
    ) -> ActionResult:
        """
        Pauses an active run.
        Boundary pause sets is_pausing=True while in RUNNING.
        Now pause interrupts in-flight command and immediately enters PAUSED.
        """
        run = await self.repository.get(run_id, user_id=user_id)
        if run is None:
            raise EntityNotFoundError(f"Run '{run_id}' not found")

        handle = self._active_runs.get(run_id)
        if handle is not None:
            return await handle.control.request_pause(mode=mode)

        # Non-active run checks
        if run.status == RunStatus.PAUSED:
            return ActionResult(status=RunStatus.PAUSED, is_pausing=False, action="noop", changed=False)

        if run.status == RunStatus.RUNNING:
            if mode == "boundary":
                await self.repository.update_status(run_id, status=run.status, is_pausing=True)
                await self.publish_event(
                    run_id,
                    {
                        "type": "status_change",
                        "payload": {"status": run.status.value, "is_pausing": True},
                    },
                )
                return ActionResult(
                    status=RunStatus.RUNNING,
                    is_pausing=True,
                    action="boundary_pause_requested",
                    changed=True,
                )
            else:
                await self.repository.update_status(run_id, status=RunStatus.PAUSED, is_pausing=False)
                await self.publish_event(
                    run_id,
                    {
                        "type": "status_change",
                        "payload": {
                            "old_status": RunStatus.RUNNING.value,
                            "new_status": RunStatus.PAUSED.value,
                            "is_pausing": False,
                        },
                    },
                )
                return ActionResult(
                    status=RunStatus.PAUSED,
                    is_pausing=False,
                    action="paused_now",
                    changed=True,
                )

        raise InvalidStateTransitionError(
            f"Cannot pause run in status '{run.status.value}'. Pause is only valid from RUNNING."
        )

    async def resume_run(self, run_id: str, user_id: str) -> ActionResult:
        """
        Resumes a paused run, or cancels a pending boundary pause.
        """
        run = await self.repository.get(run_id, user_id=user_id)
        if run is None:
            raise EntityNotFoundError(f"Run '{run_id}' not found")

        handle = self._active_runs.get(run_id)
        if handle is not None:
            return await handle.control.request_resume()

        # Non-active run checks
        if run.status == RunStatus.RUNNING:
            if run.is_pausing:
                await self.repository.update_status(run_id, status=run.status, is_pausing=False)
                await self.publish_event(
                    run_id,
                    {
                        "type": "status_change",
                        "payload": {"status": run.status.value, "is_pausing": False},
                    },
                )
                return ActionResult(
                    status=RunStatus.RUNNING,
                    is_pausing=False,
                    action="pause_cancelled",
                    changed=True,
                )
            return ActionResult(
                status=RunStatus.RUNNING,
                is_pausing=False,
                action="noop",
                changed=False,
            )

        if run.status == RunStatus.PAUSED:
            await self.repository.update_status(run_id, status=RunStatus.RUNNING, is_pausing=False)
            await self.publish_event(
                run_id,
                {
                    "type": "status_change",
                    "payload": {
                        "old_status": RunStatus.PAUSED.value,
                        "new_status": RunStatus.RUNNING.value,
                        "is_pausing": False,
                    },
                },
            )
            return ActionResult(
                status=RunStatus.RUNNING,
                is_pausing=False,
                action="resumed",
                changed=True,
            )

        raise InvalidStateTransitionError(
            f"Cannot resume run in status '{run.status.value}'."
        )

    async def terminate_run(
        self,
        run_id: str,
        user_id: str,
        reason: str = "User terminated",
    ) -> ActionResult:
        """
        Terminates a run.
        If active: delegates to AgentControl to stop loop, extract patch, destroy container.
        If queued: cancels queue entry and updates status to TERMINATED.
        If already TERMINATED: returns idempotent 200 OK.
        If SUCCEEDED or FAILED: returns 409 Conflict.
        """
        run = await self.repository.get(run_id, user_id=user_id)
        if run is None:
            raise EntityNotFoundError(f"Run '{run_id}' not found")

        # Idempotent check
        if run.status == RunStatus.TERMINATED:
            return ActionResult(status=RunStatus.TERMINATED, is_pausing=False, action="noop", changed=False)

        if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            raise InvalidStateTransitionError(
                f"Cannot terminate run in terminal state '{run.status.value}'."
            )

        handle = self._active_runs.get(run_id)
        if handle is not None:
            return await handle.control.request_terminate(reason=reason)

        # Queued run termination
        async with self._lock:
            if run_id in self._queued_run_ids:
                self._queued_run_ids.remove(run_id)
                self._queued_archives.pop(run_id, None)

        old_status = run.status.value
        await self.repository.update_status(run_id, status=RunStatus.TERMINATED)
        await self.publish_event(
            run_id,
            {
                "type": "status_change",
                "payload": {
                    "old_status": old_status,
                    "new_status": RunStatus.TERMINATED.value,
                    "reason": reason,
                },
            },
        )
        return ActionResult(status=RunStatus.TERMINATED, is_pausing=False, action="terminated", changed=True)

    async def inject_guidance(self, run_id: str, user_id: str, message: str) -> None:
        """Injects steering guidance into an active run."""
        run = await self.repository.get(run_id, user_id=user_id)
        if run is None:
            raise EntityNotFoundError(f"Run '{run_id}' not found")

        if run.status.is_terminal:
            raise InvalidStateTransitionError(
                f"Cannot inject guidance into run in terminal status '{run.status.value}'."
            )

        handle = self._active_runs.get(run_id)
        if handle is not None:
            await handle.control.inject_guidance(message)
            return

        raise InvalidStateTransitionError(
            f"Cannot inject guidance into inactive run '{run_id}'."
        )

    async def publish_event(self, run_id: str, event_data: dict[str, Any]) -> RunEvent:
        """
        Appends an event to the run's monotonic sequence in the database
        and broadcasts it to all active WebSocket subscriber queues.
        """
        event = await self.repository.append_event(run_id, event_data)

        # Broadcast to subscribers without blocking concurrency lock
        subscribers = list(self._subscribers.get(run_id, set()))
        for q in subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue for run %s is full; dropping live event.", run_id)

        return event

    async def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent]:
        """Subscribes an asyncio.Queue to live events for run_id."""
        queue: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=1000)
        if run_id not in self._subscribers:
            self._subscribers[run_id] = set()
        self._subscribers[run_id].add(queue)

        handle = self._active_runs.get(run_id)
        if handle is not None:
            handle.subscribers.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[RunEvent]) -> None:
        """Unsubscribes an asyncio.Queue from live events."""
        if run_id in self._subscribers:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

        handle = self._active_runs.get(run_id)
        if handle is not None:
            handle.subscribers.discard(queue)

    async def shutdown(self) -> None:
        """Cancels all active run tasks on application shutdown."""
        self._is_shutting_down = True
        tasks = []
        for handle in list(self._active_runs.values()):
            if handle.task and not handle.task.done():
                handle.task.cancel()
                tasks.append(handle.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
