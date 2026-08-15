"""Markdown inventory and hierarchical digest assembly for bank compaction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from markdown_it import MarkdownIt


ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
FR_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
ANY_UNIT_ID_RE = re.compile(r"\b[UP]\d{4}\b")
PROTECTED_TOKENS = {"fence", "code_block", "html_block", "html_inline"}
DIGEST_FORBIDDEN_TOKENS = PROTECTED_TOKENS | {
    "heading_open",
    "blockquote_open",
    "hr",
    "link_open",
    "image",
    "table_open",
}
ISSUE_REF_RE = re.compile(r"(?<!\w)#\d+\b")
VERSION_REF_RE = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")
ISO_REF_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
FR_REF_RE = re.compile(r"\b\d{1,2}/\d{1,2}/20\d{2}\b")
LINK_DEFINITION_RE = re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:")
MAP_BATCH_MAX_BYTES = 40_000
MAP_BATCH_MAX_UNITS = 32
MAP_CARD_MAX_BYTES = 240
MAP_OUTPUT_MAX_TOKENS = 4000


@dataclass(frozen=True)
class MarkdownUnit:
    unit_id: str
    start_byte: int
    end_byte: int
    source: bytes
    entry_date: date
    kind: str

    @property
    def size(self) -> int:
        return len(self.source)


@dataclass(frozen=True)
class SelectionPlan:
    original: bytes
    units: tuple[MarkdownUnit, ...]
    available_bytes: int


@dataclass(frozen=True)
class UnitInventory:
    mode: str
    candidates: tuple[MarkdownUnit, ...]
    protected_context: tuple[MarkdownUnit, ...]


def _line_byte_offsets(content: str) -> list[int]:
    offsets = [0]
    for line in content.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    return offsets


def _entry_date(label: str) -> date | None:
    try:
        match = ISO_DATE_RE.search(label)
        if match:
            return date(*(int(value) for value in match.groups()))
        match = FR_DATE_RE.search(label)
        if match:
            day, month, year = (int(value) for value in match.groups())
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _token_tree(tokens):
    for token in tokens:
        yield token
        if token.children:
            yield from _token_tree(token.children)


def extract_markdown_inventory(original: bytes, parser: MarkdownIt) -> UnitInventory:
    """Discover exact compressible units from Markdown content, never its filename."""
    content = original.decode("utf-8", errors="strict")
    tokens = parser.parse(content)
    lines = content.splitlines(keepends=True)
    offsets = _line_byte_offsets(content)
    boundaries = [
        token
        for token in tokens
        if token.type == "heading_open"
        and token.tag in {"h1", "h2", "h3"}
        and token.map is not None
    ]
    h3_raw: list[tuple[int, int, str, str]] = []
    list_raw: list[tuple[int, int, str, str]] = []
    h3_spans: list[tuple[int, int]] = []

    for token in boundaries:
        if token.tag != "h3":
            continue
        start_line = token.map[0]
        end_line = next(
            (item.map[0] for item in boundaries if item.map[0] > start_line),
            len(offsets) - 1,
        )
        start, end = offsets[start_line], offsets[end_line]
        h3_raw.append((start, end, lines[start_line], "h3"))
        h3_spans.append((start, end))

    for token in tokens:
        if token.type != "list_item_open" or token.level != 1 or token.map is None:
            continue
        start, end = offsets[token.map[0]], offsets[token.map[1]]
        list_raw.append((start, end, lines[token.map[0]], "list"))

    def discover(raw_units: list[tuple[int, int, str, str]]):
        result: list[tuple[int, int, str, date | None, bool]] = []
        for start, end, label, kind in sorted(raw_units):
            source = original[start:end]
            parsed = parser.parse(source.decode("utf-8", errors="strict"))
            protected = any(
                token.type in PROTECTED_TOKENS for token in _token_tree(parsed)
            )
            result.append((start, end, kind, _entry_date(label), protected))
        return result

    h3_units = discover(h3_raw)
    list_units = discover(list_raw)
    outside_h3 = [
        item
        for item in list_units
        if not any(
            item[0] < h3_end and item[1] > h3_start for h3_start, h3_end in h3_spans
        )
    ]
    dated_h3 = [item for item in h3_units if item[3] is not None]
    dated_items = [item for item in list_units if item[3] is not None]
    # One incidental date in an otherwise thematic document must not turn the
    # whole file into a journal. Two dated structural entries establish the
    # dated mode without relying on a filename or rules convention.
    if len(dated_h3) >= 2:
        mode = "dated"
        discovered = sorted([*h3_units, *outside_h3])
    elif len(dated_items) >= 2:
        mode = "dated"
        discovered = list_units
    else:
        mode = "sections"
        discovered = h3_units + outside_h3
    if mode == "sections" and not h3_units:
        raise ValueError("no dated entry or complete H3 section")
    dated = [item for item in discovered if item[3] is not None]
    recent_date = max(item[3] for item in dated) if dated else None
    candidate_spans: list[tuple[int, int, str, date]] = []
    protected_spans: list[tuple[int, int, str, date]] = []
    for start, end, kind, entry_date, protected in discovered:
        selectable = (
            entry_date is not None and entry_date != recent_date and not protected
            if mode == "dated"
            else kind == "h3" and not protected
        )
        target = candidate_spans if selectable else protected_spans
        target.append((start, end, kind, entry_date or date.min))

    candidates = tuple(
        MarkdownUnit(f"U{index:04d}", start, end, original[start:end], entry_date, kind)
        for index, (start, end, kind, entry_date) in enumerate(candidate_spans, 1)
    )
    protected_context = tuple(
        MarkdownUnit(f"P{index:04d}", start, end, original[start:end], entry_date, kind)
        for index, (start, end, kind, entry_date) in enumerate(protected_spans, 1)
    )
    _validate_non_overlapping(list(candidates) + list(protected_context))
    return UnitInventory(mode, candidates, protected_context)


def _validate_non_overlapping(units: list[MarkdownUnit]) -> None:
    ordered = sorted(units, key=lambda item: item.start_byte)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end_byte > current.start_byte:
            raise ValueError("eligible Markdown units overlap")


def delete_units(original: bytes, units: list[MarkdownUnit]) -> bytes:
    candidate = original
    previous_start = len(original) + 1
    for unit in sorted(units, key=lambda item: item.start_byte, reverse=True):
        if unit.end_byte > previous_start:
            raise ValueError("Markdown units overlap")
        if original[unit.start_byte : unit.end_byte] != unit.source:
            raise ValueError("unit offsets do not match the original bytes")
        candidate = candidate[: unit.start_byte] + candidate[unit.end_byte :]
        previous_start = unit.start_byte
    return candidate


def make_plan(original: bytes, units: list[MarkdownUnit], limit: int) -> SelectionPlan:
    if not units:
        raise ValueError("no eligible Markdown unit")
    base = delete_units(original, units)
    available = limit - len(base)
    if available <= 0:
        raise ValueError("protected content already exceeds the configured limit")
    return SelectionPlan(original, tuple(units), available)


def build_map_batches(
    units: list[MarkdownUnit],
) -> tuple[tuple[MarkdownUnit, ...], ...]:
    """Pack complete source units into small, deterministic Map requests."""
    batches: list[tuple[MarkdownUnit, ...]] = []
    current: list[MarkdownUnit] = []
    current_bytes = 0
    for unit in sorted(units, key=lambda item: item.start_byte):
        if unit.size > MAP_BATCH_MAX_BYTES:
            raise ValueError(
                f"Markdown unit {unit.unit_id} exceeds the Map batch byte limit"
            )
        if current and (
            len(current) >= MAP_BATCH_MAX_UNITS
            or current_bytes + unit.size > MAP_BATCH_MAX_BYTES
        ):
            batches.append(tuple(current))
            current = []
            current_bytes = 0
        current.append(unit)
        current_bytes += unit.size
    if current:
        batches.append(tuple(current))
    if not batches:
        raise ValueError("no Markdown unit to map")
    return tuple(batches)


def _bounded_text(value: str, max_bytes: int = MAP_CARD_MAX_BYTES) -> str:
    normalized = " ".join(value.split())
    raw = normalized.encode("utf-8")
    if len(raw) <= max_bytes:
        return normalized
    return raw[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _fallback_card(unit: MarkdownUnit) -> str:
    content = unit.source.decode("utf-8", errors="strict")
    first_line = next(
        (line.strip() for line in content.splitlines() if line.strip()), ""
    )
    return _bounded_text(first_line)


def parse_map_cards(
    output: str, known: list[MarkdownUnit]
) -> tuple[dict[str, str], int, int]:
    """Parse bounded ephemeral cards; omitted units get a source-owned label."""
    by_id = {unit.unit_id: unit for unit in known}
    cards: dict[str, str] = {}
    for line in output.splitlines():
        matches = ANY_UNIT_ID_RE.findall(line)
        if not matches or len(set(matches)) != 1:
            continue
        unit_id = matches[0]
        if unit_id not in by_id or unit_id in cards:
            continue
        text = ANY_UNIT_ID_RE.sub("", line).strip(" |:-\t")
        card = _bounded_text(text)
        if card:
            cards[unit_id] = card
    valid_cards = len(cards)
    for unit in known:
        cards.setdefault(unit.unit_id, _fallback_card(unit))
    return cards, valid_cards, len(known) - valid_cards


def _references(value: str) -> set[str]:
    return {
        match.group(0)
        for pattern in (ISSUE_REF_RE, VERSION_REF_RE, ISO_REF_RE, FR_REF_RE)
        for match in pattern.finditer(value)
    }


def _validate_digest_markdown(
    value: str, parser: MarkdownIt, preserved_context: str
) -> None:
    if not value.strip():
        raise ValueError("Qwen returned an empty digest")
    if LINK_DEFINITION_RE.search(value):
        raise ValueError("digest contains a forbidden Markdown link definition")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, (dict, list)):
        raise ValueError("Qwen returned JSON instead of a Markdown digest")
    environment: dict = {}
    parser.parse(preserved_context, environment)
    references_before = set(environment.get("references", {}))
    duplicate_refs_before = len(environment.get("duplicate_refs", []))
    tokens = parser.parse(value, environment)
    references_after = set(environment.get("references", {}))
    duplicate_refs_after = len(environment.get("duplicate_refs", []))
    if (
        references_after != references_before
        or duplicate_refs_after != duplicate_refs_before
    ):
        raise ValueError("digest contains a forbidden Markdown link definition")
    if not tokens:
        raise ValueError("Qwen returned a digest without visible Markdown content")
    for token in _token_tree(tokens):
        if token.type in DIGEST_FORBIDDEN_TOKENS:
            raise ValueError(f"digest contains forbidden Markdown token: {token.type}")
        if token.type == "inline":
            try:
                inline_json = json.loads(token.content)
            except json.JSONDecodeError:
                inline_json = None
            if isinstance(inline_json, (dict, list)):
                raise ValueError("Qwen returned JSON instead of a Markdown digest")
    allowed_roots = {
        "paragraph_open",
        "paragraph_close",
        "bullet_list_open",
        "bullet_list_close",
        "ordered_list_open",
        "ordered_list_close",
    }
    for token in tokens:
        if token.level == 0 and token.type not in allowed_roots:
            raise ValueError(f"digest contains forbidden root token: {token.type}")


def validate_digest(
    output: str,
    source: bytes,
    preserved: bytes,
    max_bytes: int,
    parser: MarkdownIt,
) -> bytes:
    """Validate a complete generated digest without repair or truncation."""
    preserved_context = preserved.decode("utf-8", errors="strict")
    _validate_digest_markdown(output, parser, preserved_context)
    normalized = output.strip()
    _validate_digest_markdown(normalized, parser, preserved_context)
    if ANY_UNIT_ID_RE.search(normalized):
        raise ValueError("digest exposes an internal unit id")
    raw = normalized.encode("utf-8", errors="strict")
    if len(raw) > max_bytes:
        raise ValueError("digest exceeds its UTF-8 byte budget")
    source_text = source.decode("utf-8", errors="strict")
    invented = _references(normalized) - _references(source_text)
    if invented:
        raise ValueError(f"digest invents references: {sorted(invented)}")
    return raw


def digest_insertion_offset(plan: SelectionPlan) -> int:
    """Return the anchor offset after all selectable units are removed."""
    h3_units = [unit for unit in plan.units if unit.kind == "h3"]
    anchor = min(h3_units or list(plan.units), key=lambda item: item.start_byte)
    removed_before = sum(
        unit.size for unit in plan.units if unit.end_byte <= anchor.start_byte
    )
    return anchor.start_byte - removed_before


def render_digest_container(
    plan: SelectionPlan,
    digest: bytes,
    mode: str,
) -> bytes:
    """Render one naturally recompactable Markdown unit around a digest."""
    h3_units = [unit for unit in plan.units if unit.kind == "h3"]
    anchor = min(h3_units or list(plan.units), key=lambda item: item.start_byte)
    dated = mode == "dated"
    max_date = max(unit.entry_date for unit in plan.units).isoformat()
    indented = b"\n".join(b"    " + line for line in digest.split(b"\n"))
    if anchor.kind == "h3":
        date_prefix = f"{max_date} — " if dated else ""
        header = (
            f"### {date_prefix}Historique compacté\n\n"
            "- **Synthèse non exhaustive** :\n\n"
        ).encode("utf-8")
    else:
        header = (
            f"- **{max_date} — Historique compacté (synthèse non exhaustive)** :\n\n"
        ).encode("utf-8")
    return header + indented + b"\n\n"


def digest_output_budget(
    plan: SelectionPlan, mode: str, container_allowance: int
) -> int:
    """Reserve wrapper and worst-case four-byte indentation for every line."""
    empty_container = render_digest_container(plan, b"", mode)
    fixed_overhead = len(empty_container) - 4
    budget = (container_allowance - fixed_overhead) // 5
    if budget <= 0:
        raise ValueError("digest container has no usable UTF-8 output budget")
    return budget


def build_digest_candidate(
    plan: SelectionPlan,
    digest: bytes,
    mode: str,
    insertion_allowance: int,
    limit: int,
) -> bytes:
    """Replace every selectable unit with one bounded digest container."""
    base = delete_units(plan.original, list(plan.units))
    offset = digest_insertion_offset(plan)
    container = render_digest_container(plan, digest, mode)
    if len(container) > insertion_allowance:
        raise ValueError("digest container exceeds its UTF-8 byte budget")
    candidate = base[:offset] + container + base[offset:]
    if len(candidate) >= len(plan.original):
        raise ValueError("candidate does not reduce the original file")
    if len(candidate) > limit:
        raise ValueError("candidate exceeds the configured byte limit")
    return candidate


def map_prompt(units: tuple[MarkdownUnit, ...]) -> str:
    """Render exact, untrusted source units for one bounded Map call."""
    payload = "\n".join(
        f"<<<{unit.unit_id} date="
        f"{unit.entry_date.isoformat() if unit.entry_date != date.min else 'undated'} "
        f"bytes={unit.size}>>>\n"
        f"{unit.source.decode('utf-8', errors='strict')}\n<<<END {unit.unit_id}>>>"
        for unit in units
    )
    return f"Unités à caractériser :\n{payload}\n"


def reduce_prompt(
    inventory: UnitInventory,
    cards: dict[str, str],
    budget: int,
) -> str:
    """Render bounded Map cards and code-owned metadata for one Reduce call."""
    candidates = {unit.unit_id for unit in inventory.candidates}
    units = sorted(
        [*inventory.candidates, *inventory.protected_context],
        key=lambda item: item.start_byte,
    )
    rows = []
    for unit in units:
        role = "selectable" if unit.unit_id in candidates else "protected"
        entry_date = (
            unit.entry_date.isoformat() if unit.entry_date != date.min else "undated"
        )
        rows.append(
            f"{role} | {unit.unit_id} | date={entry_date} | "
            f"bytes={unit.size} | {cards[unit.unit_id]}"
        )
    return (
        f"Budget du digest Markdown : {budget} octets UTF-8.\n"
        "Fiches Map non fiables :\n" + "\n".join(rows) + "\n"
    )
