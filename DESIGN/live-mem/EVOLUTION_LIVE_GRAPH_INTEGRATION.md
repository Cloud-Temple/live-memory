# Évolution — Intégration Live Memory ↔ Graph Memory

> **Statut** : DRAFT — Vague A appliquée en v2.5.0 (doctrine). Vagues B et C à reviewer par codex avant implémentation.
> **Auteur** : Cline (Christophe Lesur)
> **Date** : 2026-06-03
> **Référence v2.5.0** : `CHANGELOG.md` section [2.5.0]
> **Documents source** : feedback test LLMaaS (juin 2026), `WORKSPACE_CLINE_ADVANCE_RULES.md`, `src/live_mem/tools/graph.py`, `DESIGN/live-mem/ARCHITECTURE.md` §4.4

---

## 1. Contexte

Lors de la phase d'intégration test sur le workspace LLMaaS (juin 2026), un agent externe utilisant simultanément **Live Memory** et **Graph Memory** a remonté un constat structurant :

> *« La connexion automatique est utile, mais la synchronisation automatique de toute la Memory Bank vers Graph Memory est une mauvaise abstraction. »*

Concrètement, le retour terrain a fait apparaître 3 constats :

### 1.1 La Memory Bank est un bootstrap, pas une source canonique

- `activeContext.md` est volontairement **volatile** (session focus snapshot).
- `progress.md` est un **journal borné**, réécrit et compacté en continu.
- Les sous-fichiers `systemPatterns/*` et `techContext/*` sont des **fiches compactes**, pas des archives.
- Le consolidateur Live Memory **résume, déplace, supprime** du détail pour garder la bank légère.

### 1.2 Graph Memory doit indexer des sources stables et canoniques

- **Bons candidats** : MCO/1.Incidents, MCO/3.RFC, runbooks, documents design, README outillage.
- **Mauvais candidats** : `activeContext.md`, `progress.md`, fichiers de bank compactés ou temporaires.
- Le dépôt Git **reste la source de vérité** ; Graph Memory sert de **localisateur sémantique**.

### 1.3 `graph_push` complet de la bank a créé une dette

Sur LLMaaS, plusieurs documents issus de `live-memory/llmaas` et des copies longues de `systemPatterns/*` étaient présents dans Graph. Ces documents devenaient **stale** après chaque compaction de la bank. Nettoyage manuel exigé pour rétablir un graphe propre.

---

## 2. Architecture cible — 3 couches

```
┌─────────────────────────────────────────────────────────────┐
│  Memory Bank (Live Memory)                                  │
│  • activeContext.md  (volatile session focus)               │
│  • progress.md       (bounded recent journal)               │
│  • sub-files         (compact fact sheets)                  │
│  → COMPACT SESSION BOOTSTRAP                                │
└──────────────────┬──────────────────────────────────────────┘
                   │ (the consolidator never pushes here)
                   │
                   │  semantic locator                ┌─────────────────────────┐
                   │ ←────────────────────────────── │ Graph Memory             │
                   │                                  │  • RFCs                  │
                   │                                  │  • Incidents             │
                   │                                  │  • Runbooks              │
                   │                                  │  • Design docs           │
                   │                                  │  → DURABLE SEMANTIC INDEX│
                   │                                  └─────────┬───────────────┘
                   │                                            │
                   │                  agent-side                │
                   │                  ingestion of              │
                   │                  canonical                 │
                   │                  documents only            │
                   ▼                                            ▼
        ┌────────────────────────────────────────────────────────────────┐
        │              Repository files (Git)                            │
        │  → FINAL AUTHORITY                                              │
        └────────────────────────────────────────────────────────────────┘
```

### 2.1 Invariants à respecter

1. **Graph Memory complements the bank; it does not replace it.**
2. **Graph Memory localizes; canonical repository files confirm.**
3. Le **consolidateur Live Memory ne pousse rien dans Graph Memory.** Sa seule responsabilité = mettre à jour la bank selon les rules du space.
4. **L'ingestion Graph est portée côté agent / outillage**, à partir de documents canoniques du dépôt, avec une clé `source_path` stable.
5. `graph_push` n'est **pas** une action de routine. Réservée à : bootstrap initial d'un nouveau graphe, debug / migration explicite.
6. `activeContext.md` et `progress.md` ne doivent **jamais** finir dans Graph Memory.

---

## 3. Vague A — Doctrine (appliquée en v2.5.0)

> **Statut** : ✅ APPLIQUÉE — release v2.5.0.
> **Risque runtime** : zéro. Aucune modification de comportement du serveur.

### 3.1 Modifications appliquées

