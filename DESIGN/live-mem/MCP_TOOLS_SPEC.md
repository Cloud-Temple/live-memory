# MCP Tools Specification — Live Memory

> **Version**: 2.7.0 | **Date**: 2026-08-12 | **Author**: Cloud Temple

---

## Overview

Live Memory exposes **43 MCP tools** in 7 categories:

| Category        | Tools | Description                                        |
| --------------- | ----- | -------------------------------------------------- |
| **System** (3)  | 3     | Service health & identity                          |
| **Space** (9)   | 9     | Memory space CRUD                                  |
| **Live** (3)    | 3     | Real-time notes                                    |
| **Bank** (11)   | 11    | LLM-consolidated Memory Bank                       |
| **Graph** (4)   | 4     | Bridge to Graph Memory (long-term memory)          |
| **Backup** (5)  | 5     | Backup & restore                                   |
| **Admin** (8)   | 8     | Token management + maintenance (GC)                |

---

## Conventions

### Standardized Return Format

Every tool returns a `dict` with a `status` field:

```python
{"status": "ok", "data": ...}           # Success
{"status": "error", "message": "..."}   # Error
{"status": "created", ...}              # Resource created
{"status": "deleted", ...}              # Resource deleted
{"status": "not_found", ...}            # Resource not found
{"status": "forbidden", ...}            # Access denied
{"status": "queued", ...}               # Accepted background consolidation job
```

### Permissions

| Symbol | Permission | Description                                       |
| ------ | ---------- | ------------------------------------------------- |
| 🔓     | Public     | No auth required                                  |
| 🔑     | Read       | Token with `read` permission + space access        |
| ✏️     | Write      | Token with `write` permission + space access       |
| 🔧     | Manage     | Token with `manage` permission + space access      |
| 👑     | Admin      | Token with `admin` permission                      |

---

## 1. System — Health & Identity

### `system_health` 🔓

Checks the service health status (S3, LLMaaS, space count).

```python
@mcp.tool()
async def system_health() -> dict:
```

**Response**:
```json
{
  "status": "ok",
  "service_name": "Live Memory",
  "version": "0.8.0",
  "uptime_seconds": 3600,
  "services": {
    "s3": {"status": "ok", "latency_ms": 45},
    "llmaas": {"status": "ok", "model": "qwen3.5:27b", "latency_ms": 120}
  },
  "spaces_count": 3
}
```

---

### `system_about` 🔓

Service information, version, available tools.

```python
@mcp.tool()
async def system_about() -> dict:
```

---

## 2. Space — Memory Space Management

### `space_create` ✏️

Creates a new memory space with its rules.

```python
@mcp.tool()
async def space_create(
    space_id: str,          # Unique identifier (alphanumeric + hyphens, max 64 chars)
    description: str,       # Short description
    rules: str,             # Markdown rules content (bank structure)
    owner: str = ""         # Owner (optional, informational)
) -> dict:
```

**Behavior**:
- Validates `space_id`: regex `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`
- Creates `{space_id}/_meta.json` on S3
- Creates `{space_id}/_rules.md` on S3 (immutable after creation)
- Creates `{space_id}/live/` and `{space_id}/bank/` directories (via a `.keep` sentinel file)
- Error if the space already exists (`status: "already_exists"`)

---

### `space_list` 🔑

Lists all spaces accessible by the current token.

```python
@mcp.tool()
async def space_list() -> dict:
```

---

### `space_info` 🔑

Detailed information about a space.

```python
@mcp.tool()
async def space_info(space_id: str) -> dict:
```

---

### `space_rules` 🔑

Reads the space rules (immutable).

```python
@mcp.tool()
async def space_rules(space_id: str) -> dict:
```

---

### `space_summary` 🔑

Complete space synthesis (rules + bank + live stats). Useful for an agent to load all context at once on startup.

```python
@mcp.tool()
async def space_summary(space_id: str) -> dict:
```

---

### `space_export` 🔑

Exports a complete space as a tar.gz archive (returns base64).

```python
@mcp.tool()
async def space_export(space_id: str) -> dict:
```

---

### `space_delete` 👑

Deletes a space and ALL its data (irreversible).

