"""Regression tests for #62: compaction may legitimately absorb headings."""

import pytest

from live_mem.core.consolidator import _evaluate_edit_operations


def _operation(kind: str, heading: str = "## Absorbée", content: str = "fait") -> dict:
    return {"type": kind, "heading": heading, "content": content}


@pytest.mark.parametrize(
    "kind", ["replace_section", "append_to_section", "prepend_to_section"]
)
def test_missing_section_is_recovered_at_file_end(kind: str):
    content, recovered = _evaluate_edit_operations("# Bank\n\n## Conservée\ntexte\n", [_operation(kind)])

    assert content.endswith("## Absorbée\nfait\n")
    assert recovered == [
        {
            "type": kind,
            "heading": "## Absorbée",
            "strategy": "append_missing_section",
            "placement": "file_end",
        }
    ]


def test_missing_delete_is_idempotent_without_mutating_bank():
    original = "# Bank\n\n## Conservée\ntexte\n"
    content, recovered = _evaluate_edit_operations(
        original, [_operation("delete_section", content="")]
    )

    assert content == original
    assert recovered[0]["strategy"] == "already_absent"
    assert recovered[0]["placement"] == "none"


def test_recovered_heading_is_seen_by_later_operations():
    content, recovered = _evaluate_edit_operations(
        "# Bank\n",
        [
            _operation("replace_section", content="premier"),
            _operation("append_to_section", content="second"),
            _operation("prepend_to_section", content="zéro"),
        ],
    )

    assert content.count("## Absorbée") == 1
    assert "zéro\npremier\nsecond" in content
    assert len(recovered) == 1


@pytest.mark.parametrize(
    "operations, expected", [
        ([
            _operation("delete_section", content=""),
            _operation("append_to_section", content="recréé"),
        ], "recréé"),
        ([
            _operation("append_to_section", content="temporaire"),
            _operation("delete_section", content=""),
        ], None),
    ],
)
def test_missing_section_sequences_remain_idempotent(operations, expected):
    content, _ = _evaluate_edit_operations("# Bank\n", operations)
    assert ("## Absorbée" in content) is (expected is not None)
    if expected:
        assert expected in content


def test_add_section_after_missing_keeps_historical_end_of_file_behavior():
    content, recovered = _evaluate_edit_operations(
        "# Bank\n", [{"type": "add_section", "heading": "## Nouvelle", "content": "fait", "after": "## Absente"}]
    )
    assert content.endswith("## Nouvelle\n\nfait\n")
    assert recovered == []


@pytest.mark.parametrize(
    "operation",
    [
        _operation("replace_section", heading="Absorbée"),
        _operation("replace_section", content="  "),
        _operation("delete_section", heading="Absorbée", content=""),
    ],
)
def test_only_valid_missing_section_operations_are_recovered(operation: dict):
    with pytest.raises(ValueError):
        _evaluate_edit_operations("# Bank\n", [operation])


def test_existing_section_keeps_historical_operation_behavior():
    content, recovered = _evaluate_edit_operations(
        "# Bank\n\n## Présente\nancien\n",
        [_operation("replace_section", heading="## Présente", content="nouveau")],
    )

    assert "nouveau" in content
    assert "ancien" not in content
    assert recovered == []
