# Presales Memory Bank Rules — LIVE MEMORY v2.5.0

## Core Principle

The Presales Memory Bank is the ONLY source of truth between sessions for an AI agent dedicated to the analysis and improvement of sales proposals. After every memory reset, the agent starts from zero and depends ENTIRELY on these files to understand the opportunity context, the personas involved, and the current state of the analysis.

**Commercial rigor and argumentative consistency are critical. No insight, no identified contradiction, no effective pattern may be lost.**

## File Structure and Hierarchy

Files build on each other in a clear hierarchy:

```
proposalContext.md (foundation — opportunity, client, stakes)
├── persona-*.md (one file per decision-maker: executive, buyer, CIO, CISO, expert…)
├── rulesLearned.md (effective patterns, preferences, lessons learned)
└── analysisMethodology.md (analysis process and conventions)
    └── activeAnalysis.md (current focus — entry point of every session)
        └── analysisProgress.md (advancement journal and tracking)
```

- `proposalContext.md` is the foundational document that frames the entire analysis
- `persona-*.md` files document each decision-maker involved
- `rulesLearned.md` capitalizes cross-cutting learnings
- `activeAnalysis.md` synthesizes the current focus and next steps
- `analysisProgress.md` tracks complete advancement with visual statuses

## Mandatory Files (5 base files)

### proposalContext.md
**Analysis foundation — rarely modified.**
- Target client: industry, size, business context, strategic stakes
- Opportunity: scope, estimated amount, timeline, identified competitors
- Analyzed documents: list of proposals, appendices, RFP/RFI
- Positioning: identified strengths and weaknesses, key differentiators
- Constraints: budget, schedule, regulatory requirements, elimination criteria
- This file only changes if the opportunity context fundamentally evolves
- Every new agent must read this file first

### activeAnalysis.md
**The most dynamic file — the entry point of every session.**
- Current focus: which analysis is in progress
- Recent insights: discoveries, strengths, identified weaknesses
- Detected contradictions: inconsistencies in the proposal and resolution paths
- Concrete next steps (analyses to conduct, documents to produce)
- Pending decisions: argumentative trade-offs, positioning choices
- IMPORTANT: this file reflects the CURRENT STATE, not the full history
- Completed items must be moved to analysisProgress.md
- This is the FIRST file an agent reads to resume the analysis

### analysisProgress.md
**Advancement journal — grows over time.**
- Completed and in-progress analysis phases, with visual statuses:
  - ✅ Completed
  - 🔄 In progress
  - ⏱️ Planned
  - ❓ Awaiting clarification
- Improvements made with measured impact (before/after when possible)
- Questions/answers organized by proposal section
- Supplementary documents produced (summaries, analyses, rewrites)
- Identified problems and workarounds
- This file is the ONLY one that contains the complete chronological history