```python
@mcp.tool()
async def space_delete(
    space_id: str,
    confirm: bool = False    # Must be True to confirm
) -> dict:
```

---

## 3. Live — Real-time Notes

### `live_note` ✏️

Writes a note to the space. This is the primary tool used by agents during their work.

```python
@mcp.tool()
async def live_note(
    space_id: str,
    category: str,          # observation | decision | todo | insight | question | progress | issue
    content: str,           # Note content (free text)
    tags: str = ""          # Comma-separated tags (optional)
) -> dict:
```

> **v0.8.1**: The `agent` parameter was removed. The agent identity is always
> the authentication token's `client_name` (Token = Agent).

**Behavior**:
- Generates a unique filename: `{timestamp}_{agent}_{category}_{uuid8}.md`
- Creates the file with YAML front-matter + content
- No conflict possible (append-only, unique name)
- No lock needed
- The agent is always the token's `client_name` (Token = Agent, v0.8.1)

**Standard categories**:

| Category      | Usage                            | Examples                                |
| ------------- | -------------------------------- | --------------------------------------- |
| `observation` | Factual finding                  | "The build passes", "API returns 200"   |
| `decision`    | Technical/organizational choice  | "Going with S3 instead of SQLite"       |
| `todo`        | Task to do                       | "Implement the backup module"           |
| `insight`     | Analysis, discovered pattern     | "Pattern X is relevant here"            |
| `question`    | Open question                    | "Should we support CSV format?"         |
| `progress`    | Advancement                      | "Auth module: 80% complete"             |
| `issue`       | Problem, bug                     | "LLM timeout exceeds 60s"              |

---

### `live_read` 🔑

Reads recent live notes.

```python
@mcp.tool()
async def live_read(
    space_id: str,
    limit: int = 50,         # Max notes (default 50)
    category: str = "",      # Filter by category (optional)
    agent: str = "",         # Filter by agent (optional)
    since: str = ""          # ISO datetime: notes after this date (optional)
) -> dict:
```

---

### `live_search` 🔑

Text search in live notes (case-insensitive).

```python
@mcp.tool()
async def live_search(
    space_id: str,
    query: str,              # Text to search for
    limit: int = 20
) -> dict:
```

---

## 4. Bank — Consolidated Memory Bank

### `bank_read` 🔑

Reads a specific bank file.

```python
@mcp.tool()
async def bank_read(
    space_id: str,
    filename: str            # Filename (e.g.: "activeContext.md")
) -> dict:
```

---

### `bank_read_all` 🔑

Reads the entire memory bank in a single request. This is the tool an agent calls at startup to load all its memory context.

```python
@mcp.tool()
async def bank_read_all(space_id: str) -> dict:
```

---

### `bank_list` 🔑

Lists bank files (without their content).

```python
@mcp.tool()
async def bank_list(space_id: str) -> dict:
```

---

### `bank_consolidate` ✏️/👑

Enqueues LLM consolidation: returns immediately with a job acknowledgement. The background worker reads live notes, rules, and the current bank when the job actually runs, then uses the LLM to produce updated bank files.

Caller contract: call `bank_consolidate` once at session end, then return to the user. Do not wait for completion and do not watch/poll automatically unless the user explicitly asks for a status check.

```python
@mcp.tool()
async def bank_consolidate(
    space_id: str,
    agent: str = ""          # Filter by agent (see permissions below)
) -> dict:
```

**`agent` parameter** (added in v0.2.0, modified in v0.7.4):
- `agent=""` (empty) + **admin**: consolidates **ALL** notes
- `agent=""` (empty) + **write**: auto-detects caller → consolidates **own notes only**
- `agent="my-agent"` (= caller name): consolidates only this agent's notes → write permission sufficient
- `agent="other-agent"` (≠ caller): consolidates another agent's notes → manage permission required

**⚠️ Restrictions**:
- Only one consolidation mutates a space's bank at a time (global per-space lock)
- Same-space requests are serialized FIFO instead of rejected with `conflict`
- The PR 1 queue is in-memory only (`guarantee="in_memory_best_effort"`)
- The response explicitly sets `next_action="return_to_user_without_polling"`
- `polling.recommended=false`; `bank_consolidation_status` is manual-only for explicit status checks
- If no live notes exist, the background job result is `{"status": "ok", "notes_processed": 0, "message": "No new notes to consolidate"}`
- Configurable timeout (`CONSOLIDATION_TIMEOUT`, default 600s)

