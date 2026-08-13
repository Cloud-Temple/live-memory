# LLM Consolidation Pipeline — Live Memory

> **Version**: 2.7.1 | **Date**: 2026-08-13 | **Author**: Cloud Temple

---

## 1. Overview

Consolidation is the **intelligent core** of live-mem. It is the process by which the MCP uses an LLM to integrate live notes into structured bank files, then cleans the live stream.

**Major change in v0.6.0**: shift from a **full rewrite** mode to a **surgical editing** mode. The LLM now produces **per-section Markdown edit operations** instead of rewriting entire files. What is not explicitly touched remains intact byte-for-byte.

### Why This Change?

The former mode asked the LLM to reproduce each modified file in its entirety. However, an LLM never "copies" faithfully — it synthesizes, summarizes, rephrases. With each consolidation, content was lost (details removed, history shortened). This is the "photocopy of a photocopy" syndrome.

The new mode solves this: the LLM only touches what needs to change. The rest is mechanically preserved.

```
OLD MODE (v0.1-v0.5)                 NEW MODE (v0.6+)
─────────────────────                 ─────────────────────
LLM reads the file                    LLM reads the file
LLM rewrites the ENTIRE file          LLM decides on EDITS
→ Progressive content loss             → Zero content loss
→ High output tokens                   → Reduced output tokens
→ No auditability                      → Traceable operations
```

```
BEFORE                                    AFTER
─────                                     ─────
live/                                     live/
├── note_001.md (agent-A, observation)    ├── note_010.md (agent-B, todo)
├── note_002.md (agent-A, decision)       └── note_011.md (agent-B, insight)
├── note_003.md (agent-A, todo)               ↑ Agent-B notes untouched
├── ... (42 agent-A notes)
├── note_010.md (agent-B, todo)           bank/
└── note_011.md (agent-B, insight)        ├── projectbrief.md    (unchanged ✓)
                                          ├── activeContext.md   (2 sections edited)
bank/                                     ├── progress.md        (1 section appended)
├── projectbrief.md (existing)            ├── systemPatterns.md  (unchanged ✓)
├── activeContext.md (existing)           ├── techContext.md      (unchanged ✓)
├── progress.md (existing)                └── productContext.md  (unchanged ✓)
├── systemPatterns.md (existing)
├── techContext.md (existing)             _synthesis.md          (overwritten)
└── productContext.md (existing)

_synthesis.md (previous)
```

**Core principles**:
- Agents NEVER write to the bank. Only the LLM does, guided by the rules
- Each agent consolidates **their own notes** (`agent` parameter)
- Other agents' notes remain intact in the live stream
- The LLM produces **edit operations**, not complete files
- What is not touched remains **intact byte-for-byte**

---

## 2. The `agent` Parameter (v0.2.0+)

The `agent` parameter of `bank_consolidate` controls note filtering. Since issue #20, `bank_consolidate` enqueues a background job and returns immediately; notes are collected at job execution time, not at enqueue time. The caller contract is call once and return to the user; do not watch/poll unless an explicit status check is requested via `bank_consolidation_status`.

| Value | Behavior | Permission |
|-------|----------|------------|
| `agent=""` (empty) | Consolidates **ALL** notes | Manage/admin required |
| `agent="cline-dev"` (= caller) | Consolidates only this agent's notes | Write sufficient |
| `agent="other"` (≠ caller) | Consolidates another agent's notes | Manage/admin required |

Filtering is based on the filename: `{ts}_{agent}_{cat}_{uuid}.md` — the system looks for `_{agent}_` in the filename.

Queued and running jobs use an in-memory FIFO per `space_id` under the existing
per-space lock. Since v2.7.1, every terminal payload is persisted before its
terminal status becomes observable and before the lane is released. Completed
results therefore remain auditable after restart; jobs interrupted while
queued/running remain best-effort.

---

## 3. Detailed Pipeline

### Step 1 — Collect Inputs

```python
async def _collect_inputs(self, space_id: str, agent: str = "") -> dict:
    # 1a. Read rules (immutable)
    rules = await storage.get("{space_id}/_rules.md")

    # 1b. Read previous synthesis (cumulative context)
    synthesis = await storage.get("{space_id}/_synthesis.md")

    # 1c. Read live notes
    notes_raw = await storage.list_and_get("{space_id}/live/")
    notes_raw.sort(key=lambda n: n["key"])  # Chronological sort

    # 1d. Filter by agent if specified
    if agent:
        notes_raw = [n for n in notes_raw if f"_{agent}_" in n["key"].split("/")[-1]]

    # 1e. Limit to max_notes (oldest first)
    if len(notes_raw) > self._max_notes:
        notes_raw = notes_raw[:self._max_notes]

    # 1f. Keep keys for later deletion
    notes_keys = [n["key"] for n in notes_raw]

    # 1g. Read ALL current bank files
    bank_files = await storage.list_and_get("{space_id}/bank/")
```

