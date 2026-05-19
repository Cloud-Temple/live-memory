# ❓ FAQ — Live Memory

🇫🇷 [Version française](FAQ.fr.md)

---

## General Concepts

### What is the difference between Live Memory and graph-memory?

|                  | **Live Memory**                  | **graph-memory**                   |
| ---------------- | -------------------------------- | ---------------------------------- |
| **Type**         | Working memory                   | Long-term memory                   |
| **Data**         | Live notes + Markdown bank       | Knowledge Graph + embeddings       |
| **Storage**      | S3 (files)                       | Neo4j + Qdrant                     |
| **Intelligence** | LLM consolidates notes into bank | Vector RAG for search              |
| **Analogy**      | Whiteboard → Project notebook    | Library → Search engine            |

Both are complementary. Live Memory is for daily work, graph-memory is for persistent knowledge.

### What is a "space"?

An isolated memory space = a project. It contains:
- **Rules**: Markdown template defining the bank structure
- **Live notes**: observations, decisions, todos... from agents (append-only)
- **Bank**: Markdown files consolidated by the LLM according to rules

### What are "rules"?

Rules define the Memory Bank structure. They are written in Markdown at space creation and are **immutable**. The LLM uses them to create and maintain bank files.

Example rules (standard Memory Bank):
```markdown
### projectbrief.md
Objectives, scope, success criteria.

### activeContext.md
Current focus, recent changes, next steps.

### progress.md
What works, what's left, known issues.
```

---

## Agents and Tokens

### What is the relationship between a token and an agent?

Since **v0.8.1**, each token **is** an agent. The token's `client_name` is automatically used as the agent identity — there is no `agent=` parameter in `live_note`.

|                        | **Token = Agent**                             |
| ---------------------- | --------------------------------------------- |
| **Role**               | Authentication **and** identity               |
| **Example**            | Token `cline-dev` → agent `cline-dev`         |
| **Shareable?**         | No — 1 token = 1 agent = 1 identity           |
| **Where provided?**    | `Authorization: Bearer` header (auto-detected) |

**Why this change?** The old model (Token ≠ Agent) allowed passing a free agent name, causing orphaned notes (agent not recognized during consolidation), identity spoofing, and fragmentation.

### Can an agent read another agent's notes?

Yes! `live_read(space_id="my-project")` returns notes from ALL agents. That's the collaboration principle: each agent sees the work of others. You can also filter by agent: `live_read(space_id="my-project", agent="claude-review")`.

---

## Permissions and Security

### What are the permission levels?

Since **v1.5.0**, there are 4 **hierarchical and cumulative** levels:

