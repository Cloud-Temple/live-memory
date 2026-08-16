from pathlib import Path

import pytest

from live_mem.core import live as live_module


ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "src" / "live_mem" / "static" / "js" / "admin-app.js"


class _FakeStorage:
    async def exists(self, key: str) -> bool:
        return key == "demo/_meta.json"

    async def list_and_get(self, prefix: str) -> list[dict]:
        assert prefix == "demo/live/"
        notes = [
            {
                "key": f"demo/live/note-{index}.md",
                "content": (
                    "---\n"
                    f'timestamp: "2026-08-16T12:00:0{index}+00:00"\n'
                    'agent: "agent"\n'
                    'category: "progress"\n'
                    "tags: []\n"
                    'space_id: "demo"\n'
                    "---\n\n"
                    f"Note {index}"
                ),
            }
            for index in range(3)
        ]
        notes.append(
            {
                "key": "demo/live/other-category.md",
                "content": (
                    "---\n"
                    'timestamp: "2026-08-16T12:00:09+00:00"\n'
                    'agent: "agent"\n'
                    'category: "issue"\n'
                    "tags: []\n"
                    'space_id: "demo"\n'
                    "---\n\n"
                    "Not part of the requested category"
                ),
            }
        )
        notes.append({"key": "demo/live/malformed.md", "content": "---"})
        return notes


@pytest.mark.asyncio
async def test_live_read_exposes_true_match_count_before_limit(monkeypatch):
    monkeypatch.setattr(live_module, "get_storage", lambda: _FakeStorage())

    result = await live_module.LiveService().read_notes(
        "demo", limit=2, category="progress"
    )

    assert result["total"] == 2
    assert result["matched_total"] == 3
    assert result["has_more"] is True


def test_admin_explorer_keeps_card_limit_but_displays_true_count():
    source = ADMIN_JS.read_text()

    assert "callTool('live_read',{space_id:sid,limit:30})" in source
    assert "notes.matched_total??nl.length" in source