### Step 2 — Build the LLM Prompt (surgical editing)

The prompt requests **per-section Markdown edit operations**, not rewrites.

**Estimated token budget**:

| Component | Estimated Tokens |
|---|---|
| System prompt | ~800 |
| Rules | ~500-2000 |
| Previous synthesis | ~500-1500 |
| Live notes (42 notes × ~200 tokens) | ~8400 |
| Existing bank files (6 × ~1000 tokens) | ~6000 |
| **Total input** | **~18K tokens** |
| Response (edit operations, not complete files) | **~5-15K tokens** (instead of ~30-50K) |

### Step 3 — LLM Call

A **single LLM call** for the entire consolidation.

```python
response = await self._client.chat.completions.create(
    model=self._model,           # qwen3.5:27b
    messages=messages,
    max_tokens=self._max_tokens, # 100000
    temperature=self._temperature, # 0.3
)
```

### Step 4 — Robust JSON Extraction

Same as v0.5: handles `<think>`, ` ```json ` blocks, raw JSON.

### Step 5 — Apply Edit Operations

**This is the v0.6 innovation.** Instead of overwriting files, operations are applied surgically.

```python
for file_edit in llm_output["file_edits"]:
    if file_edit["action"] == "edit":
        # Read existing file
        existing_content = bank_index[file_edit["filename"]]
        updated_content = existing_content

        # Apply each operation sequentially
        for op in file_edit["operations"]:
            updated_content = _apply_operation(updated_content, op)

        # Write only if content changed
        if updated_content != existing_content:
            await storage.put(f"{space_id}/bank/{filename}", updated_content)

    elif file_edit["action"] == "create":
        # New file → full write
        await storage.put(f"{space_id}/bank/{filename}", file_edit["content"])

    elif file_edit["action"] == "rewrite":
        # Full rewrite (justified) → complete write
        await storage.put(f"{space_id}/bank/{filename}", file_edit["content"])
```

### Step 6 — Write Results

```python
# 6a. Bank files already written in step 5

# 6b. Write residual synthesis (with enriched front-matter)
synthesis_md = f"""---
consolidated_at: "{now}"
notes_processed: {notes_count}
mode: surgical_edit
operations_applied: {operations_applied}
operations_failed: {operations_failed}
---

{synthesis_content}"""
await storage.put(f"{space_id}/_synthesis.md", synthesis_md)

# 6c. Compute every fallible metric before the commit

# 6d. Delete processed live notes (LAST operation in the batch)
await storage.delete_many(notes_keys)

# 6e. After all batches, update _meta.json once
meta["last_consolidation"] = now
meta["consolidation_count"] += 1
meta["total_notes_processed"] += total_notes
```

### v2.7.1 failure contract

The whole LLM response is preflighted before the first write: the synthesis
must be a string, every filename/action is valid and unique, `create` cannot
overwrite, `rewrite` cannot create, and every surgical edit must apply in
memory. Bank and synthesis snapshots (plus metadata outside normal batched
mode) are restored and verified as one unit on any pre-commit failure.

`delete_many` is the batch commit point. A partial deletion triggers source
restoration from the collected notes and final-state verification. Missing
sources are exposed as `notes_unrestored`/`notes_lost`, never as processed
notes. No later fallible batch operation can trigger output rollback after a
complete deletion. Final meta and audit-read I/O runs after committed batches,
but its failure never rolls them back: it returns `partial` with their metrics.

---

## 3bis. Batch Consolidation (v0.8.0)

Starting from v0.8.0, notes are processed in **batches** instead of being sent all at once to the LLM.

### Motivation

The `qwen3.5:27b` LLM inserts **invisible Unicode characters** (ZWSP, BOM, Soft Hyphen) in filenames starting from roughly the 8th file in long JSON responses. These characters make bank files unreadable via `bank_read`. Batch consolidation produces shorter JSON responses, eliminating this problem.

### Configuration

```
CONSOLIDATION_BATCH_SIZE=5   # Notes per batch (default 5)
CONSOLIDATION_MAX_NOTES=200  # Global limit per consolidation
```

### Algorithm

```
consolidate(space_id, agent):
    1. Collect all notes + rules + bank + synthesis
    2. Split notes into batches of BATCH_SIZE
    3. For each batch (batch_idx = 1..N):
       a. If batch_idx > 1: re-read the up-to-date bank from S3
       b. Build prompt (rules + synthesis + batch notes + current bank)
       c. Call LLM → file_edits + synthesis
       d. _write_results(skip_meta=True):
          - Apply file_edits (sanitize filenames)
          - Write synthesis
          - Delete batch notes
       e. If LLM or write error → STOP (previous batches OK)
    4. Update _meta.json once (consolidation_count +1)
