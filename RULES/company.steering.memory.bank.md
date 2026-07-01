# Company Steering Memory Bank Rules — LIVE MEMORY v2.5.3

## Core Principle

The Company Steering Memory Bank is the ONLY source of truth between sessions for an AI agent assisting an executive (CEO / Managing Director) in steering the whole company: finance, sales, business units, legal, HR, risk, and compliance. After every memory reset, the agent starts from zero and depends ENTIRELY on these files to understand the company's state, its ongoing dossiers, and the decisions already made.

**Executive decisions engage the company. A figure without a date and a source is worthless. A decision without its rationale is a future dispute. Nothing may be invented, extrapolated, or silently dropped.**

## Confidentiality Notice

This bank centralizes highly sensitive information (financials, legal exposure, HR matters, strategic plans). It MUST live in a dedicated space with strictly restricted tokens (executive scope only). No content from this bank may be copied into other spaces or external documents by the agent without explicit instruction.

## Data Reliability Rules (absolute)

1. **Figures are facts, never estimates.** The consolidator must NEVER invent, round differently, extrapolate, or "update" a financial, commercial, or HR figure. Every figure kept in the bank carries its **date** and **source** (e.g., "EBITDA YTD €X.XM — reporting May 2026, CFO"). A figure whose source or date is unknown is marked `[à confirmer]`.
2. **HR data is aggregated only.** Headcount, attrition, recruitment pipeline, climate indicators — always at team/BU/company level. NEVER store individual medical information, personal difficulties, disciplinary details, or individual compensation. Named individuals appear only for role/organization facts (nominations, departures of executives, mandates).
3. **Legal exposure is quoted, not interpreted.** Litigation and contractual risks are recorded as stated by counsel, with the date of the assessment. The consolidator never re-qualifies a legal risk on its own.

## File Structure and Hierarchy

Files build on each other in a clear hierarchy:

```
companyBrief.md (foundation — mission, structure, strategic plan)
├── governance.md (bodies, decision cadence, delegations)
├── financeContext.md (P&L, cash, budget vs actual, financial KPIs)
├── salesContext.md (pipeline, bookings, key accounts, partnerships)
├── marketIntelligence.md (market, competition, regulation, public affairs)
├── legalContext.md (contracts, litigation, corporate matters)
├── hrContext.md (organization, headcount, talent, social climate)
├── riskCompliance.md (risk register, certifications, audits, security)
├── stakeholders.md (board, executive committee, key external relations)
│   ├── bu-[name].md (dynamic — one per business line: bu-csp, bu-msp, …)
│   └── dossier-[name].md (dynamic — one per strategic dossier)
└── activeContext.md (current focus — session entry point)
    └── steeringProgress.md (journal, decision log, KPI history)
```

- `companyBrief.md` is the foundational document that shapes all others
- Domain files (`governance`, `financeContext`, `salesContext`, `marketIntelligence`, `legalContext`, `hrContext`, `riskCompliance`, `stakeholders`) provide the specialized context per steering domain
- `bu-*.md` files carry the per-business-line view (P&L, dynamics, priorities)
- `dossier-*.md` files carry ongoing strategic initiatives with their own lifecycle
- `activeContext.md` synthesizes the current focus from all other files
- `steeringProgress.md` tracks advancement, the decision log, and KPI history

## Mandatory Files (11 files)

### companyBrief.md
**Company foundation — rarely modified.**
- Mission, vision, and strategic positioning (e.g., sovereign cloud, qualifications held)
- Legal structure: entities, shareholders, capital structure, subsidiaries
- Strategic plan: horizon, pillars, top-level objectives (with plan version and date)
- Business model essentials: business lines, revenue mix, key economics
- Company values and non-negotiable principles
- Anti-scope: markets, activities, or practices the company refuses
- This file only changes on a strategic pivot, a capital event, or a new strategic plan
- Every new agent must read this file first

### governance.md
**How the company is governed — semi-stable.**
- Governance bodies: board, executive committee (COMEX/CODIR), specialized committees — composition, mandate, meeting cadence
- Decision rights and delegations: who decides what, thresholds (spend, hiring, contracts)
- Reporting calendar: monthly closes, board meetings, budget cycle, strategic reviews
- Standing agenda and preparation expectations per body
- Corporate obligations calendar (AG, filings, mandates renewal)
- This file changes when governance itself changes, not at every meeting