| Level      | Includes              | Access                                                                                                                                             |
| ---------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **read**   | —                     | Read: `bank_read`, `live_read`, `space_info`, `backup_list`, etc.                                                                                  |
| **write**  | read                  | Write: `live_note`, `bank_consolidate`, `space_create`, etc.                                                                                       |
| **manage** | write + read          | Maintenance: `bank_write`, `bank_delete`, `bank_repair`, `bank_compact`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete`   |
| **admin**  | manage + write + read | Administration: `admin_create_token`, `admin_gc_notes`, etc.                                                                                       |

A `write` token **cannot** directly modify bank files or delete spaces — `manage` or `admin` is required.

### Why are permissions cumulative?

Each level **automatically includes** all lower levels. You don't need to specify `read,write` if you grant `manage` — `manage` already includes `write` and `read`.

```
read < write < manage < admin
```

In practice, when creating or updating a token, always specify the **full list** of permissions (e.g.: `"read,write,manage"`), because the `permissions` field is an **explicit list** stored on S3, not a single level. The server checks for the presence of the required level in this list.

### What type of token should I create for my use case?

| Use case | Recommended permissions | `space_ids` |
| --- | --- | --- |
| AI agent in work mode (Cline, Claude) | `read,write` | Project spaces |
| AI agent + maintenance (compaction, repair) | `read,write,manage` | Project spaces |
| Human operator (multi-project maintenance) | `read,write,manage` | All relevant spaces |
| Administrator | `read,write,manage,admin` | Empty (admin sees everything) |
| Reader / monitoring dashboard | `read` | Spaces to monitor |

### How to restrict a token to specific spaces?

Each token has a `space_ids` field listing authorized spaces:

```bash
# Restrict KSE to 3 spaces
python scripts/mcp_cli.py token update sha256:363... -p "read,write" -s "live-mem,graph-mem,mcp-office"
```

**`space_ids` semantics (v1.5.0+)**:
- `space_ids = ["a", "b"]` → access only to these spaces
- `space_ids = []` for a **non-admin** → **no access** (changed in v1.5.0, was "all" before)
- `space_ids = []` for an **admin** → access to **everything** (unchanged)

When **creating** a token via `admin_create_token`, you can use:
- `space_ids=""` (default) → "mute" token (no access to existing spaces). The response contains a `warning_no_access` field to explicitly signal this.
- `space_ids="a,b,c"` → explicit list.
- `space_ids="*"` or `space_ids="all"` → **snapshot** of all existing spaces at creation time (not future spaces — intentional to stay aligned with strict v1.5.0 semantics).

### The hash returned by `admin_list_tokens` contains `sha256:` — should I pass it as-is?

Since issue #11, **both forms are accepted** by `admin_revoke_token`, `admin_delete_token`, and `admin_update_token`:
```bash
admin_update_token(token_hash="sha256:f172084ef03...", space_ids="x")  # OK
admin_update_token(token_hash="f172084ef03...", space_ids="x")          # OK too
```

The minimum is still 16 hex characters (8 hash bytes) to avoid accidental collisions.

### What happens when a token creates a new space?

The space is **automatically added** to the token's `space_ids` (via `add_space_to_token()`). So a token restricted to `["project-a"]` that creates `project-b` ends up with `["project-a", "project-b"]`. No UX deadlock.

### How to add the `manage` permission to a token?

```bash
python scripts/mcp_cli.py token update sha256:xxx -p "read,write,manage"
```

⚠️ Permission updates **replace** the full list — always include `read,write` in addition to `manage`.

### What happened during the v1.5.0 migration?

Before v1.5.0, `space_ids=[]` meant "access to everything". Since v1.5.0, it means "no access" (for non-admin tokens).

**Automatic migration at startup**: all non-admin tokens with `space_ids=[]` were automatically assigned the list of **all existing spaces**. No access loss.

### Can I give admin rights to a token?

Yes, but with caution:
```bash
python scripts/mcp_cli.py token update sha256:xxx -p "read,write,manage,admin"
```

An admin token can manage other tokens, consolidate all agents' notes, and run the GC. It sees all spaces regardless of its `space_ids`.

---

## Consolidation

### How does consolidation work?

1. The LLM reads the **rules**, the **current bank**, the **previous synthesis**, and the **live notes**
2. It produces updated bank files (pure Markdown)
3. Consolidated notes are **deleted** from `live/`
4. A residual synthesis is saved

### What happens if 2 agents consolidate at the same time?

An `asyncio.Lock` per space prevents simultaneous consolidations:
- The first agent acquires the lock → LLM consolidation (15-30s)
- The second receives `{"status": "queued"}` with a `job_id` and queue position

This is intentional: both agents write to the same bank files. Sequential consolidation lets each agent see the previous one's work.

### Can I consolidate ALL agents' notes at once?

Yes! `bank_consolidate(space_id="my-project")` without an `agent=` parameter consolidates all notes from all agents in a single pass.

⚠️ **Permissions**: consolidating another agent's notes or all agents' notes requires a **manage** (or admin) token. A write token can only consolidate its own notes (`agent="my-name"`).

### What happens to notes after consolidation?

They are **deleted** from `live/`. Their content is integrated into bank files. This is irreversible (hence the value of backups).

### Can the consolidator invent content (hallucinate)?

Since **v1.9.0**, the consolidator includes **7 anti-hallucination rules** in its system prompt:

1. **Strict source attribution** — every fact in the bank MUST come from a note. If a section has no source, it stays empty or is marked "TBD".
2. **Domain vocabulary preservation** — project-specific terms are used verbatim, never reinterpreted via LLM priors.
3. **Metrics gating** — numbers only appear if explicitly sourced from a note.
4. **No invented structures** — file trees are NOT generated unless notes describe them.
5. **Agent/task isolation** — facts from different agents or independent tasks are never merged into the same sentence.
6. **Replaced items removal** — when a `decision` note replaces a plan, old items are removed.
7. **Transitive status inference** — if Step N+1 is completed, Step N is marked completed.

Additionally, each note is transmitted to the LLM with its **metadata** `[agent, category, tags]`, enabling proper source isolation.

**If you still see hallucinated content**, report it on [Issue #17](https://github.com/Cloud-Temple/live-memory/issues/17) with the notes and bank output.

### What is bank compaction (`bank_compact`)?

When bank files grow too large (> `BANK_FILE_MAX_SIZE`, default 15 KB), they may cause consolidation failures (LLM context window overflow) or slow performance.

`bank_compact` summarizes oversized files via a dedicated LLM call, preserving key decisions and milestones while removing obsolete details.

```bash
# Scan only (dry-run, default)
python scripts/mcp_cli.py bank compact my-space