```

### Key Properties

- **Incrementality**: each batch sees the bank modified by previous batches
- **Resilience**: if batch 4/6 fails, batches 1-3 are already integrated
- **Single meta update**: `consolidation_count` incremented by 1 (not N), `total_notes_processed` accumulated
- **Sanitization**: `_sanitize_filename()` applied on each filename before S3 write

### Enriched Metrics (background job result)

These fields are available in the completed job result when an explicit status check is requested. They are not a reason to poll automatically after `bank_consolidate`.

```json
{
  "batches_total": 6,
  "batches_completed": 6,
  "batch_size": 5,
  "notes_processed": 30,
  "llm_tokens_used": 24000
}
```

### Unicode Protection (`_sanitize_filename`)

Removes 20 types of invisible Unicode characters and normalizes 10 types of Unicode dashes to the standard ASCII hyphen (U+002D). See `consolidator.py` for the full list.

---

## 3ter. Safe Bank Compaction (v2.7.0)

Compaction uses the LLM for semantic reduction, but never asks it to reproduce
the full Markdown file. For each oversized logical file, the model must return
exactly one JSON `file_edit` with an `edit` action and only
`replace_section`/`delete_section` operations. Space rules guide what must be
preserved; bank content is explicitly treated as untrusted data and cannot
alter this response contract.

The compaction response has a stricter parser than normal consolidation:

- `finish_reason` must be `stop`; a `length` response gets one bounded retry
  with a larger available output budget, then remains rejected if incomplete;
- JSON must parse as returned, with no extraction or repair;
- every heading must match exactly once and the principal H1 cannot change;
- the result must be smaller than the input and at least 5% of its original
  UTF-8 byte size. 75% of `BANK_FILE_MAX_SIZE` is an optimization target,
  exposed as `target_met`, never a success condition;
- every valid target is planned before the first storage mutation. Invalid
  plans keep their originals while valid plans are still applied.

When at least one plan passes, the server creates a standard full-space backup.
Each valid logical result is split losslessly on line boundaries into physical objects
below the byte limit. Every object contains a machine-readable
`live-mem-split` marker, including a one-part family. Writes are read back and
verified; a failure triggers an attempt to restore the original family from
the backup. A multi-file failure restores and exactly verifies only `bank/`,
so live notes created concurrently after the backup survive. If that rollback
also fails, the result explicitly reports the restorable backup id for manual
recovery. Reports include logical sizes, reduction, operation reasons, SHA-256
hashes, model finish reason, part count, and backup id.

Applied manual compaction is a `compact` job in the same per-space FIFO as
consolidation. Automatic compaction runs inside the consolidation job before
new notes are applied. Both paths therefore share serialization and status
observability.

Automatic compaction failure does not by itself fail consolidation: a rejected
plan performs no mutation, and note integration continues against the coherent
original/partially compacted bank. An inconsistent split family or a failed
write rollback remains blocking because bank coherence is no longer proven.

---

## 4. Edit Operation Types

### 4.1 `replace_section`

Replaces the content of a section identified by its Markdown heading. The heading itself is preserved.

```json
{
  "type": "replace_section",
  "heading": "## Current Focus",
  "content": "New section content..."
}
```

**Behavior**: Everything between the heading `## Current Focus` and the next heading of the same level or higher is replaced by `content`.

**Use case**: Update the current focus in `activeContext.md`, replace a problem's status.

### 4.2 `append_to_section`

Adds content **at the end** of an existing section. Existing content is fully preserved.

```json
{
  "type": "append_to_section",
  "heading": "## Version History",
  "content": "- **v0.6.0** (03/10): Surgical consolidation."
}
```

**Behavior**: New content is added after the existing section content, before the next heading.

**Use case**: Add an entry to history, enrich a section with new information.

### 4.3 `prepend_to_section`

Adds content **at the beginning** of a section (after the heading). Existing content is fully preserved.

```json
{
  "type": "prepend_to_section",
  "heading": "## Recent Work",
  "content": "- Important new development"
}
```

### 4.4 `add_section`

Creates a new section in the file. At the end by default, or after a specific section.

```json
{
  "type": "add_section",
  "heading": "## New Section",
  "content": "New section content",
  "after": "## Existing Section"
}
```