### rulesLearned.md
**Learning capitalization — a CRITICAL file.**
- Effective argumentative patterns (phrasing that works, by persona)
- Discovered writing preferences and conventions
- Lessons learned: what works, what doesn't
- Thresholds and benchmarks: acceptable price ratios, industry benchmarks
- Identified consistency rules (e.g., don't contradict the customization positioning)
- This file grows every session and must be consulted before any writing

### analysisMethodology.md
**Analysis process and conventions — rarely modified.**
- 4-phase analysis process (preparatory, foundational, persona, synthesis)
- Analysis sequence by persona: Executive → Buyer → CISO → CIO → Expert → End Users
- Contradiction management: identification, evaluation, resolution, documentation
- Naming convention for supplementary documents: `[base_doc]-[decimal].[name]`
- Methodology for integrating new knowledge sources
- This file frames the "how" of the analysis

## Persona Files (one per decision-maker — created as needed)

Each persona involved in the purchasing decision has its own bank file. The LLM consolidator must create these files as soon as a note provides information about a persona.

### Standard Persona File Structure (`persona-[name].md`)

```
# Persona: [Role]
## Characteristics
Role, objectives, performance indicators, constraints
## Evaluation Criteria
Priorities, acceptability thresholds, vigilance points
## Decision Process
Steps, influences, risk factors
## Typical Objections
Expected objections and validated counter-arguments
## Effective Messages
Validated phrasing, arguments that resonate
## Evidence Elements
References, figures, expected certifications
## Specific Notes
Particularities, contextual adaptations
```

### Standard Personas (created as needed)
- `persona-executive.md` — CEO/Managing Director: strategic vision, ROI, business risks
- `persona-buyer.md` — Procurement Manager: TCO, contractual flexibility, benchmarks
- `persona-cio.md` — CIO: technical integration, roadmap, technical debt
- `persona-ciso.md` — CISO: compliance, certifications, security governance
- `persona-technical-expert.md` — Expert: architecture, performance, scalability

## Optional Files

- **Produced analysis documents** (executive summary, competitive analysis, etc.) — stored as additional bank files
- **Contradiction resolution files** — when a contradiction requires a dedicated document

## Note Categories and Their Presales Usage

During analysis, the agent writes atomic notes via `live_note` with these categories:

- **`observation`** — Factual findings about the proposal (strengths, weaknesses, inconsistencies, numerical data)
- **`decision`** — Argumentative choices, positioning adopted, validated rewrites
- **`progress`** — Completed analyses, documents produced, phases completed
- **`issue`** — Detected contradictions, critical weaknesses, blocking points
- **`todo`** — Analyses to conduct, documents to produce, personas to complete
- **`insight`** — Discovered patterns, effective arguments, correlations between objections and responses
- **`question`** — Points to clarify with the sales team, missing information

## When to Update the Memory Bank

The bank must be updated (via consolidation):
1. After each completed analysis phase
2. After discovering a major contradiction
3. After producing an analysis document (summary, rewrite, etc.)
4. When new argumentative patterns are identified
5. At the end of every work session (always)
6. When the user explicitly requests an update

## Instructions for the LLM Consolidator

### Mapping Note Categories to Bank Files

- `observation` (findings about the proposal) → `activeAnalysis.md` (recent insights) + `persona-*.md` (if related to a specific persona)
- `decision` (argumentative choices) → `activeAnalysis.md` (active decisions) + `rulesLearned.md` (if it is a reusable pattern)
- `progress` (advancement) → `analysisProgress.md` (journal) + `activeAnalysis.md` (current state)
- `issue` (contradictions, weaknesses) → `activeAnalysis.md` (detected contradictions) + `analysisProgress.md` (known problems)
- `todo` (analyses to do) → `activeAnalysis.md` (next steps)
- `insight` (patterns, effective arguments) → `rulesLearned.md` (capitalization) + `persona-*.md` (if persona-specific)
- `question` (points to clarify) → `activeAnalysis.md` (pending decisions) + `analysisProgress.md` (Q&A)

### Managing Persona Files

- If a note mentions a specific persona (executive, buyer, CIO, CISO, expert), the consolidator must update the corresponding `persona-[name].md` file
- If the persona file does not exist yet, create it using the standard structure defined above
- Cross-persona information goes into `rulesLearned.md`

### Consolidation Rules

1. **Never lose commercial information** — every insight, objection, and effective argument must be capitalized
2. **activeAnalysis.md is the entry point** — it is the first file read at the start of every session
3. **Synthesize, don't copy** — group similar observations into coherent paragraphs
4. **Maintain visual statuses in analysisProgress.md** — systematically use ✅🔄⏱️❓
5. **proposalContext.md is quasi-immutable** — only modify if the opportunity context changes
6. **rulesLearned.md never loses content** — only enrich, never delete (it is the long-term memory of the analysis)
7. **Clean activeAnalysis.md regularly** — move completed items to analysisProgress.md
8. **Enrich personas progressively** — every session may bring new arguments or objections
9. **Respect the hierarchy** — information must live in the appropriate file
10. **Document contradictions** — every identified contradiction must be tracked in activeAnalysis.md with a resolution path
