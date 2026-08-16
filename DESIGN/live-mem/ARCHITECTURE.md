# Architecture — Live Memory MCP Server

> **Version**: 2.8.0 | **Date**: 2026-08-16 | **Author**: Cloud Temple
> **Project**: live-mem | **License**: Apache 2.0

---

## 1. Vision

**Live Memory** is an MCP (Model Context Protocol) server that provides a **shared working memory** (Memory Bank) for collaborative AI agents. Unlike graph-memory (long-term memory via Knowledge Graph), live-mem is a **live memory**: agents write in real time, and a built-in LLM automatically consolidates those notes into a structured memory bank.

### Philosophy

```
graph-memory  = LONG-TERM Memory (documents → Knowledge Graph → RAG)
live-mem      = WORKING Memory (live notes → LLM → Memory Bank)
```

### Key Principles

1. **Two complementary modes**:
   - **Live Mode**: Agents write notes continuously (observations, decisions, todos, insights)
   - **Bank Mode**: The MCP consolidates notes into structured files via LLM, then cleans the live stream

2. **Dynamic bank, not hardcoded**: The memory bank structure is defined by the **rules** provided at space creation. The LLM creates and maintains bank files according to these rules. The MCP does not know any filename in advance.

3. **S3 as the single source of truth**: No database (no Neo4j, no Qdrant). Everything is a Markdown/JSON file on S3. Simple, portable, auditable.

4. **Native multi-agent**: Multiple agents can write simultaneously to the same space without conflict (append-only pattern for live notes).

5. **Built-in LLM**: The MCP uses an LLM (qwen3.5:27b via Cloud Temple LLMaaS) for consolidation. Agents cannot write directly to the bank — only the LLM does.

6. **Bridge to long-term memory**: The Graph Bridge (`graph_push`) pushes the consolidated bank into Graph Memory to capitalize knowledge in a queryable graph.

---

## 2. Positioning

| Aspect            | graph-memory                   | live-mem                                      |
| ----------------- | ------------------------------ | --------------------------------------------- |
| **Memory type**   | Long-term (Knowledge Base)     | Working Memory                                |
| **Input**         | Documents (PDF, DOCX, MD, CSV) | Agent text notes                              |
| **Storage**       | Neo4j + Qdrant + S3            | **S3 only**                                   |
| **Intelligence**  | Entity/relation extraction     | Consolidation & synthesis                     |
| **LLM used**      | gpt-oss:120b (extraction)      | `LLMAAS_MODEL` (consolidation) + `LLMAAS_COMPACTION_MODEL` (compaction; Mistral 119B recommended) |
| **Search**        | Hybrid Graph + vector RAG      | Direct file reading + text search             |
| **Agents**        | 1 agent per request            | **Multi-agent collaborative**                 |
| **Bridge**        | —                              | **Graph Bridge** pushes bank → graph-memory   |
| **Web interface** | `/Graph` (graph visualization) | **`/live`** (Dashboard + Timeline + Bank)     |
| **Analogy**       | A library                      | A **shared whiteboard** + structured notebook |

---

## 3. Architecture

### 3.1 Overview