- [x] **`WORKSPACE_CLINE_ADVANCE_RULES.md`** — Ajout d'une règle verbatim point 5 du feedback :
  > *"Never push `activeContext.md` or `progress.md` to Graph Memory. These files are volatile by design… They must remain Memory-Bank-only and never end up in a Graph ingestion call."*
- [x] **`src/live_mem/tools/graph.py`** — Docstring de `graph_push` enrichie : nouvelle bannière *"Advanced / debug tool — NOT for routine flows"*, section *"Why this is NOT a routine action (architecture note, v2.5.0)"* expliquant le pourquoi, listant les 2 usages acceptables (one-off bootstrap, debug/migration explicite), et pointant vers ce document.
- [x] **`README.md`** + **`README.fr.md`** — Encart « Architecture note (v2.5.0) » dans la section « 🌉 Graph Bridge — Link to Graph Memory » avec les 2 invariants.
- [x] **`DESIGN/live-mem/ARCHITECTURE.md`** — Encart équivalent ajouté dans §4.4 *Graph Push (Bridge to Graph Memory)*, juste avant le diagramme de push.
- [x] **`CHANGELOG.md`** — Section `[2.5.0] — 2026-06-03` complète (Added / Changed / Notes).
- [x] **Version bumps** — `VERSION` 2.4.0 → 2.5.0 ; badges et footers README ; `src/live_mem/__init__.py`.
- [x] **Note `decision`** écrite dans le space `live-mem` pour acter la nouvelle sémantique côté memory bank.

### 3.2 Ce que la Vague A ne change PAS

- Le code de `graph_push` n'est pas modifié. Comportement identique à la v2.4.0.
- L'API MCP est identique (même paramètres, même réponse).
- Aucun garde-fou serveur n'est encore actif. Un opérateur peut toujours appeler `graph_push(space_id)` et la bank complète sera poussée.

La Vague A pose le **contrat doctrinal**. Les Vagues B et C l'encodent dans le code.

---

## 4. Vague B — Garde-fou serveur dans `graph_push` (proposée)

> **Statut** : 🟡 À reviewer / valider par codex avant implémentation.
> **Risque runtime** : potentiel breaking pour les workflows qui poussaient activement la bank entière. Mitigation prévue via flag explicite.

### 4.1 Problème

Tant que `graph_push` pousse aveuglément TOUS les fichiers bank (incluant `activeContext.md` et `progress.md`), n'importe quel agent mal configuré peut indexer des résumés volatiles dans Graph Memory. La doctrine ne suffit pas — un humain pressé contournera. Il faut un garde-fou serveur.

### 4.2 Proposition

Ajouter, côté serveur uniquement :

1. **Configuration** : nouvelle env var `GRAPH_PUSH_VOLATILE_FILES` (CSV, défaut `activeContext.md,progress.md`) listant les fichiers bank considérés volatiles.
2. **Garde-fou par défaut dans `graph_push`** : avant l'ingestion, filtrer la liste des fichiers bank en excluant les volatiles.
3. **Nouveau paramètre `include_volatile: bool = False`** sur l'outil MCP `graph_push`. À `True`, l'opérateur réintroduit explicitement les volatiles dans le périmètre du push (cas debug / migration).
4. **Audit log** : `include_volatile=True` émet un événement structuré sur le logger `live_mem.audit` (`event=graph_push_volatile_optin`, `caller`, `space_id`, `files`).
5. **Réponse enrichie** : `graph_push` retourne désormais `{ pushed: [...], skipped_volatile: [...], errors: [...], duration_s: ... }`. Les `skipped_volatile` ne sont pas une erreur — c'est le comportement attendu.

### 4.3 Points à trancher avec codex

#### B-Q1 — Comportement par défaut : refus silencieux vs erreur explicite ?

Deux options en concurrence :

