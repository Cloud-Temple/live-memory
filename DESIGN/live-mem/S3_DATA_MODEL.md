# S3 Data Model — Live Memory

> **Version**: v2.9.0 | **Date**: 2026-08-17 | **Author**: Cloud Temple

---

## 1. Principles

- **S3 is the single source of truth**: no database, everything is a file
- **One bucket** for the entire service (`S3_BUCKET_NAME`)
- **One prefix per space**: `{space_id}/`
- **System files**: `_system/` for cross-cutting data (tokens, etc.)
- **Backups**: `_backups/` for snapshots
- **Terminal job audit**: `_consolidation_jobs/` for completed consolidation
  and compaction payloads

---

## 2. Complete S3 Tree Structure

```
{bucket}/
│
├── _system/                              # Cross-cutting data
│   └── tokens.json                       # Authentication token registry
│
├── _backups/                             # Space snapshots
│   └── {space_id}/
│       └── {timestamp}/                  # e.g.: 2026-02-20T18-00-00
│           ├── _meta.json
│           ├── _rules.md
│           ├── _synthesis.md
│           ├── bank/
│           │   ├── activeContext.md
│           │   ├── progress.md
│           │   └── ...
│           └── live/
│               ├── note_001.md
│               └── ...
│
├── _consolidation_jobs/                  # Durable terminal audit payloads
│   └── {job_id}.json                     # succeeded/failed result + metrics
│
├── {space_id}/                           # A memory space
│   ├── _meta.json                        # Space metadata
│   ├── _rules.md                         # Immutable rules (bank structure)
│   ├── _synthesis.md                     # Residual synthesis (last consolidation)
│   │
│   ├── live/                             # Real-time notes
│   │   ├── .keep                         # Sentinel (so the "folder" exists)
│   │   ├── 20260220T140000_cline_observation_a1b2c3d4.md
│   │   ├── 20260220T140130_claude_decision_e5f6a7b8.md
│   │   ├── 20260220T141500_cline_todo_c9d0e1f2.md
│   │   └── ...
│   │
│   └── bank/                             # Consolidated Memory Bank
│       ├── .keep                         # Sentinel
│       ├── projectbrief.md               # ← Created and maintained
│       ├── activeContext.md              # ← by the LLM
│       ├── progress.md                   # ← according to the rules
│       └── ...                           # ← (dynamic names)
│
└── {other_space_id}/                     # Another space (same structure)
    ├── _meta.json
    ├── _rules.md
    └── ...
```

---

## 3. System Files

### 3.1 `_system/tokens.json`

Registry of all authentication tokens.

```json
{
  "version": 1,
  "tokens": [
    {
      "hash": "sha256:a1b2c3d4e5f6...",
      "kind": "standard",
      "name": "admin-ops",
      "permissions": ["read", "write", "admin"],
      "space_ids": [],
      "created_at": "2026-02-20T14:00:00Z",
      "expires_at": null,
      "last_used_at": "2026-02-20T17:55:00Z",
      "revoked": false
    },
    {
      "hash": "sha256:f7e8d9c0b1a2...",
      "kind": "standard",
      "name": "agent-cline",
      "permissions": ["read", "write"],
      "space_ids": ["project-alpha", "project-beta"],
      "created_at": "2026-02-20T14:05:00Z",
      "expires_at": "2027-02-20T14:05:00Z",
      "last_used_at": "2026-02-20T18:00:00Z",
      "revoked": false
    },
    {
      "hash": "sha256:badgehash...",
      "kind": "space_badge",
      "name": "runtime-agent-id",
      "permissions": [],
      "space_ids": ["mis_42"],
      "created_at": "2026-08-17T14:00:00+00:00",
      "expires_at": "2026-08-18T14:00:00+00:00",
      "revoked": false
    }
  ]
}
```

**Concurrency**: Protected by a dedicated `asyncio.Lock` (`LockManager.tokens`).
Mission badges are capabilities, not ordinary scoped tokens: they always have
one `space_id`, no general permission, and a fixed 24-hour expiry. The raw
badge secret is never stored.

### 3.2 `_consolidation_jobs/{job_id}.json`

Complete terminal payload for a consolidation or applied compaction job. It
is written before the terminal state becomes observable and before the
per-space FIFO lane is released. The payload includes `space_id`; status reads
reapply normal read authorization for that space. Queued/running jobs are not
stored here and remain process-local.

---

## 4. Space Files

### 4.1 `{space_id}/_meta.json`

Space metadata. Created by `space_create`, updated by `bank_consolidate` and `graph_push`.

```json
{
  "space_id": "project-alpha",
  "description": "API v3 refactoring project",
  "owner": "cline-dev",
  "creator_token_hash": "sha256:creatorhash...",
  "created_at": "2026-02-20T14:00:00Z",
  "last_consolidation": "2026-02-20T16:00:00Z",
  "consolidation_count": 3,
  "total_notes_processed": 127,
  "graph_memory": {
    "url": "https://graph-mem.mcp.cloud-temple.app/mcp",
    "token": "gm_xxx...",
    "memory_id": "project-alpha-mem",
    "ontology": "general",
    "last_push": "2026-03-01T14:00:00Z",
    "push_count": 3,
    "files_pushed": 6
  },
  "version": 1
}
```

**Fields added in v0.3.0**: `graph_memory` (optional object) containing the Graph Memory connection config and push metrics.

**Field added in v2.9.0**: `creator_token_hash` is the exact technical proof
that can mint a mission badge for this space. It is written with `_meta.json`
last during creation and is masked from every export or downloaded backup.

---

### 4.2 `{space_id}/_rules.md`

The rules define the **desired structure** of the memory bank. They are **immutable** after space creation.

