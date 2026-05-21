# 🔌 Live Memory Integration Guide for Cline (VS Code / VSCodium)

> **Version**: 1.2.0 | **Date**: 2026-03-27

This guide walks you step by step through connecting **Cline** (the AI agent in VS Code or VSCodium) to **Live Memory** to give it a shared, persistent working memory.

---

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [Step 1 — Start Live Memory](#-step-1--start-live-memory)
- [Step 2 — Create a Token for Cline](#-step-2--create-a-token-for-cline)
- [Step 3 — Configure Cline in VS Code / VSCodium](#-step-3--configure-cline-in-vs-code--vscodium)
- [Step 4 — Create a Memory Space](#-step-4--create-a-memory-space)
- [Step 5 — Give Cline Instructions](#-step-5--give-cline-instructions)
- [Recommended Workflow](#-recommended-workflow)
- [Custom Instructions for Cline](#-custom-instructions-for-cline)
- [Multi-agent: Cline + Claude + Others](#-multi-agent--cline--claude--others)
- [Troubleshooting](#-troubleshooting)
- [With Claude Desktop](#-with-claude-desktop)

---

## 📦 Prerequisites

| Component                   | Version            | Verification                        |
| --------------------------- | ------------------ | ----------------------------------- |
| **Docker**                  | ≥ 24.0             | `docker --version`                  |
| **Docker Compose**          | v2                 | `docker compose version`            |
| **VS Code** or **VSCodium** | Recent             | —                                   |
| **Cline Extension**         | Recent             | Installed from the marketplace      |
| **Live Memory**             | Deployed & running | `curl http://localhost:8080/health`  |

---

## 🚀 Step 1 — Start Live Memory

If Live Memory is not running yet:

```bash
cd /path/to/live-memory
cp .env.example .env
# Edit .env with your S3, LLMaaS credentials, and ADMIN_BOOTSTRAP_KEY
docker compose build
docker compose up -d
```

**Verify**:

```bash
# Should return {"status": "ok", ...}
curl -s http://localhost:8080/health | jq .
```

---

## 🔑 Step 2 — Create a Token for Cline

Cline needs a **Bearer Token** with `read,write` permissions to read from and write to the memory.

### Option A — Via the CLI

```bash
cd /path/to/live-memory
export MCP_TOKEN=<your_ADMIN_BOOTSTRAP_KEY>

# Create a "write" token for Cline
python scripts/mcp_cli.py token create cline-agent read,write
```

The CLI will display something like:

```
Token created successfully!
  Name   : cline-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  This token will NEVER be displayed again. Copy it now!
```

> **⚠️ IMPORTANT**: Copy this token immediately! It will never be shown again (only the SHA-256 hash is stored).

### Option B — Via the bootstrap key (temporary)

For a quick test, you can use the `ADMIN_BOOTSTRAP_KEY` defined in your `.env` directly. But **in production**, always create a dedicated token with minimal permissions.

---

## ⚙️ Step 3 — Configure Cline in VS Code / VSCodium

### 3.1 Open Cline's MCP Settings

1. Open VS Code / VSCodium
2. Open the Cline panel (Cline icon in the sidebar)
3. Click the **⚙️ Settings** icon (gear) at the top of the Cline panel
4. Look for **"MCP Servers"** or click the **MCP** tab
5. Click **"Edit MCP Settings"** (or the button to edit the JSON)

### 3.2 Add Live Memory as an MCP Server

In the `cline_mcp_settings.json` file that opens, add the following configuration:

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

> **Replace** `lm_YOUR_TOKEN_HERE` with the token obtained in Step 2.
> **⚠️ The `timeout` parameter is critical**: LLM consolidation can take more than 60 seconds (Cline's default timeout). It is essential to increase it to 600 seconds, in accordance with your `.env` configuration.

### 3.3 Where is the Config File?

| OS                 | Typical Location                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| **macOS**          | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`     |
| **Linux**          | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`                         |
| **VSCodium macOS** | `~/Library/Application Support/VSCodium/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| **VSCodium Linux** | `~/.config/VSCodium/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`                     |

### 3.4 Verify the Connection

After saving the config file:

1. **Restart Cline** (or reload VS Code with `Ctrl+Shift+P` → "Developer: Reload Window")
2. In the Cline panel, click the **MCP** tab
3. You should see **"live-memory"** with a green ✅ indicator
4. Click on it to see the **38 available tools**

### 3.5 Remote Server (production)

If Live Memory is deployed on a server with HTTPS:

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "https://live-mem.your-domain.com/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      },
      "timeout": 600
    }
  }
}
```

---

## 📁 Step 4 — Create a Memory Space

Before Cline can write notes, you need a **memory space** with **rules** that define the Memory Bank structure.

### Via the CLI

```bash
python scripts/mcp_cli.py space create my-project \
  --rules-file ./rules/standard.md \
  -d "My development project"
```

### Via Cline Directly

You can also ask Cline to create the space. Simply tell it:

> *"Use the `space_create` tool to create a space 'my-project' with standard Memory Bank rules (projectbrief, activeContext, progress, techContext, systemPatterns, productContext)."*

Cline will use the `space_create` MCP tool to do it.

### Standard Rules Example

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

## 📝 Step 5 — Give Cline Instructions

For Cline to automatically use Live Memory, add **Custom Instructions** to its settings.

### 5.1 Where to Configure Custom Instructions

In Cline: **Settings** → **Custom Instructions**, or better yet, place a `WORKSPACE_CLINE_RULES.md` file at the root of your project (Cline automatically loads it as workspace-level instructions).

The repository ships a ready-to-use template: [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md). Simply copy it to your project root and customize the `SPACE` value.

### 5.2 Recommended Instructions (template with `{SPACE}`)

Copy the content below into your agent's **Custom Instructions** (or into a `.clinerules` file at the root of your project). This template uses the `{SPACE}` placeholder — you only need to set **one value**:


```markdown
# Cline's Memory Bank — Live Memory MCP

My memory resets completely between sessions. I depend ENTIRELY on the Memory Bank to understand the project and continue effectively.

## 🔌 Configuration (customize per project)

My persistent memory is managed by the **Live Memory** MCP server (`my-live-mem`).

> **⚙️ The only value to customize:**
>
> - **SPACE** = `my-project`       ← Replace with your space_id
>
> All instructions below use `{SPACE}` — I automatically substitute it with the value above.
> The agent name is **auto-detected** from the authentication token (no configuration needed).

## 📖 At the Start of EVERY Task (MANDATORY)

1. Call `space_rules("{SPACE}")` to read the rules (bank structure)
2. Call `bank_read_all("{SPACE}")` to load ALL consolidated context
3. Call `live_read(space_id="{SPACE}")` to read **unconsolidated notes**
4. Read the content carefully before starting
5. Identify the current focus in `activeContext.md`

> ⚠️ NEVER start working without reading the bank first.
>
> 💡 **Why read live notes?** Between sessions, notes may have been written (by me or other agents) without being consolidated into the bank. These notes contain recent context that does not yet appear in bank files. Ignoring them = risking redoing work already done or missing recent decisions.

## 📝 During Work

Write frequent, atomic notes with `live_note`:

live_note(space_id="{SPACE}", category="<category>", content="...")

The `agent` parameter is **auto-detected** from the token — no need to pass it.

**Categories**:
- `observation` — Factual findings, command outputs
- `decision` — Technical choices and their justification
- `progress` — Advancement, what is completed
- `issue` — Problems encountered, bugs
- `todo` — Identified tasks to do
- `insight` — Learnings, patterns discovered
- `question` — Points to clarify, pending decisions

## 🧠 At Session End (or after a significant block of work)

bank_consolidate(space_id="{SPACE}")

The LLM will consolidate **my own notes** (agent auto-detected from the token) by updating the bank files according to the space's rules.

> ℹ️ Only a manage+ user can consolidate all agents' notes (`agent=""`).
>
> 🔕 `bank_consolidate` is **fire-and-forget**: it returns an async job ack (`running` / `queued`) with `next_action="return_to_user_without_polling"`. **Call it once and return to the user.** Do not watch or poll. `bank_consolidation_status(job_id)` exists for **explicit manual checks only**.

## ⚠️ Mandatory Rules

1. **NEVER write directly to the bank** — only the LLM consolidation does that
2. **Always pass `space_id="{SPACE}"`** in every call
3. **Write atomic notes after each significant step** — 1 note = 1 fact, 1 decision, or 1 task
4. **Consolidate at session end** — call `bank_consolidate` once and return to the user without polling (no automatic `bank_consolidation_status` loop)
5. **Read the bank at startup** — never work without context

## 🔄 When to Request an Update

If the user asks **"update memory bank"**:
1. Write `live_note` notes summarizing the current state of work
2. Call `bank_consolidate(space_id="{SPACE}")`
3. Verify the result with `bank_read_all("{SPACE}")`

## 📊 Useful Commands

| Action                          | Command                                                                   |
| ------------------------------- | ------------------------------------------------------------------------- |
| Read all context                | `bank_read_all("{SPACE}")`                                                |
| Read the rules                  | `space_rules("{SPACE}")`                                                  |
| Write a note                    | `live_note(space_id="{SPACE}", category="...", content="...")`            |
| Consolidate                     | `bank_consolidate(space_id="{SPACE}")`                                    |
| View recent notes               | `live_read(space_id="{SPACE}")`                                           |
| View another agent's notes      | `live_read(space_id="{SPACE}", agent="other-agent")`                      |
| Space info                      | `space_info("{SPACE}")`                                                   |
```

> 💡 **For a new project**: copy this file, change the `SPACE` line, and you're done!

---

## 🔄 Recommended Workflow

### Typical Development Session Workflow

```
┌────────────────────────────────────────────────┐
│  1. STARTUP                                    │
│     space_rules("my-project")                  │
│     bank_read_all("my-project")                │
│     live_read("my-project")                    │
│     → Cline reads rules + bank + live notes    │
├────────────────────────────────────────────────┤
│  2. WORK (loop)                                │
│     • Cline codes, analyzes, responds          │
│     • live_note("observation", "Build OK")     │
│     • live_note("decision", "Going with X")    │
│     • live_note("todo", "Tests to write")      │
│     • live_note("progress", "Auth completed")  │
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
| Long session (> 20 notes)    | Consolidate every 15-20 notes            |
| Context switch                | Consolidate before changing topics       |
| End of day                    | Always consolidate                       |

### Real-time Visualization

While Cline works, open the web interface to follow along live:

```
http://localhost:8080/live
```

You'll see notes appear in real time in the **Live Timeline** and the **Bank** update after each consolidation.

---

## 📋 Custom Instructions for Cline

### Template Version (recommended)

Copy [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md) to the root of your project. Cline automatically loads this file as workspace-level instructions.

Then modify **only the `SPACE` value** to match your project. The agent name is auto-detected.

### Minimalist Version (copy-paste into Custom Instructions)

If you want an ultra-short version, add this to the global Custom Instructions:

```
You have access to Live Memory (MCP server).
- At startup: space_rules("{SPACE}"), bank_read_all("{SPACE}"), live_read("{SPACE}")
- During work: live_note(space_id="{SPACE}", category="...", content="...")
- At session end: bank_consolidate(space_id="{SPACE}") — call once and return without polling
Where {SPACE} = "my-project". The agent is auto-detected from the token.
```

---

## 👥 Multi-agent: Cline + Claude + Others

Live Memory enables **multiple agents** to collaborate on the same memory space.

### Scenario: Cline (dev) + Claude (review)

For two agents to collaborate, simply create **two different tokens** for them:

1. Create the token for Cline (`admin_create_token name="cline-dev"`)
2. Create the token for Claude (`admin_create_token name="claude-review"`)
3. Configure each agent with its own token

The agent identity is **automatically inferred from its token** every time it calls `live_note` or `bank_consolidate`. They don't need to specify it.

### Inter-agent Communication

Agents don't talk to each other directly. They communicate **via the shared space**:

```
Cline  → live_note(category="question", content="Should we support CSV?")
Claude → live_read(category="question")  ← sees Cline's question
Claude → live_note(category="decision", content="No, JSON only")
Cline  → live_read(category="decision")  ← sees Claude's answer
```

### Per-agent Consolidation

Each agent consolidates **their own notes** without interfering with others:

```
Cline  → bank_consolidate(space_id="my-project")  # Only consolidates cline-dev's notes
Claude → bank_consolidate(space_id="my-project")  # Only consolidates claude-review's notes
```

If an agent has **admin** permissions, it can consolidate everyone's notes by calling `bank_consolidate` (which by default processes all agents for an admin).

---

## 🔍 Troubleshooting

### Cline Doesn't See Live Memory Tools

1. Verify the server is running: `curl http://localhost:8080/health`
2. Check JSON syntax in `cline_mcp_settings.json` (no trailing comma)
3. Reload VS Code (`Ctrl+Shift+P` → "Developer: Reload Window")
4. In Cline's MCP tab, check if `live-memory` shows in red (connection error)

### "401 Unauthorized" Error

- The token is incorrect or revoked
- Verify the header is `"Authorization": "Bearer lm_..."` (with the `lm_` prefix)
- The bootstrap key works for testing, but create a proper token for regular use

### "Access Denied to Space" Error

The token is restricted to certain spaces (`space_ids`). Either:
- Create a token without space restriction (empty `space_ids` parameter)
- Or add the space to the token: `admin_update_token(token_hash, space_ids="my-project", action="add")`

### Cline Doesn't Use Live Memory Spontaneously

Add explicit **Custom Instructions** (see [Step 5](#-step-5--give-cline-instructions)). Without instructions, Cline doesn't know it should use these tools.

### Timeout Error / Consolidation Fails After 60 Seconds

By default, Cline and Claude Desktop interrupt MCP requests after 60 seconds, which is often insufficient for a consolidation (the LLM can take several minutes).

1. Verify you've added `"timeout": 600` in your agent's MCP configuration, matching the server timeout in your `.env` file.
2. You can follow real-time progress server-side in the logs:

```bash
docker compose logs -f live-mem-service --tail 20
```

### MCP Doesn't Connect Behind a VPN

If Live Memory is on a remote server, verify:
- That port 443 (HTTPS) or 8080 (HTTP) is accessible
- That the URL in the Cline config is correct (with `/mcp` at the end)
- Test manually: `curl -H "Authorization: Bearer lm_..." https://your-server/mcp`

---

## 🖥️ With Claude Desktop

The configuration is similar. Edit the `claude_desktop_config.json` file:

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

> **⚠️ Don't forget the `timeout` parameter** to allow for long processing times during consolidation.

Restart Claude Desktop after the modification. The 38 Live Memory tools will appear in the available tools list.

---

## 📊 Summary

| Step      | Action                                         | Time       |
| --------- | ---------------------------------------------- | ---------- |
| 1         | Start Live Memory (`docker compose up -d`)     | 1 min      |
| 2         | Create a token (`mcp_cli.py token create`)     | 30 sec     |
| 3         | Configure Cline (`cline_mcp_settings.json`)    | 2 min      |
| 4         | Create a space (`space_create`)                | 30 sec     |
| 5         | Add Custom Instructions                        | 2 min      |
| **Total** | **Ready to use**                               | **~6 min** |

---

*Live Memory Integration Guide v1.2.0 — [Full Documentation](README.md)*
