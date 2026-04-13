# Product Management Memory Bank Rules — LIVE MEMORY v1.0.0

## Core Principle

The Product Management Memory Bank is the ONLY source of truth between sessions for an AI agent supporting a product team (Product Management, Product Design, UX Writing). After every memory reset, the agent starts from zero and depends ENTIRELY on these files to understand the product strategy, portfolio, user knowledge, and ongoing work.

**Product decisions are irreversible at scale. Every insight, every user feedback, every design rationale, every strategic trade-off must be captured. Poor memory leads to poor product decisions.**

## File Structure and Hierarchy

Files build on each other in a clear hierarchy:

```
productVision.md (foundation — mission, vision, positioning, values)
├── portfolio.md (product catalog: lines, features, state, dependencies)
├── marketIntelligence.md (competition, market, regulation, trends)
├── userKnowledge.md (cross-persona synthesis, JTBD, feedback patterns)
│   └── persona-[name].md (dynamic — created as insights emerge)
├── designSystem.md (UX principles, patterns, components, conventions)
├── uxWritingGuide.md (voice & tone, terminology, multilingual glossary)
├── engineeringContext.md (architecture, tech constraints, debt, capacity)
└── discoveryPlaybook.md (discovery pipeline, frameworks, templates)
    └── activeContext.md (current focus — session entry point)
        └── roadmapProgress.md (roadmap, delivered, backlog, decision log)
```

- `productVision.md` is the foundational document that shapes all others
- Domain files (`portfolio`, `marketIntelligence`, `userKnowledge`, `designSystem`, `uxWritingGuide`, `engineeringContext`) provide specialized context
- `discoveryPlaybook.md` defines how the team works
- `activeContext.md` synthesizes the current focus from all other files
- `roadmapProgress.md` tracks advancement and decision history

## Mandatory Files (10 files)

### productVision.md
**Product foundation — rarely modified.**
- Mission and vision: why the product exists and where it's headed
- Product values: non-negotiable principles (e.g., security, privacy, openness)
- Strategic positioning: what differentiates the product in the market
- Target market segments and ideal customer profiles
- Anti-scope: what the product is NOT and will NOT become
- North-star metrics and current strategic OKRs
- Business model essentials (pricing tiers, revenue drivers)
- This file only changes if the product fundamentally pivots
- Every new agent must read this file first

