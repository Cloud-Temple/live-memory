# Medical Memory Bank Rules — LIVE MEMORY v1.9.0

## Core Principle

The Medical Memory Bank is the ONLY source of truth between sessions for an AI agent dedicated to medical follow-up. After every memory reset, the agent starts from zero and depends ENTIRELY on these files to understand the patient's health context and continue the follow-up effectively.

**The accuracy and reliability of medical data are critical. No information may be lost, distorted, or approximated.**

## File Structure and Hierarchy

Files build on each other in a clear hierarchy:

```
patientProfile.md (foundation — patient identity and context)
├── diagnosticHistory.md (pathology and medical timeline)
├── medicationsAndTreatments.md (current and past treatments)
├── specialistsAndFollowUp.md (care team and schedule)
└── healthPatterns.md (patterns and learnings from the follow-up)
    └── healthContext.md (current focus — entry point of every session)
        └── progression.md (evolution journal and complete history)
```

- `patientProfile.md` is the foundational document that guides the entire follow-up
- Intermediate files document each aspect of the follow-up
- `healthContext.md` synthesizes the current focus from all other files
- `progression.md` tracks the complete chronological evolution

## Mandatory Files (7 files)

### patientProfile.md
**Foundational document — rarely modified.**
- Demographics: age, sex, blood type, height, weight
- Personal and family medical history
- Known allergies (medications, food, environmental)
- Identified risk factors
- Lifestyle: diet, physical activity, tobacco, alcohol
- Medical coverage and emergency contacts
- This file only changes if fundamental information is discovered
- Every new agent must read this file first

### diagnosticHistory.md
**Complete pathology history.**
- Established diagnosis(es) with dates and diagnosing physicians
- Chronology of disease discovery and evolution
- Major medical events (hospitalizations, surgeries, crises)
- Key examination results that led to the diagnosis
- Identified comorbidities
- This file documents the medical PAST and only changes upon new diagnostic discoveries

### healthContext.md
**The most dynamic file — the entry point of every session.**
- Current follow-up focus: what is being worked on right now
- Recent health status: symptoms, well-being, observations
- Recent examination results (summary — details in progression.md)
- Concrete next steps: appointments, exams to schedule
- Active concerns and observations from the patient or physician
- Therapeutic decisions currently under consideration
- IMPORTANT: this file reflects the CURRENT STATE, not the full history
- Resolved items must be moved to progression.md
- This is the FIRST file an agent reads to resume the follow-up

### medicationsAndTreatments.md
**Current treatments and therapeutic history.**
- Current medications: name, dosage, frequency, route of administration
- Start date of each treatment and prescribing physician
- History of discontinued treatments (with reasons for discontinuation)
- Observed side effects (current and past)
- Observed efficacy of each treatment
- Identified drug interactions
- Specific therapeutic protocols (chemotherapy, immunotherapy, etc.)

### specialistsAndFollowUp.md
**Care team and follow-up organization.**
- Primary care physician (name, contact details, role)
- Involved specialists (name, specialty, contact details, hospital)
- Consultation frequency per specialist
- Upcoming appointment calendar
- Scheduled periodic examinations (check-ups, imaging, etc.)
- Laboratories and imaging centers used

### healthPatterns.md
**Follow-up learning journal — grows over sessions.**
- Personal treatment reactions (tolerances, sensitivities)
- Patient-specific patterns (recurring symptoms, triggers)
- Preferences and daily routine impacting health
- Identified correlations (factors ↔ worsening/improvement)
- Personalized alert thresholds for critical medical values
- Lifestyle habits and their observed health impact
- Known challenges in the follow-up (adherence, access to care, etc.)
- This file captures LEARNINGS that improve follow-up quality

### progression.md
**Evolution journal — grows over time.**
- Chronological symptom evolution (by date or period)
- Treatment response over time
- Detailed examination results (values, dates, trends)
- Current health status (stable / improving / declining)
- Known problems and open questions
- Significant events with dates
- This file is the ONLY one that contains the complete chronological history

