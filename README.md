# 🧠 Live Memory — MCP Knowledge Live Memory Service

> **Shared working memory for collaborative AI agents**

[![CI](https://github.com/Cloud-Temple/live-memory/actions/workflows/build.yml/badge.svg)](https://github.com/Cloud-Temple/live-memory/actions/workflows/build.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-cloud--temple%2Flive--memory-blue?logo=docker)](https://ghcr.io/cloud-temple/live-memory)
[![Version](https://img.shields.io/badge/version-2.7.3-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)]()
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)]()
[![Python](https://img.shields.io/badge/python-3.11+-yellow.svg)]()

🇫🇷 [Version française](README.fr.md)

---

## 📋 Table of Contents

- [Concept](#-concept)
- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Getting Started](#-getting-started)
- [MCP Tools](#-mcp-tools)
- [Graph Bridge](#-graph-bridge--link-to-graph-memory)
- [Web Interface](#-web-interface)
- [MCP Integration](#-mcp-integration)
- [CLI and Shell](#-cli-and-shell)
- [Tests](#-tests)
- [Security](#-security)
- [Project Structure](#-project-structure)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)

---

## 🎯 Concept

**Live Memory** is an MCP (Model Context Protocol) server that provides **Memory Bank as a Service** for AI agents. Multiple agents collaborate on the same project by sharing a common working memory.

```
graph-memory  = LONG-TERM memory (documents → Knowledge Graph → Vector RAG)
live-memory   = WORKING memory (live notes → LLM → Structured Memory Bank)
```

### Two Complementary Modes

| Mode         | Description                                                     | Analogy                |
| ------------ | --------------------------------------------------------------- | ---------------------- |
| **🔴 Live** | Real-time notes (observations, decisions, todos...) append-only | Shared whiteboard      |
| **📘 Bank** | LLM consolidation into structured Markdown files based on rules | Structured project log |

### Why Live Memory?

| Problem                                 | Live Memory Solution                                    |
| --------------------------------------- | ------------------------------------------------------- |
| Agents lose context between sessions    | `bank_read_all` → complete context in 1 call            |
| Multi-agent collaboration is impossible | Append-only notes, no conflicts, cross-visibility       |
| Manual consolidation is tedious         | LLM transforms raw notes into structured documentation  |
| Memory scattered in local files         | Central S3 point, accessible from everywhere            |
| No link with long-term memory           | 🌉 Graph Bridge pushes the bank into a knowledge graph |

### 🧠 Multi-agent Collaboration and Two-Level Memory Architecture

Recent research on LLM-based multi-agent systems ([Tran et al., 2025 — *Multi-Agent Collaboration Mechanisms: A Survey of LLMs*](https://arxiv.org/abs/2501.06322)) identifies **shared memory** as a fundamental component. In their formal framework, a multi-agent system is defined by **agents** (A), a **shared environment** (E), and **collaboration channels** (C). The authors emphasize that LLMs are inherently isolated algorithms, not designed to collaborate — they need a **shared memory infrastructure** to coordinate their actions.

Live Memory + Graph Memory directly implements this architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                  Shared Environment E                       │
│                                                             │
│  ┌──────────────────┐   LLM   ┌──────────────────────┐      │
│  │   Live           │ ──────► │   Bank               │      │
│  │  Real-time notes │ consolid│  Structured working  │      │
│  │  (append-only)   │  -ates  │  memory              │      │
│  └──────────────────┘         └──────────┬───────────┘      │
│                                          │                  │
│                                     graph_push              │
│                                     (MCP Streamable HTTP)   │
│                                          │                  │
│                               ┌──────────▼───────────┐      │
│                               │  🌐 Graph Memory     │      │
│                               │  Knowledge Graph     │      │
│                               │  (entities, relations│      │
│                               │   embeddings, RAG)   │      │
│                               └──────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

| Level                | Service      | Duration          | Content                                  | Usage                                         |
| -------------------- | ------------ | ----------------- | ---------------------------------------- | --------------------------------------------- |
| **Working Memory**   | Live Memory  | Session / project | Raw notes + consolidated Markdown bank   | Operational context, daily coordination       |
| **Long-term Memory** | Graph Memory | Permanent         | Entities + relations + vector embeddings | Searchable knowledge base in natural language |

**The Graph Bridge** (`graph_push`) is the collaboration channel between these two levels. Following the **late-stage collaboration** pattern described in literature (sharing consolidated outputs as inputs to another system), it transforms working documentation (Markdown) into structured knowledge (entities/relations graph).

**Why two levels?** One level is not enough:
- Working memory alone is **ephemeral** — it disappears when the project ends
- Knowledge graph alone is **too heavy** for quick daily notes
- The bridge between the two allows agents to **work fast** (live notes) while **capitalizing** knowledge (graph)

Specifically, agents can:
1. **Write quickly** without friction (live-memory, append-only, ~50ms)
2. **Automatically consolidate** via LLM into structured documentation (bank, ~15s)
3. **Persist knowledge** in a searchable graph (graph-memory, ~2min)
4. **Query the graph** in natural language to retrieve information from past projects

---

## 🏗️ Architecture

```
     Agent Cline        Agent Claude        Agent X
          │                   │                │
          └────────┬──────────┘                │
                   │                           │
                   ▼  MCP Protocol (Streamable HTTP)  ▼
          ┌────────────────────────────────────────┐
          │   Caddy WAF (Coraza CRS)               │
          │   Rate Limiting • TLS • OWASP CRS      │
          └────────────┬───────────────────────────┘
                       │
          ┌────────────┴───────────────────┐
          │   Live Memory MCP (:8002)      │
          │   43 tools • Auth Bearer       │
          │   LLM Consolidation            │
          └──────┬──────────┬──────┬───────┘
                 │          │      │
          ┌──────┴──┐  ┌────┴───┐  │
          │   S3    │  │ LLMaaS │  │  MCP Streamable HTTP
          │Dell ECS │  │ CT API │  │  (optional)
          └─────────┘  └────────┘  │
                       ┌───────────┴────────────┐
                       │   Graph Memory         │
                       │   (long-term memory)   │
                       │   Neo4j + Qdrant       │
                       └────────────────────────┘
```

**Minimal Stack**: S3 + LLM. No local database.
**Optional**: connection to Graph Memory for long-term memory (knowledge graph).

---

## 📦 Prerequisites

- **Docker** >= 24.0 + **Docker Compose** v2
- **Python 3.11+** (for CLI, optional)
- A compatible **S3 storage** (Cloud Temple Dell ECS, AWS, MinIO)
- An OpenAI API compatible **LLM** (Cloud Temple LLMaaS, OpenAI, etc.)

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/Cloud-Temple/live-memory.git
cd live-memory
```

### 2. Configure the environment

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Configuration](#-configuration)).

### 3a. Docker Start (recommended)

```bash
# Build images (WAF + MCP server)
docker compose build

# Start services
docker compose up -d

# Check status
docker compose ps

# Health check
curl -s http://localhost:8080/health
```

### 3b. Local Start (development)

```bash
# Install dependencies
uv pip install -e .

# Run server
python -m live_mem
```

### 4. Install CLI (optional)

```bash
uv pip install -e .
```

### 5. Verify Installation

```bash
# Health check via CLI
python scripts/mcp_cli.py health

# Or full E2E test (creates space, writes notes, consolidates)
python scripts/test_recette.py
```

### Exposed Ports

| Service    | Port   | Description                                 |
| ---------- | ------ | ------------------------------------------- |
| **WAF**    | `8080` | Only exposed port — Caddy WAF → Live Memory |
| MCP Server | `8002` | Internal Docker network only                |

---

## ⚙️ Configuration

Edit `.env`. All variables are documented in `.env.example`.

### Mandatory Variables

| Variable               | Description              | Example                                      |
| ---------------------- | ------------------------ | -------------------------------------------- |
| `S3_ENDPOINT_URL`      | S3 endpoint URL          | `https://takinc5acc.s3.fr1.cloud-temple.com` |
| `S3_ACCESS_KEY_ID`     | S3 access key            | `AKIA...`                                    |
| `S3_SECRET_ACCESS_KEY` | S3 secret key            | `wJal...`                                    |
| `S3_BUCKET_NAME`       | Bucket name              | `live-mem`                                   |
| `S3_REGION_NAME`       | S3 region                | `fr1`                                        |
| `LLMAAS_API_URL`       | LLM API URL (must include `/v1`)  | `https://api.ai.cloud-temple.com/v1` |
| `LLMAAS_API_KEY`       | LLM API key                       | `sk-...`                             |
| `ADMIN_BOOTSTRAP_KEY`  | Admin bootstrap key (≥ 32 chars)  | `my-secret-key-change-me`           |

### Optional Variables — LLM

The service can use distinct OpenAI-compatible models for consolidation and
hierarchical compaction.

| Variable                  | Default           | Description                     |
| ------------------------- | ----------------- | ------------------------------- |
| `LLMAAS_MODEL`            | `qwen3.5:27b` | Consolidation model name as exposed by the provider |
| `LLMAAS_COMPACTION_MODEL` | `LLMAAS_MODEL` | Dedicated Map/Reduce compaction model. `mistral-small4:119b` is recommended for 2.8.0 |
| `LLMAAS_CONTEXT_WINDOW`   | `131072`          | TOTAL context window of the model (input + output combined, in tokens). Qwen3 235B = 128K |
| `LLMAAS_MAX_TOKENS`       | `16384`           | Max OUTPUT tokens per request. The consolidator adjusts dynamically: `output = min(MAX_TOKENS, CONTEXT_WINDOW - input)` |
| `LLMAAS_TEMPERATURE`      | `0.3`             | LLM creativity (0.0 = deterministic, 1.0 = very creative) |
| `PROXY_URL`               | _(none)_          | Outbound HTTP proxy (e.g. `http://10.0.0.1:3128`). **Custom variable** (not `HTTP_PROXY`) — injected manually into boto3 (S3) and httpx (LLM). Not supported for Graph Memory connections. |

### Optional Variables — Consolidation and Compaction

| Variable                  | Default           | Description                     |
| ------------------------- | ----------------- | ------------------------------- |
| `MCP_SERVER_PORT`         | `8002`            | MCP server listening port       |
| `MCP_SERVER_DEBUG`        | `false`           | Detailed logs (full error messages) |
| `CONSOLIDATION_TIMEOUT`   | `600`             | Timeout per LLM call (seconds)  |
| `CONSOLIDATION_MAX_NOTES` | `200`             | Max notes per consolidation     |
| `CONSOLIDATION_BATCH_SIZE`| `5`               | Notes per LLM batch (small = precise, large = faster) |
| `CONSOLIDATION_COOLDOWN_SECONDS` | `60`      | Per-space anti-spam cooldown for `bank_consolidate` (`0` disables) |
| `CONSOLIDATION_VALIDATION_ENABLED` | `false` | Optional post-consolidation check for unattributed claims |
| `CONSOLIDATION_VALIDATION_MAX_EXAMPLES` | `20` | Max examples returned by the validation pass |
| `COMPACT_THRESHOLD`       | `0.6`             | Legacy compatibility setting; compaction follows the logical UTF-8 byte limit per file |
| `BANK_FILE_MAX_SIZE`      | `15360`           | Universal UTF-8 byte limit for a logical Bank file. Oversized files use hierarchical Map/Reduce digest compaction; dated files reserve 25% of their available space for future growth |
| `RESPONSE_MAX_BYTES`      | `524288`          | Max non-MCP response body size before truncation |
| `API_TOOL_MAX_BODY_BYTES` | `1048576`         | Max request body accepted by `/api/tool` |

---

## ▶️ Getting Started

```bash
docker compose up -d
docker compose ps       # Check status
docker compose logs -f live-mem-service --tail 50  # Logs
```

---

## 🔧 MCP Tools

43 tools exposed via the MCP protocol (Streamable HTTP), divided into 7 categories.

### System (3 tools)

| Tool            | Parameters | Description                                            |
| --------------- | ---------- | ------------------------------------------------------ |
| `system_health` | —          | Health status (S3, LLMaaS, number of spaces)           |
| `system_whoami` | —          | 👤 Current token identity (name, permissions, spaces) |
| `system_about`  | —          | Service identity (version, tools, capabilities)        |

### Space (9 tools)

| Tool                 | Parameters                                   | Description                                               |
| -------------------- | -------------------------------------------- | --------------------------------------------------------- |
| `space_create`       | `space_id`, `description`, `rules`, `owner?` | Creates a space with its rules (bank structure)           |
| `space_update`       | `space_id`, `description?`, `owner?`         | Updates description and/or owner                          |
| `space_update_rules` | `space_id`, `rules`                          | 📜 Updates space rules (manage)                          |
| `space_list`         | —                                            | Lists spaces accessible by current token                  |
| `space_info`    | `space_id`                                   | Detailed info (notes, bank, consolidation)                |
| `space_rules`   | `space_id`                                   | Reads immutable space rules                               |
| `space_summary` | `space_id`                                   | Complete summary: rules + bank + stats (agent startup)    |
| `space_export`  | `space_id`                                   | tar.gz export in base64                                   |
| `space_delete`  | `space_id`, `confirm`                        | Deletes the space (⚠️ irreversible, manage required)    |

### Live (3 tools)

| Tool          | Parameters                                  | Description                                                                                                                 |
| ------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `live_note`   | `space_id`, `category`, `content`, `tags?`  | Writes a timestamped note (agent = token name). Categories: observation, decision, todo, insight, question, progress, issue |
| `live_read`   | `space_id`, `limit?`, `category?`, `agent?` | Reads live notes (optional filters)                                                                                         |
| `live_search` | `space_id`, `query`, `limit?`               | Full-text search in notes                                                                                                   |

### Bank (11 tools)

| Tool               | Parameters                        | Description                                                                                             |
| ------------------ | --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `bank_read`        | `space_id`, `filename`            | Reads a bank file (supports subfolders: `personaProfiles/buyer.md`)                                     |
| `bank_read_all`    | `space_id`                        | Reads entire bank in one request (🚀 agent startup)                                                    |
| `bank_list`        | `space_id`                        | Lists bank files with relative paths (without content)                                                  |
| `bank_consolidate` | `space_id`, `agent?`              | 🧠 Enqueues async LLM consolidation. Call once; do not watch/poll unless explicitly requested |
| `bank_consolidation_status` | `job_id`              | Manual-only status check for a job returned by `bank_consolidate` or applied `bank_compact` |
| `bank_consolidation_queues` | `space_ids?`          | Read-only summary of consolidation lanes by space |
| `bank_stale_spaces` | `min_notes?=5`, `min_age_days?=5`, `space_ids?` | 🚨 Lists spaces with ≥N unconsolidated notes whose oldest is ≥D days old (supervision) |
| `bank_compact`     | `space_id`, `dry_run?`            | 🔧 Scans or enqueues strict LLM compaction with UTF-8 byte checks, backup, rollback and audit hashes. `dry_run=True` by default (manage) |
| `bank_repair`      | `space_id`, `dry_run?`            | 🔧 Repairs corrupted filenames (Unicode, parasitic prefixes). `dry_run=True` by default (manage)       |
| `bank_write`       | `space_id`, `filename`, `content` | ✏️ Writes/replaces a bank file directly — bypasses LLM consolidation (manage)                         |
| `bank_delete`      | `space_id`, `filename`            | 🗑️ Deletes a bank file + its Unicode duplicates (manage, irreversible)                               |

Applied `bank_compact` is asynchronous: it joins the same per-space FIFO as
consolidation and returns a `job_id`. For each logical file above
`BANK_FILE_MAX_SIZE`, bounded Map calls create ephemeral cards for complete
Markdown source units and one Reduce writes a compact, non-exhaustive Markdown
digest. The server validates that digest, replaces all eligible historical
units with one code-owned, recompactable container, and requires the candidate
to fit the configured limit. Recent, undated, code-bearing, HTML-bearing and
external content stays byte-identical. In dated mode, the digest may consume at
most 75% of the space left after protected content; the remaining 25% is growth
headroom. All candidates are validated before a full-space backup is created.
Persisted content is read back and verified; failure triggers a verified
`bank/` rollback. If rollback also fails, the job reports the `backup_id` needed
for manual restore. No new `*.part-NNN.md` object is created. Legacy
v2.7.x multipart families are read losslessly, then reassembled into their
single canonical file by compaction, consolidation, or an explicit
`bank_write` restoration.

Since v2.7.1, consolidation validates the complete LLM edit plan before the
first write. Bank and synthesis outputs (plus metadata outside normal batched
mode) are rolled back and verified as one batch on failure; source notes are
deleted only after every fallible operation in that batch has completed. Final
metadata/audit I/O runs after committed batches but can only return `partial`;
it never rolls them back. Partial note deletion exposes verified
restoration/loss metrics.
Multi-file compaction restores only `bank/`, so a live note created
concurrently is never removed by rollback. Terminal job results are persisted
for post-restart audit; active/queued jobs remain an in-memory FIFO.

In the 2.8.0 candidate, automatic pre-consolidation compaction is a gate. Any
preflight, Map, Reduce, candidate, backup, persistence, or rollback failure
blocks `bank_consolidate`; no source note is consumed and no later Bank mutation
starts.

> **2.8.0 release candidate — product-owner accepted, not deployed:** bounded
> Maps plus one Reduce passed the real-corpus mechanical gates. Comparative
> review selected `mistral-small4:119b` as the recommended compaction model: it
> preserved the global meaning and important operational points better than the
> tested Qwen models. `gpt-oss:120b` is not supported for this compaction path:
> it reached `finish_reason=length` with the product Map ceiling of 4,000 tokens
> and remained slower and less faithful in an 8,000-token R&D rerun. Compaction
> is intentionally lossy and still requires a manual canary before production.
> See the
> [2.8.0 hierarchical compaction design](DESIGN/live-mem/COMPACTION_EXTRACTIVE_V2_8.md).

### Graph (4 tools) — 🌉 Link to Graph Memory

| Tool               | Parameters                                           | Description                                                                                               |
| ------------------ | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `graph_connect`    | `space_id`, `url`, `token`, `memory_id`, `ontology?` | Connects a space to Graph Memory. Tests connection, creates memory if needed. Default ontology: `general` |
| `graph_push`       | `space_id`                                           | Synchronizes bank → graph. Smart delete + re-ingest, orphan cleanup. ~30s/file                            |
| `graph_status`     | `space_id`                                           | Connection status + graph stats (documents, entities, relations, top entities, documents list)            |
| `graph_disconnect` | `space_id`                                           | Disconnects (data remains in graph)                                                                       |

### Backup (5 tools)

| Tool              | Parameters                 | Description                              |
| ----------------- | -------------------------- | ---------------------------------------- |
| `backup_create`   | `space_id`, `description?` | Creates a full snapshot on S3            |
| `backup_list`     | `space_id?`                | Lists available backups                  |
| `backup_restore`  | `backup_id`                | Restores a backup (space must not exist) |
| `backup_download` | `backup_id`                | Download as tar.gz base64                |
| `backup_delete`   | `backup_id`                | Deletes a backup                         |

### Admin (8 tools)

| Tool                 | Parameters                                                        | Description                                                                                                  |
| -------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `admin_create_token` | `name`, `permissions`, `space_ids?`, `expires_in_days?`, `email?` | Creates a token (⚠️ displayed only once). Permissions: read, write, manage, admin. Optional email for traceability |
| `admin_list_tokens`  | —                                                                 | Lists active tokens                                                                                          |
| `admin_revoke_token` | `token_hash`                                                      | Revokes a token (makes it unusable)                                                                          |
| `admin_delete_token` | `token_hash`                                                      | Physically deletes a token from the registry (⚠️ irreversible)                                             |
| `admin_purge_tokens` | `revoked_only?`                                                   | Bulk purge: revoked only (default) or all tokens                                                             |
| `admin_update_token` | `token_hash`, `space_ids`, `action`                               | Modifies token spaces (add/remove/set)                                                                       |
| `admin_bulk_update_tokens` | `filters`, `delta`, `confirm?`                            | Bulk token update with filters and add/remove/set operations                                                  |
| `admin_gc_notes`     | `space_id?`, `max_age_days?`, `confirm?`, `delete_only?`          | Garbage Collector: cleans orphaned notes                                                                     |

---

## 🌉 Graph Bridge — Link to Graph Memory

> ⚠️ **Architecture note (v2.5.0) — Live Memory + Graph Memory responsibility separation**
>
> - **Memory Bank** (Live Memory) = compact session bootstrap. `activeContext.md` is a volatile focus snapshot, `progress.md` is a bounded recent journal. The consolidator continuously rewrites and compacts these files.
> - **Graph Memory** = durable semantic index for **stable canonical documents** (RFCs, incidents, runbooks, design docs, infrastructure inventories).
> - **Repository files** = final authority.
>
> **Graph Memory complements the bank; it does not replace it. Graph Memory localizes; canonical repository files confirm.**
>
> Therefore, **`graph_push` is NOT a routine action**: pushing the full bank into the graph teaches it transient content that a later compaction strands as stale. Routine flows should ingest **canonical repository documents** directly into Graph Memory from the agent / tooling layer, using stable `source_path` keys. `graph_push` remains available for one-off bootstrap and explicit debug / migration only.
>
> In particular, `activeContext.md` and `progress.md` **must never** end up in Graph Memory. A future revision (tracked in [`DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md`](DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md)) will turn this into a server-side guardrail. See [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) for the agent-side template.

Live Memory can push its Memory Bank into a [Graph Memory](https://github.com/Cloud-Temple/graph-memory) instance for long-term memory. The knowledge graph extracts entities, relations, and embeddings from bank files.

### Workflow

```
1. graph_connect(space_id, url, token, memory_id, ontology="general")
   └─ Tests connection, creates Graph Memory if needed

2. bank_consolidate(space_id)
   └─ Queues async consolidation; call once and do not watch/poll unless explicitly requested

3. graph_push(space_id)
   ├─ Lists documents in Graph Memory
   ├─ For each modified bank file:
   │   ├─ document_delete (removes orphaned entities)
   │   └─ memory_ingest (complete graph recalculation)
   ├─ Cleans deleted bank documents
   └─ Updates metrics (last_push, push_count)

4. graph_status(space_id)
   └─ Stats: 79 entities, 61 relations, top entities, documents...
```

### Smart Push (delete + re-ingest)

Each push is a **complete refresh** of the graph for that file. Existing files are deleted then re-ingested so Graph Memory recalculates entities, relations, and embeddings with up-to-date content.

### Available Ontologies

| Ontology            | Usage                                      |
| ------------------- | ------------------------------------------ |
| `general` (default) | Versatile: FAQ, specs, certifications, CSR |
| `legal`             | Legal documents, contracts                 |
| `cloud`             | Cloud infrastructure, product sheets       |
| `managed-services`  | Managed services, outsourcing              |
| `presales`          | Pre-sales, RFP/RFI, proposals              |

---

## 🖥️ Web Interface

Live Memory exposes a **web interface** on `/live` to visualize memory spaces in real-time.

### Access

```
http://localhost:8080/live
```

### Features

| Zone                               | Content                                                                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **📊 Dashboard** (left)           | Space info, consolidation (date + counters), live/bank stats, colored agents, categories with %, Markdown rules, Graph Memory |
| **🔴 Live Timeline** (top-right)  | Live notes grouped by date (Today/Yesterday/date), cards with agent + category + Markdown                                     |
| **📘 Bank Viewer** (bottom-right) | Consolidated file tabs, Markdown rendering with marked.js                                                                     |

### Layout

```
┌──────────────┬────────────────────────────┐
│  📊 Dashboard│  🔴 Live Timeline          │
│  (info,      │  (auto-refresh, date group)│
│   agents,    ├────────────────────────────┤
│   rules...)  │  📘 Bank (Markdown tabs)   │
└──────────────┴────────────────────────────┘
```

### Smart Auto-refresh

- Configurable: 3s / 5s / 10s / 30s / manual
- **Anti-flicker**: only re-renders DOM if data has changed
- Pulsing green dot with last refresh timestamp
- Space selection → immediate loading (no button needed)

### REST API (5 endpoints)

| Endpoint                        | Description                                              |
| ------------------------------- | -------------------------------------------------------- |
| `GET /api/spaces`               | List of spaces                                           |
| `GET /api/space/{id}`           | Complete info (meta + rules + stats + graph-memory)      |
| `GET /api/live/{id}`            | Live notes (filters: `?agent=`, `?category=`, `?limit=`) |
| `GET /api/bank/{id}`            | Bank file list                                           |
| `GET /api/bank/{id}/{filename}` | Bank file content                                        |

`/api/*` endpoints require a Bearer Token. `/live` page and `/static/*` files are public.

### Admin Console (`/admin`)

A full **administration console** is available at `/admin`, exposing all 43 MCP tools through a web interface:

```
http://localhost:8080/admin
```

| Section | Features |
| --- | --- |
| **📊 Dashboard** | Health status (clickable → service details), spaces count, active tokens, version/uptime, identity bar |
| **📂 Spaces** | CRUD, info/rules modals, explore link, delete with confirmation |
| **🔑 Tokens** | Create/update/revoke/delete, visual space chips with delta calculation |
| **🔍 Explorer** | Live notes + bank files side-by-side for any space |
| **💾 Backups** | Create/restore/delete, "Backup All", dynamic columns |
| **🌉 Graph Bridge** | Status check, push, disconnect per space |
| **🧹 Maintenance** | Consolidate, compact, repair, GC, purge — single space selector, compact action list |

- **Auth**: requires a valid token (same as `/live`), session via HttpOnly cookie
- **CSP-safe**: zero inline handlers, all via `data-action` + event delegation
- **Upload Rules**: file picker (`.md`) or paste directly from the Rules modal

---

## 🔌 MCP Integration

> 📖 **Full Guide**: See [`CLINE_INTEGRATION_GUIDE.md`](CLINE_INTEGRATION_GUIDE.md) for the step-by-step guide (Cline configuration, custom instructions, workflow, multi-agents, troubleshooting). Equivalent guides exist for [`CLAUDE_CODE_INTEGRATION.md`](CLAUDE_CODE_INTEGRATION.md) and [`CODEX_INTEGRATION.md`](CODEX_INTEGRATION.md).

### With Cline (VS Code / VSCodium)

In Cline's MCP settings (`cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN"
      }
    }
  }
}
```

To configure the **Custom Instructions** for your agent, copy one of the two workspace rule templates into your Cline global Custom Instructions (or into a `.clinerules/` directory in your project):

| Template                                                                | When to use                                                                                  |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md)                  | Workspaces with **Live Memory only**.                                                        |
| [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md)  | Workspaces also connected to **Graph Memory** (Graph-first lookup, compaction discipline, agent-side ingestion). |

Customize a few placeholders (`{LIVE_MCP_SERVER}`, `{SPACE}`, and for the advanced template `{GRAPH_MCP_SERVER}` / `{GRAPH_MEMORY_ID}`). The agent name is **auto-detected** from the authentication token — nothing else to configure.

> 💡 **Ready-to-use templates**: [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md) (Live-only) and [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) (Live + Graph) — copy and customize the placeholders.
>
> 📖 **Detailed integration guides**: [`CLINE_INTEGRATION_GUIDE.md`](CLINE_INTEGRATION_GUIDE.md), [`CLAUDE_CODE_INTEGRATION.md`](CLAUDE_CODE_INTEGRATION.md), [`CODEX_INTEGRATION.md`](CODEX_INTEGRATION.md).

### With Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN"
      }
    }
  }
}
```

### Via Python (MCP client)

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def example():
    headers = {"Authorization": "Bearer your_token"}
    async with streamablehttp_client("http://localhost:8080/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Load all context
            result = await session.call_tool("bank_read_all", {
                "space_id": "my-project"
            })

            # Write a note
            await session.call_tool("live_note", {
                "space_id": "my-project",
                "category": "observation",
                "content": "Build passing in CI"
            })
```

---

## 💻 CLI and Shell

### CLI Installation

```bash
pip install click rich prompt-toolkit mcp[cli]>=1.8.0
export MCP_URL=http://localhost:8080
export MCP_TOKEN=your_token
```

### CLI Commands (Click)

```bash
python scripts/mcp_cli.py health
python scripts/mcp_cli.py whoami                       # Current token identity
python scripts/mcp_cli.py about
python scripts/mcp_cli.py space list
python scripts/mcp_cli.py space create my-project --rules-file rules.md
python scripts/mcp_cli.py live note my-project observation "Build OK"
python scripts/mcp_cli.py bank consolidate my-project
python scripts/mcp_cli.py bank read-all my-project
python scripts/mcp_cli.py token create agent-cline read,write
python scripts/mcp_cli.py graph connect my-project URL TOKEN MEM-ID -o general
python scripts/mcp_cli.py graph push my-project
python scripts/mcp_cli.py graph status my-project
python scripts/mcp_cli.py graph disconnect my-project
```

### Interactive Shell

```bash
python scripts/mcp_cli.py shell
```

Autocomplete, history, Rich display. See [scripts/README.md](scripts/README.md) for full reference.

---

## 🧪 Tests

Unified test script with **4 selectable suites** via `--suite`:

```bash
docker compose up -d   # Prerequisite

# All suites (44 tests, ~60s)
python scripts/test_recette.py --url http://localhost:8080

# Single suite
python scripts/test_recette.py --suite recette     # Agent pipeline (7 tests)
python scripts/test_recette.py --suite isolation    # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite      # MCP tools (19 tests)

# Graph Memory suite (optional, requires running graph-memory)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token your_token

# List available suites
python scripts/test_recette.py --list

# Step-by-step + verbose
python scripts/test_recette.py --suite isolation -v --step --no-cleanup
```

| Suite       | Tests | Description                                                                         |
| ----------- | ----- | ----------------------------------------------------------------------------------- |
| `recette`   | 7     | Full pipeline: token → notes → LLM consolidation → bank                             |
| `isolation` | 18    | Multi-tenant isolation v0.7.1: cross-space access, backup filtering, auto-add token |
| `qualite`   | 19    | MCP tools regression testing: system, admin, space, live, bank, backup, GC          |
| `graph`     | ~8    | Graph Memory bridge: connect, push, status, disconnect (optional)                   |

---

## 🔒 Security

### Authentication

- **Bearer Token** mandatory on all MCP requests
- **Bootstrap key** to create the first admin token
- **SHA-256 Tokens** stored on S3 (never in clear text)
- **3 levels**: read, write, admin
- **Space scope**: a token can be limited to specific spaces

### WAF (Caddy + Coraza)

- **OWASP CRS**: SQL/XSS injection, path traversal, SSRF
- **Rate Limiting**: 200 MCP/min (Streamable HTTP)
- **Automatic TLS**: Let's Encrypt in production (`SITE_ADDRESS=domain.com`)
- **Non-root container**: `mcp` user

---

## 📂 Project Structure

```
live-memory/
├── src/live_mem/              # Source code (43 MCP tools + web interface)
│   ├── server.py              # FastMCP server + middlewares
│   ├── config.py              # pydantic-settings configuration
│   ├── auth/                  # Authentication
│   │   ├── middleware.py      #   Auth + Logging + StaticFiles
│   │   └── context.py         #   check_access, check_write, check_admin
│   ├── static/                # /live web interface
│   │   ├── live.html          #   SPA (Dashboard + Live + Bank)
│   │   ├── css/live.css       #   Styles (Cloud Temple theme)
│   │   ├── js/                #   7 JS modules (config, api, app, dashboard, timeline, bank, sidebar)
│   │   └── img/               #   Cloud Temple SVG Logo
│   ├── core/                  # Business services
│   │   ├── storage.py         #   S3 dual SigV2/SigV4 (Dell ECS)
│   │   ├── space.py           #   Memory spaces CRUD
│   │   ├── live.py            #   Live notes (append-only)
│   │   ├── consolidator.py    #   LLM Pipeline (4 steps)
│   │   ├── graph_bridge.py    #   🌉 Link to Graph Memory
│   │   ├── tokens.py          #   SHA-256 tokens management
│   │   ├── backup.py          #   S3 snapshots
│   │   ├── gc.py              #   Garbage Collector
│   │   ├── locks.py           #   asyncio locks per space
│   │   └── models.py          #   Pydantic models
│   └── tools/                 # MCP Tools (7 modules)
│       ├── system.py          #   3 tools (health, whoami, about)
│       ├── space.py           #   9 tools (spaces CRUD)
│       ├── live.py            #   3 tools (notes)
│       ├── bank.py            #   11 tools (bank + consolidation + supervision + maintenance)
│       ├── graph.py           #   4 tools (Graph Bridge)
│       ├── backup.py          #   5 tools (snapshots)
│       └── admin.py           #   8 tools (tokens + GC + purge + bulk)
├── scripts/                   # CLI + Shell + Tests
├── waf/                       # Caddy + Coraza WAF
├── WORKSPACE_CLINE_RULES.md           # 📋 Cline Custom Instructions template — Live Memory only
├── WORKSPACE_CLINE_ADVANCE_RULES.md   # 📋 Cline Custom Instructions template — Live Memory + Graph Memory
├── RULES/                     # 📜 Memory Bank rules templates (general, book, medical, presales, product management, company steering)
├── DESIGN/live-mem/           # 9 architecture documents
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml             # Dependencies & project config (uv)
├── uv.lock                    # uv lockfile
├── VERSION                    # 2.7.3
├── CHANGELOG.md
└── FAQ.md
```

---

## 🔍 Troubleshooting

### Service does not start

```bash
docker compose logs live-mem-service --tail 50
docker compose logs waf --tail 20
```

### 401 Unauthorized

- Check your token: `Authorization: Bearer YOUR_TOKEN`
- Bootstrap key is not a token — create a token first via `admin_create_token`

### Consolidation fails

- Check LLMaaS credentials in `.env`
- Default timeout is 600s — increase `CONSOLIDATION_TIMEOUT` if needed
- `bank_consolidate` returns an async job acknowledgement (`running` or `queued`) with `next_action="return_to_user_without_polling"`; call it once and do not watch/poll unless explicitly requested
- `bank_consolidation_status(job_id)` remains available for manual status checks only

---

## 🤝 Contributing

Development is driven **entirely through GitHub** — issues, branches, pull
requests, code reviews and project status all live there. This makes the
project easy to **pilot remotely from the command line** with the `gh` CLI
(including by AI coding agents): create an issue, branch, open a PR, review
and merge without ever leaving the terminal or the GitHub UI.

The full, mandatory workflow is documented in
**[`WORKSPACE_WORKFLOW_GIT.md`](WORKSPACE_WORKFLOW_GIT.md)**:

- **Branch + PR only** — no local merge into `main`; every change lands
  through a pull request merged on GitHub.
- **Issue lifecycle** — self-assign, move the Projects status to *In
  Progress*, keep solution-design discussion in the issue.
- **PR ↔ issue link** — a `Closes #N` keyword in the PR **body** auto-closes
  the issue on merge.
- **PR-channel reviews** — once a PR is open, code-review discussion moves to
  the PR; every review conclusion is published on GitHub (`gh pr review` /
  `gh pr comment`), not only in chat.

Following this file keeps the issue and PR histories clean and auditable, and
lets a contributor (or an agent) drive the whole cycle reproducibly via `gh`.

---

## 🔗 Related Projects

| Project          | Description                              | Link                                                                                 |
| ---------------- | ---------------------------------------- | ------------------------------------------------------------------------------------ |
| **graph-memory** | Long-term memory (Knowledge Graph + RAG) | [github.com/Cloud-Temple/graph-memory](https://github.com/Cloud-Temple/graph-memory) |

---

## 📄 License

Apache License 2.0

---

## 👤 Author

**Cloud Temple** — [cloud-temple.com](https://www.cloud-temple.com)

Developed by **Christophe Lesur**.

---

*Live Memory v2.7.3 — Shared working memory for collaborative AI agents*