### portfolio.md
**Living product catalog — updated as features evolve.**
- Product suite overview organized by product line or subscription tier
- Per feature: status (GA / beta / alpha / planned / deprecated), supported platforms, known limitations
- Feature × segment matrix (what's available for each customer segment)
- Dependencies between features and components
- Product debt: broken UX, inconsistencies, incomplete features, legacy issues
- Existing integrations and extension points
- This file is the single source of truth for "what does the product do today"

### marketIntelligence.md
**External awareness — competitive and market context.**
- Competitive landscape: key competitors with relative strengths/weaknesses
- Positioning axes: how the product compares on key dimensions (security, UX, price, compliance, etc.)
- Market trends: regulatory shifts, technology trends, customer behavior changes
- Regulatory constraints: compliance requirements relevant to the product (data protection, certifications, industry standards)
- Win/loss patterns: why deals are won or lost, recurring themes from sales
- Weak signals and market opportunities: emerging needs not yet addressed
- This file helps the agent make market-aware product recommendations

### userKnowledge.md
**Cross-persona user intelligence — the voice of the customer.**
- Jobs to Be Done by segment: what customers hire the product to accomplish
- Recurring pain points across all personas (top 10, ranked by frequency/severity)
- Feedback patterns: themes from support tickets, NPS surveys, feature requests, user interviews
- User research insights: synthesized findings (summaries, not raw data)
- Behavioral patterns: how users actually use the product vs. how it was designed
- Feature adoption metrics and usage patterns (if tracked)
- This file provides the transverse view; persona-specific details live in persona files

### designSystem.md
**UX principles, patterns, and component state.**
- Design principles: the guiding philosophy for all design decisions
- Recurring UX patterns and conventions (navigation, layout, interaction patterns)
- Component library state: what exists, what's missing, what needs rework
- Platform-specific design considerations (mobile vs. desktop vs. web)
- Accessibility guidelines and current compliance state
- Design debt: known UX issues, inconsistencies between platforms, outdated patterns
- This file helps an agent produce design recommendations consistent with existing standards

### uxWritingGuide.md
**Voice, tone, and terminology — how the product speaks.**
- Brand personality: how the product should feel in words (professional, friendly, authoritative, etc.)
- Tone guidelines by context: errors, onboarding, empty states, success messages, marketing, notifications
- Terminology glossary: approved terms, forbidden terms, and why (multilingual if applicable)
- Do / Don't examples: concrete before/after rewrites for common patterns
- Naming conventions: how features, UI elements, and actions are named
- Localization notes: language-specific considerations, translation pitfalls
- This file ensures consistent product voice across all touchpoints

### engineeringContext.md
**Technical reality that shapes product decisions.**
- High-level architecture: backend services, client platforms, infrastructure overview
- Key technical constraints impacting product decisions (protocols, encryption, federation, etc.)
- Team capacity by scope or domain: how many engineers, what bandwidth
- Known technical debt impacting product quality or velocity
- Platform-specific limitations: what's possible on each client vs. what's not
- Release process and cadence: how and when things ship
- This file bridges the gap between product ambition and engineering reality

### discoveryPlaybook.md
**How the team discovers and specifies — semi-stable.**
- **Discovery pipeline**: the stages an idea or feature request goes through, from intake to general availability. Typical stages: Intake → Triage → Accepted → Discovery → Scoping → Development → Early Access → GA (plus Rejected, Freezer)
- **Idea vs. feature request distinction**: internal ideas vs. external customer/prospect requests — both feed the same funnel but carry different context
- **Discovery frameworks** (reference, not prescription): F.O.C.U.S.E.D. (Frame, Observe, Claim, Unfold, Steal, Execute, Decide), Opportunity Solution Tree, Double Diamond, Continuous Discovery Habits, Design Sprint. The team picks what fits each situation.
- **Product Trio** principle: PM + Designer + Engineer collaborate from discovery onward, not through sequential handoffs
- **Prioritization framework**: team-specific scoring or ranking method (document here when formalized)
- **Spec/PRD template**: structure and expectations for product specifications
- **Go/no-go criteria**: what conditions must be met before committing to build a feature
- This file defines the "how" of product work and changes only when the process evolves

### activeContext.md
**The most dynamic file — the entry point of every session.**
- Current focus: features in discovery, specs in progress, decisions pending
- Recently completed work (last few sessions, not full history)
- Active product decisions and trade-offs being evaluated
- Open questions and blockers
- Concrete next steps (prioritized action list)
- IMPORTANT: this file reflects the CURRENT STATE, not the full history
- Completed items must be moved to roadmapProgress.md
- This is the FIRST file an agent reads to resume work
- **Target size: < 8 KB** — beyond this, move history to roadmapProgress.md

### roadmapProgress.md
**Advancement journal and decision archive — grows over time.**
- Current quarter roadmap and planning horizon
- Delivered features with dates and retrospective: what was the impact, what did we learn
- Prioritized backlog: validated features not yet scheduled (remove items when shipped)
- **Decision log (ADR format)**:
  ```
  ### [DATE] Decision: [title]
  - **Context**: why the question arose
  - **Options considered**: A, B, C with pros/cons
  - **Decision**: what was chosen
  - **Rationale**: why
  - **Consequences**: what this implies going forward
  ```
- Key product metrics tracking (adoption, engagement, retention, NPS — whatever is monitored)
- Status indicators: ✅ Shipped | 🔄 In Progress | ⏱️ Planned | ❌ Rejected | 🧊 Frozen
- This file is the ONLY one that contains the complete chronological history

## Dynamic Files (created by the consolidator as needed)

### Persona Files (`persona-[name].md`)

Created when notes provide insights about a specific user persona. The consolidator must create the file on first mention and enrich it progressively over time.

**Template structure:**

```markdown
# Persona: [Role Name]

## Profile
Role, organizational context, type of organization, tech-savviness level

## Goals
Primary and secondary goals when using the product

## Pain Points
Key frustrations, challenges, and unmet needs

## Jobs to Be Done
What they hire the product to accomplish (functional, emotional, social)

## Decision Criteria
What matters when evaluating or choosing the product

## Behavioral Patterns
How they actually use (or would use) the product day-to-day

## Key Objections
Common pushback, concerns, or reasons for churn

## Effective Messages
Arguments, framings, and value propositions that resonate

## Notes
Specific observations, verbatim quotes, anecdotes from research or feedback
```

**Consolidator rules for personas:**
- Create the file as soon as a note provides persona-specific information
- Cross-persona insights belong in `userKnowledge.md`, not in individual persona files
- Never delete persona content — only enrich and refine over time
- If a note mentions conflicting behaviors between personas, document the conflict in both persona files

### Feature Files (`feature-[name].md`)

Created when a feature enters active discovery or specification. Archived to `roadmapProgress.md` when shipped, rejected, or frozen.

**Template structure:**

```markdown
# Feature: [Name]

## Current Phase
Problem Framing | Research | Ideation | Prototyping | Validation | Specification | Handed Off

## Target Outcome
What business or product result we're seeking (tied to OKR or north-star metric)

## Opportunities Identified
User pain points, needs, and desires justifying this feature

## Solutions Explored
Options considered with pros/cons for each

## Assumptions to Test
Critical hypotheses and how to validate them (experiments, interviews, data analysis)

## Decisions Made
Choices and their rationale (mini-ADR: what, why, what was rejected)

## Spec / Deliverable
Link or summary of the current deliverable (PRD, prototype, wireframes)

## Constraints
Technical, regulatory, business, or timeline constraints shaping the solution

## Open Questions
What's still unresolved, who needs to answer, by when
```

**Consolidator rules for features:**
- Create the file when a note indicates a feature has entered discovery
- Update the "Current Phase" as the feature progresses
- When a feature ships or is rejected, summarize its outcome in `roadmapProgress.md` and remove the feature file (or mark it as archived)
- Maximum ~10 active feature files at a time — if more exist, consider whether some should be frozen or rejected

## Note Categories and Their Product Team Usage

During work, the agent writes atomic notes via `live_note` with these categories:

- **`observation`** — Factual finding: data point, user feedback, test result, market signal, competitive move, usage metric
- **`decision`** — Product, design, or UX writing choice and its rationale: feature scope, design direction, terminology change, prioritization call
- **`progress`** — Advancement: spec completed, prototype validated, feature shipped, research study finished, design review done
- **`issue`** — Problem identified: UX debt, inconsistency, negative user feedback, engineering blocker, competitive threat, missed target
- **`todo`** — Task to do: user interview to schedule, spec to write, prototype to test, design review to run, competitor to analyze
- **`insight`** — Learning: UX pattern discovered, market correlation identified, user behavior revelation, design principle validated, effective messaging found
- **`question`** — Point to clarify: trade-off to resolve, missing information, validation needed from stakeholder, open design question

## When to Update the Memory Bank

The bank must be updated (via consolidation):
1. After a discovery phase milestone (e.g., problem validated, solution selected, spec approved)
2. After a product decision (roadmap change, feature scoped/rejected, pivot)
3. After user research sessions or significant feedback received
4. After a design review or UX writing review producing actionable changes
5. At the end of every work session (always)
6. When the user explicitly requests an update

## Agent Workflow

### At Session Start (mandatory)
1. Read ALL bank files (`bank_read_all`)
2. Check completeness and consistency across files
3. Identify current focus in `activeContext.md`
4. Review active feature files to understand ongoing discovery/spec work
5. Develop a work strategy before taking action

### During Work
1. Write frequent, atomic notes via `live_note` — one note = one fact, one decision, or one task
2. NEVER write directly to the bank — only the LLM consolidation does that
3. Check other agents' notes via `live_read` if working in a multi-agent setup (PM agent, Design agent, etc.)

### At Session End
1. Consolidate notes via `bank_consolidate`
2. Verify the bank reflects the work accomplished

## Instructions for the LLM Consolidator

### Mapping Note Categories to Bank Files

- `observation` (factual findings) → `activeContext.md` (recent work) + `userKnowledge.md` (if user-related) or `marketIntelligence.md` (if market-related) or `portfolio.md` (if product state) + `persona-*.md` (if persona-specific)
- `decision` (product/design choices) → `activeContext.md` (active decisions) + `feature-*.md` (if feature-related) + `roadmapProgress.md` (if strategic, add ADR entry) + `designSystem.md` or `uxWritingGuide.md` (if design/writing standard)
- `progress` (advancement) → `roadmapProgress.md` (journal + metrics) + `activeContext.md` (current state) + `feature-*.md` (update phase)
- `issue` (problems) → `activeContext.md` (if blocking) + `portfolio.md` (if product debt) + `engineeringContext.md` (if tech constraint) + `feature-*.md` (if feature-specific)
- `todo` (tasks) → `activeContext.md` (next steps)
- `insight` (learnings) → `userKnowledge.md` (if user behavior) or `marketIntelligence.md` (if market) + `designSystem.md` (if UX pattern) + `persona-*.md` (if persona-specific) + `discoveryPlaybook.md` (if process learning)
- `question` (open points) → `activeContext.md` (pending decisions) + `feature-*.md` (if feature-specific)

### Managing Dynamic Files

**Persona files:**
- If a note mentions a specific persona (by role, segment, or name), update the corresponding `persona-[name].md`
- If the persona file doesn't exist yet, create it using the template defined above
- Cross-persona information goes in `userKnowledge.md`

**Feature files:**
- If a note references a feature in active discovery/specification, update the corresponding `feature-[name].md`
- If the feature file doesn't exist yet, create it using the template defined above
- When a feature is marked as shipped, rejected, or frozen, summarize in `roadmapProgress.md` and remove the feature file

### Consolidation Rules

1. **Never lose product-relevant information** — every insight, decision, user feedback, and market signal must be reflected somewhere in the bank. Obsolete, replaced, or duplicated data MUST be cleaned up.
2. **activeContext.md is the entry point** — it's the first file read at every session start; keep it focused and current
3. **Synthesize, don't copy** — group related notes into coherent, readable paragraphs
4. **Maintain the decision log in roadmapProgress.md** — every strategic product decision gets an ADR entry with date, context, options, rationale, and consequences
5. **productVision.md is quasi-immutable** — only modify if a note fundamentally changes the product's mission, vision, or positioning
6. **Clean activeContext.md aggressively** — move completed items to roadmapProgress.md; target < 8 KB
7. **Enrich personas progressively** — every user research note, interview finding, or feedback pattern enriches the relevant persona file; never delete persona content, only refine
8. **Manage feature file lifecycle** — create on discovery entry, update throughout, archive on completion or rejection
9. **Respect the hierarchy** — information must live in the appropriate file per the structure defined above
10. **Keep files concise** — activeContext.md < 8 KB, other files < 15 KB. Beyond that, synthesize or archive to roadmapProgress.md
11. **Update, don't duplicate** — if a section already exists on the same topic, REPLACE it with updated content. Never create duplicate sections.
12. **Track design and writing standards** — when a note establishes a new UX pattern or writing convention, add it to `designSystem.md` or `uxWritingGuide.md` respectively
