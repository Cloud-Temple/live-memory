# RULES — Rules Templates for Live Memory

This directory contains **rules templates** that can be used when creating a memory space (`space_create`) in Live Memory.

## What Are Rules?

**Rules** define the **structure of a space's Memory Bank**: which files must be created and maintained, what content is expected in each, and how the LLM consolidator should organize notes into structured files.

Rules are **immutable after space creation** — choosing the right template from the start matters.

## Why Rules Are Critical

Rules are not mere documentation. They are **injected verbatim into the LLM prompt** at every consolidation (`bank_consolidate`). Here is the pipeline:

1. The consolidator reads `_rules.md` word for word from S3
2. The full content is injected into the user prompt sent to the LLM
3. The system prompt instructs the LLM to *"strictly follow the structure defined in the rules"*

**In practice, every word you write in the rules is read and interpreted by the LLM consolidator.** It is a direct contract between you and the model. Consolidation instructions (category-to-file mapping, reliability rules, domain-specific guidelines) are not decorative — they genuinely shape the LLM's behavior.

> ⚠️ **Consequence**: the quality of the rules directly determines the quality of the consolidation. Precise rules produce a structured and reliable bank. Vague rules produce unpredictable results.

## Available Templates

| File                                 | Domain              | Description                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------ | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `live-mem.standard.memory.bank.md`   | **General**         | Versatile template for any software project. 6 mandatory files (projectbrief, productContext, activeContext, systemPatterns, techContext, progress). Ideal for development, architecture, and project management. This is the template used by the `live-mem` space itself.                                                                                  |
| `book.memory.bank.md`               | **Writing**         | Template for book writing (essay, novel, guide). 6 mandatory files (bookbrief, bookContext, narrativeDesign, writingContext, activeContext, progress). Narrative tracking, voice and tone, word counts per chapter, review feedback, chapter-level progress tracking.                                                                                        |
| `medical.memory.bank.md`            | **Medical**         | Template for medical follow-up. 7 mandatory files (profilGeneral, histoireDiagnostic, contexteSante, medicamentationTraitements, specialistesSuivi, profilSante, progression) + 2 optional (visualisationDonnees, protocoleUrgence). Includes an absolute reliability rule for biological data.                                                              |
| `presales.memory.bank.md`           | **Presales**        | Template for B2B sales proposal analysis. 5 base files (proposalContext, activeAnalysis, analysisProgress, rulesLearned, methodologieAnalyse) + dynamic persona files (one per decision-maker: executive, buyer, CIO, CISO, expert). Contradiction management, argumentative pattern capitalization, visual tracking.                                        |
| `product.management.memory.bank.md` | **Product Management** | Template for a product team (PM + Product Design + UX Writing). 11 mandatory files (productVision, portfolio, marketIntelligence, userKnowledge, stakeholders, designSystem, communicationGuide, engineeringContext, discoveryPlaybook, activeContext, roadmapProgress) + dynamic persona, feature, and framework files. Discovery pipeline, reference frameworks (JTBD, PLG, 7 Powers…), enriched feature template, stakeholder intelligence, ADR decision log. |

## How to Use a Template

1. **Choose** the template that fits your domain
2. **Customize** if needed (rules are free-form Markdown)
3. **Create the space** by passing the rules content:

```python
space_create(
    space_id="my-project",
    description="My development project",
    rules=<content of the chosen .md file>
)
```

Or via the CLI:
```bash
python scripts/mcp_cli.py space create my-project "My project" --rules-file RULES/standard.memory.bank.md
```

## Creating Your Own Template

You can create a custom template by drawing inspiration from the standard model. Key elements to define:

- **Mandatory files**: names, roles, expected content
- **Hierarchy**: how files build on each other
- **Consolidation mapping**: which note category feeds which file
- **Consolidation rules**: instructions for the LLM (don't lose information, synthesize, etc.)

> 💡 **Tip**: a good rules template is precise enough to guide the LLM consolidator, yet flexible enough to adapt as the project evolves.
