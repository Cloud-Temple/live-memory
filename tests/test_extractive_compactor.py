"""Mutation-focused tests for hierarchical Markdown digest compaction."""

from datetime import date

from markdown_it import MarkdownIt
import pytest

from live_mem.core.extractive_compactor import (
    MAP_BATCH_MAX_BYTES,
    MAP_BATCH_MAX_UNITS,
    MAP_CARD_MAX_BYTES,
    MarkdownUnit,
    build_digest_candidate,
    build_map_batches,
    delete_units,
    digest_output_budget,
    digest_insertion_offset,
    extract_markdown_inventory,
    map_prompt,
    make_plan,
    parse_map_cards,
    reduce_prompt,
    render_digest_container,
    validate_digest,
)


PARSER = MarkdownIt().enable("table")


def _unit(unit_id: str, start: int, size: int) -> MarkdownUnit:
    return MarkdownUnit(
        unit_id, start, start + size, b"x" * size, date(2026, 8, 1), "h3"
    )


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
    assert (
        delete_units(original, units)
        == b"\xef\xbb\xbf# progress\n\n" + protected + recent
    )


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
        b"# Patterns\n## Groupe\n"
        + first
        + second
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
    unit = MarkdownUnit("U0001", 0, len(source), source, date(2026, 8, 1), "list")
    original = source + b"protected"

    assert make_plan(original, [unit], 12).available_bytes == 3
    with pytest.raises(ValueError, match="protected content"):
        make_plan(original, [unit], 8)


def test_map_batches_keep_units_indivisible_and_bounded():
    units = [_unit(f"U{index:04d}", (index - 1) * 1300, 1300) for index in range(1, 35)]

    batches = build_map_batches(units)

    assert [len(batch) for batch in batches] == [30, 4]
    assert all(len(batch) <= MAP_BATCH_MAX_UNITS for batch in batches)
    assert all(
        sum(unit.size for unit in batch) <= MAP_BATCH_MAX_BYTES for batch in batches
    )
    assert [unit for batch in batches for unit in batch] == units


def test_map_batch_rejects_an_indivisible_unit_above_its_bound():
    oversized = _unit("U0001", 0, MAP_BATCH_MAX_BYTES + 1)

    with pytest.raises(ValueError, match="exceeds the Map batch"):
        build_map_batches([oversized])


