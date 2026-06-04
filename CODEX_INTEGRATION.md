# 🔌 Live Memory Integration Guide for OpenAI Codex

> **Version**: 2.1.0 | **Date**: 2026-05-16

This guide walks you through connecting **OpenAI Codex** to **Live Memory**, giving it a shared, persistent working memory across coding sessions.

---

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [Step 1 — Obtain a Live Memory Token](#-step-1--obtain-a-live-memory-token)
- [Step 2 — Configure Codex via `.codex/config.toml`](#-step-2--configure-codex-via-codexconfigtoml)
- [Step 3 — Create a Memory Space](#-step-3--create-a-memory-space)
- [Step 4 — Give Codex Instructions](#-step-4--give-codex-instructions)
- [Recommended Workflow](#-recommended-workflow)
- [Troubleshooting](#-troubleshooting)

---

## 📦 Prerequisites

| Component          | Detail                                                              |
| ------------------ | ------------------------------------------------------------------- |
| **OpenAI Codex**   | CLI or environment with MCP server support                          |
| **Live Memory**    | Running instance (self-hosted or Cloud Temple managed service)      |
| **Bearer Token**   | `read,write` token created on your Live Memory instance            |

---

## 🔑 Step 1 — Obtain a Live Memory Token

Codex needs a **Bearer Token** with at minimum `read,write` permissions.

### Option A — Via the CLI

```bash
cd /path/to/live-memory
export MCP_TOKEN=<your_ADMIN_BOOTSTRAP_KEY>

# Create a "write" token for Codex
python scripts/mcp_cli.py token create codex-agent read,write
```

The CLI will display something like:

```
Token created successfully!
  Name   : codex-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  This token will NEVER be displayed again. Copy it now!
```

> **⚠️ IMPORTANT**: Copy this token immediately! It will never be shown again (only the SHA-256 hash is stored).

### Option B — Via the Admin Console

1. Open `https://<your-live-mem-instance>/admin` in your browser
2. Log in with your admin credentials
3. Navigate to **Admin → Tokens**
4. Click **Create Token**, fill in the name (`codex-agent`), set permissions to `read,write`
5. Copy the displayed token

### Option C — Cloud Temple Managed Service

If you are using the **Cloud Temple managed Live Memory** instance, your token has already been provisioned. Use it directly — it looks like:

```
lm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ Your token is confidential. Never include it in documentation or commit it to a repository.

---

## ⚙️ Step 2 — Configure Codex via `.codex/config.toml`

Codex reads its MCP server configuration from `.codex/config.toml` at the root of your project (or in your home directory for global configuration).

### 2.1 Create or Edit the Configuration File

```bash
mkdir -p ~/.codex
# or at project level:
mkdir -p .codex
```

### 2.2 Add the Live Memory Server

Open `.codex/config.toml` and add the following section:

```toml
[mcp_servers.my-live-mem]
http_headers = { "Authorization" = "Bearer lm_YOUR_TOKEN_HERE" }
enabled = true
url = "https://my.live-mem.mcp.cloud-temple.app/mcp"
```

> **Replace** `lm_YOUR_TOKEN_HERE` with the token obtained in Step 1.

### 2.3 Full Example with Cloud Temple Managed Service

```toml
[mcp_servers.my-live-mem]
http_headers = { "Authorization" = "Bearer lm_YOUR_TOKEN_HERE" }
enabled = true
url = "https://my.live-mem.mcp.cloud-temple.app/mcp"
```

### 2.4 Self-Hosted Instance Example

```toml
[mcp_servers.live-memory]
http_headers = { "Authorization" = "Bearer lm_YOUR_TOKEN_HERE" }
enabled = true
url = "https://live-mem.your-domain.com/mcp"
```

For a local development instance:

```toml
[mcp_servers.live-memory]
http_headers = { "Authorization" = "Bearer lm_YOUR_TOKEN_HERE" }
enabled = true
url = "http://localhost:8080/mcp"
```

### 2.5 Where to Place `config.toml`

| Scope           | Location                           | When to Use                            |
| --------------- | ---------------------------------- | -------------------------------------- |
| **Global**      | `~/.codex/config.toml`             | All projects share the same server     |
| **Per-project** | `<project-root>/.codex/config.toml`| Per-project MCP configuration          |

> **Precedence**: project-level config overrides global config if both exist.

### 2.6 Verify the Connection

After saving `config.toml`, test connectivity:

```bash
# Should return {"status": "ok", ...}
curl -s -H "Authorization: Bearer lm_YOUR_TOKEN_HERE" \
  https://my.live-mem.mcp.cloud-temple.app/health | jq .
```

---

## 📁 Step 3 — Create a Memory Space

Before Codex can write notes, you need a **memory space** with **rules** that define the Memory Bank structure.

### Via the Live Memory CLI

```bash
python scripts/mcp_cli.py space create my-project \
  --rules-file ./RULES/live-mem.standard.memory.bank.md \
  -d "My Codex project"
```

### Via Codex Directly (MCP Tool)

Ask Codex to create the space using the `space_create` MCP tool:

> *"Use the `space_create` tool with `space_id='my-project'` and standard Memory Bank rules (projectbrief, activeContext, progress, techContext, systemPatterns, productContext)."*

### Standard Rules Template

```markdown
# Memory Bank Rules

## Files to Maintain

### projectbrief.md
Vision, objectives, project scope.

### activeContext.md
Current focus, work in progress, recent decisions, next steps.

### progress.md
What works, what remains to build, known issues.

### techContext.md
Technologies used, configuration, technical constraints.

### systemPatterns.md
Architecture, patterns, technical decisions, components.

### productContext.md
Why this project exists, problems solved, user experience.
```

---

## 📝 Step 4 — Give Codex Instructions

> 🔭 **Workspace also connected to Graph Memory?** When the same workspace uses both Live Memory **and** a Graph Memory MCP server (durable semantic index for incidents, RFCs, runbooks, cross-document recall), base your `AGENTS.md` on the advanced rules template [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) rather than the standard block below. It adds Graph-first lookup, bank compaction discipline, and agent-side ingestion. **Key invariants** (apply regardless of agent): the Live Memory consolidator never ingests anything into Graph Memory; Graph ingestion stays an explicit, scoped agent action started from canonical repository files; never put tokens or endpoints in the rules.

For Codex to automatically use Live Memory, add instructions in a `AGENTS.md` file at the root of your project (Codex automatically loads it as agent-level instructions).

### 4.1 Recommended `AGENTS.md` Template

```markdown
# Codex Agent Instructions — Live Memory MCP

My memory resets completely between sessions. I depend ENTIRELY on the Memory Bank
to understand the project and continue effectively.

## MCP Server Configuration

My persistent memory is managed by the **Live Memory** MCP server (`my-live-mem`).

> **The only value to customize:**
> - **SPACE** = `my-project`  ← Replace with your space_id
>
> All instructions below use `{SPACE}`. Agent name is auto-detected from the token.

## At the Start of EVERY Task (MANDATORY)

1. Call `space_rules("{SPACE}")` to read the rules (bank structure)
2. Call `bank_read_all("{SPACE}")` to load ALL consolidated context
3. Call `live_read(space_id="{SPACE}")` to read **unconsolidated notes**
4. Read the content carefully before starting
5. Identify the current focus in `activeContext.md`

> ⚠️ NEVER start working without reading the bank first.

## During Work

Write frequent, atomic notes with `live_note`:

```
live_note(space_id="{SPACE}", category="<category>", content="...")
```

**Categories**: `observation`, `decision`, `progress`, `issue`, `todo`, `insight`, `question`

## At Session End

```
bank_consolidate(space_id="{SPACE}")
```

> 🔕 `bank_consolidate` is **fire-and-forget**: it returns an async job ack (`running` / `queued`) with `next_action="return_to_user_without_polling"`. **Call it once and return to the user.** Do not watch or poll. `bank_consolidation_status(job_id)` exists for **explicit manual checks only**.

## Mandatory Rules

1. **NEVER write directly to the bank** — only the LLM consolidation does that
2. **Always pass `space_id="{SPACE}"`** in every call
3. **Write atomic notes after each significant step** — 1 note = 1 fact, 1 decision, or 1 task
4. **Consolidate at session end** — call `bank_consolidate` once and return to the user without polling (no automatic `bank_consolidation_status` loop)
5. **Read the bank at startup** — never work without context
```

### 4.2 Minimalist Version (inline prompt)

```
You have access to Live Memory (MCP server: my-live-mem).
- At startup: space_rules("my-project"), bank_read_all("my-project"), live_read("my-project")
- During work: live_note(space_id="my-project", category="...", content="...")
- At session end: bank_consolidate(space_id="my-project") — call once and return without polling
The agent name is auto-detected from the authentication token.
```

---

## 🔄 Recommended Workflow

```
┌────────────────────────────────────────────────┐
│  1. STARTUP                                    │
│     space_rules("my-project")                  │
│     bank_read_all("my-project")                │
│     live_read("my-project")                    │
│     → Codex reads rules + bank + live notes    │
├────────────────────────────────────────────────┤
│  2. WORK (loop)                                │
│     • Codex codes, analyzes, responds          │
│     • live_note("observation", "Tests pass")   │
│     • live_note("decision", "Using FastAPI")   │
│     • live_note("todo", "Add auth")            │
│     • live_note("progress", "API done")        │
├────────────────────────────────────────────────┤
│  3. SESSION END                                │
│     bank_consolidate("my-project")             │
│     → LLM synthesizes notes into bank          │
│     → Live notes deleted after success         │
└────────────────────────────────────────────────┘
```

### Consolidation Frequency

| Situation                    | Recommendation                           |
| ---------------------------- | ---------------------------------------- |
| Short session (< 10 notes)   | Consolidate at session end               |
| Long session (> 20 notes)    | Consolidate every 15–20 notes            |
| Context switch               | Consolidate before changing topics       |
| End of day                   | Always consolidate                       |

---

## 👥 Multi-agent: Codex + Cline + Others

Live Memory enables **multiple agents** to collaborate on the same memory space:

1. Create one token per agent (`codex-agent`, `cline-agent`, `claude-agent`, etc.)
2. Configure each agent with its own token
3. All agents share the same `space_id`

Agent identity is **automatically inferred from the token** — no manual specification needed.

Inter-agent communication happens **through the shared space**:

```
Codex  → live_note(category="todo", content="Add pagination to /users endpoint")
Cline  → live_read(category="todo")  ← sees Codex's task
Cline  → live_note(category="progress", content="Pagination implemented")
Codex  → live_read(category="progress")  ← picks up where Cline left off
```

---

## 🔍 Troubleshooting

### Codex Doesn't See Live Memory Tools

1. Verify `config.toml` is in the correct location and the TOML syntax is valid
2. Ensure `enabled = true` is set in the `[mcp_servers.my-live-mem]` section
3. Confirm the URL ends with `/mcp`
4. Test the token manually:

```bash
curl -s -H "Authorization: Bearer lm_YOUR_TOKEN_HERE" \
  https://my.live-mem.mcp.cloud-temple.app/health
```

### "401 Unauthorized" Error

- The token is incorrect, expired, or revoked
- Verify the header value: `"Authorization" = "Bearer lm_..."` (note the `lm_` prefix)
- Check if the token has been revoked via the admin console

### "Access Denied to Space" Error

The token is restricted to certain spaces (`space_ids`). Either:
- Create a token without space restriction
- Or add the space to the token:
  ```
  admin_update_token(token_hash, space_ids_add="my-project")
  ```

### Consolidation Is Slow or Times Out

LLM consolidation typically takes 30–120 seconds. If Codex times out:

1. Check if your Codex environment allows configuring a longer MCP timeout
2. Monitor server-side progress in logs:

```bash
docker compose logs -f live-mem-service --tail 20
```

3. Use `bank_consolidate` in smaller batches (it processes notes in batches of 10 by default)

### TOML Syntax Errors

Common mistakes in `config.toml`:

```toml
# ✅ CORRECT
http_headers = { "Authorization" = "Bearer lm_abc123" }

# ❌ WRONG (JSON syntax, not TOML)
http_headers = { "Authorization": "Bearer lm_abc123" }

# ❌ WRONG (missing quotes around value)
http_headers = { "Authorization" = Bearer lm_abc123 }
```

---

## 📊 Summary

| Step      | Action                                                    | Time       |
| --------- | --------------------------------------------------------- | ---------- |
| 1         | Obtain a token (`token create codex-agent`)               | 1 min      |
| 2         | Edit `.codex/config.toml` with URL + Authorization header | 2 min      |
| 3         | Create a memory space (`space_create`)                    | 30 sec     |
| 4         | Add `AGENTS.md` with Memory Bank instructions             | 2 min      |
| **Total** | **Ready to use**                                          | **~6 min** |

---

*Live Memory Integration Guide for OpenAI Codex v1.0.0 — [Full Documentation](README.md)*