**Response**:

```json
{
  "status": "running",
  "job_id": "consol_...",
  "space_id": "my-project",
  "agent": "cline-dev",
  "requested_by": "cline-dev",
  "queue_position": 1,
  "guarantee": "in_memory_best_effort",
  "next_action": "return_to_user_without_polling",
  "polling": {
    "recommended": false,
    "mode": "manual_only",
    "status_tool": "bank_consolidation_status",
    "instruction": "Do not wait for completion or poll automatically. Store the job_id only if an explicit status check is needed."
  }
}
```

### `bank_consolidation_status` 🔑

Returns the in-memory status for a consolidation job.

```python
@mcp.tool()
async def bank_consolidation_status(job_id: str) -> dict:
```

Returns `queued`, `running`, `succeeded`, `failed`, or `not_found`. The caller must have read access to the job's `space_id`. This tool is for explicit manual status checks only; clients must not call it automatically after every `bank_consolidate`.

---

### `bank_consolidation_queues` 🔑

Read-only summary of the consolidation lanes (one per space). Use it to drive a multi-space dashboard without N+1 calls.

```python
@mcp.tool()
async def bank_consolidation_queues(space_ids: str = "") -> dict:
```

**Behavior**:

- If `space_ids` is empty → enumerates all spaces accessible to the caller (or all spaces if admin).
- Returns one lane per space with: `lane_state` (idle/queued/running/failed), `running_job`, `queued_count`, `latest_jobs`, `parallelism_model`, `service_config.batch_size`.
- Adds aggregated counters: `total_spaces`, `active_spaces`, `running_spaces`, `queued_jobs`, `failed_recent`.
- Denied spaces are surfaced under `denied_spaces`.

---

### `bank_stale_spaces` 🔑

Read-only supervision tool that identifies memory banks whose consolidation has fallen behind. Useful to detect inactive agents that left notes queued or sessions that forgot to consolidate.

```python
@mcp.tool()
async def bank_stale_spaces(
    min_notes: int = 5,
    min_age_days: int = 5,
    space_ids: str = "",
) -> dict:
```

**Definition**: a space is `stale` iff `live_notes_count >= min_notes` **AND** `oldest_note_age_days >= min_age_days` (both inclusive).

**Behavior**:

- Lightweight S3 listing (`list_objects` on `{space}/live/`) — no content fetched.
- Oldest note age derived from the timestamp prefix of the filename (`YYYYMMDDTHHMMSS_…`), not from S3 `LastModified` (deterministic, clock-independent).
- Returns `spaces` (filtered + sorted by notes_count DESC, age DESC), `scanned` (every inspected space with its is_stale flag), and `denied_spaces`.
- Displayed `oldest_note_age_days` is truncated to 2 decimals (never rounded up) so the UI never shows an age exceeding the real value at the threshold boundary.

**Payload sketch**:

```json
{
    "status": "ok",
    "spaces": [
        {
            "space_id": "...",
            "live_notes_count": 12,
            "oldest_note_age_days": 8.5,
            "oldest_note_timestamp": "2026-05-13T18:00:00+00:00",
            "oldest_note_filename": "20260513T180000_agent_observation_<hash>.md",
            "is_stale": true
        }
    ],
    "scanned": [...],
    "total_spaces": 25,
    "total_stale": 3,
    "min_notes": 5,
    "min_age_days": 5,
    "denied_spaces": []
}
```

Clients can then iterate and call `bank_consolidate(space_id=…)` per stale space; admin UIs typically expose a per-row button and a bulk "Consolidate all stale" action.

---

### `bank_compact` 🔧

Scans oversized logical bank files or enqueues strict semantic LLM compaction.
Requires `manage`; `dry_run` defaults to `true`.

```python
@mcp.tool()
async def bank_compact(
    space_id: str,
    dry_run: bool = True,
) -> dict:
```

