# Architecture — Live Memory MCP Server

> **Version**: 1.6.0 | **Date**: 2026-04-25 | **Author**: Cloud Temple
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
| **LLM used**      | gpt-oss:120b (extraction)      | qwen3.5:27b (consolidation)                   |
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
│  │  42 MCP Tools   │  │  LLM Service     │                 │
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
| **MCP Server**           | Python MCP server (42 tools, 7 categories) | FastMCP + Uvicorn (ASGI)                 |
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
        5. Applies operations surgically
           on existing bank files (v0.6.0)
           → What is not touched remains intact byte-for-byte
           → Zero content loss (vs full rewrite)
        6. Writes _synthesis.md (residual for next consolidation)
        7. Deletes processed live notes (LAST — atomicity)
        8. Updates _meta.json (counters)
```

### 4.4 Graph Push (Bridge to Graph Memory)

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

Live Memory also exposes an **administration console** on `/admin` covering all 42 MCP tools:

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
CONSOLIDATION_MAX_NOTES=500      # Max notes per consolidation
```

---

*Document updated April 25, 2026 — Live Memory v1.6.0*