```
          Agent Cline         Agent Claude        Agent X
              │                    │                 │
              └────────┬───────────┘                 │
                       │                             │
                       ▼ MCP Protocol (Streamable HTTP)     ▼
┌──────────────────────────────────────────────────────────┐
│                    Coraza WAF (Caddy)                     │
│  • OWASP CRS • Rate Limiting • TLS Let's Encrypt        │
│  • MCP routes without WAF (streaming)                    │
└──────────────────────────┬───────────────────────────────┘
                           │ Internal Docker network
                           ▼
┌────────────────────────────────────────────────────────────┐
│              Live Memory MCP Server (:8002)                │
│                                                            │
│  ┌─────────────────┐  ┌──────────────────┐                 │
│  │  43 MCP Tools   │  │  LLM Service     │                 │
│  │  (7 categories) │  │  (consolidator)  │                 │
│  └────────┬────────┘  └────────┬─────────┘                 │
│           │                    │                           │
│  ┌────────┴────────────────────┴──────────┐                │
│  │         Storage Service (S3)           │                │
│  │  • Hybrid SigV2/V4 (Dell ECS)          │                │
│  │  • asyncio locks per file              │                │
│  └────────────────────┬───────────────────┘                │
│                       │                                    │
│  ┌────────────────────┴───────────────────┐                │
│  │         Auth Middleware (ASGI)         │                │
│  │  • Bearer Token • R/W/A Permissions    │                │
│  │  • Space access control                │                │
│  └────────────────────────────────────────┘                │
│                                                            │
│  ┌─────────────────────────────────────────┐               │
│  │         Web Interface (/live)           │               │
│  │  • StaticFilesMiddleware (ASGI)         │               │
│  │  • Dashboard + Timeline + Bank Viewer   │               │
│  │  • 5 REST API endpoints (/api/*)        │               │
│  └─────────────────────────────────────────┘               │
│                                                            │
│  ┌─────────────────────────────────────────┐               │
│  │         Graph Bridge (optional)         │               │
│  │  • MCP Streamable HTTP client to Graph Memory           │
│  │  • Sync bank → knowledge graph          │               │
│  └─────────────────────────────────────────┘               │
└──────────────────────────┬─────────────────────────────────┘
                           │
              ┌────────────┼────────────────────┐
              ▼            ▼                    ▼
    ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐
    │  S3 Object   │ │  LLMaaS API  │ │  Graph Memory      │
    │  Store       │ │  (Cloud      │ │  (optional)        │
    │  (Dell ECS)  │ │   Temple)    │ │  Neo4j + Qdrant    │
    │  Bucket:     │ │  qwen3-2507  │ │  via MCP Streamable HTTP       │
    │  live-mem    │ │  :235b       │ │                    │
    └──────────────┘ └──────────────┘ └────────────────────┘
```

### 3.2 Components

| Component                | Role                                       | Technology                               |
| ------------------------ | ------------------------------------------ | ---------------------------------------- |
| **WAF**                  | Secure reverse proxy                       | Caddy + Coraza OWASP CRS + Rate Limiting |
| **MCP Server**           | Python MCP server (43 tools, 7 categories) | FastMCP + Uvicorn (ASGI)                 |
| **Storage Service**      | S3 abstraction (read/write/listing)        | boto3 hybrid SigV2/V4                    |
| **Consolidator Service** | LLM synthesis of notes → bank              | AsyncOpenAI (qwen3.5:27b)                |
| **Graph Bridge**         | Bridge to Graph Memory (long-term memory)  | MCP SDK (streamablehttp_client)          |
| **Auth Middleware**      | Bearer Token authentication                | Custom ASGI middleware                   |
| **Token Manager**        | Token management (CRUD)                    | JSON on S3 (`_system/tokens.json`)       |
| **Static Files**         | Web interface /live + REST API             | ASGI middleware (StaticFilesMiddleware)  |
| **GC Service**           | Orphaned note cleanup                      | Scan + consolidation/deletion            |

### 3.3 External Services

| Service          | Provider                                    | Usage                     | Required    |
| ---------------- | ------------------------------------------- | ------------------------- | ----------- |
| **S3**           | Cloud Temple (Dell ECS) or compatible       | Storage for ALL data      | ✅          |
| **LLMaaS**       | Cloud Temple (OpenAI-compatible API)        | Consolidation live → bank | ✅          |
| **Graph Memory** | graph-memory instance (MCP Streamable HTTP) | Long-term memory (graph)  | ❌ Optional |

### 3.4 Tech Stack

| Component          | Technology              | Role                               |
| ------------------ | ----------------------- | ---------------------------------- |
| MCP Framework      | `FastMCP` (Python SDK)  | Exposes tools via Streamable HTTP  |
| HTTP Server        | `Uvicorn` (ASGI)        | Serves the FastMCP application     |
| Configuration      | `pydantic-settings`     | Environment variables + `.env`     |
| Scriptable CLI     | `Click`                 | Command-line interface             |
| Interactive Shell  | `prompt_toolkit`        | Autocompletion, history            |
| Display            | `Rich`                  | Tables, panels, colors, Markdown   |
| MCP Client         | MCP SDK ≥1.8.0          | CLI + Graph Bridge → server        |
| Auth               | Bearer Token            | Token-based authentication         |
| S3 Client          | `boto3`                 | S3 storage (hybrid SigV2/V4)       |
| LLM Client         | `openai` (AsyncOpenAI)  | LLMaaS API calls                   |
| Container          | Docker + Docker Compose | Deployment                         |
| Reverse Proxy      | Caddy + Coraza          | TLS, WAF, Rate Limiting            |
| Web Interface      | HTML/CSS/JS vanilla     | Dashboard, Timeline, Bank Viewer   |
| Markdown Rendering | `marked.js` + `DOMPurify` (vendored locally) | Bank file rendering + XSS sanitization |

