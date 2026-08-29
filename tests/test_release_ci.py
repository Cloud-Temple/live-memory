"""Regression checks for the release-only GHCR publishing guard."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "build.yml"


def test_ghcr_publication_is_restricted_to_release_tags():
    """A branch or RC push must never receive GHCR write permissions."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "  build:\n"
        "    name: Build & Push Docker Image\n"
        "    if: startsWith(github.ref, 'refs/tags/v')"
    ) in workflow
    assert "type=ref,event=branch" not in workflow