**Note**: If the heading has no `#`, it is automatically completed to `## heading`.

### 4.5 `delete_section`

Deletes an entire section (heading + content).

```json
{
  "type": "delete_section",
  "heading": "## Obsolete Section"
}
```

---

## 5. Markdown Editing Engine

### 5.1 Parsing into Sections

The `_parse_sections()` engine splits a Markdown file into sections:

```python
[
    {"heading": "",                    "level": 0, "content": "preamble..."},
    {"heading": "# Title",            "level": 1, "content": "\n..."},
    {"heading": "## Current Focus",   "level": 2, "content": "\nContent..."},
    {"heading": "## Recent Work",     "level": 2, "content": "\n- Item 1\n..."},
]
```

Each section contains:
- `heading`: the complete heading line (`## Title`)
- `heading_text`: the text without the `#` marks (`Title`)
- `level`: the level (number of `#`, 0 for preamble)
- `content`: all text between this heading and the next

### 5.2 Flexible Search

`_find_section_index()` searches for a section with 3 levels of flexibility:

1. **Exact match**: `"## Current Focus"` → direct match
2. **Without `#`**: `"Current Focus"` → finds `"## Current Focus"`
3. **Case-insensitive**: `"current focus"` → finds `"## Current Focus"`

This flexibility is crucial because the LLM may vary how it references headings.

### 5.3 Reconstruction

`_reconstruct_from_sections()` recomposes the file from modified sections. Idempotency guarantee: `reconstruct(parse(content))` preserves all non-empty lines.

### 5.4 Tests

77 unit tests cover the engine:
- Parsing, searching, reconstruction
- Idempotency (parse → reconstruct = identity)
- All operations (replace, append, prepend, add, delete)
- Chained operations
- Edge cases (empty file, no headings, sub-levels, special characters)
- Realistic end-to-end scenario
- Legacy format backward compatibility

```bash
python scripts/test_markdown_engine.py
# ✅ ALL TESTS PASS: 77/77
```

---

## 6. Prompts

### 6.1 System Prompt

```
You are an assistant specialized in Memory Bank maintenance for projects.

Your mission: integrate work notes into structured Markdown files
via SURGICAL EDITS.

## Core principle: EDIT, DON'T REWRITE

⚠️ You must NEVER return the full content of a file unless:
- It's a new file to create (action "create")
- The file requires a major restructuring (action "rewrite")

For existing files, you produce edit operations per Markdown SECTION.
Anything you don't explicitly touch remains INTACT — that's the point.

## Available operation types:
1. replace_section — Replace a section's content
2. append_to_section — Add content at the END of a section
3. prepend_to_section — Add content at the START of a section
4. add_section — Create a new section
5. delete_section — Remove a section

## Rules:
- Prefer append_to_section and replace_section
- For progress.md: ALWAYS append, NEVER delete history
- Headings must match EXACTLY those in the file
- If a file doesn't need modification, DON'T INCLUDE IT
```

### 6.2 Expected Response Format

```json
{
  "file_edits": [
    {
      "filename": "activeContext.md",
      "action": "edit",
      "operations": [
        {
          "type": "replace_section",
          "heading": "## Current Focus",
          "content": "New section content..."
        },
        {
          "type": "append_to_section",
          "heading": "## Recent Work",
          "content": "- New item added"
        }
      ]
    },
    {
      "filename": "new_file.md",
      "action": "create",
      "content": "# Title\n\nFull content of the new file..."
    },
    {
      "filename": "restructured_file.md",
      "action": "rewrite",
      "content": "# Title\n\nFull rewritten content...",
      "reason": "Major restructuring needed because..."
    }
  ],
  "synthesis": "Concise summary of processed notes..."
}
```

### 6.3 Per-file Actions

| Action | Usage | Content Returned | When? |
|--------|-------|------------------|-------|
| `edit` | Existing file | Edit operations | 95% of cases |
| `create` | New file | Full content | First consolidation |
| `rewrite` | Restructuring | Full content + reason | Exceptional |

---

## 7. Backward Compatibility

If the LLM returns the old format (`bank_files` instead of `file_edits`), a `_convert_legacy_format()` function automatically converts:

- `"action": "updated"` → `"action": "rewrite"` (fallback)
- `"action": "created"` → `"action": "create"`

This safety net ensures the transition is transparent.

---

## 8. Error Handling

### 8.1 Non-JSON LLM Response

Same as v0.5: retry with explicit reminder.

### 8.2 Section Not Found

If an operation references a heading that doesn't exist in the file:
- The operation fails with a `ValueError`
- The error is logged but doesn't stop the consolidation
- Other operations are applied normally
- The `operations_failed` counter is incremented