# Apply compaction
python scripts/mcp_cli.py bank compact my-space --apply
```

**Auto-compaction** is also triggered automatically before consolidation if the bank exceeds `COMPACT_THRESHOLD` (default 60%) of the LLM's output budget.

### Can I use an HTTP proxy for outbound connections?

Yes! Since **v1.8.1**, set `PROXY_URL` in `.env`:

```env
PROXY_URL=http://10.0.0.1:3128
```

This routes S3 (boto3) and LLM (httpx) traffic through the proxy. It's a **custom variable** (not `HTTP_PROXY`) to avoid affecting other Python libraries. Graph Memory connections are not supported through the proxy.

---

## Garbage Collector

### Why a Garbage Collector?

If an agent writes notes but never consolidates (crash, deletion, oversight), notes accumulate endlessly in `live/`. The GC identifies and handles these orphaned notes.

### How does the GC work?

3 modes via `admin_gc_notes`:

| Mode              | Parameters                       | Action                                                                 |
| ----------------- | -------------------------------- | ---------------------------------------------------------------------- |
| **Dry-run**       | `confirm=False` (default)        | Scans and reports                                                      |
| **Consolidation** | `confirm=True`                   | Consolidates notes into bank via LLM + adds a "⚠️ GC" notice         |
| **Deletion**      | `confirm=True, delete_only=True` | Deletes without consolidating (data loss)                              |

By default, the GC **consolidates** (does not delete) to avoid data loss.

### Does the GC leave a trace in the bank?

Yes! The GC writes a special note before each consolidation:
```
⚠️ GARBAGE COLLECTOR — Forced consolidation
The GC detected X orphaned notes from agent 'agent-name' (> 7 days).
These notes were never consolidated by the agent.
```

The LLM sees this note and integrates it into the bank, ensuring traceability.

---

## Docker and Deployment

### How to test locally?

```bash
# 1. Configure environment
cp .env.example .env
nano .env  # Fill in S3, LLMaaS, ADMIN_BOOTSTRAP_KEY

# 2. Start the stack
docker compose build
docker compose up -d

# 3. Test
python scripts/test_recette.py           # Basic acceptance
python scripts/test_hallucination.py     # Anti-hallucination (Issue #17)
```

### How does the WAF work?

Caddy + Coraza (OWASP CRS) protects against injections, XSS, etc. MCP routes (Streamable HTTP) are authenticated by token on the server side. Other routes pass through the WAF.

### How to deploy to production?

1. Set `SITE_ADDRESS=my-domain.com` in `.env`
2. Expose ports 80+443 in docker-compose.yml
3. Caddy automatically obtains a Let's Encrypt certificate
4. See [DEPLOIEMENT_PRODUCTION.md](DESIGN/live-mem/DEPLOIEMENT_PRODUCTION.md) for details

---

## S3 and Storage

### Why S3 and not a database?

- Simplicity: no schema, no migrations, no DB server
- Portability: everything is Markdown/JSON files
- Scalability: S3 handles billions of objects
- Cost: S3 storage is very affordable

### Why two S3 clients (SigV2 + SigV4)?

Constraint of Dell ECS (Cloud Temple S3):
- SigV2 for data operations (PUT, GET, DELETE)
- SigV4 for metadata operations (HEAD, LIST)

If you use AWS S3 or MinIO, a single SigV4 client is sufficient.

### Can I use AWS S3 or MinIO?

Yes! Configure `S3_ENDPOINT_URL` and credentials. The dual SigV2/V4 is only needed for Dell ECS. For other S3 providers, modify `core/storage.py` to use a single client.

---

## CLI and Shell

### How to configure the CLI?

3 ways to pass the URL and token:

```bash
# 1. Environment variables
export MCP_URL=http://localhost:8080
export MCP_TOKEN=lm_xxx
python scripts/mcp_cli.py health

