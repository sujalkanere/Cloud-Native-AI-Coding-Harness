"""
Postgres Run Repository for Cloud-Native AI Coding Harness.
Implements IRunRepository contract adhering strictly to Spec §3.2, §3.3, §3.5, §4, §7.
Guarantees:
- Serialized, monotonic, gap-free seq counter per run.
- Per-user run isolation (unauthorized access returns None -> 404).
- Cross-dialect compatibility (PostgreSQL and SQLite for in-memory unit tests).
- Backend restart stale run recovery.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.errors import EntityNotFoundError
from backend.app.domain.interfaces import IRunRepository
from backend.app.domain.models import Run, RunEvent, RunOptions, RunStatus
from backend.app.infrastructure.database.models import EventModel, RunModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresRunRepository(IRunRepository):
    """
    Asynchronous SQLAlchemy 2 repository implementing IRunRepository.
    Enforces per-run serialized monotonic event sequencing and per-user isolation.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_run_lock(self, run_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if run_id not in self._run_locks:
                self._run_locks[run_id] = asyncio.Lock()
            return self._run_locks[run_id]

    @staticmethod
    def _to_domain_run(model: RunModel) -> Run:
        options_data = model.options if isinstance(model.options, dict) else {}
        return Run(
            id=model.id,
            user_id=model.user_id,
            repo_url=model.repo_url,
            task=model.task,
            status=RunStatus(model.status),
            options=RunOptions(**options_data),
            is_pausing=model.is_pausing,
            baseline_sha=model.baseline_sha,
            error_reason=model.error_reason,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_domain_event(model: EventModel) -> RunEvent:
        payload_data = model.payload if isinstance(model.payload, dict) else {}
        return RunEvent(
            seq=model.seq,
            ts=model.ts,
            type=model.type,
            payload=payload_data,
        )

    async def create(self, run: Run) -> Run:
        async with self._session_factory() as session:
            async with session.begin():
                model = RunModel(
                    id=run.id,
                    user_id=run.user_id,
                    repo_url=run.repo_url,
                    task=run.task,
                    status=run.status.value,
                    options=run.options.model_dump(),
                    is_pausing=run.is_pausing,
                    baseline_sha=run.baseline_sha,
                    error_reason=run.error_reason,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
                session.add(model)
            await session.refresh(model)
            return self._to_domain_run(model)

    async def get(self, run_id: str, user_id: str | None = None) -> Run | None:
        async with self._session_factory() as session:
            stmt = select(RunModel).where(RunModel.id == run_id)
            if user_id is not None:
                # Per-user scoping (Spec §3.5): returns None for unauthorized user -> maps to 404
                stmt = stmt.where(RunModel.user_id == user_id)
            res = await session.execute(stmt)
            model = res.scalar_one_or_none()
            if model is None:
                return None
            return self._to_domain_run(model)

    async def list(self, user_id: str | None = None) -> list[Run]:
        async with self._session_factory() as session:
            stmt = select(RunModel).order_by(RunModel.created_at.desc())
            if user_id is not None:
                stmt = stmt.where(RunModel.user_id == user_id)
            res = await session.execute(stmt)
            models = res.scalars().all()
            return [self._to_domain_run(m) for m in models]

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_reason: str | None = None,
        is_pausing: bool | None = None,
        baseline_sha: str | None = None,
    ) -> Run:
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(RunModel).where(RunModel.id == run_id)
                res = await session.execute(stmt)
                model = res.scalar_one_or_none()
                if model is None:
                    raise EntityNotFoundError(f"Run {run_id} not found")

                model.status = status.value
                if error_reason is not None:
                    model.error_reason = error_reason
                if is_pausing is not None:
                    model.is_pausing = is_pausing
                if baseline_sha is not None:
                    model.baseline_sha = baseline_sha
                model.updated_at = datetime.now(UTC)

            await session.refresh(model)
            return self._to_domain_run(model)

    async def append_event(self, run_id: str, event_data: dict[str, Any]) -> RunEvent:
        """
        Appends an event with a monotonically increasing, gap-free sequence number.
        Serialized per run via in-memory lock and row-level database lock.
        Concurrent producers for distinct runs execute in full parallel.
        """
        lock = await self._get_run_lock(run_id)
        async with lock, self._session_factory() as session:
            async with session.begin():
                # Check run existence and acquire row lock on Postgres
                bind = session.get_bind()
                stmt = select(RunModel.id).where(RunModel.id == run_id)
                if bind.dialect.name == "postgresql":
                    stmt = stmt.with_for_update()

                res = await session.execute(stmt)
                if res.scalar_one_or_none() is None:
                    raise EntityNotFoundError(f"Run {run_id} not found")

                # Calculate monotonic gap-free seq
                seq_stmt = select(func.coalesce(func.max(EventModel.seq), 0)).where(
                    EventModel.run_id == run_id
                )
                max_seq = (await session.execute(seq_stmt)).scalar_one()
                new_seq = int(max_seq) + 1

                ts = event_data.get("ts") or datetime.now(UTC)
                event_type = event_data["type"]
                payload = event_data.get("payload", {})

                event_model = EventModel(
                    run_id=run_id,
                    seq=new_seq,
                    ts=ts,
                    type=event_type,
                    payload=payload,
                )
                session.add(event_model)

            await session.refresh(event_model)
            return self._to_domain_event(event_model)

    async def list_events(self, run_id: str, after_seq: int | None = None) -> list[RunEvent]:
        async with self._session_factory() as session:
            stmt = select(EventModel).where(EventModel.run_id == run_id)
            if after_seq is not None:
                stmt = stmt.where(EventModel.seq > after_seq)
            stmt = stmt.order_by(EventModel.seq.asc())
            res = await session.execute(stmt)
            models = res.scalars().all()
            return [self._to_domain_event(m) for m in models]

    async def recover_stale_runs(self) -> list[Run]:
        """
        Transitions any runs left in RUNNING or PAUSED to FAILED(reason=backend_restarted)
        and appends a status_change event for each recovered run (Spec §4, §7).
        """
        recovered: list[Run] = []
        async with self._session_factory() as session:
            # 1. Query stale runs
            stmt = select(RunModel).where(RunModel.status.in_(["RUNNING", "PAUSED"]))
            res = await session.execute(stmt)
            stale_models = res.scalars().all()
            stale_ids = [m.id for m in stale_models]

            if not stale_ids:
                return []

            # 2. Update runs in bulk
            now = datetime.now(UTC)
            update_stmt = (
                update(RunModel)
                .where(RunModel.id.in_(stale_ids))
                .values(
                    status=RunStatus.FAILED.value,
                    error_reason="backend_restarted",
                    is_pausing=False,
                    updated_at=now,
                )
            )
            await session.execute(update_stmt)
            await session.commit()

        # 3. Append status change event and collect recovered domain runs
        for run_id in stale_ids:
            run = await self.get(run_id)
            if run is not None:
                recovered.append(run)
                await self.append_event(
                    run_id,
                    {
                        "type": "status_change",
                        "payload": {
                            "status": RunStatus.FAILED.value,
                            "error_reason": "backend_restarted",
                            "is_pausing": False,
                        },
                    },
                )

        return recovered
