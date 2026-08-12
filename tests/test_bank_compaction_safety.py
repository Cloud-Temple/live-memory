# -*- coding: utf-8 -*-
"""Adversarial regression tests for issue #37 (silent bank destruction)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from live_mem.core.consolidator import (
    ConsolidatorService,
    _build_compaction_units,
    _content_sha256,
    _parse_split_part,
    _split_markdown_losslessly,
    _split_marker,
    _utf8_size,
)
from live_mem.core.backup import BackupService
from live_mem.core.locks import LockManager
from live_mem.tools.bank import register as register_bank_tools
from live_mem.tools.backup import _parse_backup_id
from live_mem.tools.space import register as register_space_tools


def _service(max_size: int = 4096) -> ConsolidatorService:
    service = object.__new__(ConsolidatorService)
    service._bank_file_max_size = max_size
    service._max_tokens = 4096
    service._context_window = 131072
    service._model = "test-model"
    service._client = AsyncMock()
    return service


def _large_french_markdown() -> str:
    lines = ["# progress.md\n"]
    for index in range(180):
        lines.append(
            f"## Jalon {index}\n"
            f"- Décision vérifiée numéro {index} — aucune donnée ne doit disparaître.\n"
        )
    return "".join(lines)


def _oversized_section_markdown() -> str:
    return "# progress.md\n\n## Historique\n" + (
        "Décision ancienne et redondante à synthétiser.\n" * 180
    )


def _llm_plan_response(
    *,
    filename: str = "progress.md",
    heading: str = "## Historique",
    compacted: str = "Décisions structurantes conservées.",
    finish_reason: str = "stop",
    operation_type: str = "replace_section",
):
    operation = {
        "type": operation_type,
        "heading": heading,
        "content": compacted,
        "reason": "Fusion des répétitions",
    }
    payload = {
        "file_edits": [
            {
                "filename": filename,
                "action": "edit",
                "operations": [operation],
            }
        ]
    }
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=json.dumps(payload)),
            )
        ]
    )


class MemoryStorage:
    """S3 stand-in that keeps object contents and copies inspectable."""

    def __init__(self, objects: dict[str, str]):
        self.objects = dict(objects)
        self.copy_calls: list[tuple[str, str]] = []
        self.fail_copy = False
        self.fail_restore = False
        self.corrupt_reads = False

    async def get_json(self, key: str):
        return {"space_id": "sp"} if key == "sp/_meta.json" else None

    async def exists(self, key: str):
        return key in self.objects

    async def list_and_get(self, prefix: str):
        return [
            {"key": key, "content": value}
            for key, value in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    async def put(self, key: str, content: str):
        self.objects[key] = content

    async def get(self, key: str):
        value = self.objects.get(key)
        if self.corrupt_reads and key.startswith("sp/bank/"):
            return "corrupted"
        return value

    async def copy_object(self, source: str, destination: str):
        if self.fail_copy:
            raise RuntimeError("backup unavailable")
        if self.fail_restore and source.startswith("_backups/"):
            raise RuntimeError("restore unavailable")
        self.copy_calls.append((source, destination))
        self.objects[destination] = self.objects[source]

    async def delete(self, key: str):
        self.objects.pop(key, None)

    async def delete_many(self, keys: list[str]):
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)

    async def put_json(self, key: str, value: dict):
        self.objects[key] = str(value)

    async def list_objects(self, prefix: str):
        return [
            {"Key": key, "Size": _utf8_size(value)}
            for key, value in self.objects.items()
            if key.startswith(prefix)
        ]


def test_split_is_utf8_byte_aware_and_lossless():
    content = _large_french_markdown()
    assert _utf8_size(content) > len(content), "French UTF-8 must exercise byte drift"

    parts, error = _split_markdown_losslessly("progress.md", content, 4096)

    assert error is None
    assert parts is not None and len(parts) > 1
    assert all(_utf8_size(rendered) <= 4096 for _, rendered in parts)
    reconstructed = "".join(
        _parse_split_part(filename, rendered)[1] for filename, rendered in parts
    )
    assert reconstructed == content
    assert _content_sha256(reconstructed) == _content_sha256(content)


def test_split_refuses_to_cut_an_oversized_line():
    content = "# title\n" + ("é" * 3000)

    parts, error = _split_markdown_losslessly("progress.md", content, 4096)

    assert parts is None
    assert "single line" in error


@pytest.mark.asyncio
async def test_apply_uses_llm_plan_reduces_bytes_and_creates_backup():
    content = _oversized_section_markdown()
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            "sp/_rules.md": "# Rules\n",
            "sp/bank/progress.md": content,
        }
    )
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "ok"
    assert result["files_compacted"] == 1
    assert result["files_failed"] == 0
    assert result["size_unit"] == "utf-8 bytes"
    assert "backup_id" in result
    backed_up_sources = {source for source, _ in storage.copy_calls}
    assert backed_up_sources == {
        "sp/_meta.json",
        "sp/_rules.md",
        "sp/bank/progress.md",
    }
    sid, timestamp, error = _parse_backup_id(result["backup_id"])
    assert error is None and sid == "sp" and timestamp is not None

    service._client.chat.completions.create.assert_awaited_once()
    persisted = storage.objects["sp/bank/progress.md"]
    metadata, compacted = _parse_split_part("progress.md", persisted)
    assert metadata == {"source": "progress.md", "part": 1, "total": 1}
    assert compacted == (
        "# progress.md\n\n## Historique\n\nDécisions structurantes conservées.\n"
    )
    assert _utf8_size(compacted) < _utf8_size(content)
    assert _utf8_size(compacted) <= int(4096 * 0.75)

    for key in [key for key in storage.objects if key.startswith("sp/")]:
        storage.objects.pop(key)
    with patch("live_mem.core.backup.get_storage", return_value=storage):
        restored = await BackupService().restore(result["backup_id"])
    assert restored["status"] == "ok"
    assert storage.objects["sp/_meta.json"] == '{"space_id":"sp"}'
    assert storage.objects["sp/_rules.md"] == "# Rules\n"
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_parseable_truncated_llm_plan_is_never_written():
    content = _oversized_section_markdown()
    storage = MemoryStorage(
        {"sp/_meta.json": '{"space_id":"sp"}', "sp/bank/progress.md": content}
    )
    storage.put = AsyncMock(side_effect=storage.put)
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response(
        finish_reason="length"
    )

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert "incomplete" in result["files"][0]["error"]
    storage.put.assert_not_awaited()
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_repairable_truncated_json_is_rejected_without_write():
    content = _oversized_section_markdown()
    storage = MemoryStorage(
        {"sp/_meta.json": '{"space_id":"sp"}', "sp/bank/progress.md": content}
    )
    storage.put = AsyncMock(side_effect=storage.put)
    service = _service()
    service._client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content='{"file_edits":[{"filename":"progress.md","action":"edit","operations":[{"type":"replace_section","heading":"## Historique","content":"coupé'
                ),
            )
        ]
    )

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert "invalid LLM compaction plan" in result["files"][0]["error"]
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_forbidden_compaction_operation_is_rejected_atomically():
    content = _oversized_section_markdown()
    storage = MemoryStorage(
        {"sp/_meta.json": '{"space_id":"sp"}', "sp/bank/progress.md": content}
    )
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response(
        operation_type="append_to_section"
    )

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert result["files"][0]["error"] == "plan contains a forbidden operation"
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_logical_split_family_is_compacted_even_when_parts_fit_limit():
    logical = _oversized_section_markdown()
    parts, error = _split_markdown_losslessly("progress.md", logical, 4096)
    assert error is None and parts is not None and len(parts) > 1
    assert all(_utf8_size(rendered) <= 4096 for _, rendered in parts)
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            **{f"sp/bank/{name}": value for name, value in parts},
        }
    )
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "ok"
    assert result["files_compacted"] == 1
    metadata, body = _parse_split_part(
        "progress.md", storage.objects["sp/bank/progress.md"]
    )
    assert metadata == {"source": "progress.md", "part": 1, "total": 1}
    assert body.startswith("# progress.md")
    assert not any(
        "part-" in key for key in storage.objects if key.startswith("sp/bank/")
    )


@pytest.mark.asyncio
async def test_dry_run_never_calls_llm_or_writes():
    content = _oversized_section_markdown()
    storage = MemoryStorage(
        {"sp/_meta.json": '{"space_id":"sp"}', "sp/bank/progress.md": content}
    )
    storage.put = AsyncMock(side_effect=storage.put)
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=True)

    assert result["status"] == "ok"
    assert result["files_over_limit"] == 1
    service._client.chat.completions.create.assert_not_awaited()
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_compaction_prompt_includes_rules_beyond_character_2000():
    content = _oversized_section_markdown()
    rules = "R" * 2100 + "\nSENTINELLE_CONSERVATION_ABSOLUE"
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response()

    candidate, details = await service._plan_single_file_compaction(
        "progress.md", content, 4096, rules
    )

    assert candidate is not None, details
    call = service._client.chat.completions.create.await_args.kwargs
    assert "SENTINELLE_CONSERVATION_ABSOLUE" in call["messages"][1]["content"]


@pytest.mark.asyncio
async def test_backup_failure_preserves_original_without_any_write():
    content = _oversized_section_markdown()
    storage = MemoryStorage({"sp/bank/progress.md": content})
    storage.fail_copy = True
    storage.put = AsyncMock(side_effect=storage.put)
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert result["files_failed"] == 1
    storage.put.assert_not_awaited()
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_post_write_verification_failure_rolls_back_original():
    content = _oversized_section_markdown()
    storage = MemoryStorage({"sp/bank/progress.md": content})
    storage.corrupt_reads = True
    service = _service()
    service._client.chat.completions.create.return_value = _llm_plan_response()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert result["files_failed"] == 1
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_rollback_failure_is_fatal_and_preserves_live_notes():
    logical = "# progress.md\n" + "entry\n" * 100
    parts, error = _split_markdown_losslessly("progress.md", logical, 2048)
    assert error is None and parts is not None and len(parts) > 1
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            "sp/live/note.md": "important note\n",
            **{f"sp/bank/{name}": value for name, value in parts},
        }
    )
    storage.corrupt_reads = True
    storage.fail_restore = True
    service = _service()
    service._deduplicate_content = AsyncMock(
        side_effect=lambda content, filename: (content, 0)
    )
    output = {
        "file_edits": [
            {
                "filename": "progress.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "# progress.md",
                        "content": "new entry",
                    }
                ],
            }
        ],
        "synthesis": "must not be persisted",
    }
    bank_files = await storage.list_and_get("sp/bank/")

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            "sp", output, bank_files, ["sp/live/note.md"], 1, {}, skip_meta=True
        )

    assert result["status"] == "error"
    assert result["backup_id"].startswith("sp/")
    assert storage.objects["sp/live/note.md"] == "important note\n"
    assert "sp/_synthesis.md" not in storage.objects


@pytest.mark.asyncio
async def test_consolidate_propagates_the_fatal_backup_id():
    service = _service()
    service._batch_size = 1
    service._validation_enabled = False
    service._collect_inputs = AsyncMock(
        return_value={
            "notes": ["note"],
            "notes_keys": ["sp/live/note.md"],
            "bank_files": [],
            "rules": "rules",
            "synthesis": "",
        }
    )
    service._compact_bank_if_needed = AsyncMock(
        return_value={"compacted": False, "files_failed": 0}
    )
    service._build_prompt = lambda **kwargs: []
    service._call_llm = AsyncMock(
        return_value={"status": "ok", "data": {}, "usage": {}}
    )
    service._write_results = AsyncMock(
        return_value={
            "status": "error",
            "message": "rollback failed",
            "backup_id": "sp/2026-08-12T12-00-00-000001",
            "operations_applied": 1,
            "operations_failed": 1,
            "operation_failures": [{"reason": "rollback failed"}],
            "bank_files_updated": 1,
            "bank_files_created": 0,
        }
    )
    storage = MemoryStorage({"sp/_meta.json": '{"space_id":"sp"}'})

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.consolidate("sp", enforce_cooldown=False)

    assert result["status"] == "error"
    assert result["backup_id"] == "sp/2026-08-12T12-00-00-000001"
    assert result["operations_failed"] == 1
    assert result["operation_failures"] == [{"reason": "rollback failed"}]


@pytest.mark.asyncio
async def test_consolidator_reassembles_edits_and_resplits_logical_file():
    canonical = _split_marker("progress.md", 1, 2) + "# progress.md\n\n## First\nold\n"
    second = _split_marker("progress.md", 2, 2) + "## Target\nold target\n"
    storage = MemoryStorage(
        {
            "sp/bank/progress.md": canonical,
            "sp/bank/progress.part-002.md": second,
        }
    )
    service = _service()
    service._deduplicate_content = AsyncMock(
        side_effect=lambda content, filename: (content, 0)
    )
    output = {
        "file_edits": [
            {
                "filename": "progress.part-002.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "replace_section",
                        "heading": "## Target",
                        "content": "new target",
                    }
                ],
            }
        ],
        "synthesis": "done",
    }

    bank_files = await storage.list_and_get("sp/bank/")
    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            "sp", output, bank_files, [], 1, {}, skip_meta=True
        )

    assert result["operations_failed"] == 0
    rewritten_parts = [
        (key.removeprefix("sp/bank/"), value)
        for key, value in sorted(storage.objects.items())
        if key.startswith("sp/bank/")
    ]
    reconstructed = "".join(
        _parse_split_part(filename, value)[1] for filename, value in rewritten_parts
    )
    assert "new target" in reconstructed
    assert "old target" not in reconstructed


@pytest.mark.asyncio
async def test_one_part_compacted_family_is_resplit_after_later_growth():
    compacted_body = "# progress.md\n\n## Target\nshort\n"
    canonical = _split_marker("progress.md", 1, 1) + compacted_body
    storage = MemoryStorage({"sp/bank/progress.md": canonical})
    service = _service(max_size=2048)
    service._deduplicate_content = AsyncMock(
        side_effect=lambda content, filename: (content, 0)
    )
    output = {
        "file_edits": [
            {
                "filename": "progress.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "## Target",
                        "content": "growth\n" * 400,
                    }
                ],
            }
        ],
        "synthesis": "done",
    }

    bank_files = await storage.list_and_get("sp/bank/")
    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            "sp", output, bank_files, [], 1, {}, skip_meta=True
        )

    assert result["operations_failed"] == 0
    rewritten_parts = [
        (key.removeprefix("sp/bank/"), value)
        for key, value in sorted(storage.objects.items())
        if key.startswith("sp/bank/")
    ]
    assert len(rewritten_parts) > 1
    assert all(_utf8_size(value) <= 2048 for _, value in rewritten_parts)
    reconstructed = "".join(
        _parse_split_part(filename, value)[1] for filename, value in rewritten_parts
    )
    assert reconstructed.startswith("# progress.md")
    assert "growth" in reconstructed


@pytest.mark.asyncio
async def test_rewrite_is_refused_when_addressed_to_a_split_part():
    canonical = _split_marker("progress.md", 1, 2) + "# progress.md\n"
    second = _split_marker("progress.md", 2, 2) + "## Target\nold\n"
    storage = MemoryStorage(
        {
            "sp/bank/progress.md": canonical,
            "sp/bank/progress.part-002.md": second,
        }
    )
    service = _service()
    output = {
        "file_edits": [
            {
                "filename": "progress.part-002.md",
                "action": "rewrite",
                "content": "# erased\n",
            }
        ],
        "synthesis": "partial",
    }

    bank_files = await storage.list_and_get("sp/bank/")
    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            "sp", output, bank_files, [], 1, {}, skip_meta=True
        )

    assert result["operations_failed"] == 1
    assert storage.objects["sp/bank/progress.part-002.md"] == second


@pytest.mark.asyncio
async def test_split_refuses_existing_target_outside_family():
    content = _large_french_markdown()
    unrelated = "# legitimate document\n"
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            "sp/bank/progress.md": content,
            "sp/bank/progress.part-002.md": unrelated,
        }
    )
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert storage.objects["sp/bank/progress.md"] == content
    assert storage.objects["sp/bank/progress.part-002.md"] == unrelated


@pytest.mark.asyncio
async def test_stale_part_delete_failure_rolls_back_family():
    logical = "# progress.md\n" + "entry\n" * 100
    parts, error = _split_markdown_losslessly("progress.md", logical, 2048)
    assert error is None and parts is not None and len(parts) > 1
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            **{f"sp/bank/{name}": value for name, value in parts},
        }
    )
    original = dict(storage.objects)
    storage.delete_many = AsyncMock(return_value=0)
    service = _service(max_size=4096)
    bank_files = await storage.list_and_get("sp/bank/")
    unit = next(
        unit
        for unit in _build_compaction_units("sp", bank_files)
        if unit["source"] == "progress.md"
    )
    replacement, split_error = _split_markdown_losslessly("progress.md", logical, 4096)
    assert split_error is None and replacement is not None

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        backup_id = await service._create_compaction_backup("sp")
        ok, write_error = await service._write_split_parts(
            "sp", unit, replacement, backup_id
        )

    assert ok is False
    assert "stale split part deletion failed" in str(write_error)
    for key, value in original.items():
        assert storage.objects[key] == value


@pytest.mark.asyncio
async def test_incomplete_family_fails_even_below_limit():
    second = _split_marker("progress.md", 2, 2) + "orphan\n"
    storage = MemoryStorage({"sp/bank/progress.part-002.md": second})
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=True)

    assert result["status"] == "error"
    assert result["files_failed"] == 1


def _bank_tool(name: str):
    mcp = FastMCP(name="test")
    register_bank_tools(mcp)
    tool = mcp._tool_manager._tools[name]
    for attr in ("fn", "func", "handler", "_fn", "run", "callback"):
        fn = getattr(tool, attr, None)
        if callable(fn):
            return fn
    raise AssertionError(f"Tool {name} has no callable")


def _space_tool(name: str):
    mcp = FastMCP(name="test")
    register_space_tools(mcp)
    tool = mcp._tool_manager._tools[name]
    for attr in ("fn", "func", "handler", "_fn", "run", "callback"):
        fn = getattr(tool, attr, None)
        if callable(fn):
            return fn
    raise AssertionError(f"Tool {name} has no callable")


@pytest.mark.asyncio
async def test_bank_read_reassembles_a_split_family():
    logical = "# progress.md\n" + "entry\n" * 100
    parts, error = _split_markdown_losslessly("progress.md", logical, 2048)
    assert error is None and parts is not None and len(parts) > 1
    storage = MemoryStorage({f"sp/bank/{name}": value for name, value in parts})

    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.core.storage.get_storage", return_value=storage),
    ):
        result = await _bank_tool("bank_read")("sp", "progress.md")

    assert result["status"] == "ok"
    assert result["content"] == logical
    assert result["parts"] == len(parts)

    storage.objects["sp/_meta.json"] = '{"space_id":"sp"}'
    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.core.storage.get_storage", return_value=storage),
    ):
        all_result = await _bank_tool("bank_read_all")("sp")

    assert all_result["status"] == "ok"
    assert all_result["files"] == [
        {
            "filename": "progress.md",
            "content": logical,
            "size": _utf8_size(logical),
            "parts": len(parts),
        }
    ]


@pytest.mark.asyncio
async def test_bank_write_waits_for_the_shared_bank_lock():
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            "sp/bank/progress.md": "old\n",
        }
    )
    lock_manager = LockManager()
    lock = lock_manager.consolidation("sp")
    await lock.acquire()

    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.auth.context.check_manage_permission", return_value=None),
        patch("live_mem.core.storage.get_storage", return_value=storage),
        patch("live_mem.core.locks.get_lock_manager", return_value=lock_manager),
    ):
        task = asyncio.create_task(
            _bank_tool("bank_write")("sp", "progress.md", "new\n")
        )
        await asyncio.sleep(0)
        assert not task.done()
        assert storage.objects["sp/bank/progress.md"] == "old\n"
        lock.release()
        result = await task

    assert result["status"] == "ok"
    assert storage.objects["sp/bank/progress.md"] == "new\n"


@pytest.mark.asyncio
async def test_space_delete_refuses_while_the_bank_lock_is_held():
    lock_manager = LockManager()
    lock = lock_manager.consolidation("sp")
    await lock.acquire()
    space_service = AsyncMock()

    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.auth.context.check_manage_permission", return_value=None),
        patch("live_mem.core.locks.get_lock_manager", return_value=lock_manager),
        patch("live_mem.core.space.get_space_service", return_value=space_service),
    ):
        result = await _space_tool("space_delete")("sp", confirm=True)

    lock.release()
    assert result["status"] == "conflict"
    space_service.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_bank_write_refuses_a_split_family():
    logical = "# progress.md\n" + "entry\n" * 100
    parts, error = _split_markdown_losslessly("progress.md", logical, 2048)
    assert error is None and parts is not None and len(parts) > 1
    storage = MemoryStorage(
        {
            "sp/_meta.json": '{"space_id":"sp"}',
            **{f"sp/bank/{name}": value for name, value in parts},
        }
    )
    lock_manager = LockManager()

    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.auth.context.check_manage_permission", return_value=None),
        patch("live_mem.core.storage.get_storage", return_value=storage),
        patch("live_mem.core.locks.get_lock_manager", return_value=lock_manager),
    ):
        result = await _bank_tool("bank_write")("sp", "progress.md", "new\n")

    assert result["status"] == "conflict"
    assert storage.objects[f"sp/bank/{parts[0][0]}"] == parts[0][1]

    with (
        patch("live_mem.auth.context.check_access", return_value=None),
        patch("live_mem.auth.context.check_manage_permission", return_value=None),
        patch("live_mem.core.storage.get_storage", return_value=storage),
        patch("live_mem.core.locks.get_lock_manager", return_value=lock_manager),
    ):
        delete_result = await _bank_tool("bank_delete")(
            "sp", "progress.md", confirm=True
        )

    assert delete_result["status"] == "conflict"
    assert all(f"sp/bank/{name}" in storage.objects for name, _ in parts)


@pytest.mark.asyncio
async def test_llm_call_refuses_an_unsafe_context_budget():
    service = _service()
    service._context_window = 1000
    service._max_tokens = 500
    service._client = AsyncMock()

    result = await service._call_llm([{"role": "user", "content": "x" * 4000}])

    assert result["status"] == "error"
    service._client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_operation_exposes_file_section_and_reason():
    storage = MemoryStorage({"sp/bank/progress.md": "# progress.md\n"})
    service = _service()
    service._deduplicate_content = AsyncMock(
        side_effect=lambda content, filename: (content, 0)
    )
    output = {
        "file_edits": [
            {
                "filename": "progress.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "## Missing",
                        "content": "never written",
                    }
                ],
            }
        ],
        "synthesis": "partial",
    }

    bank_files = await storage.list_and_get("sp/bank/")
    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            "sp", output, bank_files, [], 1, {}, skip_meta=True
        )

    assert result["operations_failed"] == 1
    assert result["operation_failures"] == [
        {
            "filename": "progress.md",
            "operation": "append_to_section",
            "heading": "## Missing",
            "reason": "Section non trouvée: ## Missing",
        }
    ]