Dry-run returns logical sizes in UTF-8 bytes and identifies files above
`BANK_FILE_MAX_SIZE` without invoking the LLM or writing. With
`dry_run=false`, the tool returns immediately with a `compact_*` job id in the
same per-space FIFO as consolidation. The job is visible through
`bank_consolidation_status` and `bank_consolidation_queues`.

The worker obtains a strict JSON section-edit plan from the LLM, validates the
complete result locally, creates a full-space backup, and persists a verified
split family when required. Invalid/truncated model output or any pre-write
validation failure preserves every original. The final result exposes logical
byte sizes, part counts, hashes, operation reasons, failures, and `backup_id`.
A persistence failure triggers a rollback attempt; if that also fails, the
reported backup id is the manual recovery point.

---

## 5. Graph — Bridge to Graph Memory

### `graph_connect` ✏️

Connects a Live Memory space to a Graph Memory instance. Tests the connection, creates the memory if needed.

```python
@mcp.tool()
async def graph_connect(
    space_id: str,
    url: str,                # Graph Memory URL (e.g.: "http://localhost:8080/mcp")
    token: str,              # Bearer token for Graph Memory
    memory_id: str,          # Target memory identifier
    ontology: str = "general"  # general | legal | cloud | managed-services | presales
) -> dict:
```

**Behavior**:
- Normalizes the URL (adds `/mcp` if missing)
- Tests the MCP Streamable HTTP connection
- Creates the memory in Graph Memory if it doesn't exist
- Saves config in `_meta.json` (`graph_memory` field)

---

### `graph_push` ✏️

Synchronizes the bank into Graph Memory. Deletes old documents and re-ingests up-to-date bank files.

```python
@mcp.tool()
async def graph_push(space_id: str) -> dict:
```

**Behavior**:
- The space must first be connected via `graph_connect`
- Intelligent delete + re-ingestion (graph recalculation)
- Orphan cleanup (files removed from the bank)
- ~10-30s per file (LLM entity/relation extraction + embeddings)
- Updates metrics in `_meta.json`

---

### `graph_status` 🔑

Checks the Graph Memory connection status and retrieves graph stats.

```python
@mcp.tool()
async def graph_status(space_id: str) -> dict:
```

---

### `graph_disconnect` ✏️

Disconnects a space from Graph Memory. Data already pushed remains in the graph.

```python
@mcp.tool()
async def graph_disconnect(space_id: str) -> dict:
```

---

## 6. Backup — Backup & Restore

### `backup_create` ✏️

Creates a complete snapshot of the space on S3.

```python
@mcp.tool()
async def backup_create(
    space_id: str,
    description: str = ""
) -> dict:
```

---

### `backup_list` 🔑

Lists available backups. If `space_id` is empty → lists all accessible backups.

```python
@mcp.tool()
async def backup_list(space_id: str = "") -> dict:
```

---

### `backup_restore` 👑

Restores a space from a backup. The space MUST NOT exist (delete it first).

```python
@mcp.tool()
async def backup_restore(
    backup_id: str,          # Format: "space_id/timestamp"
    confirm: bool = False
) -> dict:
```

---

### `backup_download` 🔑

Downloads a backup as a tar.gz archive (base64).

```python
@mcp.tool()
async def backup_download(backup_id: str) -> dict:
```

---

### `backup_delete` 👑

Deletes a backup.

```python
@mcp.tool()
async def backup_delete(
    backup_id: str,
    confirm: bool = False
) -> dict:
```

---

## 7. Admin — Token Management & Maintenance

### `admin_create_token` 👑

Creates a new authentication token.

```python
@mcp.tool()
async def admin_create_token(
    name: str,               # Descriptive name
    permissions: str,         # "read", "read,write", or "read,write,admin"
    space_ids: str = "",     # Authorized spaces (empty = all)
    expires_in_days: int = 0  # 0 = no expiration
) -> dict:
```

The token is hashed with SHA-256 before storage in `_system/tokens.json`.

---

### `admin_list_tokens` 👑

Lists metadata of all tokens (never the token itself in clear text).

```python
@mcp.tool()
async def admin_list_tokens() -> dict:
```

---

### `admin_revoke_token` 👑

Revokes a token (permanently disables it).

```python
@mcp.tool()
async def admin_revoke_token(token_hash: str) -> dict:
```

---

### `admin_update_token` 👑

Updates a token's permissions or authorized spaces.