def test_map_cards_are_bounded_and_fallback_omissions_to_source_labels():
    first = MarkdownUnit(
        "U0001", 0, 20, b"### 2026-08-01 - first\n", date(2026, 8, 1), "h3"
    )
    second = MarkdownUnit(
        "U0002", 20, 40, b"### 2026-08-02 - second\n", date(2026, 8, 2), "h3"
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


def test_digest_validation_allows_technical_markdown_and_rejects_invention():
    source = b"Decision #80 livree en v1.2.3 le 2026-08-01."
    output = "- Décision #80 livrée en `v1.2.3` le 2026-08-01."

    assert validate_digest(output, source, source, 200, PARSER) == output.encode()

    with pytest.raises(ValueError, match="invents references"):
        validate_digest("- Décision #81.", source, source, 200, PARSER)
    with pytest.raises(ValueError, match="internal unit id"):
        validate_digest("- Garder U0001.", source, source, 200, PARSER)


@pytest.mark.parametrize(
    "output, reason",
    [
        ("### Heading", "heading_open"),
        ("```sh\necho no\n```", "fence"),
        ("<span>raw</span>", "html_inline"),
        ("> citation", "blockquote_open"),
        ("---", "hr"),
        ("[lien](https://example.test)", "link_open"),
        ("[ref]: https://example.test", "link definition"),
        ("[foo\\]]: https://example.test\n\n- résumé", "link definition"),
        ("[foo\nbar]: https://example.test\n\n- résumé", "link definition"),
        ("![image](x.png)", "image"),
        ("| A | B |\n|---|---|\n|x|y|", "table_open"),
        ('{"plan":["delete"]}', "JSON"),
        ('{"plan":["delete"]}\n\n- résumé', "JSON"),
    ],
)
def test_digest_validation_rejects_active_or_structured_output(output, reason):
    with pytest.raises(ValueError, match=reason):
        validate_digest(output, b"source", b"source", 500, PARSER)


def test_mixed_digest_uses_h3_anchor_and_is_recompactable():
    old_list = b"- **2026-08-01** ancienne liste avec beaucoup de details historiques\n"
    old_h3 = (
        b"### 2026-08-02 - ancien H3\n" + b"- detail historique important et long\n" * 4
    )
    recent_h3 = b"### 2026-08-03 - H3 recent\n- exact\n"
    original = b"# Journal\n" + old_list + old_h3 + recent_h3
    inventory = extract_markdown_inventory(original, PARSER)
    plan = make_plan(original, list(inventory.candidates), 500)
    digest = b"- Decision historique #80."

    candidate = build_digest_candidate(plan, digest, inventory.mode, 300, 500)

    assert digest_insertion_offset(plan) == len(b"# Journal\n")
    assert old_list not in candidate and old_h3 not in candidate
    assert recent_h3 in candidate
    second = extract_markdown_inventory(candidate, PARSER)
    assert second.mode == "dated"
    assert len(second.candidates) == 1
    assert second.candidates[0].kind == "h3"
    assert b"Historique compact" in second.candidates[0].source
    assert [unit.source for unit in second.protected_context] == [recent_h3]

    second_plan = make_plan(candidate, list(second.candidates), 500)
    replacement = build_digest_candidate(
        second_plan, b"- Nouveau.", second.mode, 300, 500
    )
    assert digest not in replacement
    assert replacement.count(b"Historique compact") == 1
    assert recent_h3 in replacement


def test_digest_cannot_activate_a_reference_link_in_protected_content():
    old = (
        b"- **2026-08-01** ancien historique suffisamment long pour reduction "
        + b"details repetitifs " * 12
        + b"\n"
    )
    recent = b"- **2026-08-02** recent [ref]\n"
    original = old + recent
    inventory = extract_markdown_inventory(original, PARSER)
    plan = make_plan(original, list(inventory.candidates), 500)

    with pytest.raises(ValueError, match="link definition"):
        validate_digest("[ref]: https://example.test", original, recent, 200, PARSER)

    unsafe = build_digest_candidate(
        plan, b"[ref]: https://example.test", inventory.mode, 300, 500
    )
    assert any(
        child.type == "link_open"
        for token in PARSER.parse(unsafe.decode())
        for child in (token.children or [])
    )


def test_protected_reference_definition_cannot_activate_a_digest_link():
    preserved = b"[ref]: https://example.test\n"
    source = b"historique supprimable\n" + preserved

    with pytest.raises(ValueError, match="link_open"):
        validate_digest("- Voir [ref].", source, preserved, 200, PARSER)


def test_sections_digest_hides_dated_internal_lists_from_next_inventory():
    first = b"### Pattern A\n" + b"- invariant detaille et durable\n" * 4
    second = b"### Pattern B\n" + b"- invariant detaille et durable\n" * 4
    original = b"# Patterns\n" + first + second
    inventory = extract_markdown_inventory(original, PARSER)
    plan = make_plan(original, list(inventory.candidates), 500)
    digest = b"- 2026-08-01 - decision\n- 2026-08-02 - incident"

    candidate = build_digest_candidate(plan, digest, inventory.mode, 400, 500)
    second_inventory = extract_markdown_inventory(candidate, PARSER)

    assert second_inventory.mode == "sections"
    assert len(second_inventory.candidates) == 1
    assert second_inventory.candidates[0].kind == "h3"
    assert render_digest_container(plan, digest, inventory.mode) in candidate

    second_plan = make_plan(candidate, list(second_inventory.candidates), 500)
    replacement = build_digest_candidate(
        second_plan, b"- Nouveau pattern durable.", second_inventory.mode, 400, 500
    )
    assert digest not in replacement
    assert replacement.count(b"Historique compact") == 1


def test_list_digest_is_one_recompactable_dated_item():
    old = (
        b"- **2026-08-01** ancien avec beaucoup de details historiques "
        + b"qui seront remplaces par une synthese courte " * 4
        + b"\n"
    )
    recent = b"- **2026-08-02** recent\n"
    original = b"# Journal\n### Updates\n" + old + recent
    inventory = extract_markdown_inventory(original, PARSER)
    plan = make_plan(original, list(inventory.candidates), 500)

    candidate = build_digest_candidate(
        plan,
        "- Décision ancienne.\n- Risque résolu.".encode(),
        inventory.mode,
        300,
        500,
    )
    second = extract_markdown_inventory(candidate, PARSER)

    assert second.mode == "dated"
    assert len(second.candidates) == 1
    assert second.candidates[0].kind == "list"
    assert [unit.source for unit in second.protected_context] == [recent]

    second_plan = make_plan(candidate, list(second.candidates), 500)
    replacement = build_digest_candidate(
        second_plan, b"- Digest remplace.", second.mode, 300, 500
    )
    assert b"D\xc3\xa9cision ancienne" not in replacement
    assert replacement.count(b"Historique compact") == 1
    assert recent in replacement


def test_digest_container_budget_is_exact_and_never_truncated():
    old = b"- **2026-08-01** ancien\n"
    recent = b"- **2026-08-02** recent\n"
    inventory = extract_markdown_inventory(old + recent, PARSER)
    plan = make_plan(old + recent, list(inventory.candidates), 500)
    digest = b"mot " * 20
    container = render_digest_container(plan, digest, inventory.mode)

    with pytest.raises(ValueError, match="container exceeds"):
        build_digest_candidate(plan, digest, inventory.mode, len(container) - 1, 500)


@pytest.mark.parametrize(
    "source", [b"### 2026-08-01\nancien\n", b"- **2026-08-01** ancien\n"]
)
def test_reduce_budget_uses_exact_minimal_wrapper(source):
    recent = b"- **2026-08-02** recent\n" if source.startswith(b"-") else b""
    inventory = extract_markdown_inventory(source + recent, PARSER)
    plan = make_plan(source + recent, list(inventory.candidates), 500)
    allowance = 160
    budget = digest_output_budget(plan, inventory.mode, allowance)
    digest = b"x" * budget

    assert len(render_digest_container(plan, digest, inventory.mode)) == allowance
    validate_digest(digest.decode(), source + recent, recent, budget, PARSER)
    with pytest.raises(ValueError, match="byte budget"):
        validate_digest("x" * (budget + 1), source + recent, recent, budget, PARSER)


def test_reduce_budget_counts_utf8_bytes_and_final_multiline_indentation():
    old = b"- **2026-08-01** ancien historique " + b"x" * 300 + b"\n"
    recent = b"- **2026-08-02** recent\n"
    inventory = extract_markdown_inventory(old + recent, PARSER)
    plan = make_plan(old + recent, list(inventory.candidates), 500)
    allowance = 100
    budget = digest_output_budget(plan, inventory.mode, allowance)
    multibyte = "é" * (budget // 2)
    digest = validate_digest(multibyte, old + recent, recent, budget, PARSER)

    assert len(digest) <= budget
    multiline = b"\n".join(b"x" for _ in range((budget + 1) // 2))
    assert len(multiline) <= budget
    with pytest.raises(ValueError, match="container exceeds"):
        build_digest_candidate(plan, multiline, inventory.mode, allowance, 500)


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
    digest_prompt = reduce_prompt(inventory, cards, 100)

    assert "jalon utile" in source_prompt and "etat recent intact" in source_prompt
    assert "selectable | U0001 | date=2026-08-01" in digest_prompt
    assert "protected | P0001 | date=2026-08-02" in digest_prompt
    assert "bytes=" in digest_prompt and "décision durable" in digest_prompt
    assert (
        "jalon utile" not in digest_prompt and "etat recent intact" not in digest_prompt
    )
