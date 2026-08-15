"""Mutation-focused tests for exact extractive Markdown selection."""

from datetime import date

from markdown_it import MarkdownIt
import pytest

from live_mem.core.extractive_compactor import (
    MAP_BATCH_MAX_BYTES,
    MAP_BATCH_MAX_UNITS,
    MAP_CARD_MAX_BYTES,
    MarkdownUnit,
    SelectionPlan,
    build_candidate,
    build_map_batches,
    delete_units,
    extract_markdown_inventory,
    map_prompt,
    make_plan,
    parse_map_cards,
    parse_ranking,
    reduce_prompt,
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

    inventory = extract_markdown_inventory(original, PARSER)
    units = list(inventory.candidates)

    assert inventory.mode == "dated"
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

    inventory = extract_markdown_inventory(original, PARSER)

    assert inventory.mode == "dated"
    assert inventory.candidates == ()
    assert delete_units(original, list(inventory.candidates)) == original


def test_pattern_h3_sections_stop_at_h1_h2_and_h3():
    first = b"### Pattern A\n- exact A\n"
    second = b"### Pattern B\n- exact B\n"
    original = (
        b"# Patterns\n## Groupe\n" + first + second
        + b"# Annexe\n- H1 exact\n## Suite\n- H2 exact\n"
    )

    inventory = extract_markdown_inventory(original, PARSER)
    units = list(inventory.candidates)

    assert inventory.mode == "sections"
    assert [unit.source for unit in units] == [first, second]
    assert delete_units(original, units) == (
        b"# Patterns\n## Groupe\n# Annexe\n- H1 exact\n## Suite\n- H2 exact\n"
    )


def test_dates_in_h3_bodies_do_not_turn_a_thematic_file_into_a_journal():
    original = (
        b"# Knowledge\n"
        b"### First invariant\nObserved on 2026-08-01.\n"
        b"### Second invariant\nObserved on 2026-08-02.\n"
    )

    inventory = extract_markdown_inventory(original, PARSER)

    assert inventory.mode == "sections"
    assert len(inventory.candidates) == 2


def test_dated_mode_never_falls_back_to_undated_h3_sections():
    old = b"### 2026-08-01 - old\n- compressible\n"
    undated = b"### Permanent appendix\n- protected\n"
    recent = b"### 2026-08-02 - recent\n- protected\n"

    inventory = extract_markdown_inventory(old + undated + recent, PARSER)

    assert inventory.mode == "dated"
    assert [unit.source for unit in inventory.candidates] == [old]
    assert [unit.source for unit in inventory.protected_context] == [undated, recent]


def test_dated_items_under_undated_h3_protect_the_latest_day():
    old = b"- **2026-08-01** old\n"
    recent = b"- **2026-08-02** recent\n"
    original = b"# Journal\n### Updates\n" + old + recent

    inventory = extract_markdown_inventory(original, PARSER)

    assert inventory.mode == "dated"
    assert [unit.source for unit in inventory.candidates] == [old]
    assert [unit.source for unit in inventory.protected_context] == [recent]


def test_dated_h3_journal_includes_non_overlapping_list_era():
    old_list = b"- **2026-08-01** old list entry\n"
    recent_list = b"- **2026-08-03** recent list entry\n"
    old_h3 = (
        b"### 2026-08-02 - old section\n"
        b"- **2026-07-01** nested body item, not a separate unit\n"
    )
    recent_h3 = b"### 2026-08-03 - recent section\n- exact\n"
    preamble = b"# Progress\n"
    original = preamble + old_list + recent_list + old_h3 + recent_h3

    inventory = extract_markdown_inventory(original, PARSER)

    assert inventory.mode == "dated"
    assert [unit.source for unit in inventory.candidates] == [old_list, old_h3]
    assert [unit.source for unit in inventory.protected_context] == [
        recent_list,
        recent_h3,
    ]
    assert delete_units(original, list(inventory.candidates)) == (
        preamble + recent_list + recent_h3
    )


def test_one_dated_h3_in_thematic_document_remains_section_mode():
    first = b"### 2026-08-01 baseline\n- invariant\n"
    second = b"### Durable mechanism\n- invariant\n"

    inventory = extract_markdown_inventory(first + second, PARSER)

    assert inventory.mode == "sections"
    assert [unit.source for unit in inventory.candidates] == [first, second]


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


def test_map_batches_keep_units_indivisible_and_bounded():
    units = [_unit(f"U{index:04d}", (index - 1) * 1300, 1300) for index in range(1, 35)]

    batches = build_map_batches(units)

    assert [len(batch) for batch in batches] == [30, 4]
    assert all(len(batch) <= MAP_BATCH_MAX_UNITS for batch in batches)
    assert all(sum(unit.size for unit in batch) <= MAP_BATCH_MAX_BYTES for batch in batches)
    assert [unit for batch in batches for unit in batch] == units


def test_map_batch_rejects_an_indivisible_unit_above_its_bound():
    oversized = _unit("U0001", 0, MAP_BATCH_MAX_BYTES + 1)

    with pytest.raises(ValueError, match="exceeds the Map batch"):
        build_map_batches([oversized])


def test_map_cards_are_bounded_and_fallback_omissions_to_source_labels():
    first = MarkdownUnit(
        "U0001", 0, 20, b"### 2026-08-01 - first\n", date(2026, 8, 1)
    )
    second = MarkdownUnit(
        "U0002", 20, 40, b"### 2026-08-02 - second\n", date(2026, 8, 2)
    )
    output = (
        "U9999 | unknown\n"
        "U0001 U9999 | multiple ids rejected\n"
        "U0001 | fiche de U0001 " + ("é" * 300) + "\n"
        "U0001 | duplicate ignored\n"
    )

    cards, valid, fallback = parse_map_cards(output, [first, second])

    assert valid == 1
    assert fallback == 1
    assert len(cards["U0001"].encode("utf-8")) <= MAP_CARD_MAX_BYTES
    assert "U0001" not in cards["U0001"]
    assert cards["U0002"] == "### 2026-08-02 - second"

    fallback_cards, fallback_valid, fallback_count = parse_map_cards(
        "U0001 U9999 | ambiguous", [first, second]
    )

    assert fallback_valid == 0
    assert fallback_count == 2
    assert fallback_cards == {
        "U0001": "### 2026-08-01 - first",
        "U0002": "### 2026-08-02 - second",
    }


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


def test_map_and_reduce_prompts_keep_source_and_ephemeral_cards_separate():
    old = b"- **2026-08-01** : jalon utile\n"
    recent = b"- **2026-08-02** : etat recent intact\n"
    inventory = extract_markdown_inventory(old + recent, PARSER)
    units = tuple(
        sorted(
            [*inventory.candidates, *inventory.protected_context],
            key=lambda item: item.start_byte,
        )
    )

    source_prompt = map_prompt(units)
    cards = {"U0001": "décision durable", "P0001": "état final"}
    ranking_prompt = reduce_prompt(inventory, cards, 100)

    assert "jalon utile" in source_prompt and "etat recent intact" in source_prompt
    assert "selectable | U0001 | date=2026-08-01" in ranking_prompt
    assert "protected | P0001 | date=2026-08-02" in ranking_prompt
    assert "bytes=" in ranking_prompt and "décision durable" in ranking_prompt
    assert "jalon utile" not in ranking_prompt and "etat recent intact" not in ranking_prompt