```python
@mcp.tool()
async def admin_update_token(
    token_hash: str,
    space_ids: str = "",     # New spaces (empty = no change)
    permissions: str = ""    # New permissions (empty = no change)
) -> dict:
```

---

### `admin_gc_notes` 👑

Garbage Collector: identifies and processes orphaned notes (older than `max_age_days`).

```python
@mcp.tool()
async def admin_gc_notes(
    space_id: str = "",       # Target space (empty = all spaces)
    max_age_days: int = 7,    # Threshold in days
    confirm: bool = False,    # False = dry-run, True = execute
    delete_only: bool = False # If True + confirm: deletes WITHOUT consolidating
) -> dict:
```

**3 modes**:
1. `confirm=False` (default): **DRY-RUN** — scans and reports orphaned note count
2. `confirm=True`: **CONSOLIDATES** orphaned notes via LLM (with "⚠️ GC forced consolidation" notice)
3. `confirm=True, delete_only=True`: **DELETES** notes without consolidating (data loss)

---

## Complete Matrix — Tools × Permissions

| Tool                 | Read | Write | Manage | Admin | Public |
| -------------------- | :--: | :---: | :----: | :---: | :----: |
| `system_health`      |      |       |        |       |   ✅   |
| `system_about`       |      |       |        |       |   ✅   |
| `system_whoami`      |  ✅  |       |        |       |        |
| `space_create`       |      |  ✅   |        |       |        |
| `space_update`       |      |  ✅   |        |       |        |
| `space_update_rules` |      |       |   ✅   |       |        |
| `space_list`         |  ✅  |       |        |       |        |
| `space_info`         |  ✅  |       |        |       |        |
| `space_rules`        |  ✅  |       |        |       |        |
| `space_summary`      |  ✅  |       |        |       |        |
| `space_export`       |  ✅  |       |        |       |        |
| `space_delete`       |      |       |   ✅   |       |        |
| `live_note`          |      |  ✅   |        |       |        |
| `live_read`          |  ✅  |       |        |       |        |
| `live_search`        |  ✅  |       |        |       |        |
| `bank_read`          |  ✅  |       |        |       |        |
| `bank_read_all`      |  ✅  |       |        |       |        |
| `bank_list`          |  ✅  |       |        |       |        |
| `bank_consolidate`   |      |  ✅*  |        |       |        |
| `bank_consolidation_status` |  ✅  |       |        |       |        |
| `bank_consolidation_queues` |  ✅  |       |        |       |        |
| `bank_stale_spaces`  |  ✅  |       |        |       |        |
| `bank_compact`       |      |       |   ✅   |       |        |
| `bank_repair`        |      |       |   ✅   |       |        |
| `bank_write`         |      |       |   ✅   |       |        |
| `bank_delete`        |      |       |   ✅   |       |        |
| `graph_connect`      |      |  ✅   |        |       |        |
| `graph_push`         |      |  ✅   |        |       |        |
| `graph_status`       |  ✅  |       |        |       |        |
| `graph_disconnect`   |      |  ✅   |        |       |        |
| `backup_create`      |      |  ✅   |        |       |        |
| `backup_list`        |  ✅  |       |        |       |        |
| `backup_restore`     |      |       |   ✅   |       |        |
| `backup_download`    |  ✅  |       |        |       |        |
| `backup_delete`      |      |       |   ✅   |       |        |
| `admin_create_token` |      |       |        |  ✅   |        |
| `admin_list_tokens`  |      |       |        |  ✅   |        |
| `admin_revoke_token` |      |       |        |  ✅   |        |
| `admin_delete_token` |      |       |        |  ✅   |        |
| `admin_purge_tokens` |      |       |        |  ✅   |        |
| `admin_update_token` |      |       |        |  ✅   |        |
| `admin_bulk_update_tokens` |      |       |        |  ✅   |        |
| `admin_gc_notes`     |      |       |        |  ✅   |        |

\* `bank_consolidate`: write is sufficient for consolidating your own notes (`agent=caller` or `agent=""` auto-detected). Manage/admin required to consolidate ALL notes or another agent's notes (`agent=other`).

---

*Document updated August 12, 2026 — Live Memory v2.7.0*