## Recommended Files (optional)

### dataVisualization.md
**Tracking tables and trends.**
- Tracking tables for key medical values (blood sugar, blood pressure, markers, etc.)
- Reference points and normal ranges for each parameter
- Identified trends in the data (improvement, decline, stability)
- Observed correlations between different parameters
- This file is essential for conditions requiring regular biological monitoring

### emergencyProtocol.md
**Vital information for emergencies.**
- Prioritized emergency contacts (family, primary physician, emergency services)
- Critical symptoms to watch for (warning signs specific to the condition)
- Immediate actions to take depending on the situation
- Essential information for emergency services (allergies, treatments, condition)
- Condition-specific emergency procedures
- Hospital case number if applicable

## Note Categories and Their Medical Usage

During follow-up, the agent writes atomic notes via `live_note` with these categories:

- **`observation`** — Clinical findings, examination results, symptoms reported by the patient
- **`decision`** — Treatment changes, specialist referrals, therapeutic choices
- **`progress`** — Health status evolution, treatment response, improvement/decline
- **`issue`** — Side effects, complications, concerning symptoms, adherence problems
- **`todo`** — Appointments to schedule, exams to plan, prescriptions to renew
- **`insight`** — Patterns discovered, correlations identified, learnings about the patient's profile
- **`question`** — Points to clarify with the physician, therapeutic choices to discuss

## When to Update the Memory Bank

The bank must be updated (via consolidation):
1. After receiving new examination or test results
2. After a medical consultation (summary, decisions, prescriptions)
3. Upon significant changes in health status
4. After any treatment modification
5. At the end of every follow-up session (always)
6. When the user explicitly requests an update
7. After any urgent medical incident

## Absolute Reliability Rule

**⚠️ Mandatory rule for the LLM consolidator:**

When consolidating notes that contain biological test results or medical values:
1. **Systematic double-checking** of every transcribed parameter
2. **Perfect fidelity** to source data — no approximation tolerated
3. **No data loss** — every value must be reported
4. **Units preserved** — always report measurement units
5. **Exact dates** — every result must be dated

## Instructions for the LLM Consolidator

### Mapping Note Categories to Bank Files

- `observation` (results, symptoms) → `healthContext.md` (recent status) + `progression.md` (history) + `dataVisualization.md` (numerical values)
- `decision` (therapeutic changes) → `healthContext.md` (active decisions) + `medicationsAndTreatments.md` (if treatment modification)
- `progress` (evolution) → `progression.md` (journal) + `healthContext.md` (current status)
- `issue` (complications, side effects) → `healthContext.md` (if active) + `medicationsAndTreatments.md` (side effects) + `progression.md` (history)
- `todo` (appointments, exams) → `healthContext.md` (next steps) + `specialistsAndFollowUp.md` (calendar)
- `insight` (patterns, correlations) → `healthPatterns.md` (learnings) + `healthContext.md` (if currently relevant)
- `question` (points to clarify) → `healthContext.md` (active concerns)

### Consolidation Rules

1. **Never lose medical information** — every note must be reflected in the appropriate file
2. **healthContext.md is the entry point** — it is the first file read at the start of every session
3. **Absolute precision for values** — transcribe numbers, units, and dates exactly, with no approximation
4. **Maintain chronology in progression.md** — group by date or period with timestamps
5. **patientProfile.md is quasi-immutable** — only modify for fundamental discoveries (new allergy, major new diagnosis)
6. **Clean healthContext.md regularly** — move resolved items to progression.md to keep the current focus lightweight
7. **Enrich, don't overwrite** — when updating, enrich existing content rather than replacing it
8. **Update dataVisualization.md** — if a note contains numerical values, update the corresponding tracking tables
9. **Respect the hierarchy** — information must live in the appropriate file per the defined structure
10. **Flag alerts** — if a value exceeds an alert threshold defined in healthPatterns.md, mention it in healthContext.md