### 3.5 ASGI Middleware Stack

```
Incoming HTTP request
    │
    ▼
AuthMiddleware          ← Extracts Bearer token, injects into contextvars
    │
    ▼
LoggingMiddleware       ← Traces method, path, status, duration (stderr)
    │
    ▼
StaticFilesMiddleware   ← Intercepts /live, /static/*, /api/*
    │
    ▼
mcp.streamable_http_app()           ← MCP Streamable HTTP handler (tools via /mcp)
```

> **Note v0.5.0**: `HostNormalizerMiddleware` was removed — Host header normalization is now handled natively by the Caddy WAF.

---

## 4. Data Flows

### 4.1 Writing (Live Mode)

```
Agent → live_note("observation", "The auth module works")
                │
                ▼
        MCP Server verifies auth + space access
                │
                ▼
        Generates a unique name:
        20260220T180512_cline-dev_observation_a3f8b2c1.md
                │
                ▼
        PUT S3: {space_id}/live/{filename}
        (content = YAML front-matter + text)
```

### 4.2 Reading (Bank Mode)

```
Agent → bank_read_all("project-alpha")
                │
                ▼
        MCP Server verifies auth + space access
                │
                ▼
        LIST S3: {space_id}/bank/*
                │
                ▼
        GET S3: each bank file
                │
                ▼
        Returns: {files: [{filename, content}, ...], total_size, file_count}
```

### 4.3 Consolidation (Bank Mode — via LLM)

```
Agent → bank_consolidate("project-alpha", agent="cline-dev")
                │
                ▼
        1. Reads _rules.md
        2. Reads the agent's live notes (or all if agent="")
        3. Reads the current bank (all files)
        4. Reads _synthesis.md (previous context)
                │
                ▼
        For all bank files in a single LLM request:
        ┌──────────────────────────────────────────────┐
        │  LLM Prompt:                                 │
        │  - Space rules                               │
        │  - Relevant live notes                       │
        │  - Current content of all bank files         │
        │  - Previous synthesis                        │
        │  →  LLM returns a JSON with                  │
        │     EDIT OPERATIONS per section              │
        │     (replace_section, append_to_section,     │
        │     add_section, delete_section) + synthesis │
        └──────────────────────────────────────────────┘
                │
                ▼
        5. Preflights the complete edit plan
           → synthesis must be textual
           → create cannot overwrite; rewrite requires a target
           → every surgical operation is applied in memory first
        6. Applies operations surgically
           on existing bank files (v0.6.0)
           → What is not touched remains intact byte-for-byte
           → Zero content loss (vs full rewrite)
        7. Writes _synthesis.md (residual for next consolidation)
        8. Computes every fallible metric
        9. Deletes processed live notes (LAST batch commit)
       10. Updates _meta.json once after all committed batches
```

Each batch snapshots bank, synthesis, and (outside batched mode) metadata. Any
invalid operation or storage exception before source-note deletion restores
the complete output snapshot and verifies both contents and the exact bank
keyset. A partial note deletion restores and re-reads every collected source;
loss metrics are explicit and are never counted as processed notes. If the
final metadata/audit update fails after committed batches, the result is
`partial` and retains their exact metrics—committed batches are not rolled
back.

### 4.4 Safe Hierarchical Bank Compaction

Compaction inventories complete source Markdown units, creates bounded ephemeral
Map cards, and persists one validated non-exhaustive Reduce digest. Recent and
protected bytes remain exact. Every limit is measured in UTF-8 bytes.

