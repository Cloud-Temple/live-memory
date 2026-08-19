# -*- coding: utf-8 -*-
"""Regression tests for empty LLM merges during section deduplication."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from live_mem.core.consolidator import ConsolidatorService


def _service() -> ConsolidatorService:
    service = object.__new__(ConsolidatorService)
    service._model = "test-model"
    service._client = AsyncMock()
    return service


def _response(content: str | None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _duplicated_content(second: str = "- décision B\n") -> str:
    return (
        "# Progress\n\n"
        "## Hors plan / En attente\n"
        "- décision A\n\n"
        "## Stable\n"
        "- invariant\n\n"
        "## Hors plan / En attente\n"
        f"{second}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_output",
    [None, "", "   \n", "<think>analyse seulement</think>", "```markdown\n\n```"],
)
async def test_invalid_llm_merge_preserves_all_duplicate_sections(raw_output):
    service = _service()
    service._client.chat.completions.create = AsyncMock(
        return_value=_response(raw_output)
    )
    original = _duplicated_content()

    content, merged_count, failure_count = await service._deduplicate_content(
        original, "progress.md"
    )

    assert content == original
    assert merged_count == 0
    assert failure_count == 1


@pytest.mark.asyncio
async def test_llm_exception_preserves_all_duplicate_sections():
    service = _service()
    service._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("backend unavailable")
    )
    original = _duplicated_content()

    content, merged_count, failure_count = await service._deduplicate_content(
        original, "progress.md"
    )

    assert content == original
    assert merged_count == 0
    assert failure_count == 1


@pytest.mark.asyncio
async def test_one_non_blank_version_is_kept_without_llm_call():
    service = _service()
    service._merge_sections_via_llm = AsyncMock()
    original = _duplicated_content(second="\n")

    content, merged_count, failure_count = await service._deduplicate_content(
        original, "progress.md"
    )

    assert content.count("## Hors plan / En attente") == 1
    assert "- décision A" in content
    assert content.index("- décision A") < content.index("## Stable")
    assert merged_count == 1
    assert failure_count == 0
    service._merge_sections_via_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_blank_versions_reduce_to_one_empty_section_without_llm():
    service = _service()
    service._merge_sections_via_llm = AsyncMock()
    original = (
        "# Progress\n\n"
        "## Hors plan / En attente\n\n"
        "## Stable\n- invariant\n\n"
        "## Hors plan / En attente\n"
    )

    content, merged_count, failure_count = await service._deduplicate_content(
        original, "progress.md"
    )

    assert content.count("## Hors plan / En attente") == 1
    assert "## Stable\n- invariant" in content
    assert merged_count == 1
    assert failure_count == 0
    service._merge_sections_via_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_non_blank_merge_keeps_nominal_behavior():
    service = _service()
    service._merge_sections_via_llm = AsyncMock(
        return_value="- décision A\n- décision B"
    )

    content, merged_count, failure_count = await service._deduplicate_content(
        _duplicated_content(), "progress.md"
    )

    assert content.count("## Hors plan / En attente") == 1
    assert "- décision A\n- décision B" in content
    assert merged_count == 1
    assert failure_count == 0


class _Storage:
    def __init__(self, objects: dict[str, str]):
        self.objects = dict(objects)

    async def get(self, key: str):
        return self.objects.get(key)

    async def exists(self, key: str):
        return key in self.objects

    async def put(self, key: str, content: str):
        self.objects[key] = content

    async def get_json(self, key: str):
        return {}

    async def put_json(self, key: str, value: dict):
        self.objects[key] = value

    async def list_objects(self, prefix: str):
        return [{"Key": key} for key in sorted(self.objects) if key.startswith(prefix)]

    async def delete_many(self, keys: list[str]):
        deleted = 0
        for key in keys:
            if key in self.objects:
                del self.objects[key]
                deleted += 1
        return deleted

    async def delete(self, key: str):
        return self.objects.pop(key, None) is not None

    async def copy_object(self, source: str, destination: str):
        self.objects[destination] = self.objects[source]


def _split_marker(source: str, part: int, total: int) -> str:
    next_name = f"progress.part-{part + 1:03d}.md" if part < total else None
    metadata = {"source": source, "part": part, "total": total, "next": next_name}
    return (
        "<!-- live-mem-split "
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        + " -->\n"
    )


@pytest.mark.asyncio
async def test_edit_batch_preserves_two_files_and_reports_dedup_failures():
    progress = _duplicated_content()
    context = (
        _duplicated_content()
        .replace("décision A", "risque A")
        .replace("décision B", "risque B")
    )
    note_key = "sp/live/note.md"
    storage = _Storage(
        {
            "sp/bank/progress.md": progress,
            "sp/bank/activeContext.md": context,
            note_key: "note source",
        }
    )
    service = _service()
    service._merge_sections_via_llm = AsyncMock(return_value=None)
    llm_output = {
        "file_edits": [
            {
                "filename": "progress.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "## Stable",
                        "content": "- ajout progress",
                    }
                ],
            },
            {
                "filename": "activeContext.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "## Stable",
                        "content": "- ajout contexte",
                    }
                ],
            },
        ],
        "synthesis": "lot intégré",
    }

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            space_id="sp",
            llm_output=llm_output,
            bank_files=[
                {"key": "sp/bank/progress.md", "content": progress},
                {"key": "sp/bank/activeContext.md", "content": context},
            ],
            notes_keys=[note_key],
            notes_count=1,
            usage={},
            notes=[{"key": note_key, "content": "note source"}],
        )

    assert not result.get("operation_failures"), result.get("operation_failures")
    assert result["status"] == "ok", result
    assert result["notes_processed"] == 1
    assert result["bank_files_updated"] == 2
    assert result["dedup_failures_count"] == 2
    assert storage.objects["sp/bank/progress.md"].count("## Hors plan / En attente") == 2
    assert "- décision A" in storage.objects["sp/bank/progress.md"]
    assert "- décision B" in storage.objects["sp/bank/progress.md"]
    assert "- ajout progress" in storage.objects["sp/bank/progress.md"]
    assert storage.objects["sp/bank/activeContext.md"].count("## Hors plan / En attente") == 2
    assert "- risque A" in storage.objects["sp/bank/activeContext.md"]
    assert "- risque B" in storage.objects["sp/bank/activeContext.md"]
    assert "- ajout contexte" in storage.objects["sp/bank/activeContext.md"]
    assert note_key not in storage.objects


@pytest.mark.asyncio
async def test_legacy_split_edit_preserves_duplicates_and_canonicalizes():
    first = (
        _split_marker("progress.md", 1, 2)
        + "# Progress\n\n## Hors plan / En attente\n- décision A\n\n"
    )
    second = (
        _split_marker("progress.md", 2, 2)
        + "## Stable\n- invariant\n\n"
        "## Hors plan / En attente\n- décision B\n"
    )
    note_key = "sp/live/note.md"
    storage = _Storage(
        {
            "sp/bank/progress.md": first,
            "sp/bank/progress.part-002.md": second,
            note_key: "note source",
        }
    )
    service = _service()
    service._merge_sections_via_llm = AsyncMock(return_value=None)
    output = {
        "file_edits": [
            {
                "filename": "progress.part-002.md",
                "action": "edit",
                "operations": [
                    {
                        "type": "append_to_section",
                        "heading": "## Stable",
                        "content": "- ajout split",
                    }
                ],
            }
        ],
        "synthesis": "lot intégré",
    }

    with patch("live_mem.core.consolidator.get_storage", return_value=storage):
        result = await service._write_results(
            space_id="sp",
            llm_output=output,
            bank_files=[
                {"key": "sp/bank/progress.md", "content": first},
                {"key": "sp/bank/progress.part-002.md", "content": second},
            ],
            notes_keys=[note_key],
            notes_count=1,
            usage={},
            notes=[{"key": note_key, "content": "note source"}],
        )

    assert not result.get("operation_failures"), result.get("operation_failures")
    assert result["status"] == "ok", result
    assert result["dedup_failures_count"] == 1
    assert "sp/bank/progress.part-002.md" not in storage.objects
    canonical = storage.objects["sp/bank/progress.md"]
    assert canonical.count("## Hors plan / En attente") == 2
    assert "- décision A" in canonical
    assert "- décision B" in canonical
    assert "- ajout split" in canonical
    assert note_key not in storage.objects
