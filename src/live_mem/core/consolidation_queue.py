# -*- coding: utf-8 -*-
"""
In-memory bank consolidation and compaction queue.

Issue #20: make `bank_consolidate` asynchronous from the caller point of
view while preserving the existing single-process / per-space lock model.

The queue is intentionally in-memory for PR 1. Acknowledgements therefore
carry the explicit `in_memory_best_effort` guarantee: accepted jobs survive
normal async scheduling, but not a process restart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from .consolidator import get_consolidator
from .locks import get_lock_manager
from .storage import get_storage

logger = logging.getLogger("live_mem.consolidation_queue")

QUEUE_GUARANTEE = "in_memory_best_effort"
TERMINAL_STATUSES = {"succeeded", "failed"}
NO_AUTO_POLLING_NEXT_ACTION = "return_to_user_without_polling"
NO_AUTO_POLLING_CONTRACT = {
    "recommended": False,
    "mode": "manual_only",
    "status_tool": "bank_consolidation_status",
    "instruction": (
        "Do not wait for completion or poll automatically. Store the job_id "
        "only if an explicit status check is needed."
    ),
}
PERSISTED_JOB_PREFIX = "_consolidation_jobs/"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConsolidationJob:
    job_id: str
    space_id: str
    agent: str
    requested_by: str
    job_type: str = "consolidate"
    requested_at: str = field(default_factory=_now)
    queued_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    guarantee: str = QUEUE_GUARANTEE
    progress: dict[str, Any] = field(default_factory=dict)


class ConsolidationQueueService:
    """FIFO queue with one background worker per active space."""

    def __init__(self, max_history: int = 100):
        self._state_lock = asyncio.Lock()
        self._queues: dict[str, deque[str]] = defaultdict(deque)
        self._active_jobs: dict[str, str] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._jobs: dict[str, ConsolidationJob] = {}
        self._max_history = max_history

    async def enqueue(
        self,
        space_id: str,
        agent: str,
        requested_by: str,
        job_type: str = "consolidate",
    ) -> dict:
        """
        Add a consolidation job and start the per-space worker if needed.

        Duplicate pending jobs are coalesced only for non-global agent scopes.
        A manage/admin `agent=""` job is kept distinct because it can process
        all agents and should not silently collapse narrower semantics.
        """
        async with self._state_lock:
            if agent:
                existing_id = self._find_pending_job(space_id, agent)
                if existing_id:
                    return self._job_payload(self._jobs[existing_id])

            job_id = (
                f"{'compact' if job_type == 'compact' else 'consol'}_{uuid.uuid4().hex}"
            )
            job = ConsolidationJob(
                job_id=job_id,
                space_id=space_id,
                agent=agent,
                requested_by=requested_by,
                job_type=job_type,
                progress={
                    "phase": "queued",
                    "batch_size": get_settings().consolidation_batch_size,
                    "notes_total": None,
                    "notes_done": 0,
                    "batches_total": None,
                    "batches_done": 0,
                    "current_batch": 0,
                },
            )
            self._jobs[job_id] = job

            if space_id not in self._active_jobs:
                job.status = "running"
                job.started_at = _now()
                self._active_jobs[space_id] = job_id
            else:
                self._queues[space_id].append(job_id)

            self._trim_history_locked()
            self._ensure_worker_locked(space_id)
            return self._job_payload(job)

    async def enqueue_compaction(self, space_id: str, requested_by: str) -> dict:
        """Enqueue a manual compaction in the existing per-space lane."""
        return await self.enqueue(
            space_id=space_id,
            agent="",
            requested_by=requested_by,
            job_type="compact",
        )

    async def get_job(self, job_id: str) -> dict:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job:
                return self._job_payload(job)

        # Issue #40 — terminal results must remain attributable after a
        # service restart.  The in-memory queue is still best-effort for jobs
        # that were running, but completed payloads are durable.
        persisted = await get_storage().get_json(f"{PERSISTED_JOB_PREFIX}{job_id}.json")
        if isinstance(persisted, dict) and persisted.get("job_id") == job_id:
            return persisted
        return {
            "status": "not_found",
            "message": f"Consolidation job '{job_id}' introuvable",
        }

    async def _persist_terminal_payload(self, payload: dict) -> None:
        """Persist the complete terminal payload for post-restart audit."""
        await get_storage().put_json(
            f"{PERSISTED_JOB_PREFIX}{payload['job_id']}.json", payload
        )

    async def _finalize_job(
        self,
        space_id: str,
        job: ConsolidationJob,
        result: dict[str, Any],
        error: str | None = None,
    ) -> None:
        """Persist a terminal result before exposing it or releasing its lane."""
        succeeded = result.get("status") == "ok" and error is None
        progress = {
            **job.progress,
            "phase": "done" if succeeded else "failed",
            "batch_size": result.get("batch_size", job.progress.get("batch_size")),
            "notes_total": result.get(
                "notes_processed", job.progress.get("notes_total")
            ),
            "notes_done": result.get(
                "notes_processed", job.progress.get("notes_done")
            ),
            "batches_total": result.get(
                "batches_total", job.progress.get("batches_total")
            ),
            "batches_done": result.get(
                "batches_completed", job.progress.get("batches_done")
            ),
        }
        terminal_job = replace(
            job,
            status="succeeded" if succeeded else "failed",
            result=result,
            error=None if succeeded else error or result.get("message", "Consolidation failed"),
            finished_at=_now(),
            progress=progress,
        )
        payload = self._job_payload(terminal_job)
        payload["queue_position"] = 0

        try:
            await self._persist_terminal_payload(payload)
        except Exception:
            logger.exception(
                "Terminal consolidation result persistence failed — job=%s",
                job.job_id,
            )
            failed_result = {
                **result,
                "audit_persistence_error": True,
            }
            terminal_job = replace(
                terminal_job,
                status="failed",
                result=failed_result,
                error="Terminal result persistence failed",
                progress={**progress, "phase": "failed"},
            )

        async with self._state_lock:
            job.status = terminal_job.status
            job.result = terminal_job.result
            job.error = terminal_job.error
            job.finished_at = terminal_job.finished_at
            job.progress = terminal_job.progress
            self._finish_active_locked(space_id, job.job_id)

    async def get_space_summary(self, space_id: str) -> dict:
        async with self._state_lock:
            active_id = self._active_jobs.get(space_id)
            active = self._jobs.get(active_id) if active_id else None
            queued_ids = list(self._queues.get(space_id, ()))
            queued_jobs = [
                self._job_payload(self._jobs[job_id]) for job_id in queued_ids
            ]
            latest = [
                self._job_payload(job)
                for job in reversed(self._jobs.values())
                if job.space_id == space_id
            ][:10]
            if active:
                lane_state = "running"
            elif queued_ids:
                lane_state = "queued"
            elif latest and latest[0].get("status") == "failed":
                lane_state = "failed"
            else:
                lane_state = "idle"

            return {
                "space_id": space_id,
                "lane_state": lane_state,
                "parallelism_model": "one_worker_per_space",
                "guarantee": QUEUE_GUARANTEE,
                "running_job": self._job_payload(active) if active else None,
                "queued_count": len(queued_ids),
                "queued_job_ids": queued_ids,
                "queued_jobs": queued_jobs,
                "latest_jobs": latest,
                "service_config": {
                    "batch_size": get_settings().consolidation_batch_size,
                },
            }

    def _find_pending_job(self, space_id: str, agent: str) -> str | None:
        for job_id in self._queues.get(space_id, ()):
            job = self._jobs[job_id]
            if job.agent == agent and job.status == "queued":
                return job_id
        return None

    def _ensure_worker_locked(self, space_id: str) -> None:
        worker = self._workers.get(space_id)
        if worker and not worker.done():
            return
        self._workers[space_id] = asyncio.create_task(self._worker(space_id))

    async def _worker(self, space_id: str) -> None:
        while True:
            async with self._state_lock:
                active_id = self._active_jobs.get(space_id)
                if not active_id:
                    next_id = self._pop_next_job_locked(space_id)
                    if not next_id:
                        self._workers.pop(space_id, None)
                        return
                    active_id = next_id

                job = self._jobs[active_id]

            try:

                async def progress_callback(progress: dict) -> None:
                    await self._update_progress(job.job_id, progress)

                async with get_lock_manager().consolidation(space_id):
                    if job.job_type == "compact":
                        await progress_callback({"phase": "compacting"})
                        result = await get_consolidator().compact_bank(
                            space_id,
                            dry_run=False,
                            progress_callback=progress_callback,
                        )
                    else:
                        result = await get_consolidator().consolidate(
                            space_id,
                            agent=job.agent,
                            enforce_cooldown=False,
                            progress_callback=progress_callback,
                        )
                await self._finalize_job(space_id, job, result)
            except Exception:
                logger.exception("Consolidation job failed — job=%s", job.job_id)
                await self._finalize_job(
                    space_id,
                    job,
                    {"status": "error", "message": "Consolidation job failed"},
                    error="Consolidation job failed",
                )

    async def _update_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.progress.update(progress)

    def _pop_next_job_locked(self, space_id: str) -> str | None:
        queue = self._queues.get(space_id)
        if not queue:
            return None

        job_id = queue.popleft()
        if not queue:
            self._queues.pop(space_id, None)

        job = self._jobs[job_id]
        job.status = "running"
        job.started_at = _now()
        self._active_jobs[space_id] = job_id
        return job_id

    def _finish_active_locked(self, space_id: str, job_id: str) -> None:
        if self._active_jobs.get(space_id) == job_id:
            self._active_jobs.pop(space_id, None)
        self._trim_history_locked()

    def _queue_position_locked(self, job: ConsolidationJob) -> int:
        if self._active_jobs.get(job.space_id) == job.job_id:
            return 1
        queue = self._queues.get(job.space_id, ())
        try:
            return list(queue).index(job.job_id) + 2
        except ValueError:
            return 0

    def _job_payload(self, job: ConsolidationJob) -> dict:
        payload = {
            "status": job.status,
            "job_id": job.job_id,
            "space_id": job.space_id,
            "job_type": job.job_type,
            "agent": job.agent,
            "scope": (
                "bank"
                if job.job_type == "compact"
                else "agent"
                if job.agent
                else "all_agents"
            ),
            "scope_label": (
                "Bank compaction"
                if job.job_type == "compact"
                else f"Agent: {job.agent}"
                if job.agent
                else "All agents"
            ),
            "requested_by": job.requested_by,
            "queue_position": self._queue_position_locked(job),
            "guarantee": job.guarantee,
            "requested_at": job.requested_at,
            "queued_at": job.queued_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "progress": dict(job.progress),
            "next_action": NO_AUTO_POLLING_NEXT_ACTION,
            "polling": dict(NO_AUTO_POLLING_CONTRACT),
        }
        if job.status == "running":
            payload["message"] = (
                f"Async {job.job_type} job accepted and running for "
                f"space '{job.space_id}'. Do not wait for completion by "
                "default. Use bank_consolidation_status only for an explicit "
                "status check."
            )
        elif job.status == "queued":
            payload["message"] = (
                f"Async {job.job_type} job accepted. Another bank job is "
                f"running for '{job.space_id}'; this job is queued at "
                f"position {payload['queue_position']}. Do not wait for "
                "completion by default. Use bank_consolidation_status only "
                "for an explicit status check."
            )
        if job.result is not None:
            payload["result"] = job.result
        if job.error:
            payload["error"] = job.error
        return payload

    def _trim_history_locked(self) -> None:
        if len(self._jobs) <= self._max_history:
            return

        protected = set(self._active_jobs.values())
        for queue in self._queues.values():
            protected.update(queue)

        for job_id, job in list(self._jobs.items()):
            if len(self._jobs) <= self._max_history:
                break
            if job_id not in protected and job.status in TERMINAL_STATUSES:
                self._jobs.pop(job_id, None)


_queue_service: ConsolidationQueueService | None = None


def get_consolidation_queue() -> ConsolidationQueueService:
    global _queue_service
    if _queue_service is None:
        _queue_service = ConsolidationQueueService()
    return _queue_service


def reset_consolidation_queue_for_tests() -> None:
    """Reset singleton state for deterministic unit tests."""
    global _queue_service
    _queue_service = None