```
bank_compact(dry_run=False) ──► per-space FIFO (`job_type="compact"`)
                                      │
                                      ▼
                              Read complete logical bank
                                      │
                                      ▼
                         Detect each oversized file mode
                         from Markdown structure and content
                                      │
                                      ▼
                         Dedicated compaction model evaluates the file
                         - bounded Map cards, then one Reduce
                         - same-file protected context only
                         - one validated non-exhaustive digest
                                      │
                                      ▼
                         Every candidate ready before backup
                                      │
                                      ▼
                         Full-space backup, write, readback
                         and bank-only rollback on persistence failure
                                      │
                                      ▼
                         One verified canonical Markdown object
                         (the byte threshold triggers compaction;
                         it is not a storage-size ceiling)
```

Any Map, Reduce, digest or candidate failure cancels the complete job before backup. No
compaction path creates `*.part-NNN.md` objects. A later consolidation
reconstructs any legacy v2.7.x split family and writes one canonical file.
No filename has a compaction role. A file is handled in dated mode when at
least two complete dates occur in structural entry labels; otherwise its
complete H3 sections are eligible. Recent, undated, code-bearing and HTML-bearing
units are protected. A file with neither structure fails closed before the
first LLM call. All Map and worst-case Reduce prompts are preflighted before any
request. The digest replaces all selectable historical units inside one
recompactable code-owned container; reports expose `planned_llm_calls`.
Manual compaction jobs are
observable through `bank_consolidation_status` and
`bank_consolidation_queues`; automatic pre-consolidation compaction exposes its
phase on the consolidation job. If both persistence and rollback fail, the job
reports the restorable `backup_id` and requires manual recovery.

The bank-only rollback is deliberate: `live_note` does not take the
consolidation lock, so restoring the full space could delete a note created
after the backup. Multi-file rollback verifies the exact final bank keyset and
content before it is reported as successful.

In 2.8.0, any pre-consolidation compaction failure is blocking: note
consolidation does not continue against an oversized or incompletely planned
bank. Originals and live notes remain untouched.

### 4.5 Graph Push (Bridge to Graph Memory)

> ⚠️ **Architecture invariant (v2.5.0) — Live ↔ Graph responsibility separation**
>
> The Memory Bank is a **compact session bootstrap**, not a long-term archive: `activeContext.md` is a volatile focus snapshot, `progress.md` is a bounded recent journal, sub-files are compact fact sheets. The Live Memory consolidator continuously rewrites and compacts them. Graph Memory, on the other hand, must index **stable canonical documents** (RFCs, incidents, runbooks, design docs, infrastructure inventories) and serves as a **semantic locator** for those documents.
>
> Therefore:
> - **Graph Memory complements the bank; it does not replace it.**
> - **Graph Memory localizes; canonical repository files confirm.**
> - **The Live Memory consolidator never pushes anything into Graph Memory.** Graph ingestion is an **agent / tooling responsibility**, started from canonical repository documents.
> - **`graph_push` is NOT a routine action.** It remains available for one-off bootstrap of a new graph or for explicit debug / migration. In particular, `activeContext.md` and `progress.md` must never end up in Graph Memory.
>
> A future revision (tracked in [`./EVOLUTION_LIVE_GRAPH_INTEGRATION.md`](./EVOLUTION_LIVE_GRAPH_INTEGRATION.md)) will turn this contract into a server-side guardrail. For v2.5.0 the contract is doctrinal — enforced through the agent rules template ([`../../WORKSPACE_CLINE_ADVANCE_RULES.md`](../../WORKSPACE_CLINE_ADVANCE_RULES.md)) and the `graph_push` docstring. The push flow described below remains accurate; it just must not be called in routine session-end consolidation.

```
Agent → graph_push("project-alpha")
                │
                ▼
        1. Reads graph_memory config from _meta.json
        2. Lists bank files
                │
                ▼
        For each bank file:
        ┌─────────────────────────────────────────────┐
        │  Via MCP Streamable HTTP to Graph Memory:   │
        │  1. Deletes old document (if existing)      │
        │  2. Ingests new content                     │
        │     (LLM entity/relation extraction)        │
        │  ~10-30s per file                           │
        └─────────────────────────────────────────────┘
                │
                ▼
        3. Cleans orphans (files removed from the bank)
        4. Updates metrics in _meta.json
```

