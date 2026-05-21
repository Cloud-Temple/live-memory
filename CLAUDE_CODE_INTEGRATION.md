# 🔌 Live Memory Integration Guide for Claude Code

> **Version**: 1.0.0 | **Date**: 2026-05-16

This guide walks you through connecting **Claude Code** (Anthropic's CLI, or its IDE extension) to **Live Memory** to give it shared, persistent working memory.

---

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [Step 1 — Start Live Memory](#-step-1--start-live-memory)
- [Step 2 — Create a token for Claude Code](#-step-2--create-a-token-for-claude-code)
- [Step 3 — Connect Claude Code to Live Memory](#-step-3--connect-claude-code-to-live-memory)
- [Step 4 — Create a memory space](#-step-4--create-a-memory-space)
- [Step 5 — Give Claude Code its instructions](#-step-5--give-claude-code-its-instructions)
- [Recommended Workflow](#-recommended-workflow)
- [Multi-agent: Claude Code + Cline + Claude Desktop + others](#-multi-agent-claude-code--cline--claude-desktop--others)
- [Troubleshooting](#-troubleshooting)
- [With Claude Desktop](#-with-claude-desktop)
- [Summary](#-summary)

---

## 📦 Prerequisites

| Component            | Version            | Check                               |
| -------------------- | ------------------ | ----------------------------------- |
| **Docker**           | ≥ 24.0             | `docker --version`                  |
| **Docker Compose**   | v2                 | `docker compose version`            |
| **Claude Code**      | ≥ 2.1              | `claude --version`                  |
| **Live Memory**      | Deployed & running | `curl http://localhost:8080/health` |

> 💡 If Claude Code is not installed: `npm install -g @anthropic-ai/claude-code` (macOS/Linux/Windows) or use the dedicated installer — see Anthropic's official documentation. Claude Code provides the `claude` command in the terminal and ships IDE extensions (VS Code, JetBrains) that share the same configuration.

---

## 🚀 Step 1 — Start Live Memory

If Live Memory is not yet running:

```bash
cd /path/to/live-memory
cp .env.example .env
# Edit .env with your S3 credentials, LLMaaS settings, and ADMIN_BOOTSTRAP_KEY
docker compose build
docker compose up -d
```

**Check**:

```bash
# Should return {"status": "ok", ...}
curl -s http://localhost:8080/health | jq .
```

---

## 🔑 Step 2 — Create a token for Claude Code

Claude Code needs a **Bearer Token** with `read,write` permissions to read and write the memory.

### Option A — Via the CLI

```bash
cd /path/to/live-memory
export MCP_TOKEN=<your_ADMIN_BOOTSTRAP_KEY>

# Create a "read,write" token for Claude Code
python scripts/mcp_cli.py token create claude-code-agent read,write
```

The CLI will print something like:

```
Token created successfully!
  Name   : claude-code-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  This token will NEVER be displayed again. Copy it now!
```

> **⚠️ IMPORTANT**: Copy this token immediately! It will never be shown again (only the SHA-256 hash is stored).

### Option B — Via the bootstrap key (temporary)

For a quick test, you can use the `ADMIN_BOOTSTRAP_KEY` defined in your `.env` directly. But **in production**, always create a dedicated token with minimal permissions.

---

## ⚙️ Step 3 — Connect Claude Code to Live Memory

Claude Code stores its MCP configuration in a JSON file. Three scopes are available:

| Scope     | Location                                       | Reach                              |
| --------- | ---------------------------------------------- | ---------------------------------- |
| `local`   | `~/.claude.json` (key `projects.<cwd>`)        | Current directory only             |
| `user`    | `~/.claude.json` (top-level `mcpServers` key)  | All projects of the current user   |
| `project` | `.mcp.json` at the project root                | Committed to the repo (teams)      |

For personal multi-project use, the `user` scope is usually the most convenient.

### 3.1 — CLI method (recommended)

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  https://your-server/mcp \
  --header "Authorization: Bearer lm_YOUR_TOKEN_HERE"
```

For a local server over HTTP:

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  http://localhost:8080/mcp \
  --header "Authorization: Bearer lm_YOUR_TOKEN_HERE"
```

### 3.2 — Manual edit

If you prefer editing the JSON directly, add the following block to `~/.claude.json` (`user` scope, under the top-level `mcpServers` key):

```json
{
  "mcpServers": {
    "live-memory": {
      "type": "http",
      "url": "https://your-server/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

> **Replace** `lm_YOUR_TOKEN_HERE` with the token from Step 2 and `your-server` with your domain (or `localhost:8080` locally).

For the `project` scope (config shared across the team), create a `.mcp.json` file at the project root with the same format.

### 3.3 — Verify the connection

After configuration:

```bash
claude mcp list
```

You should see `live-memory` with a connected status. Then launch Claude Code in a project and ask:

> *"Call `system_health` on live-memory and show me the response."*

If Claude replies with `{"status": "ok", ...}`, the connection works.

### 3.4 — Whitelist the tools (avoid permission prompts)

Claude Code asks for confirmation on every unauthorized MCP tool call. To avoid these interruptions, add the Live Memory tools to the project (or user) allow-list.

Create or edit `.claude/settings.local.json` at the project root:

```json
{
  "permissions": {
    "allow": [
      "mcp__live-memory__space_list",
      "mcp__live-memory__space_info",
      "mcp__live-memory__space_rules",
      "mcp__live-memory__bank_read_all",
      "mcp__live-memory__bank_read",
      "mcp__live-memory__live_read",
      "mcp__live-memory__live_note",
      "mcp__live-memory__live_search",
      "mcp__live-memory__bank_consolidate",
      "mcp__live-memory__system_health"
    ]
  }
}
```

> 💡 **Naming convention**: Claude Code exposes each MCP tool as `mcp__<server-name>__<tool-name>`. If you named your server `live-memory-prod` in Step 3.1, adjust the prefix accordingly.

Interactive alternative: type `/permissions` in a Claude Code session to open the permissions editor.

For a global configuration (all projects), use `~/.claude/settings.json` instead.

### 3.5 — Remote HTTPS server

For a production deployment, the URL and JSON block are identical — only the scheme changes (`https://` instead of `http://`). No additional option is required on the Claude Code side.

---

## 📁 Step 4 — Create a memory space

Before Claude Code can write notes, you need a **memory space** with **rules** that define the Memory Bank structure.

### Via the CLI

```bash
python scripts/mcp_cli.py space create my-project \
  --rules-file ./RULES/standard.memory.bank.md \
  -d "My development project"
```

Several rule templates are provided in the `RULES/` directory of the repo:

| Template                                  | Use case                                              |
| ----------------------------------------- | ----------------------------------------------------- |
| `RULES/standard.memory.bank.md`           | Classic Cline Memory Bank (6 project files)           |
| `RULES/product.management.memory.bank.md` | Product team (vision, portfolio, personas, features)  |
| `RULES/medical.memory.bank.md`            | Patient follow-up / clinical file                     |
| `RULES/presales.memory.bank.md`           | Pre-sales, prospect qualification, RFP                |
| `RULES/book.memory.bank.md`               | Book writing / editorial project                      |
| `RULES/live-mem.standard.memory.bank.md`  | Development of the Live Memory server itself          |

### Through Claude Code directly

You can also ask Claude to create the space. Just tell it:

> *"Use the `space_create` tool to create a space called `my-project` with standard Memory Bank rules (projectbrief, activeContext, progress, techContext, systemPatterns, productContext)."*

Claude Code will invoke the MCP `space_create` tool.

### Example of standard rules

```markdown
# Memory Bank Rules

## Files to maintain

### projectbrief.md
Vision, goals, project scope.

### activeContext.md
Current focus, ongoing work, recent decisions, next steps.

### progress.md
What works, what's left to do, known issues.

### techContext.md
Technologies used, configuration, technical constraints.

### systemPatterns.md
Architecture, patterns, technical decisions, components.

### productContext.md
Why this project exists, problems solved, user experience.
```

---

## 📝 Step 5 — Give Claude Code its instructions

Claude Code automatically reads `CLAUDE.md` files on startup. Two possible locations:

| Location                  | Reach                                              | Recommended for                       |
| ------------------------- | -------------------------------------------------- | ------------------------------------- |
| `<project-root>/CLAUDE.md` | The current project (committed with the repo)     | Project-specific workflow             |
| `~/.claude/CLAUDE.md`     | All projects of the current user (private)         | Global preferences, identity, style   |

For Live Memory, the project-level `CLAUDE.md` is the ideal spot because `{SPACE}` is project-specific.

### Recommended template (paste into `CLAUDE.md`)

This template uses the `{SPACE}` placeholder — you only need to configure **one value**:

```markdown
# Memory Bank — Live Memory MCP

My memory resets completely between sessions. I depend ENTIRELY on the Memory Bank to understand the project and continue effectively.

## 🔌 Configuration (to customize per project)

My persistent memory is managed by the **Live Memory** MCP server (`live-memory`).

> **⚙️ The only value to customize:**
>
> - **SPACE** = `my-project`       ← Replace with your space_id
>
> All instructions below use `{SPACE}` — I substitute it automatically with the value above.
> The agent name is **auto-detected** from the authentication token (no need to configure it).

## 📖 At the start of EVERY task (MANDATORY)

1. Call `space_rules("{SPACE}")` to read the rules (bank structure)
2. Call `bank_read_all("{SPACE}")` to load ALL consolidated context
3. Call `live_read(space_id="{SPACE}")` to read **unconsolidated notes**
4. Read the content carefully before starting
5. Identify the current focus in `activeContext.md`

> ⚠️ NEVER start working without having read the bank.
>
> 💡 **Why read live notes?** Between sessions, notes may have been written (by me or other agents) without being consolidated yet. These notes contain recent context not yet reflected in the bank files. Ignoring them = risking redoing work already done or missing recent decisions.

## 📝 During work

Write frequent, atomic notes via `live_note`:

    live_note(space_id="{SPACE}", category="<category>", content="...")

The `agent` parameter is **auto-detected** from the token — no need to pass it.

**Categories**:
- `observation` — Factual findings, command results
- `decision` — Technical choices and their rationale
- `progress` — Advancement, completed work
- `issue` — Problems encountered, bugs
- `todo` — Identified tasks to do
- `insight` — Learnings, discovered patterns
- `question` — Points to clarify, pending decisions

## 🧠 At session end (or after a significant work block)

    bank_consolidate(space_id="{SPACE}")

The LLM will consolidate **my own notes** (agent auto-detected from token) by updating the bank files according to the space rules.

> ℹ️ Only an admin can consolidate notes from all agents (`agent=""`).
>
> 🔕 `bank_consolidate` is **fire-and-forget**: it returns an async job ack (`running` / `queued`) with `next_action="return_to_user_without_polling"`. **Call it once and return to the user.** Do not watch or poll. `bank_consolidation_status(job_id)` exists for **explicit manual checks only**.

## ⚠️ Strict rules

1. **NEVER write directly into the bank** — only the LLM consolidation does that
2. **Always pass `space_id="{SPACE}"`** in every call
3. **Write atomic notes after each significant step** — 1 note = 1 fact, 1 decision, or 1 task
4. **Consolidate at session end** — call `bank_consolidate` once and return to the user without polling (no automatic `bank_consolidation_status` loop)
5. **Read the bank at startup** — never work without context

## 🔄 When to request an update

If the user says **"update memory bank"**:
1. Write `live_note` notes summarizing the current state of work
2. Call `bank_consolidate(space_id="{SPACE}")`
3. Verify the result with `bank_read_all("{SPACE}")`

## 📊 Useful commands

| Action                          | Command                                                                   |
| ------------------------------- | ------------------------------------------------------------------------- |
| Read full context               | `bank_read_all("{SPACE}")`                                                |
| Read rules                      | `space_rules("{SPACE}")`                                                  |
| Write a note                    | `live_note(space_id="{SPACE}", category="...", content="...")`            |
| Consolidate                     | `bank_consolidate(space_id="{SPACE}")`                                    |
| See recent notes                | `live_read(space_id="{SPACE}")`                                           |
| See another agent's notes       | `live_read(space_id="{SPACE}", agent="other-agent")`                      |
| Space info                      | `space_info("{SPACE}")`                                                   |
```

> 💡 **For a new project**: copy this file into `<project-root>/CLAUDE.md`, change the `SPACE` line, that's it!

### Minimalist version (`~/.claude/CLAUDE.md` global)

If you'd rather not commit Live Memory instructions in every project, add this short block to `~/.claude/CLAUDE.md`:

```
You have access to Live Memory (MCP server "live-memory").
- At startup: space_rules("{SPACE}"), bank_read_all("{SPACE}"), live_read("{SPACE}")
- During work: live_note(space_id="{SPACE}", category="...", content="...")
- At session end: bank_consolidate(space_id="{SPACE}") — call once and return without polling
`{SPACE}` is defined in the current project's CLAUDE.md. The agent is auto-detected from the token.
```

Each project then declares only its `{SPACE}` value in its own `CLAUDE.md`.

---

## 🔄 Recommended Workflow

### Typical development session workflow

```
┌────────────────────────────────────────────────┐
│  1. STARTUP                                    │
│     space_rules("my-project")                  │
│     bank_read_all("my-project")                │
│     live_read("my-project")                    │
│     → Claude reads rules + bank + live notes   │
├────────────────────────────────────────────────┤
│  2. WORK (loop)                                │
│     • Claude codes, analyzes, replies          │
│     • live_note("observation", "Build OK")     │
│     • live_note("decision", "Going with X")    │
│     • live_note("todo", "Tests to write")      │
│     • live_note("progress", "Auth done")       │
├────────────────────────────────────────────────┤
│  3. SESSION END                                │
│     bank_consolidate("my-project")             │
│     → LLM synthesizes notes into the bank      │
│     → Live notes deleted after success         │
└────────────────────────────────────────────────┘
```

### Consolidation frequency

| Situation                   | Recommendation                       |
| --------------------------- | ------------------------------------ |
| Short session (< 10 notes)  | Consolidate at session end           |
| Long session (> 20 notes)   | Consolidate every 15–20 notes        |
| Context switch              | Consolidate before switching topics  |
| End of day                  | Always consolidate                   |

### Real-time visualization

While Claude Code works, open the web UI to watch live:

```
http://localhost:8080/live
```

Notes will appear in real time in the **Live Timeline**, and the **Bank** updates after each consolidation.

---

## 👥 Multi-agent: Claude Code + Cline + Claude Desktop + others

Live Memory lets **multiple agents** collaborate on the same memory space.

### Scenario: Claude Code (dev) + Cline (review) + Claude Desktop (synthesis)

For several agents to collaborate, create **one token per identity**:

1. `admin_create_token name="claude-code-dev"`
2. `admin_create_token name="cline-review"`
3. `admin_create_token name="claude-desktop-synth"`
4. Configure each agent with its own token

The agent's identity is **automatically derived from its token** every time it calls `live_note` or `bank_consolidate`. No `agent` parameter to pass.

### Agent-to-agent communication

Agents don't talk to each other directly. They communicate **through the shared space**:

```
Claude Code   → live_note(category="question", content="Should we support CSV?")
Cline         → live_read(category="question")   ← sees the question
Cline         → live_note(category="decision", content="No, JSON only")
Claude Code   → live_read(category="decision")   ← sees the answer
```

### Per-agent consolidation

Each agent consolidates **its own notes** without interfering with others'. If an agent has **admin** rights, it can consolidate notes from all agents by calling `bank_consolidate` (which, for an admin, defaults to processing everyone).

---

## 🔍 Troubleshooting

### `claude mcp list` doesn't show live-memory

1. Check the server is running: `curl http://localhost:8080/health`
2. Check the JSON syntax in `~/.claude.json` (no trailing comma, braces closed)
3. Fully quit Claude Code and relaunch — the file is read only at startup
4. Inspect the logs: `claude --debug` then run a short session

### "401 Unauthorized" error

- Token is wrong, expired, or revoked
- Make sure the header is `"Authorization": "Bearer lm_..."` (with the `lm_` prefix)
- Watch for stray spaces/newlines when copy-pasting the token
- The bootstrap key works for tests, but create a real token for normal use

### "Access denied to space" error

The token is restricted to certain spaces (`space_ids`). Either:
- Create a token without space restriction (empty `space_ids` parameter)
- Or add the space to the token: `admin_update_token(token_hash, space_ids="my-project", action="add")`

### Claude Code prompts for permission on every call

Whitelist the tools via `.claude/settings.local.json` (see Step 3.4), or type `/permissions` in the session to add them interactively.

### Claude Code doesn't use Live Memory on its own

Without an explicit `CLAUDE.md`, Claude Code doesn't know it should call these tools at the start of a session. Add the Step 5 template to `<project-root>/CLAUDE.md` or `~/.claude/CLAUDE.md`.

### MCP won't connect behind a VPN or proxy

If Live Memory is on a remote server, check that:
- Port 443 (HTTPS) or 8080 (HTTP) is reachable
- The URL in the Claude Code config is correct (with `/mcp` at the end)
- Manual test: `curl -H "Authorization: Bearer lm_..." https://your-server/mcp`

### Following a consolidation in progress

Server-side, watch the logs:

```bash
docker compose logs -f live-mem-service --tail 20
```

Claude Code keeps the HTTP connection open for the entire call, so a long consolidation doesn't typically cause client-side timeout issues.

---

## 🖥️ With Claude Desktop

Configuration is similar to Claude Code, but the file changes. Edit `claude_desktop_config.json`:

| OS          | Location                                                          |
| ----------- | ----------------------------------------------------------------- |
| **macOS**   | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json`                     |
| **Linux**   | `~/.config/Claude/claude_desktop_config.json`                     |

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      },
      "timeout": 600
    }
  }
}
```

> **⚠️ For Claude Desktop**: add `"timeout": 600` to allow long consolidations. Claude Code does not need this parameter.

Restart Claude Desktop after the change. The Live Memory tools will appear in the available tools list.

> ℹ️ **Note**: Claude Desktop does not provide a per-tool allow-list system (unlike Claude Code). Permissions are managed at the application level.

---

## 📊 Summary

| Step      | Action                                                  | Time       |
| --------- | ------------------------------------------------------- | ---------- |
| 1         | Start Live Memory (`docker compose up -d`)              | 1 min      |
| 2         | Create a token (`mcp_cli.py token create`)              | 30 sec     |
| 3         | Configure Claude Code (`claude mcp add`)                | 1 min      |
| 3.4       | Whitelist the tools (`.claude/settings.local.json`)     | 1 min      |
| 4         | Create a space (`space_create`)                         | 30 sec     |
| 5         | Add the project's `CLAUDE.md`                           | 2 min      |
| **Total** | **Ready to use**                                        | **~6 min** |

---

*Live Memory ↔ Claude Code integration guide v1.0.0 — [Full documentation](README.md)*