### financeContext.md
**Financial state of the company — updated at each close.**
- P&L structure and current snapshot: revenue, gross margin, EBITDA, net result — always dated with source
- Budget vs actual: current-year budget, landing forecast, main variances with explanations
- Cash position and forecast: treasury, debt, covenants, upcoming maturities
- Financial KPIs tracked: ARR/MRR, backlog, DSO/DPO, capex plan — as defined by the company
- Investment decisions in force (approved capex, envelopes)
- Alert thresholds: what deviation triggers escalation
- Keep only the CURRENT snapshot in detail; move superseded snapshots to `steeringProgress.md` (KPI history)

### salesContext.md
**Commercial engine — pipeline and accounts.**
- Pipeline state: weighted pipeline, coverage vs target, key deals in progress (stage, amount, close date)
- Bookings and revenue vs commercial targets, by segment or BU
- Key accounts: top clients, health status, renewal dates, upsell/churn risks
- Partnerships and channel: active partners, terms, performance
- Win/loss patterns: why deals are won or lost, recurring competitive themes
- Pricing decisions in force and discount policy boundaries
- Cross-BU commercial view; BU-specific detail lives in `bu-*.md`

### marketIntelligence.md
**External awareness — market, competition, regulation, public affairs.**
- Competitive landscape: key competitors, moves, relative positioning
- Market trends: demand shifts, technology trends, pricing dynamics
- Regulatory and political environment: laws, directives, qualification schemes affecting the business (e.g., data protection, sectoral security requirements, sovereignty rules), with their timelines
- Public affairs: relevant institutional relationships, consultations, industry bodies
- Weak signals and opportunities: emerging needs, adjacent markets, M&A targets or threats
- This file helps the agent make market-aware recommendations

### legalContext.md
**Legal state of the company — contracts, litigation, corporate.**
- Significant contracts in force: top client/supplier contracts, key terms, renewal/termination dates, commitments given (SLA, penalties, liability caps)
- Litigation and pre-litigation: each matter with status, exposure as assessed by counsel (dated), next milestone
- Corporate matters: ongoing operations (M&A, restructuring, capital), mandates, insurance coverage
- Contractual policy: standard positions, red lines, delegation of signature
- Regulatory obligations with legal impact (processing registers, DPO matters, notifications)
- Apply the "legal exposure is quoted, not interpreted" reliability rule strictly

### hrContext.md
**Organization and people — aggregated view only.**
- Organization: organigram summary, key roles, open executive positions
- Headcount and dynamics: total FTE, per BU/function, hiring plan vs actual, attrition rate — dated
- Talent: critical skills, key-person dependencies (by role, not personal details), succession considerations
- Social climate: works council (CSE) topics, ongoing negotiations, climate indicators (eNPS, absenteeism) — aggregated
- Compensation policy: principles, budget envelopes, current campaigns (no individual data)
- Training and certification plans relevant to strategy
- Apply the "HR data is aggregated only" reliability rule strictly

### riskCompliance.md
**Risk register and compliance state — a CRITICAL file for a regulated business.**
- Risk register: top risks (strategic, operational, financial, cyber, compliance) with owner, assessment, mitigation status
- Certifications and qualifications: each scheme held or targeted (e.g., security qualifications, health data hosting, ISO standards) with scope, expiry/renewal dates, audit calendar
- Audit state: recent findings, remediation plans, deadlines
- Security posture: major incidents (summary and status), crisis mechanisms in place
- Compliance obligations calendar: what is due, when, to whom
- Insurance and business continuity essentials
- Renewal dates and audit deadlines must NEVER be lost or go stale

### stakeholders.md
**Steering the relationships — internal and external.**
- Board members and shareholders: expectations, sensitivities, communication preferences
- Executive committee: each member's scope, current objectives, working style, points of attention
- Key external stakeholders: regulators, strategic clients, strategic partners, banks — state of the relationship, last interactions, next steps
- Communication matrix: who gets what information, when, in what format
- Organizational dynamics: alignments, tensions, escalation paths
- This file helps the agent tailor recommendations and communications to their audience

### activeContext.md
**The most dynamic file — the entry point of every session.**
- Current focus: the 3–7 topics the executive is actively steering
- Recently completed work (last few sessions, not full history)
- Decisions pending: trade-offs on the table, options under evaluation, who must weigh in
- Alerts: anything red or trending red (financial, legal, HR, delivery, compliance)
- Concrete next steps (prioritized action list, with owners and deadlines when known)
- IMPORTANT: this file reflects the CURRENT STATE, not the full history
- Completed items must be moved to steeringProgress.md
- This is the FIRST file an agent reads to resume work
- **Target size: < 8 KB** — beyond this, move history to steeringProgress.md

