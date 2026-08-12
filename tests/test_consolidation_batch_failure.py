# -*- coding: utf-8 -*-
"""
Tests for issue #32 — a failed batch must never produce a fake success.

Production incident (2026-07-08, space `terraform-provider`): every LLM
call was rejected by the backend, `consolidate()` still returned
`status="ok"` with `notes_processed=0`, and the queue exposed the job as
`succeeded`. The failure stayed invisible for 6 days.

These tests are deliberately adversarial: they replay the exact incident
conditions (first batch rejected with the real 262144 error message) and
assert on every observable side effect (status, metrics, `_meta.json`
untouched, no bank write attempted), not just on the happy path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from live_mem.core.consolidation_queue import (
    ConsolidationQueueService,
    reset_consolidation_queue_for_tests,
)
from live_mem.core.consolidator import ConsolidatorService

# Real error template returned by the LLMaaS backend during the incident.
INCIDENT_LLM_ERROR = (
    "LLM call failed: Error code: 400 — This model's maximum context length "
    "is 262144 tokens. However, you requested 200000 output tokens and your "
    "prompt contains at least 62145 input tokens, for a total of at least "
    "262145 tokens."
)


class FakeStorage:
    """Minimal S3 stand-in tracking every mutating call."""

    def __init__(self, notes: list[dict]):
        self._notes = notes
        self.put_json_calls: list[tuple[str, dict]] = []

    async def get_json(self, key: str):
        return {"space_id": "sp", "consolidation_count": 3}

    async def put_json(self, key: str, value: dict):
        self.put_json_calls.append((key, value))

    async def get(self, key: str):
        return None  # no rules / no synthesis

    async def list_and_get(self, prefix: str):
        if prefix.endswith("/live/"):
            return list(self._notes)
        return []  # empty bank

    async def list_objects(self, prefix: str):
        return []


def _notes(count: int) -> list[dict]:
    return [
        {
            "key": f"sp/live/20260708T10000{i}_CLR_observation_{i:04x}.md",
            "content": f"note {i}",
        }
        for i in range(count)
    ]


def _consolidator(batch_size: int = 2) -> ConsolidatorService:
    """
    Build a ConsolidatorService without touching network or env.

    __init__ instantiates an AsyncOpenAI client (requires an API key and
    spawns httpx machinery), so the pipeline attributes are set manually.
    Every LLM/storage interaction is mocked per-test.
    """
    svc = object.__new__(ConsolidatorService)
    svc._model = "test-model"
    svc._context_window = 131072
    svc._max_tokens = 16384
    svc._temperature = 0.3
    svc._max_notes = 200
    svc._batch_size = batch_size
    svc._cooldown_seconds = 0
    svc._compact_threshold = 0.6
    svc._bank_file_max_size = 15360
    svc._validation_enabled = False
    svc._validation_max_examples = 20
    return svc


def _ok_llm_result() -> dict:
    return {
        "status": "ok",
        "data": {"file_edits": [], "synthesis": "s"},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _ok_write_result(notes_count: int) -> dict:
    return {
        "status": "ok",
        "notes_processed": notes_count,
        "bank_files_created": 0,
        "bank_files_updated": 1,
        "operations_applied": 1,
        "operations_failed": 0,
        "llm_tokens_used": 15,
        "llm_prompt_tokens": 10,
        "llm_completion_tokens": 5,
        "synthesis_size": 1,
    }


@pytest.mark.asyncio
class TestFirstBatchFailure:
    """Replay of the incident: batch 1 rejected → the job must NOT succeed."""

    async def test_first_batch_llm_failure_returns_error_not_ok(self):
        storage = FakeStorage(_notes(4))  # 4 notes, batch_size=2 → 2 batches
        svc = _consolidator(batch_size=2)
        write_results = AsyncMock()

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ), patch.object(
            svc,
            "_call_llm",
            new=AsyncMock(
                return_value={"status": "error", "message": INCIDENT_LLM_ERROR}
            ),
        ), patch.object(svc, "_write_results", new=write_results):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "error", (
            "A consolidation whose FIRST batch failed must not report ok "
            f"(got {result['status']!r})"
        )
        assert result["notes_processed"] == 0
        assert result["batches_completed"] == 0
        assert result["batches_total"] == 2
        assert result["failed_batch"] == 1
        # The upstream error must be exploitable by the caller/UI.
        assert "262144" in result["message"]
        assert "4 note(s) left in live/" in result["message"]
        # No bank write must have been attempted.
        write_results.assert_not_awaited()
        # _meta.json must NOT be touched: no fake last_consolidation.
        assert storage.put_json_calls == []

    async def test_first_batch_write_failure_returns_error(self):
        storage = FakeStorage(_notes(2))
        svc = _consolidator(batch_size=2)

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ), patch.object(
            svc, "_call_llm", new=AsyncMock(return_value=_ok_llm_result())
        ), patch.object(
            svc,
            "_write_results",
            new=AsyncMock(
                return_value={"status": "error", "message": "S3 write failed"}
            ),
        ):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "error"
        assert result["batches_completed"] == 0
        assert result["failed_batch"] == 1
        assert "S3 write failed" in result["message"]
        assert storage.put_json_calls == []


@pytest.mark.asyncio
class TestPartialFailure:
    """Failure after successful batches → partial, work is acknowledged."""

    async def test_second_batch_failure_returns_partial_with_metrics(self):
        storage = FakeStorage(_notes(4))  # 2 batches of 2
        svc = _consolidator(batch_size=2)

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ), patch.object(
            svc,
            "_call_llm",
            new=AsyncMock(
                side_effect=[
                    _ok_llm_result(),
                    {"status": "error", "message": INCIDENT_LLM_ERROR},
                ]
            ),
        ), patch.object(
            svc, "_write_results", new=AsyncMock(return_value=_ok_write_result(2))
        ):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "partial", (
            "Batch 2 failed after batch 1 was applied: reporting plain ok "
            "hides the failure, reporting plain error hides the applied work"
        )
        assert result["batches_completed"] == 1
        assert result["notes_processed"] == 2
        assert result["failed_batch"] == 2
        assert "262144" in result["message"]
        assert "1 batch(es) applied" in result["message"]
        # Work WAS integrated → meta must reflect it.
        assert len(storage.put_json_calls) == 1
        meta_key, meta = storage.put_json_calls[0]
        assert meta_key == "sp/_meta.json"
        assert meta["total_notes_processed"] == 2

    async def test_failed_surgical_operation_returns_partial_with_details(self):
        storage = FakeStorage(_notes(2))
        svc = _consolidator(batch_size=2)
        write_result = _ok_write_result(2)
        write_result["operations_failed"] = 1
        write_result["operation_failures"] = [
            {
                "filename": "progress.md",
                "operation": "append_to_section",
                "heading": "## Missing",
                "reason": "Section non trouvée: ## Missing",
            }
        ]

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ), patch.object(
            svc, "_call_llm", new=AsyncMock(return_value=_ok_llm_result())
        ), patch.object(
            svc, "_write_results", new=AsyncMock(return_value=write_result)
        ):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "partial"
        assert result["operations_failed"] == 1
        assert result["operation_failures"] == write_result["operation_failures"]
        assert "see operation_failures" in result["message"]


@pytest.mark.asyncio
class TestFullSuccessNonRegression:
    """The nominal contract must not change."""

    async def test_all_batches_ok_still_returns_ok(self):
        storage = FakeStorage(_notes(4))
        svc = _consolidator(batch_size=2)

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ), patch.object(
            svc, "_call_llm", new=AsyncMock(return_value=_ok_llm_result())
        ), patch.object(
            svc, "_write_results", new=AsyncMock(return_value=_ok_write_result(2))
        ):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "ok"
        assert result["batches_completed"] == 2
        assert result["notes_processed"] == 4
        assert "failed_batch" not in result
        assert "message" not in result
        assert len(storage.put_json_calls) == 1

    async def test_no_notes_still_returns_ok(self):
        storage = FakeStorage([])
        svc = _consolidator(batch_size=2)

        with patch(
            "live_mem.core.consolidator.get_storage", return_value=storage
        ):
            result = await svc.consolidate("sp", agent="CLR", enforce_cooldown=False)

        assert result["status"] == "ok"
        assert result["notes_processed"] == 0


@pytest.mark.asyncio
class TestQueueIntegration:
    """End-to-end through the queue: the job must expose the failure."""

    async def test_job_is_failed_with_exploitable_error_on_batch_failure(self):
        reset_consolidation_queue_for_tests()

        class IncidentConsolidator:
            async def consolidate(
                self, space_id, agent="", enforce_cooldown=True, progress_callback=None
            ):
                # Shape returned by consolidate() after the fix when the
                # first batch fails (incident replay).
                return {
                    "status": "error",
                    "space_id": space_id,
                    "notes_processed": 0,
                    "batches_total": 50,
                    "batches_completed": 0,
                    "failed_batch": 1,
                    "message": f"Batch 1/50 failed: {INCIDENT_LLM_ERROR}",
                }

        queue = ConsolidationQueueService()
        with patch(
            "live_mem.core.consolidation_queue.get_consolidator",
            return_value=IncidentConsolidator(),
        ):
            job = await queue.enqueue("terraform-provider", "CLR", "CLR")
            for _ in range(50):
                status = await queue.get_job(job["job_id"])
                if status["status"] in ("succeeded", "failed"):
                    break
                await asyncio.sleep(0.01)

        assert status["status"] == "failed", (
            "A consolidation with 0/50 batches completed must never be "
            "exposed as succeeded (this is the exact incident symptom)"
        )
        assert "262144" in status["error"]
        assert status["result"]["notes_processed"] == 0
        assert status["progress"]["phase"] == "failed"

    async def test_partial_result_is_exposed_as_failed_job(self):
        reset_consolidation_queue_for_tests()

        class PartialConsolidator:
            async def consolidate(
                self, space_id, agent="", enforce_cooldown=True, progress_callback=None
            ):
                return {
                    "status": "partial",
                    "space_id": space_id,
                    "notes_processed": 60,
                    "batches_total": 50,
                    "batches_completed": 30,
                    "failed_batch": 31,
                    "message": f"Batch 31/50 failed: {INCIDENT_LLM_ERROR}",
                }

        queue = ConsolidationQueueService()
        with patch(
            "live_mem.core.consolidation_queue.get_consolidator",
            return_value=PartialConsolidator(),
        ):
            job = await queue.enqueue("terraform-provider", "CLR", "CLR")
            for _ in range(50):
                status = await queue.get_job(job["job_id"])
                if status["status"] in ("succeeded", "failed"):
                    break
                await asyncio.sleep(0.01)

        assert status["status"] == "failed"
        assert "Batch 31/50" in status["error"]
        # Partial progress must stay visible for the operator.
        assert status["result"]["batches_completed"] == 30
        assert status["result"]["notes_processed"] == 60
