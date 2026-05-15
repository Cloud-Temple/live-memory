# Cline's Memory Bank — Live Memory MCP - Version 1.9.0

My memory resets completely between sessions. I depend ENTIRELY on the Memory Bank to understand the project and continue effectively.

## 🔌 Configuration (customize per project)

My persistent memory is managed by the **Live Memory** MCP server (`**<YOUR MCP SERVER NAME>**`).

> **⚙️ The only value to customize:**
>
> - **SPACE** = `**<YOUR SPACE NAME>**`
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

```
live_note(space_id="{SPACE}", category="<category>", content="...")
```

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

```
bank_consolidate(space_id="{SPACE}")
```

The LLM will consolidate **my own notes** (agent auto-detected from the token) by updating the bank files according to the space's rules.

> ℹ️ Only a manage+ user can consolidate all agents' notes (`agent=""`).

## ⚠️ Mandatory Rules

1. **NEVER write directly to the bank** — only the LLM consolidation does that
2. **Always pass `space_id="{SPACE}"`** in every call
3. **Write atomic notes after each significant step** — 1 note = 1 fact, 1 decision, or 1 task
4. **Consolidate at session end after a summary note** — never leave without consolidating, but always after validating with the user
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