### steeringProgress.md
**Advancement journal, decision log, and KPI history — grows over time.**
- Chronological journal of major company events (closes, board meetings, deals signed, audits passed) with dates
- **Decision log (ADR format)** — every structural executive decision gets an entry:
  ```
  ### [DATE] Decision: [title]
  - **Context**: why the question arose
  - **Options considered**: A, B, C with pros/cons
  - **Decision**: what was chosen, by whom (DG, COMEX, board)
  - **Rationale**: why
  - **Consequences**: what this implies going forward
  ```
- KPI history: superseded financial/commercial/HR snapshots moved from the domain files, kept as compact dated tables
- Closed dossiers: outcome summary of each archived `dossier-*.md`
- Status indicators: ✅ Done | 🔄 In progress | ⏱️ Planned | ⚠️ At risk | ❌ Abandoned
- This file is the ONLY one that contains the complete chronological history

## Dynamic Files (created by the consolidator as needed)

### Business Unit Files (`bu-[name].md`)

One file per business line (e.g., `bu-csp.md` for the cloud services business, `bu-msp.md` for managed services, and any future line). Created on first mention, enriched over time, never deleted while the BU exists.

**Template structure:**

```markdown
# Business Unit: [Name]

## Mission & Offer
What this BU sells, to whom, and its role in the company strategy

## Financial Snapshot (dated)
Revenue, margin, main cost drivers — current period, with source and date

## Commercial Dynamics
Pipeline, key deals, top clients, churn/renewal risks specific to this BU

## Operations & Delivery
Delivery state, capacity, quality/SLA indicators, major projects

## Team
Headcount (aggregated), key roles, hiring status, organizational points

## Risks & Dependencies
BU-specific risks, dependencies on other BUs, suppliers, or platforms

## Current Priorities
The BU's active objectives and their status

## Notes
Dated observations that don't fit above
```

**Consolidator rules for BU files:**
- Cross-BU information (consolidated P&L, group-level pipeline) belongs in the domain files, not in BU files
- Financial snapshots follow the same absolute reliability rule (date + source)
- If a BU is closed or merged, summarize its outcome in `steeringProgress.md` and mark the file as archived

### Dossier Files (`dossier-[name].md`)

One file per strategic dossier in progress: an acquisition, a certification campaign, a major bid, a reorganization, a fundraising, a crisis. Created when the dossier becomes active; archived to `steeringProgress.md` when closed.

**Template structure:**

```markdown
# Dossier: [Name]

## Status
Active | On hold | Closing — plus current phase and target deadline

## Stakes
Why this dossier matters, expected outcome, what happens if it fails

## Parties Involved
Internal owners, external counterparts, advisors

## Current State
Where the dossier stands right now (dated)

## Decisions Made
Mini-ADR entries: what was decided, when, why

## Open Questions & Next Steps
What remains to be resolved, who must act, by when

## Risks
Dossier-specific risks and mitigation

## Confidentiality
Circle of people aware; anything requiring special handling
```

**Consolidator rules for dossiers:**
- Create the file when a note indicates a new strategic dossier has opened
- Update "Current State" and "Decisions Made" as notes arrive; keep the file self-sufficient (an agent must understand the dossier from this file alone)
- When the dossier closes, write its outcome summary in `steeringProgress.md` and remove the dossier file (or mark it archived)
- Maximum ~10 active dossier files — beyond that, question whether some are actually on hold

## Note Categories and Their Steering Usage

During work, the agent writes atomic notes via `live_note` with these categories:

- **`observation`** — Factual finding: a reported figure, a client signal, a competitor move, a regulatory announcement, a stakeholder reaction, an audit finding
- **`decision`** — Executive choice and its rationale: budget arbitration, pricing call, organizational change, contractual position, go/no-go on a dossier
- **`progress`** — Advancement: close completed, deal signed, audit passed, milestone reached on a dossier
- **`issue`** — Problem: financial variance, deal at risk, litigation opened, key departure, compliance gap, delivery incident
- **`todo`** — Action to take: analysis to request, meeting to hold, arbitration to prepare, document to review
- **`insight`** — Learning: market pattern, negotiation lesson, organizational dynamic understood, what worked or failed and why
- **`question`** — Point to clarify: missing figure, pending legal opinion, stakeholder position to confirm

## When to Update the Memory Bank