### 8.3 LLM Timeout / Partial Write

Same as v0.5: logical atomicity, notes deleted last.

### 8.4 Automatic Truncated JSON Repair (v1.7.4)

**Problem**: qwen3.x sometimes generates JSON with an unterminated string (`Unterminated string`). The model thinks it has finished (`finish_reason=stop`) but the JSON is structurally invalid. The gap between `completion_tokens` (includes thinking tokens) and `visible_tokens_est` (~raw_len/4) confirms this is not a budget truncation but a generation bug.

**Mechanism**: before the expensive retry (2nd full LLM call, ~100s + ~50K tokens), `_call_llm()` attempts automatic repair via `_repair_json()`:

1. **Detection**: only the `Unterminated string` error is handled (other JSON errors go to the classic retry)
2. **Truncation**: `json_str[:exc.pos]` keeps all valid JSON before the unclosed `"` opening
3. **Placeholder**: `""` is added as a replacement value
4. **Closure**: `_close_json_structure()` traverses the partial JSON with a stack-based automaton, tracks strings/escapes, and closes missing `}` and `]`
5. **Cleanup**: the last operation (the one with `content=""`) is removed to avoid a `replace_section` with empty content that would erase a section
6. **Default synthesis**: if missing from the truncated JSON, a placeholder value is added

**Safeguard**: if repair produces 0 `file_edits` (very early truncation, no complete operation), the code falls back to the LLM retry instead of accepting an empty result (prevents silent note deletion without bank writes).

**Decision**: repair OR retry, never both. If repair succeeds with ≥1 file_edit, the repaired result is used (last truncated operation lost, all others preserved). If repair fails or produces 0 edits, classic retry.

```
Attempt 1 → Invalid JSON
  ├── _repair_json() → ≥1 file_edits → USE (saves ~100s)
  ├── _repair_json() → 0 file_edits → RETRY (too early truncation)
  └── _repair_json() → None        → RETRY (non-Unterminated error)
Attempt 2 → classic retry (messages + explicit reminder)
```

**Tests**: 29 unit tests in `tests/test_json_repair.py` — `_close_json_structure` (10 tests: nesting, strings, escapes, backslash) + `_repair_json` (19 tests: exact counting, truncation in content/heading/filename, truncated create, realistic qwen3.6 scenario).

---

## 9. LLMaaS Configuration

```env
LLMAAS_API_URL=https://api.ai.cloud-temple.com/v1
LLMAAS_API_KEY=your_key
LLMAAS_MODEL=qwen3.5:27b
LLMAAS_MAX_TOKENS=100000
LLMAAS_TEMPERATURE=0.3
CONSOLIDATION_TIMEOUT=600
CONSOLIDATION_MAX_NOTES=200
```

---

## 10. Metrics

Each consolidation returns enriched metrics:

```json
{
  "status": "ok",
  "space_id": "project-alpha",
  "notes_processed": 42,
  "bank_files_updated": 2,
  "bank_files_created": 0,
  "bank_files_unchanged": 4,
  "operations_applied": 5,
  "operations_failed": 0,
  "synthesis_size": 850,
  "llm_tokens_used": 25000,
  "llm_prompt_tokens": 17000,
  "llm_completion_tokens": 8000,
  "duration_seconds": 20.2
}
```

**Expected gains**:
- `llm_completion_tokens`: reduced by ~50-70% (operations vs. complete files)
- Zero content loss in untouched files
- `operations_applied/failed`: auditability of modifications

---

## 11. Scenarios

### Scenario 1: First Consolidation (fresh space)

```
Input: 15 agent-A notes, 0 bank files, no synthesis
→ LLM uses "create" action for the 6 bank files
→ 15 agent-A notes deleted
→ Duration: ~20s
```

### Scenario 2: Typical Consolidation (surgical editing)

```
Input: 5 agent-A notes, 6 existing bank files
→ LLM produces 3 file_edits with "edit" action:
   - activeContext.md: replace_section "## Focus" + append "## Recent Work"
   - progress.md: append "## History"
   - systemPatterns.md: append "## Decisions"
→ 3 files updated, 3 unchanged (projectbrief, productContext, techContext)
→ 5 agent-A notes deleted
→ Duration: ~15s (fewer output tokens)
```

### Scenario 3: Consolidation with Operation Error

```
Input: 3 notes, 6 bank files
→ LLM produces 2 edits, 1 with section not found
→ Failed operation is logged, others applied
→ Metrics: operations_applied=3, operations_failed=1
```

---

*Document updated August 13, 2026 — Live Memory v2.7.1*
