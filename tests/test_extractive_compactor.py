"""Mutation-focused tests for exact extractive Markdown selection."""

from datetime import date

from markdown_it import MarkdownIt
import pytest

from live_mem.core.extractive_compactor import (
    MarkdownUnit,
    SelectionPlan,
    build_candidate,
    delete_units,
    extract_pattern_units,
    extract_progress_units,
    make_plan,
    parse_ranking,
    progress_prompt,
    select_under_budget,
)


PARSER = MarkdownIt()


def _unit(unit_id: str, start: int, size: int) -> MarkdownUnit:
    return MarkdownUnit(unit_id, start, start + size, b"x" * size, date(2026, 8, 1))


def test_progress_units_are_complete_utf8_and_exclude_recent_and_protected():
    old = "### 2026-08-01 — café\n- décision exacte\n\n".encode()
    protected = b"### 2026-08-02 - code\n```sh\necho intact\n```\n\n"
    recent = b"### 2026-08-03 - recent\n- stays exact\n"
    original = b"\xef\xbb\xbf# progress\n\n" + old + protected + recent

    units = extract_progress_units(original, PARSER)

    assert [unit.source for unit in units] == [old]
    assert original[units[0].start_byte : units[0].end_byte] == old
    assert delete_units(original, units) == b"\xef\xbb\xbf# progress\n\n" + protected + recent


@pytest.mark.parametrize(
    "protected_body",
    [
        b"    command --secret\r\n",
        b"<div>raw block</div>\r\n",
        b"- value <span>raw inline</span>\r\n",
    ],
)
def test_crlf_code_and_html_entries_remain_byte_exact(protected_body):
    protected = b"### 2026-08-01 - protected\r\n" + protected_body + b"\r\n"
    recent = b"### 2026-08-02 - recent\r\n- exact\r\n"
    original = b"# progress\r\n\r\n" + protected + recent

    units = extract_progress_units(original, PARSER)

    assert units == []
    assert delete_units(original, units) == original


def test_pattern_h3_sections_stop_at_h1_h2_and_h3():
    first = b"### Pattern A\n- exact A\n"
    second = b"### Pattern B\n- exact B\n"
    original = (
        b"# Patterns\n## Groupe\n" + first + second
        + b"# Annexe\n- H1 exact\n## Suite\n- H2 exact\n"
    )

    units = extract_pattern_units(original, PARSER)

    assert [unit.source for unit in units] == [first, second]
    assert delete_units(original, units) == (
        b"# Patterns\n## Groupe\n# Annexe\n- H1 exact\n## Suite\n- H2 exact\n"
    )


def test_plan_budget_is_exact_and_fails_when_protected_base_is_too_large():
    source = b"old"
    unit = MarkdownUnit("U0001", 0, len(source), source, date(2026, 8, 1))
    original = source + b"protected"

    assert make_plan(original, [unit], 12).available_bytes == 3
    with pytest.raises(ValueError, match="protected content"):
        make_plan(original, [unit], 8)


def test_ranking_ignores_unknown_and_duplicates_but_requires_one_known_id():
    known = [_unit("U0001", 0, 10), _unit("U0002", 10, 10)]

    ranking = parse_ranking("prose U9999 U0002 U0002 U0001", known)

    assert [unit.unit_id for unit in ranking] == ["U0002", "U0001"]
    with pytest.raises(ValueError, match="no known"):
        parse_ranking("U9999", known)


def test_greedy_budget_uses_ranking_then_restores_document_order():
    first = _unit("U0001", 0, 40)
    second = _unit("U0002", 40, 80)
    third = _unit("U0003", 120, 30)

    selected = select_under_budget([second, third, first], 75)

    assert [unit.unit_id for unit in selected] == ["U0001", "U0003"]
    assert sum(unit.size for unit in selected) == 70


def test_known_but_indivisible_ranking_cannot_delete_every_eligible_unit():
    known = _unit("U0001", 0, 11)

    with pytest.raises(ValueError, match="no ranked Markdown unit fits"):
        select_under_budget([known], 5)


def test_candidate_is_only_exact_selected_source_plus_untouched_base():
    first = b"- **2026-08-01** : exact one\n"
    second = b"- **2026-08-02** : exact two\n"
    recent = b"- **2026-08-03** : exact recent\n"
    original = first + second + recent
    one = MarkdownUnit("U0001", 0, len(first), first, date(2026, 8, 1))
    two = MarkdownUnit(
        "U0002", len(first), len(first) + len(second), second, date(2026, 8, 2)
    )
    plan = SelectionPlan(original, (one, two), 100)

    assert build_candidate(plan, [two], 100) == second + recent


def test_progress_prompt_contains_exact_authorities_but_not_generated_edits():
    source = b"- **2026-08-01** : jalon utile\n"
    unit = MarkdownUnit("U0001", 0, len(source), source, date(2026, 8, 1))

    prompt = progress_prompt([unit], b"# active\nSTATE\n# patterns\nINVARIANT")

    assert "U0001" in prompt
    assert "STATE" in prompt and "INVARIANT" in prompt
    assert "file_edits" not in prompt and "replace_section" not in prompt