The bank must be updated (via consolidation):
1. After each monthly/quarterly close or reporting cycle
2. After each governance meeting (board, COMEX) with decisions
3. After a significant event on a dossier (milestone, decision, setback)
4. After a significant external event (regulatory change, competitor move, client crisis)
5. At the end of every work session (always)
6. When the user explicitly requests an update

## Agent Workflow

### At Session Start (mandatory)
1. Read ALL bank files (`bank_read_all`)
2. Check completeness and consistency; verify figures are dated and sourced
3. Identify current focus and alerts in `activeContext.md`
4. Review active `dossier-*.md` files to understand ongoing initiatives
5. Check `riskCompliance.md` for upcoming deadlines (audits, renewals, obligations)
6. Develop a work strategy before taking action

### During Work
1. Write frequent, atomic notes via `live_note` — one note = one fact, one decision, or one action; always include date and source for figures
2. NEVER write directly to the bank — only the LLM consolidation does that
3. Check other agents' notes via `live_read` if working in a multi-agent setup (e.g., a finance agent and a sales agent feeding the same space)

### At Session End
1. Consolidate notes via `bank_consolidate`
2. Verify the bank reflects the work accomplished and that no alert was lost

## Instructions for the LLM Consolidator

### Mapping Note Categories to Bank Files

- `observation` → `activeContext.md` (recent work) + the relevant domain file: `financeContext.md` (figures), `salesContext.md` (commercial), `marketIntelligence.md` (market/regulatory), `legalContext.md` (legal), `hrContext.md` (HR, aggregated), `riskCompliance.md` (risk/audit/security), `stakeholders.md` (stakeholder behavior) + `bu-*.md` (if BU-specific) + `dossier-*.md` (if dossier-specific)
- `decision` → `activeContext.md` (active decisions) + `steeringProgress.md` (ADR entry if structural) + the relevant domain file + `dossier-*.md` (if dossier-related) + `governance.md` (if it changes decision rights or cadence)
- `progress` → `steeringProgress.md` (journal) + `activeContext.md` (current state) + `dossier-*.md` (update status/state)
- `issue` → `activeContext.md` (alerts, if red or trending red) + the relevant domain file + `riskCompliance.md` (if it belongs in the risk register) + `dossier-*.md` (if dossier-specific)
- `todo` → `activeContext.md` (next steps, with owner and deadline when known)
- `insight` → the relevant domain file (`marketIntelligence.md`, `stakeholders.md`, `salesContext.md`…) + `bu-*.md` or `dossier-*.md` if specific
- `question` → `activeContext.md` (decisions pending) + `dossier-*.md` (if dossier-specific)

### Consolidation Rules

1. **Never lose steering-relevant information** — every figure, decision, alert, and deadline must be reflected somewhere in the bank. Obsolete, replaced, or duplicated data MUST be cleaned up.
2. **Apply the Data Reliability Rules absolutely** — never invent or extrapolate a figure; keep date + source on every figure; mark unsourced figures `[à confirmer]`; keep HR data aggregated; quote legal assessments without re-qualifying them.
3. **activeContext.md is the entry point** — first file read at every session start; keep it focused on current topics, alerts, and pending decisions
4. **Maintain the decision log in steeringProgress.md** — every structural executive decision gets an ADR entry with date, context, options, decision authority, rationale, and consequences
5. **companyBrief.md is quasi-immutable** — only modify on a strategic pivot, capital event, or new strategic plan
6. **Current snapshot in domain files, history in steeringProgress.md** — when a new financial/commercial/HR snapshot arrives, REPLACE the previous one in the domain file and move the superseded snapshot to the KPI history
7. **Deadlines never go stale** — certification renewals, audit dates, contract expiries, and corporate obligations must always be current in `riskCompliance.md`, `legalContext.md`, and `governance.md`
8. **Clean activeContext.md aggressively** — move completed items to steeringProgress.md; target < 8 KB
9. **Manage dossier lifecycle** — create on opening, keep self-sufficient, archive with an outcome summary in steeringProgress.md on closing
10. **Enrich BU files progressively** — BU-specific facts go to `bu-*.md`; cross-BU synthesis stays in the domain files
11. **Respect the hierarchy** — information must live in the appropriate file per the structure defined above
12. **Update, don't duplicate** — if a section already exists on the same topic, REPLACE it with updated content. Never create duplicate sections.
13. **Keep files concise** — activeContext.md < 8 KB, other files < 15 KB. Beyond that, synthesize or archive to steeringProgress.md
14. **Preserve confidentiality framing** — never soften or drop confidentiality mentions on dossiers; never copy sensitive details into files with broader purpose than necessary