- **B-Q1.a** (proposée) : **refus silencieux** — `graph_push` sans flag explicite filtre les volatiles et les renvoie dans `skipped_volatile`. La réponse contient `status="ok"`.
  - ✅ Rétrocompatible pour les usages "saine bank" (où l'agent ne pousse de toute façon pas les volatiles).
  - ✅ N'interrompt pas les workflows automatisés existants qui s'attendent à un succès.
  - ❌ Un opérateur qui voulait vraiment pousser tout ne le voit pas tout de suite.
- **B-Q1.b** : **erreur explicite** — `graph_push` retourne `status="error"` et liste les volatiles bloqués. L'opérateur DOIT passer `include_volatile=True` pour pousser.
  - ✅ Force la prise de conscience.
  - ❌ Breaking pour tout client qui appelait `graph_push` en routine.

> **Recommandation Cline** : B-Q1.a (refus silencieux + champ `skipped_volatile` visible). Coût UX faible, breaking nul.

#### B-Q2 — Granularité du filtre

- **B-Q2.a** : liste exacte de noms (`activeContext.md,progress.md`) → simple.
- **B-Q2.b** : patterns glob (`activeContext.md,progress.md,*.draft.md,_synthesis*`) → plus expressif mais aussi plus surprenant.

> **Recommandation Cline** : B-Q2.a pour démarrer, B-Q2.b en évolution si besoin émerge.

#### B-Q3 — `graph_push` et bank vide / aucun fichier non-volatile

Si après filtrage il ne reste **aucun fichier** à pousser : retourner `status="ok", pushed=[], skipped_volatile=[...]`, ou `status="empty"` ? La sémantique propre est `ok` (aucune erreur), mais un humain qui regarde la réponse risque d'interpréter mal.

### 4.4 Critères d'acceptation Vague B

- [ ] `graph_push` filtre par défaut les fichiers listés dans `GRAPH_PUSH_VOLATILE_FILES`.
- [ ] La réponse contient `skipped_volatile: [...]` (jamais vide en filtrage par défaut).
- [ ] `include_volatile=True` réintroduit les volatiles + émet un audit log.
- [ ] Aucun appel `graph_push` ne pousse `activeContext.md`/`progress.md` sans `include_volatile=True`.
- [ ] Tests anti-complaisants `tests/test_graph_volatile_guard.py` :
  - test_push_skips_volatile_by_default
  - test_push_with_include_volatile_pushes_everything
  - test_include_volatile_emits_audit_log
  - test_only_volatile_files_returns_empty_pushed_not_error
  - test_volatile_filter_is_configurable
- [ ] Documentation : `MCP_TOOLS_SPEC.md`, README, ARCHITECTURE §4.4 mis à jour pour montrer la nouvelle réponse et le nouveau paramètre.

### 4.5 Estimation

~150 lignes de code (tools/graph.py + core/graph_bridge.py + config.py + tests), ~1h dev + 30 min revue + 30 min docs. Pas de breaking change si B-Q1.a est retenue.

---

## 5. Vague C — Outil `canonical_ingest` côté serveur (proposée)

> **Statut** : 🟡 À reviewer / valider par codex avant implémentation.
> **Risque runtime** : nouveau outil, additif. Pas de breaking.
> **Note** : Vague C est une vraie évolution produit. Le code peut ne pas être implémenté dans la même PR que la Vague B.

### 5.1 Problème

Aujourd'hui, l'ingestion Graph « propre » repose sur un script agent (`ingest_mco_corpus.py` côté LLMaaS, par exemple) qui :
- liste les fichiers canoniques du dépôt selon une convention,
- les filtre (extensions, exclusions),
- calcule un `source_path` stable + SHA-256,
- envoie en mode dry-run / check-remote / apply via le MCP Graph Memory.

Cette logique est **dupliquée par workspace** et n'est pas standardisée. Live Memory peut offrir un **outil MCP serveur** qui industrialise cette ingestion canonique.

### 5.2 Proposition

1. **Configuration `canonical_sources` par space**, écrite dans `_meta.json` (ou fichier dédié — voir C-Q1) :
   - `paths` : list de chemins repo autorisés (relatifs au repo agent, glob accepté).
   - `exclude` : list de patterns à exclure.
   - `source_path_template` : ex. `"{repo}/{relative_path}"`.
   - `sha256_required` : bool (oblige le calcul de hash).
2. **Nouvel outil MCP `graph_canonical_ingest(space_id, mode)`** :
   - `mode="dry-run"` : liste ce qui SERAIT ingéré (paths, hashes, `source_path`s).
   - `mode="check-remote"` : compare avec Graph Memory pour produire un plan `SKIP / UPDATE / INGEST`.
   - `mode="apply"` : exécute le plan.
3. **Pré-requis** : l'agent fournit les fichiers (via `content_base64` ou via un `source_path` que Live Memory sait résoudre). Cf C-Q2 ci-dessous.
4. **Audit** : chaque `apply` produit un log structuré `event=canonical_ingest` détaillé.

### 5.3 Points à trancher avec codex

#### C-Q1 — Où stocker la config `canonical_sources` ?

- **C-Q1.a** : dans `_meta.json` du space (champ `canonical_sources: {...}`).
  - ✅ Cohérent avec `graph_memory` config déjà stockée là.
  - ✅ Isolé par space.
  - ❌ Pas versionnable côté agent (vit sur S3).
- **C-Q1.b** : fichier dédié `canonical_sources.yaml` à la racine du repo agent, lu par l'agent et envoyé au serveur à chaque appel.
  - ✅ Versionnable, review-friendly.
  - ❌ Plus de surface de bug (drift fichier vs serveur).
- **C-Q1.c** : les deux (`_meta.json` pour la persistance côté serveur, `canonical_sources.yaml` comme source recommandée).

> **Recommandation Cline** : C-Q1.a pour la phase 1 (simple, isolé). C-Q1.c en évolution si l'usage le justifie.

#### C-Q2 — Qui possède le contenu des fichiers ?

Live Memory ne lit pas le dépôt Git de l'agent. Donc soit :

- **C-Q2.a** : l'agent push lui-même via le MCP Graph Memory en s'appuyant sur la config canonique côté Live Memory comme **source de plan** (dry-run / check-remote). Live Memory ne pousse rien.
- **C-Q2.b** : l'agent push les blobs vers un endpoint Live Memory (S3) qui forward vers Graph Memory.

> **Recommandation Cline** : C-Q2.a. Live Memory reste un **planificateur** ; l'ingestion reste agent-driven. Évite de transformer Live Memory en proxy MCP.

#### C-Q3 — Périmètre v1 du tool

Pour ne pas surdimensionner, démarrer minimal :
- v1 : `graph_canonical_ingest_plan(space_id)` retourne le plan (sans exécution), basé sur la config `_meta.json`.
- v2+ : exécution via callback agent (hors scope phase 1).

### 5.4 Critères d'acceptation Vague C

À définir avec codex selon les arbitrages C-Q1/Q2/Q3.

### 5.5 Estimation

Phase 1 (planification seule, `graph_canonical_ingest_plan`) : ~250 lignes, ~3h dev + tests + docs. Phase 2+ : à scoper.

---

## 6. Points pour la review codex

Codex est sollicité pour reviewer ce document et trancher les 5 questions ouvertes :

| Réf  | Question                                                                                 | Recommandation Cline |
| ---- | ---------------------------------------------------------------------------------------- | -------------------- |
| B-Q1 | Refus silencieux (skipped_volatile) vs erreur explicite ?                                | B-Q1.a (silencieux)  |
| B-Q2 | Filtre par noms exacts vs patterns glob ?                                                | B-Q2.a (exacts)      |
| B-Q3 | Sémantique de la réponse quand aucun fichier non-volatile ne reste ?                     | `status=ok, pushed=[]` |
| C-Q1 | Config `canonical_sources` dans `_meta.json` vs fichier YAML dépôt ?                     | C-Q1.a (`_meta.json`) |
| C-Q2 | Live Memory planifie (ingest agent-driven) vs Live Memory pousse (proxy) ?               | C-Q2.a (planifie)    |

Méthode de review : `codex exec` avec ce document en input. Voir `Annexe A` ci-dessous.

---

## 7. Roadmap

| Vague | Statut       | Cible release | Risque runtime              | Dépendance     |
| ----- | ------------ | ------------- | --------------------------- | -------------- |
| A     | ✅ Appliquée | v2.5.0        | Aucun                       | —              |
| B     | 🟡 À review  | v2.6.0        | Faible si B-Q1.a            | Review codex   |
| C     | 🟡 À review  | v2.7.0+       | Nul (additif)               | Vague B + codex |

---

## Annexe A — Méthode de review codex

```bash
cd /Users/clesur/PROJETS/live-mem
codex exec --skip-git-repo-check \
  "Tu es invité à reviewer le document DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md.
   Il décrit la séparation Live Memory ↔ Graph Memory en 3 vagues. La Vague A est déjà
   appliquée en v2.5.0 (doctrine, zéro runtime change). Les Vagues B (garde-fou serveur
   dans graph_push) et C (outil canonical_ingest) attendent une validation avant
   implémentation.

   Tranche explicitement les 5 questions B-Q1, B-Q2, B-Q3, C-Q1, C-Q2 listées
   dans la section 6 du document. Justifie chaque arbitrage. Identifie aussi
   les points aveugles du document (risques, alternatives non explorées).
   Réponds en français, format markdown structuré."
```

---

## Annexe B — Références

- Feedback agent externe (juin 2026) : voir conversation Cline, contexte test LLMaaS.
- `WORKSPACE_CLINE_ADVANCE_RULES.md` (v2.5.0) — template avancé.
- `src/live_mem/tools/graph.py` — docstring `graph_push` v2.5.0.
- `DESIGN/live-mem/ARCHITECTURE.md` §4.4 — encart d'architecture v2.5.0.
- `README.md` / `README.fr.md` — section « 🌉 Graph Bridge » v2.5.0.
- `CHANGELOG.md` section `[2.5.0]`.
