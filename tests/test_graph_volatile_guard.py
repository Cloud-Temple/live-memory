# -*- coding: utf-8 -*-
"""Tests for graph_push volatile bank-file guardrails."""

from __future__ import annotations

import base64
import json
import logging
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from live_mem.auth.context import current_token_info
from live_mem.config import get_settings
from live_mem.core.graph_bridge import GraphBridgeService
from live_mem.tools.graph import register as register_graph_tools


class FakeStorage:
    def __init__(self, bank_files: dict[str, str]):
        self.meta = {
            "space_id": "alpha",
            "graph_memory": {
                "url": "https://graph.example.com/mcp",
                "token": "gm-token",
                "memory_id": "mem-alpha",
                "ontology": "general",
                "push_count": 0,
                "files_pushed": 0,
            },
        }
        self.bank_files = bank_files
        self.saved_meta = None

    async def get_json(self, key: str) -> dict:
        assert key == "alpha/_meta.json"
        return self.meta

    async def list_and_get(self, prefix: str) -> list[dict]:
        assert prefix == "alpha/bank/"
        return [
            {
                "key": f"alpha/bank/{filename}",
                "content": content,
                "size": len(content),
                "last_modified": "",
            }
            for filename, content in self.bank_files.items()
        ]

    async def put_json(self, key: str, data: dict) -> None:
        assert key == "alpha/_meta.json"
        self.saved_meta = data


class FakeGraphMemoryClient:
    existing_documents: list[str] = []
    batch_calls: list[tuple[str, dict]] = []

    def __init__(self, url: str, token: str, timeout: float = 120.0):
        self.url = url
        self.token = token
        self.timeout = timeout

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        assert tool_name == "document_list"
        return {
            "status": "ok",
            "documents": [
                {"filename": filename} for filename in self.existing_documents
            ],
        }

    async def call_tools_batch(self, calls: list[tuple[str, dict]]) -> list[dict]:
        self.__class__.batch_calls.extend(calls)
        return [{"status": "ok"} for _ in calls]


@contextmanager
def _patched_graph_dependencies(storage: FakeStorage):
    FakeGraphMemoryClient.batch_calls = []
    FakeGraphMemoryClient.existing_documents = []
    with patch("live_mem.core.graph_bridge.get_storage", return_value=storage), patch(
        "live_mem.core.graph_bridge.GraphMemoryClient",
        new=FakeGraphMemoryClient,
    ):
        yield


def _ingested_filenames() -> list[str]:
    return [
        args["filename"]
        for tool, args in FakeGraphMemoryClient.batch_calls
        if tool == "memory_ingest"
    ]


def _decoded_ingests() -> dict[str, str]:
    decoded = {}
    for tool, args in FakeGraphMemoryClient.batch_calls:
        if tool != "memory_ingest":
            continue
        decoded[args["filename"]] = base64.b64decode(
            args["content_base64"]
        ).decode("utf-8")
    return decoded


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_push_skips_volatile_by_default():
    storage = FakeStorage(
        {
            "activeContext.md": "# active",
            "progress.md": "# progress",
            "productContext.md": "# product",
        }
    )

    with _patched_graph_dependencies(storage):
        result = await GraphBridgeService().push("alpha")

    assert result["status"] == "ok"
    assert result["pushed"] == 1
    assert result["pushed_files"] == ["productContext.md"]
    assert sorted(result["skipped_volatile"]) == [
        "activeContext.md",
        "progress.md",
    ]
    assert _ingested_filenames() == ["productContext.md"]
    assert _decoded_ingests() == {"productContext.md": "# product"}
    assert "warning" in result


@pytest.mark.asyncio
async def test_push_with_include_volatile_pushes_everything(caplog):
    storage = FakeStorage(
        {
            "activeContext.md": "# active",
            "progress.md": "# progress",
            "productContext.md": "# product",
        }
    )

    with caplog.at_level(logging.INFO, logger="live_mem.audit"):
        with _patched_graph_dependencies(storage):
            result = await GraphBridgeService().push(
                "alpha",
                include_volatile=True,
                audit_caller="manager",
            )

    assert result["status"] == "ok"
    assert result["pushed"] == 3
    assert result["skipped_volatile"] == []
    assert _ingested_filenames() == [
        "activeContext.md",
        "progress.md",
        "productContext.md",
    ]

    audit_payloads = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "live_mem.audit" and "graph_push_volatile_optin" in r.message
    ]
    assert audit_payloads
    assert audit_payloads[-1]["event"] == "graph_push_volatile_optin"
    assert audit_payloads[-1]["caller"] == "manager"
    assert audit_payloads[-1]["space_id"] == "alpha"
    assert sorted(audit_payloads[-1]["files"]) == [
        "activeContext.md",
        "progress.md",
    ]


@pytest.mark.asyncio
async def test_only_volatile_files_returns_empty_pushed_not_error():
    storage = FakeStorage(
        {
            "activeContext.md": "# active",
            "progress.md": "# progress",
        }
    )

    with _patched_graph_dependencies(storage):
        result = await GraphBridgeService().push("alpha")

    assert result["status"] == "ok"
    assert result["pushed"] == 0
    assert result["pushed_files"] == []
    assert sorted(result["skipped_volatile"]) == [
        "activeContext.md",
        "progress.md",
    ]
    assert result["message"] == "No non-volatile bank files to push"
    assert FakeGraphMemoryClient.batch_calls == []


@pytest.mark.asyncio
async def test_volatile_filter_is_configurable(monkeypatch):
    monkeypatch.setenv("GRAPH_PUSH_VOLATILE_FILES", "productContext.md")
    get_settings.cache_clear()
    storage = FakeStorage(
        {
            "activeContext.md": "# active",
            "productContext.md": "# product",
            "techContext.md": "# tech",
        }
    )

    with _patched_graph_dependencies(storage):
        result = await GraphBridgeService().push("alpha")

    assert result["status"] == "ok"
    assert result["skipped_volatile"] == ["productContext.md"]
    assert _ingested_filenames() == ["activeContext.md", "techContext.md"]


@pytest.mark.asyncio
async def test_nested_volatile_basename_is_skipped_by_default():
    storage = FakeStorage(
        {
            "1.MEMORY_BANK/activeContext.md": "# active",
            "stable/runbook.md": "# runbook",
        }
    )

    with _patched_graph_dependencies(storage):
        result = await GraphBridgeService().push("alpha")

    assert result["skipped_volatile"] == ["1.MEMORY_BANK/activeContext.md"]
    assert _ingested_filenames() == ["stable/runbook.md"]


@pytest.mark.asyncio
async def test_graph_push_include_volatile_requires_manage_permission():
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self, annotations=None):
            def decorator(func):
                self.tools[func.__name__] = func
                return func

            return decorator

    mcp = FakeMCP()
    register_graph_tools(mcp)
    push = mcp.tools["graph_push"]
    bridge = AsyncMock()

    tok = current_token_info.set(
        {
            "client_name": "writer",
            "permissions": ["read", "write"],
            "allowed_resources": ["alpha"],
        }
    )
    try:
        with patch("live_mem.core.graph_bridge.get_graph_bridge", return_value=bridge):
            result = await push("alpha", include_volatile=True)
    finally:
        current_token_info.reset(tok)

    assert result["status"] == "error"
    assert "manage" in result["message"]
    bridge.push.assert_not_called()