# 2. CLI parameters
python scripts/mcp_cli.py --url http://my-server:8080 --token lm_xxx health

# 3. Automatic (reads .env)
python scripts/mcp_cli.py health   # Default URL 8080, token from .env
```

### How to get help on a command?

```bash
# CLI Click (native --help)
python scripts/mcp_cli.py space --help
python scripts/mcp_cli.py bank consolidate --help

# Interactive shell
live-mem> help           # global help
live-mem> help space     # space subcommands
live-mem> space          # same
live-mem> help bank      # bank subcommands
```

### Can I use the CLI in JSON mode for scripting?

Yes! Add `--json` to any command:

```bash
python scripts/mcp_cli.py space list --json | jq '.spaces[].space_id'
```

---

## Troubleshooting — Common Issues

### I get a 403 on all spaces

**Most common cause**: your token has `space_ids=[]` (no access). Since v1.5.0, a non-admin token without `space_ids` cannot access anything.

**Diagnosis**:
```bash
python scripts/mcp_cli.py token list --json | jq '.tokens[] | select(.name=="my-token") | .space_ids'
```

**Solution**: ask an admin to update your spaces:
```bash
python scripts/mcp_cli.py token update sha256:xxx -s "space-a,space-b"
```

### My `manage` token can't do anything

A `manage` token without `space_ids` is a "maintainer with nothing to maintain". It can only create new spaces (which are auto-added to its `space_ids`).

**Solution**: add spaces to manage:
```bash
python scripts/mcp_cli.py token update sha256:xxx -s "space-a,space-b"
```

### Consolidation fails with "LLM returned invalid JSON"

Probable cause: the bank is too large. The LLM has a limited context window and may fail on long JSON responses.

**Solutions**:
1. Compact the bank: `bank_compact my-space --apply`
2. Check sizes: `bank_list my-space` — if a file exceeds 15 KB, it's a compaction candidate
3. Retry consolidation after compaction

### `bank_consolidate` returns "queued"

Another agent (or yourself in another terminal) is consolidating the same space. Your request was accepted and will run after earlier same-space jobs.

**Solution**: keep the returned `job_id` and call `bank_consolidation_status(job_id)`, or inspect `space_info` for the queue summary.

### I can't find my notes after consolidation

That's normal! Notes are **deleted** from `live/` after consolidation. Their content is integrated into bank files. Use `bank_read_all` to find the consolidated content.

If you think notes were lost, check the residual synthesis: `space_summary my-space`.

---

## Limits and Performance

### How many notes can be written?

No theoretical limit. Each note = 1 S3 file (~200-500 bytes). Consolidation processes up to 500 notes at a time (`CONSOLIDATION_MAX_NOTES`).

### What is the latency?

| Operation                     | Typical latency |
| ----------------------------- | --------------- |
| `live_note` (write)           | ~50ms           |
| `live_read` (read)            | ~100ms          |
| `bank_consolidate` (12 notes) | ~15-30s         |
| `bank_read_all` (6 files)     | ~200ms          |
| `system_health`               | ~500ms          |

### How many simultaneous agents?

No limit on the number of agents writing in parallel (append-only, zero conflicts). Consolidation is queued FIFO per space (1 job mutates a space's bank at a time).