---

## 5. Memory Spaces

A **space** is an isolated namespace. Each space has:
- A unique identifier (`space_id`: alphanumeric + hyphens, max 64 chars)
- **Immutable rules** (defined at creation, never change)
- A `live/` folder for notes
- A `bank/` folder for consolidated files
- Metadata (`_meta.json`), optionally including Graph Memory config
- A residual synthesis (`_synthesis.md`)

Spaces are isolated: a token can only access its authorized spaces.

---

## 6. Web Interface

Live Memory exposes a **SPA web interface** on `/live`:

```
┌──────────────┬──────────────────────────────┐
│  📊 Dashboard│  🔴 Live Timeline             │
│  (info,      │  (auto-refresh, grouped/date)│
│   agents,    ├──────────────────────────────┤
│   rules...)  │  📘 Bank (Markdown tabs)     │
└──────────────┴──────────────────────────────┘
```

- **Header**: version badge (from `/health`), health status indicator (🟢/🟠/🔴 dot from `/health`), clock, health tooltip on hover showing service details (S3, LLMaaS latency, bucket, model)
- **Dashboard**: space stats, consolidation, agents, categories, rules, Graph Memory
- **Live Timeline**: notes grouped by date, Markdown rendering (sanitized via DOMPurify)
- **Bank Viewer**: wrapped multi-line tabs (flex-wrap, scrollable), Markdown rendering via vendored `marked.js` + `DOMPurify`
- **Auto-refresh**: 3s/5s/10s/30s/manual, anti-flicker via hash comparison, dynamic space list refresh (new spaces appear automatically)
- **Auth**: HttpOnly cookie via `/api/login` (LM2-04), legacy localStorage auto-purged
- **CSP-safe**: no inline event handlers (`addEventListener` only), `script-src 'self'`
- **5 REST API endpoints** (`/api/*`) + `/health` (public) to feed the interface

### Admin Console (`/admin`)

Live Memory also exposes an **administration console** on `/admin` covering all 43 MCP tools:

- **Architecture**: internal proxy via `_mcp_ref.call_tool_direct()` bypassing the Streamable HTTP protocol. The ASGI auth middleware injects the token context before each call, so security is inherited from the MCP layer.
- **Backend**: `POST /api/tool` route in `auth/middleware.py`, protected (401 without session). Routes `/admin` and `/static/css/admin.css`, `/static/js/admin-*.js` served by StaticFilesMiddleware.
- **Frontend**: 4 files (`admin.html`, `admin.css`, `admin-api.js`, `admin-app.js`), vanilla JS, dark theme matching `/live`.
- **7 sidebar sections**: Dashboard (4 stat cards + identity bar + clickable Health → modal), Spaces (CRUD table), Tokens (create/update/revoke with visual space chips), Explorer (live notes + bank side-by-side), Backups (dynamic columns, "Backup All"), Graph Bridge, Maintenance (compact action list with shared space selector).
- **CSP-safe**: zero inline `onclick`, all via `data-action` attributes + global event delegation.
- **Upload Rules**: file picker (`.md`) or paste directly, calls `space_update_rules` via proxy.

---

## 7. Architecture Comparison

### What live-mem reuses from graph-memory

| Pattern                             | graph-memory | live-mem     |
| ----------------------------------- | ------------ | ------------ |
| 3-layer pattern (MCP + CLI + Shell) | ✅           | ✅           |
| S3 Dell ECS hybrid SigV2/V4         | ✅           | ✅           |
| Auth Bearer Token + bootstrap key   | ✅           | ✅           |
| WAF Caddy + Coraza + Rate Limiting  | ✅           | ✅           |
| Docker Compose + isolated network   | ✅           | ✅           |
| Non-root container                  | ✅           | ✅           |
| LLMaaS Cloud Temple (OpenAI API)    | ✅           | ✅           |
| Backup/Restore on S3                | ✅           | ✅           |
| Token management (CRUD)             | ✅ (Neo4j)   | ✅ (S3 JSON) |
| Standardized return format          | ✅           | ✅           |
| Logs on stderr                      | ✅           | ✅           |
| Lazy-loading services               | ✅           | ✅           |
| Web visualization interface         | ✅ (/Graph)  | ✅ (/live)   |

