# Standard Memory Bank Rules — LIVE MEMORY v2.5.0

## Core Principle

The Memory Bank is the ONLY source of truth between sessions for an AI agent. After every memory reset, the agent starts from zero and depends ENTIRELY on these files to understand the project and continue effectively. The quality and accuracy of the bank are therefore critical.

## File Structure and Hierarchy

Files build on each other in a clear hierarchy:

```
projectbrief.md (foundation)
├── productContext.md (why the project exists)
├── systemPatterns.md (architecture and patterns)
└── techContext.md (tech stack and setup)
    └── activeContext.md (current focus summary)
        └── progress.md (advancement journal)
```

- `projectbrief.md` is the foundational document that shapes all others
- `productContext.md`, `systemPatterns.md`, `techContext.md` derive from it
- `activeContext.md` synthesizes the current focus from all other files
- `progress.md` tracks overall advancement and history

## Mandatory Files (6 files)

### projectbrief.md
**Project foundation — rarely modified.**
- Fundamental vision and objectives of the project
- Explicit scope and boundaries
- Key requirements and structural constraints
- Stakeholders and owner
- Source of truth for the project's scope
- This file only changes if the project fundamentally pivots
- Every new agent must read this file first

### productContext.md
**Why this project exists — the product context.**
- Concrete problems the project solves
- How the product works (main flow, key concepts)
- Domain terminology and vocabulary
- User experience goals (UX goals)
- Positioning relative to existing alternatives
- This file helps a new agent understand the "why" and the "how"

### activeContext.md
**The most dynamic file — the entry point of every session.**
- Current focus: what is being worked on right now
- Recently completed work (last few sessions, not the full history)
- Concrete next steps (prioritized todo list)
- Active decisions and ongoing considerations
- Important patterns and preferences recently discovered
- Learnings and insights from the session
- IMPORTANT: this file must reflect the CURRENT STATE, not the full history
- Completed items must be moved to progress.md
- This is the FIRST file an agent reads to resume work
- **Target size: < 8 KB** — beyond this, it signals inflation; move history to progress.md

### systemPatterns.md
**Architecture and technical patterns of the project.**
- Overall system architecture (with text diagrams if relevant)
- Key technical decisions and their justification (why this choice)
- Design patterns used and conventions
- Relationships and dependencies between components
- Critical implementation paths
- Code conventions, standards, and best practices
- This file captures STRUCTURAL DECISIONS, not implementation details
- **When a pattern evolves** (e.g., architecture migration), REPLACE the existing section — do not keep the old version

### techContext.md
**Tech stack and development environment.**
- Technologies used with versions and roles
- Development setup (step-by-step, commands)
- Known technical constraints and workarounds
- Dependencies and their management
- Source file structure (annotated tree)
- Tool usage patterns (CLI, Docker, tests)
- This file enables a new agent to set up their environment

### progress.md
**Advancement journal — grows over time.**
- What works (by version or milestone), with dates
- What remains to be built (roadmap, backlog) — **remove completed items**
- Overall project status (green/yellow/red)
- Known problems and documented workarounds
- Key metrics (lines of code, tests, coverage, MCP tools) — **always up to date**
- Chronological evolution of project decisions
- This file is the ONLY one that contains the complete history

## Additional Context

Beyond the 6 mandatory files, additional files may be created in the bank when they help organize:
- Complex feature documentation
- Integration specifications
- API documentation
- Test strategies
- Deployment procedures

## When to Update the Memory Bank

The bank must be updated (via consolidation):
1. After discovering new project patterns or conventions
2. After implementing significant changes
3. When the context needs clarification
4. At the end of every work session (always)
5. Before a major topic change
6. When the user explicitly requests an update

## Recommended Agent Workflow

### At Session Start (every session)
1. Read ALL bank files (`bank_read_all`)
2. Verify that files are complete and consistent
3. Identify the current focus in `activeContext.md`
4. Develop a work strategy

### During Work
1. Write frequent, atomic notes via `live_note`:
   - `observation`: factual findings, command outputs
   - `decision`: technical choices and their justification
   - `todo`: identified tasks to do
   - `progress`: advancement, what is completed
   - `issue`: problems encountered, bugs
   - `insight`: learnings, patterns discovered
   - `question`: points to clarify, pending decisions
2. NEVER write directly to the bank — only the LLM consolidation does that
3. Check other agents' notes via `live_read` if working in a multi-agent setup

### At Session End
1. Consolidate notes via `bank_consolidate`
2. Verify the bank reflects the work accomplished

## Instructions for the LLM Consolidator

### Mapping Note Categories to Bank Files
- `observation` → `activeContext.md` (recent work) + relevant file depending on the topic
- `decision` → `activeContext.md` (active decisions) + `systemPatterns.md` if architectural
- `todo` → `activeContext.md` (next steps)
- `progress` → `progress.md` (what works) + `activeContext.md` (recent work)
- `issue` → `progress.md` (known problems) + `activeContext.md` if blocking
- `insight` → `activeContext.md` (learnings) + `systemPatterns.md` if it is a pattern
- `question` → `activeContext.md` (pending decisions)

### Consolidation Rules
1. **Never lose relevant information** — every note must be reflected somewhere in the bank. Obsolete, replaced, or duplicated data MUST be cleaned up.
2. **activeContext.md is the entry point** — it is the first file an agent reads at session start
3. **Synthesize, don't copy** — group similar notes into coherent, readable paragraphs
4. **Maintain chronology in progress.md** — group by version/milestone with dates
5. **projectbrief.md is quasi-immutable** — only modify if a note fundamentally changes the project's vision
6. **Clean activeContext.md** — move completed items to progress.md to keep the current focus lightweight
7. **Update, don't duplicate** — if a section already exists on the same topic, REPLACE it with updated content. Never create duplicate sections.
8. **Respect the hierarchy** — information must live in the appropriate file per the defined hierarchy
9. **Clean up obsolete content** — remove completed items from backlogs ("What Remains to Be Built"), update metrics when they change, delete sections superseded by newer versions
10. **Keep files concise** — activeContext.md < 8 KB, other files < 15 KB. Beyond that, synthesize or archive to progress.md
