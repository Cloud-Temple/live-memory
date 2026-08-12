# -*- coding: utf-8 -*-
"""Adversarial regression tests for issue #37 (silent bank destruction)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from live_mem.core.consolidator import (
    ConsolidatorService,
    _content_sha256,
    _parse_split_part,
    _split_markdown_losslessly,
    _split_marker,
    _utf8_size,
)


def _service(max_size: int = 4096) -> ConsolidatorService:
    service = object.__new__(ConsolidatorService)
    service._bank_file_max_size = max_size
    return service


def _large_french_markdown() -> str:
    lines = ["# progress.md\n"]
    for index in range(180):
        lines.append(
            f"## Jalon {index}\n"
            f"- Décision vérifiée numéro {index} — aucune donnée ne doit disparaître.\n"
        )
    return "".join(lines)


class MemoryStorage:
    """S3 stand-in that keeps object contents and copies inspectable."""

    def __init__(self, objects: dict[str, str]):
        self.objects = dict(objects)
        self.copy_calls: list[tuple[str, str]] = []
        self.fail_copy = False
        self.corrupt_reads = False

    async def get_json(self, key: str):
        return {"space_id": "sp"} if key == "sp/_meta.json" else None

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
async def test_apply_creates_backup_and_never_calls_llm():
    content = _large_french_markdown()
    storage = MemoryStorage({"sp/bank/progress.md": content})
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "ok"
    assert result["files_split"] == 1
    assert result["files_failed"] == 0
    assert result["size_unit"] == "utf-8 bytes"
    assert "backup_id" in result
    assert storage.copy_calls, "a restorable snapshot must precede replacement"

    physical_parts = [
        (key.removeprefix("sp/bank/"), value)
        for key, value in sorted(storage.objects.items())
        if key.startswith("sp/bank/")
    ]
    assert len(physical_parts) > 1
    assert all(_utf8_size(value) <= 4096 for _, value in physical_parts)
    reconstructed = "".join(
        _parse_split_part(filename, value)[1]
        for filename, value in physical_parts
    )
    assert reconstructed == content


@pytest.mark.asyncio
async def test_backup_failure_preserves_original_without_any_write():
    content = _large_french_markdown()
    storage = MemoryStorage({"sp/bank/progress.md": content})
    storage.fail_copy = True
    storage.put = AsyncMock(side_effect=storage.put)
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert result["files_failed"] == 1
    storage.put.assert_not_awaited()
    assert storage.objects["sp/bank/progress.md"] == content


@pytest.mark.asyncio
async def test_post_write_verification_failure_rolls_back_original():
    content = _large_french_markdown()
    storage = MemoryStorage({"sp/bank/progress.md": content})
    storage.corrupt_reads = True
    service = _service()

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service.compact_bank("sp", dry_run=False)

    assert result["status"] == "error"
    assert result["files_failed"] == 1
    assert storage.objects["sp/bank/progress.md"] == content


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
                "filename": "progress.md",
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
        _parse_split_part(filename, value)[1]
        for filename, value in rewritten_parts
    )
    assert "new target" in reconstructed
    assert "old target" not in reconstructed


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
