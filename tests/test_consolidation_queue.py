# -*- coding: utf-8 -*-
"""
Tests for issue #20 — asynchronous in-memory consolidation queue.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from live_mem.auth.context import current_token_info
from live_mem.core.consolidation_queue import (
    ConsolidationQueueService,
    QUEUE_GUARANTEE,
    reset_consolidation_queue_for_tests,
)
from live_mem.tools.bank import register as register_bank_tools


class FakeConsolidator:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def consolidate(
        self, space_id: str, agent: str = "", enforce_cooldown: bool = True
    ) -> dict:
        self.calls.append(
            {
                "space_id": space_id,
                "agent": agent,
                "enforce_cooldown": enforce_cooldown,
            }
        )
        self.started.set()
        await self.release.wait()
        return {"status": "ok", "space_id": space_id, "notes_processed": 1}


def _token(name: str, permissions: list[str]) -> dict:
    return {
        "client_name": name,
        "permissions": permissions,
        "allowed_resources": ["project"],
    }


def _bank_tool(name: str):
    mcp = FastMCP(name="test")
    register_bank_tools(mcp)
    tool = mcp._tool_manager._tools[name]
    for attr in ("fn", "func", "handler", "_fn", "run", "callback"):
        fn = getattr(tool, attr, None)
        if callable(fn):
            return fn
    raise AssertionError(f"Tool {name} has no callable")


@pytest.fixture(autouse=True)
def reset_queue():
    reset_consolidation_queue_for_tests()
    yield
    reset_consolidation_queue_for_tests()


@pytest.mark.asyncio
async def test_enqueue_first_job_returns_running_and_processes_without_cooldown():
    fake = FakeConsolidator()
    queue = ConsolidationQueueService()

    with patch(
        "live_mem.core.consolidation_queue.get_consolidator",
        return_value=fake,
    ):
        result = await queue.enqueue("project", "agent-a", "agent-a")
        assert result["status"] == "running"
        assert result["queue_position"] == 1
        assert result["guarantee"] == QUEUE_GUARANTEE

        await asyncio.wait_for(fake.started.wait(), timeout=1)
        fake.release.set()
        for _ in range(20):
            status = await queue.get_job(result["job_id"])
            if status["status"] == "succeeded":
                break
            await asyncio.sleep(0.01)

    assert status["status"] == "succeeded"
    assert fake.calls == [
        {
            "space_id": "project",
            "agent": "agent-a",
            "enforce_cooldown": False,
        }
    ]


@pytest.mark.asyncio
async def test_same_space_second_request_is_queued_not_conflict_and_fifo():
    fake = FakeConsolidator()
    queue = ConsolidationQueueService()

    with patch(
        "live_mem.core.consolidation_queue.get_consolidator",
        return_value=fake,
    ):
        first = await queue.enqueue("project", "agent-a", "agent-a")
        await asyncio.wait_for(fake.started.wait(), timeout=1)
        second = await queue.enqueue("project", "agent-b", "agent-b")

        assert first["status"] == "running"
        assert second["status"] == "queued"
        assert second["queue_position"] == 2

        fake.release.set()
        await asyncio.sleep(0.05)
        first_status = await queue.get_job(first["job_id"])
        second_status = await queue.get_job(second["job_id"])

    assert first_status["status"] == "succeeded"
    assert second_status["status"] == "succeeded"
    assert [call["agent"] for call in fake.calls] == ["agent-a", "agent-b"]


@pytest.mark.asyncio
async def test_different_spaces_start_independently():
    calls = []
    release = asyncio.Event()

    class ParallelFake:
        async def consolidate(self, space_id, agent="", enforce_cooldown=True):
            calls.append(space_id)
            await release.wait()
            return {"status": "ok", "space_id": space_id}

    queue = ConsolidationQueueService()

    with patch(
        "live_mem.core.consolidation_queue.get_consolidator",
        return_value=ParallelFake(),
    ):
        await queue.enqueue("space-a", "agent-a", "agent-a")
        await queue.enqueue("space-b", "agent-b", "agent-b")

        for _ in range(20):
            if set(calls) == {"space-a", "space-b"}:
                break
            await asyncio.sleep(0.01)
        release.set()
        await asyncio.sleep(0)

    assert set(calls) == {"space-a", "space-b"}


@pytest.mark.asyncio
async def test_pending_same_agent_job_is_coalesced():
    fake = FakeConsolidator()
    queue = ConsolidationQueueService()

    with patch(
        "live_mem.core.consolidation_queue.get_consolidator",
        return_value=fake,
    ):
        await queue.enqueue("project", "agent-a", "agent-a")
        await asyncio.wait_for(fake.started.wait(), timeout=1)

        second = await queue.enqueue("project", "agent-a", "agent-a")
        third = await queue.enqueue("project", "agent-a", "agent-a")

        fake.release.set()
        for _ in range(20):
            second_status = await queue.get_job(second["job_id"])
            if second_status["status"] == "succeeded":
                break
            await asyncio.sleep(0.01)

    assert second["status"] == "queued"
    assert third["job_id"] == second["job_id"]
    assert second_status["status"] == "succeeded"


@pytest.mark.asyncio
async def test_failed_job_status_exposes_error():
    class FailingConsolidator:
        async def consolidate(self, space_id, agent="", enforce_cooldown=True):
            return {"status": "error", "message": "LLM unavailable"}

    queue = ConsolidationQueueService()

    with patch(
        "live_mem.core.consolidation_queue.get_consolidator",
        return_value=FailingConsolidator(),
    ):
        result = await queue.enqueue("project", "agent-a", "agent-a")
        for _ in range(20):
            status = await queue.get_job(result["job_id"])
            if status["status"] == "failed":
                break
            await asyncio.sleep(0.01)

    assert status["status"] == "failed"
    assert status["error"] == "LLM unavailable"
    assert status["result"]["status"] == "error"


@pytest.mark.asyncio
async def test_bank_consolidate_rejects_read_token_before_enqueue():
    tok = current_token_info.set(_token("reader", ["read"]))
    try:
        with patch(
            "live_mem.core.consolidation_queue.ConsolidationQueueService.enqueue",
            new=AsyncMock(),
        ) as enqueue:
            result = await _bank_tool("bank_consolidate")(space_id="project")
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "error"
    assert "write" in result["message"]
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_write_token_auto_scopes_blank_agent_to_caller():
    tok = current_token_info.set(_token("alice", ["read", "write"]))
    try:
        with patch(
            "live_mem.core.consolidation_queue.ConsolidationQueueService.enqueue",
            new=AsyncMock(return_value={"status": "running", "job_id": "j1"}),
        ) as enqueue:
            result = await _bank_tool("bank_consolidate")(space_id="project")
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "running"
    enqueue.assert_awaited_once_with(
        space_id="project",
        agent="alice",
        requested_by="alice",
    )


@pytest.mark.asyncio
async def test_write_token_cannot_enqueue_other_agent_scope():
    tok = current_token_info.set(_token("alice", ["read", "write"]))
    try:
        result = await _bank_tool("bank_consolidate")(
            space_id="project",
            agent="bob",
        )
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "error"
    assert "manage" in result["message"]


@pytest.mark.asyncio
async def test_manage_token_can_enqueue_global_scope():
    tok = current_token_info.set(_token("maintainer", ["read", "write", "manage"]))
    try:
        with patch(
            "live_mem.core.consolidation_queue.ConsolidationQueueService.enqueue",
            new=AsyncMock(return_value={"status": "running", "job_id": "j1"}),
        ) as enqueue:
            result = await _bank_tool("bank_consolidate")(space_id="project")
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "running"
    enqueue.assert_awaited_once_with(
        space_id="project",
        agent="",
        requested_by="maintainer",
    )


@pytest.mark.asyncio
async def test_bank_consolidation_status_requires_space_read_access():
    tok = current_token_info.set(_token("reader", ["read"]))
    try:
        with patch(
            "live_mem.core.consolidation_queue.ConsolidationQueueService.get_job",
            new=AsyncMock(
                return_value={
                    "status": "queued",
                    "job_id": "consol_1",
                    "space_id": "other-space",
                }
            ),
        ):
            result = await _bank_tool("bank_consolidation_status")(job_id="consol_1")
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "error"
    assert "Accès refusé" in result["message"]
