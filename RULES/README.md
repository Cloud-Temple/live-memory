# RULES — Modèles de Rules pour Live Memory

Ce répertoire contient des **modèles de rules** (templates) utilisables lors de la création d'un espace mémoire (`space_create`) dans Live Memory.

## Qu'est-ce qu'une Rule ?

Les **rules** définissent la **structure de la Memory Bank** d'un espace : quels fichiers doivent être créés et maintenus, quel contenu y est attendu, et comment le LLM consolidateur doit organiser les notes en fichiers structurés.

Elles sont **immuables après création** de l'espace — il est donc important de bien les choisir dès le départ.

## Pourquoi les Rules sont critiques

Les rules ne sont pas une simple documentation. Elles sont **injectées intégralement dans le prompt du LLM** à chaque consolidation (`bank_consolidate`). Voici le pipeline :

1. Le consolidateur lit `_rules.md` mot pour mot depuis S3
2. Le contenu complet est injecté dans le prompt utilisateur envoyé au LLM
3. Le system prompt instruit le LLM de *"respecter STRICTEMENT la structure définie dans les rules"*

**Concrètement, chaque mot que vous écrivez dans les rules est lu et interprété par le LLM consolidateur.** C'est un contrat direct entre vous et le modèle. Les instructions de consolidation (mapping catégories → fichiers, règles de fiabilité, consignes spécialisées) ne sont pas décoratives — elles orientent réellement le comportement du LLM.

> ⚠️ **Conséquence** : la qualité des rules détermine directement la qualité de la consolidation. Des rules précises produisent une bank structurée et fiable. Des rules vagues produisent des résultats imprévisibles.

## Modèles disponibles

| Fichier                              | Domaine         | Description                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------ | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `live-mem.standard.memory.bank.md`   | **Général**     | Modèle polyvalent pour tout projet logiciel. 6 fichiers obligatoires (projectbrief, productContext, activeContext, systemPatterns, techContext, progress). Idéal pour le développement, l'architecture et la gestion de projet. C'est le modèle utilisé par le space `live-mem`.                                                                     |
| `book.memory.bank.md`               | **Écriture**    | Modèle pour l'écriture de livres (essai, roman, guide). 6 fichiers obligatoires (bookbrief, bookContext, narrativeDesign, writingContext, activeContext, progress). Suivi narratif, voix et ton, compteurs de mots par chapitre, retours de relecture, tracking d'avancement par chapitre.                                                           |
| `medical.memory.bank.md`            | **Médical**     | Modèle adapté au suivi médical. 7 fichiers obligatoires (profilGeneral, histoireDiagnostic, contexteSante, medicamentationTraitements, specialistesSuivi, profilSante, progression) + 2 optionnels (visualisationDonnees, protocoleUrgence). Inclut une règle de fiabilité absolue pour les données biologiques.                                     |
| `presales.memory.bank.md`           | **Avant-vente** | Modèle pour l'analyse de propositions commerciales B2B. 5 fichiers de base (proposalContext, activeAnalysis, analysisProgress, rulesLearned, methodologieAnalyse) + fichiers personas dynamiques (un par décideur : dirigeant, acheteur, DSI, RSSI, expert). Gestion des contradictions, capitalisation des patterns argumentaires, tracking visuel. |
| `product.management.memory.bank.md` | **Product Management** | Modèle pour une équipe produit (PM + Product Design + UX Writing). 10 fichiers obligatoires (productVision, portfolio, marketIntelligence, userKnowledge, designSystem, uxWritingGuide, engineeringContext, discoveryPlaybook, activeContext, roadmapProgress) + fichiers dynamiques personas (`persona-*.md`) et features (`feature-*.md`). Pipeline discovery (intake → GA), frameworks de référence (F.O.C.U.S.E.D., OST, Product Trio), decision log ADR, templates persona et feature. |

## Comment utiliser un modèle

1. **Choisir** le modèle adapté à votre domaine
2. **Personnaliser** si nécessaire (les rules sont en Markdown libre)
3. **Créer l'espace** en passant le contenu des rules :

```python
space_create(
    space_id="mon-projet",
    description="Mon projet de développement",
    rules=<contenu du fichier .md choisi>
)
```

Ou via la CLI :
```bash
python scripts/mcp_cli.py space create mon-projet "Mon projet" --rules-file RULES/standard.memory.bank.md
```

## Créer son propre modèle

Vous pouvez créer un modèle personnalisé en vous inspirant du modèle standard. Les éléments clés à définir sont :

- **Les fichiers obligatoires** : noms, rôles, contenu attendu
- **La hiérarchie** : comment les fichiers se construisent les uns sur les autres
- **Le mapping consolidation** : quelle catégorie de note alimente quel fichier
- **Les règles de consolidation** : instructions pour le LLM (ne pas perdre d'info, synthétiser, etc.)

> 💡 **Conseil** : un bon modèle de rules est suffisamment précis pour guider le LLM consolidateur, mais assez flexible pour s'adapter à l'évolution du projet.