### What live-mem does NOT reuse

| Element                    | Reason                 |
| -------------------------- | ---------------------- |
| Neo4j                      | No knowledge graph     |
| Qdrant                     | No vector search       |
| Chunking (SemanticChunker) | No document ingestion  |
| Entity/relation extraction | Not relevant for notes |
| RAG                        | No semantic search     |

### What live-mem adds

| Element                     | Description                                                   |
| --------------------------- | ------------------------------------------------------------- |
| **Multi-agent live notes**  | Concurrent writing without conflict (append-only)             |
| **LLM Consolidation**       | Automatic synthesis notes → bank via LLM                      |
| **Per-agent consolidation** | `bank_consolidate(agent="...")` filters notes                 |
| **Dynamic rules**           | Bank structure defined by rules, not hardcoded                |
| **Bank read_all**           | Complete bank reading in a single request                     |
| **Residual synthesis**      | `_synthesis.md` as a bridge between consolidations            |
| **Tokens on S3**            | No longer requires Neo4j for token storage                    |
| **Graph Bridge**            | MCP Streamable HTTP bridge to graph-memory (long-term memory) |
| **Garbage Collector**       | Cleanup/consolidation of orphaned notes                       |
| **Web interface /live**     | Dashboard + Timeline + Bank Viewer with auto-refresh          |

---

## 8. Prerequisites

### Minimum Hardware

| Resource | Minimum   | Recommended |
| -------- | --------- | ----------- |
| CPU      | 1 vCPU    | 2 vCPU      |
| RAM      | 1 GB      | 2 GB        |
| Disk     | 10 GB SSD | 20 GB SSD   |

> **Note**: live-mem is much lighter than graph-memory (no Neo4j or Qdrant). The MCP service consumes ~100 MB at rest, ~500 MB during LLM consolidation.

### Network

| Port     | Direction | Usage                                        |
| -------- | --------- | -------------------------------------------- |
| **80**   | Inbound   | HTTP → redirect to HTTPS (prod)              |
| **443**  | Inbound   | HTTPS (TLS Let's Encrypt, prod)              |
| **8080** | Inbound   | HTTP (dev only)                              |
| —        | Outbound  | `api.ai.cloud-temple.com` (LLMaaS)           |
| —        | Outbound  | `*.s3.fr1.cloud-temple.com` (S3)             |
| —        | Outbound  | Graph Memory (MCP Streamable HTTP, optional) |

---

## 9. Configuration (.env)

### Required Variables

```env
# ─── S3 ───
S3_ENDPOINT_URL=https://your-endpoint.s3.fr1.cloud-temple.com
S3_ACCESS_KEY_ID=AKIA_YOUR_KEY
S3_SECRET_ACCESS_KEY=your_secret
S3_BUCKET_NAME=live-mem
S3_REGION_NAME=fr1

# ─── LLMaaS ───
LLMAAS_API_URL=https://api.ai.cloud-temple.com/v1
LLMAAS_API_KEY=your_key
LLMAAS_MODEL=qwen3.5:27b
LLMAAS_COMPACTION_MODEL=mistral-small4:119b
LLMAAS_MAX_TOKENS=100000
LLMAAS_TEMPERATURE=0.3

# ─── Auth ───
ADMIN_BOOTSTRAP_KEY=change_me_to_a_strong_random_key_64chars
```

### Optional Variables

```env
# ─── Server ───
MCP_SERVER_PORT=8002
MCP_SERVER_DEBUG=false
WAF_PORT=8080
SITE_ADDRESS=:8080

# ─── Consolidation ───
CONSOLIDATION_TIMEOUT=600        # LLM timeout in seconds
CONSOLIDATION_MAX_NOTES=200      # Max notes per consolidation

# ─── Outbound proxy (optional) ───
# Custom variable (not HTTP_PROXY) injected manually into boto3 (S3) and
# httpx (LLM). Covers S3, LLMaaS consolidation, AND the health probes
# (/health endpoint + system_health tool) since v2.6.0. Not applied to
# Graph Memory connections.
PROXY_URL=http://10.0.0.1:3128
```

---

*Document updated August 16, 2026 — Live Memory v2.8.0*