> **Key point**: The MCP does not know which bank files exist or will exist. It is the LLM that reads the rules and creates/maintains the corresponding files.

---

### 4.3 `{space_id}/_synthesis.md`

Residual synthesis produced by the last consolidation. Serves as a **context bridge** between two consolidations.

```markdown
---
consolidated_at: "2026-02-20T16:00:00Z"
notes_processed: 42
---

## Consolidation #3 Synthesis

### Key Facts
- The authentication module has been implemented and tested
- Decision: use S3 as the sole backend

### Points of Attention
- The 60s LLM timeout is too short
```

This file is **overwritten** at each consolidation.

---

### 4.4 Live Notes: `{space_id}/live/{filename}.md`

Each note is a Markdown file with YAML front-matter.

**Naming convention**:
```
{YYYYMMDD}T{HHMMSS}_{agent}_{category}_{uuid8}.md
```

**Content format**:

```markdown
---
timestamp: "2026-02-20T14:00:00Z"
agent: "cline-dev"
category: "observation"
tags: ["auth", "bearer", "test"]
space_id: "project-alpha"
---

The Bearer token authentication module works correctly.
```

---

### 4.5 Bank Files: `{space_id}/bank/{filename}.md`

Bank files are pure Markdown, **without front-matter**. Their content is entirely managed by the LLM during consolidation.

Filenames are **decided by the LLM** based on the rules.

Versions v2.7.0 through v2.7.2 could store a compacted logical file as a marked
split family. This format is now legacy and read-only for migration. Part 1
keeps the canonical filename; later parts use `{stem}.part-NNN.md`. Every part
starts with a machine-readable comment:

```markdown
<!-- live-mem-split {"source":"progress.md","part":1,"total":2,"next":"progress.part-002.md"} -->
```

The marker is storage metadata, not bank content. Readers validate and
reconstruct the complete family. The next compaction, consolidation edit, or
explicit `bank_write` restoration writes the exact logical content under the
single canonical filename and removes the legacy parts. New multipart families
are never created. Missing, duplicated, or inconsistent parts fail closed.
Manually named files such as `progress-2.md` remain ordinary independent files.

---

## 5. S3 Operations per MCP Tool

| Tool | S3 Operations | Pattern |
|---|---|---|
| `space_create` | PUT `_rules.md`, `live/.keep`, `bank/.keep`, then `_meta.json` | 4 PUTs; meta last is creation marker |
| `space_badge_mint` | GET `_meta.json`, read/PUT `_system/tokens.json` | creator proof + one badge mutation under locks |
| `space_list` | LIST `*/` (top-level prefixes), GET `*/_meta.json` | N GETs |
| `space_info` | GET `_meta.json`, LIST `live/*`, LIST `bank/*` | 1 GET + 2 LISTs |
| `space_rules` | GET `_rules.md` | 1 GET |
| `space_summary` | GET `_meta.json`, GET `_rules.md`, GET `bank/*` | N GETs |
| `space_export` | LIST + GET all files | N GETs |
| `space_delete` | PUT revoked badges in `_system/tokens.json`, then LIST + DELETE space files | revocation persists before deletion |
| `live_note` | PUT `live/{filename}` | 1 PUT |
| `live_read` | LIST `live/*`, GET selected files | 1 LIST + N GETs |
| `live_search` | LIST `live/*`, GET all, text filter | 1 LIST + N GETs |
| `bank_read` | GET `bank/{filename}` | 1 GET |
| `bank_read_all` | LIST `bank/*`, GET all | 1 LIST + N GETs |
| `bank_list` | LIST `bank/*` | 1 LIST |
| `bank_consolidate` | GET rules + GET live/* + GET bank/* + PUT bank/* + DELETE live/* + PUT _synthesis + PUT terminal job audit | Many |
| `bank_compact` dry-run | GET meta + bank/* | 1 LIST + N GETs |
| `bank_compact` apply | GET meta + bank/* + full backup copy + PUT/GET/DELETE bank parts + PUT terminal job audit | Many |
| `graph_connect` | GET+PUT `_meta.json` (add graph_memory config) | 1 GET + 1 PUT |
| `graph_push` | LIST `bank/*`, GET `bank/*`, GET+PUT `_meta.json` | N GETs + 1 PUT |
| `graph_status` | GET `_meta.json` | 1 GET |
| `graph_disconnect` | GET+PUT `_meta.json` (remove graph_memory config) | 1 GET + 1 PUT |
| `backup_create` | LIST + GET everything → PUT into `_backups/` | N GETs + N PUTs |
| `backup_restore` | GET from `_backups/` → PUT into `{space_id}/` | N GETs + N PUTs |
| `admin_gc_notes` | LIST `*/live/*`, GET old notes, DELETE/consolidate | Variable |

---

## 6. S3 Considerations

### 6.1 Dell ECS — Hybrid Configuration

SigV2 for PUT/GET/DELETE, SigV4 for HEAD/LIST. See `CLOUD_TEMPLE_SERVICES.md`.

### 6.2 Limits

| Parameter | Value | Impact |
|---|---|---|
| Max object size | 5 GB | No concern (notes are a few KB) |
| Max object count | Unlimited | OK |
| GET latency | ~20-50ms | OK for individual reads |
| LIST latency | ~50-100ms | Can be slow if >1000 live notes |
| LIST cost | 1 request per 1000 objects | Consider pagination |

### 6.3 Pagination

For spaces with many notes (>1000), the `StorageService` handles pagination automatically via `list_objects_v2` with `ContinuationToken`.

### 6.4 Consistency

S3 provides **strong consistency** for PUT and DELETE followed by GET. No waiting delay needed after writes.

---

*Document updated August 17, 2026 — Live Memory v2.9.0*
