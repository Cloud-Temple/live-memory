# Changelog — Live Memory

Toutes les modifications notables sont documentées ici.
Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [Unreleased]

### Ajouté
- **Support proxy HTTP sortant (`PROXY_URL`)** — Nouvelle variable d'environnement optionnelle pour router les appels sortants (S3 et LLM) via un proxy HTTP. Utilise une variable custom (`PROXY_URL`) plutôt que `HTTP_PROXY`/`HTTPS_PROXY` pour ne pas affecter les autres bibliothèques Python qui lisent automatiquement les variables d'environnement OS.
  - `storage.py` : proxy injecté dans les deux clients boto3 (SigV2 et SigV4) via `Config(proxies=...)`.
  - `consolidator.py` : proxy injecté dans `AsyncOpenAI` via un `httpx.AsyncClient(proxy=...)` pré-configuré.
  - `graph_bridge.py` : non supporté (limitation du SDK MCP `streamablehttp_client` — documenté dans le code).
  - Validation au démarrage : si `PROXY_URL` est défini, l'URL doit commencer par `http://` ou `https://`.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/config.py` | Nouveau champ `proxy_url: str = ""` + validation dans `_validate_config` |
| `src/live_mem/core/storage.py` | Construction de `_proxies` depuis `proxy_url`, injection dans `Config()` SigV2 et SigV4, log au démarrage |
| `src/live_mem/core/consolidator.py` | Import `httpx`, construction `httpx.AsyncClient(proxy=...)` si `proxy_url`, passage à `AsyncOpenAI(http_client=...)` |
| `src/live_mem/core/graph_bridge.py` | Note de limitation dans la docstring de `GraphMemoryClient.__init__` |
| `.env.example` | Nouvelle entrée `#PROXY_URL=http://10.185.132.250:3128` (commentée) |
| `README.md`, `README.en.md` | Ligne `PROXY_URL` dans le tableau des variables optionnelles |

---

## [1.7.4] — 2026-05-10

### Ajouté
- **Réparation automatique de JSON LLM tronqué** — Nouvelle fonction `_repair_json()` dans `consolidator.py` qui détecte les erreurs "Unterminated string" (fréquentes avec qwen3.x, `finish_reason=stop`) et répare le JSON avant de retomber sur le retry coûteux. Stratégie : tronquer au point de l'erreur, fermer les structures JSON ouvertes via `_close_json_structure()`, supprimer la dernière opération tronquée. Économise ~100s et ~50K tokens par occurrence.
- **Garde-fou retry sur repair vide** — Si la réparation JSON réussit mais produit 0 `file_edits` (troncature très précoce), le code retombe sur le retry LLM au lieu d'accepter silencieusement un résultat vide (évite la perte de données).
- **29 tests unitaires** (`tests/test_json_repair.py`) — Couvrent `_close_json_structure` (10 tests : niveaux imbriqués, strings avec accolades, échappements, backslash) et `_repair_json` (19 tests : comptage exact d'opérations, troncature dans content/heading/filename, create tronqué, guillemets échappés, scénario réaliste qwen3.6, intégrité JSON).

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/core/consolidator.py` | `_call_llm()` : tentative de repair avant retry, garde-fou `repaired_files > 0`. Nouvelles fonctions `_repair_json()` et `_close_json_structure()` |
| `tests/test_json_repair.py` | **Nouveau** — 29 tests unitaires (5 classes) |
| `DESIGN/live-mem/CONSOLIDATION_LLM.md` | Section 8.4 : réparation automatique JSON |
| `VERSION`, `__init__.py`, `CHANGELOG.md` | Bump 1.7.3 → 1.7.4 |

---

## [1.7.3] — 2026-05-07

### Amélioré
- **Logging diagnostic consolidation** — Le WARNING `LLM: JSON invalide` dans `_call_llm()` logge maintenant `finish_reason`, `completion_tokens` et `visible_tokens_est` en plus des champs existants. Permet de diagnostiquer les JSON tronqués (thinking tokens consommant le budget de sortie, cap API côté serveur, ou arrêt prématuré du modèle) sans avoir à deviner la cause.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/core/consolidator.py` | `_call_llm()` : capture `finish_reason` et `completion_tokens` après chaque appel LLM, ajout de `visible_tokens_est` dans le WARNING |
| `VERSION`, `__init__.py`, `CHANGELOG.md` | Bump 1.7.2 → 1.7.3 |

---

## [1.7.2] — 2026-05-05

### Corrigé
- **Issue #11 — Token UX traps** — Trio cohérent de bugs UX autour des tokens (pas une faille de sécurité, mais source garantie de friction à chaque onboarding).
  - **Documentation contradictoire avec v1.5.0** : les `Field.description` et docstrings de `admin_create_token` (`tools/admin.py`) et `TokenService.create_token` (`core/tokens.py`) disaient encore "vide = tous les espaces", alors que la sémantique stricte v1.5.0 stipule "vide = aucun accès" pour les non-admin. Corrigé pour refléter la réalité du code.
  - **Tokens "muets" créés silencieusement** : `admin_create_token(space_ids="")` produisait un token techniquement valide mais incapable d'accéder à aucun espace existant (403 systématique). La réponse contient désormais un champ `warning_no_access` explicite quand le token résultant n'a aucun espace autorisé et n'est pas admin.
  - **Sucre syntaxique `*` / `all`** : `admin_create_token(space_ids="*")` ou `space_ids="all"` prend désormais un **snapshot** des espaces existants au moment de la création (les futurs nouveaux spaces ne sont pas inclus, pour rester aligné avec la sémantique stricte v1.5.0). La réponse inclut `snapshot_taken: true` et un message `info` détaillant la liste matérialisée.
  - **Préfixe `sha256:` non documenté** : `_find_token_by_hash` exigeait que le hash passé à `admin_revoke_token` / `admin_delete_token` / `admin_update_token` inclue le préfixe `sha256:` retourné par `admin_list_tokens`. Si l'utilisateur copiait juste la partie hex, l'opération retournait silencieusement `Token introuvable`. La méthode normalise désormais l'entrée et accepte les deux formes (`sha256:abc...` ou `abc...`). La validation min 16 chars s'applique maintenant sur le hex pur, et le message d'erreur indique la longueur du hex pur (review #12).
  - **Cohérence `admin_update_token`** (review #12) : le sucre `*`/`all` et le `warning_no_access` sont également appliqués à `update_token` (extraction d'un helper privé `_resolve_space_ids`), évitant que la même trappe UX réapparaisse lors d'une mise à jour.

---

## [1.7.1] — 2026-05-04

### Corrigé
- **Bug critique : contextvars stale dans les sessions MCP Streamable HTTP** — Les `check_access()`, `check_write_permission()`, `check_manage_permission()` et `check_admin_permission()` lisaient `current_token_info` depuis un contextvar figé à l'initialisation de la session MCP. Le SDK MCP Python crée un task `anyio` long-running par session (`streamable_http_manager.py:243-276`) ; les tool handlers s'exécutent dans ce task avec une copie du contexte asyncio de l'initialisation. Les mises à jour de `space_ids` (via `add_space_to_token` lors de `space_create`) ou de permissions (via `admin_update_token`) étaient invisibles jusqu'au redémarrage de la session MCP.
  - **Fix** : Ajout d'un `_fresh_token_store` (dict global mutable) dans `auth/context.py`, alimenté par `AuthMiddleware` à chaque requête HTTP. Les fonctions `check_xxx()` utilisent désormais `_get_effective_token_info()` qui priorise le store frais sur le contextvar stale.
  - **Impact** : les `space_ids` et permissions sont immédiatement visibles après modification, sans reconnexion MCP.
- **CLI `token list` : hash tronqué inutilisable** — Rich tronquait le hash SHA-256 (73 chars) à ~10 chars (`sha256:f9…`), rendant impossible le copier-coller pour `token update/revoke/delete` (minimum 16 chars requis par `_find_token_by_hash`). Fix : troncature explicite à 24 chars (`sha256:f97fbf7c3b4460ff…`), suffisant pour identifier un token de manière unique. Hash complet toujours disponible via `--json`.
- **`space_list` : données stale** — Utilisait `current_token_info.get()` directement au lieu de `_get_effective_token_info()`, souffrant du même bug de contextvar stale.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/auth/context.py` | +56 lignes : `_fresh_token_store`, `update_fresh_token()`, `_get_effective_token_info()`. Les 4 `check_xxx()` utilisent `_get_effective_token_info()` |
| `src/live_mem/auth/middleware.py` | `AuthMiddleware.__call__()` : appel `update_fresh_token()` après validation |
| `src/live_mem/tools/space.py` | `space_list()` : utilise `_get_effective_token_info()` |
| `scripts/cli/display.py` | `show_token_list()` : hash tronqué à 24 chars au lieu de laisser Rich tronquer |
| `VERSION`, `__init__.py`, `README.md`, `README.en.md`, `CHANGELOG.md` | Bump 1.7.0 → 1.7.1 |

---

## [1.7.0] — 2026-04-27

### Corrigé
- **Issue #8 — Web UI : descriptions d'espaces non tronquées dans le dropdown** — Sur l'interface `/live`, le sélecteur `<select id="spaceSelect">` affichait `space_id — description` complète. Quand un espace avait une description longue (plusieurs phrases), le dropdown s'étirait au-delà du viewport et cassait la mise en page du header. Les `<option>` HTML natifs ne supportant pas `text-overflow: ellipsis`, la troncature doit se faire côté JS.
  - **Fix JS** (`src/live_mem/static/js/app.js` — `fillSpaceSelect`) : description tronquée à `MAX_DESC = 70` caractères avec suffixe `…`. Description complète conservée en `option.title` (tooltip natif au survol). La valeur `option.value = s.space_id` reste intacte (zéro impact fonctionnel).
  - **Fix CSS** (`src/live_mem/static/css/live.css`) : ajout de `#spaceSelect { max-width: 360px; text-overflow: ellipsis; }` pour borner la largeur du sélecteur fermé, même quand un `space_id` lui-même est très long.

### Fichiers modifiés
| Fichier                                | Changements                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `src/live_mem/static/js/app.js`        | `fillSpaceSelect()` : troncature à 70 chars + `option.title` avec description complète           |
| `src/live_mem/static/css/live.css`     | Règle `#spaceSelect` : `max-width: 360px` + `text-overflow: ellipsis`                            |
| `VERSION`, `__init__.py`, `README.md`, `README.en.md`, `CHANGELOG.md` | Bump 1.6.1 → 1.7.0 |

---

## [1.6.1] — 2026-04-25


### Corrigé
- **Audit middleware "unauthenticated"** — `AuditMiddleware` wrappait `AuthMiddleware`, son `finally` s'exécutait après le `reset()` du contextvar → le client apparaissait toujours comme `"unauthenticated"` dans les logs d'audit. Fix : réordonnancement de la pile middleware (Audit maintenant wrappé PAR Auth). Ajout d'un audit log directement dans `AuthMiddleware` pour les rejets 401.
- **Diagnostic consolidation JSON** — Ajout du logging de la réponse brute du LLM (tronquée à 500 chars) en cas d'échec de parsing JSON (`json_error`, `raw_len`, `raw_preview`). Permet de diagnostiquer la cause racine des échecs de consolidation.

### Modifié
- **Pile middlewares ASGI** — Corrigée : RequestId → Metrics → Auth → **Audit** → Logging → ResponseLimit → StaticFiles → MCP. L'audit est désormais wrappé par Auth pour accéder au `current_token_info` avant son `reset()`. Les rejets 401 sont audités par Auth directement.

---

## [1.6.0] — 2026-04-25

### Ajouté (PR #7 — BeArchiTek/Benoit Kohler)
- **Health probe enrichi** — `/health` teste désormais S3 **et** LLMaaS, retourne `healthy`/`degraded`/`unhealthy` avec détail par service, latence et disponibilité du modèle configuré. Probe LLMaaS via `models.list()` (zéro consommation de tokens).
- **4 middlewares ASGI** — `RequestIdMiddleware` (UUID `X-Request-Id`), `MetricsMiddleware` (`/metrics` Prometheus + JSON), `AuditMiddleware` (trail JSON structuré), `ResponseLimitMiddleware` (512 KB sur `/api/*`, paths MCP exclus).
- **MCP tool annotations** — `readOnlyHint`, `destructiveHint`, `idempotentHint` sur les 39 outils MCP, conforme au standard MCP.
- **Config validation fail-fast** — Le serveur refuse de démarrer si la configuration est invalide (port hors range, S3 partiel, URL malformée, bootstrap key par défaut, etc.).
- **37 tests unitaires** — Couverture des middlewares, de la validation de config et du health probe (`tests/test_config.py`, `tests/test_middleware.py`).
- **Logging JSON structuré** — Format JSON pour l'agrégation de logs en production (ELK, Loki).
- **Docker Compose profiles** — MinIO en `profiles: [dev]` : `docker compose up` = prod (S3 distant), `docker compose --profile dev up` = dev (MinIO local).

### Modifié
- **Migration dépendances** — `requirements.txt` → `pyproject.toml` + `uv.lock`. ⚠️ **Breaking change** : `pip install -r requirements.txt` ne fonctionne plus, utiliser `uv sync --frozen`.
- **Dockerfile** — Multi-stage avec `uv sync --frozen`, layer caching séparé deps/source.
- **CLI health** — Utilise HTTP `/health` directement au lieu du handshake MCP complet (plus rapide, pas d'auth nécessaire).
- **Pile middlewares ASGI** — Réordonnée : Audit → Auth → RequestId → Metrics → ResponseLimit → Logging → StaticFiles → MCP. L'audit middleware est placé avant l'auth pour capturer les rejets 403.
- **CLI `token update`** — Fix du bug `--permissions` avec `default=None` au lieu de `default=""` (Click.Choice rejetait la valeur vide).

### Corrigé
- **ResponseLimitMiddleware** — Paths MCP (`/mcp`) exclus de la troncature pour protéger `space_export` et `backup_download` (archives base64 > 512 KB).

---

## [1.5.1] — 2026-04-22

### Corrigé
- **Détection hiérarchique des doublons** — `_detect_duplicates()` comparait les headings de façon plate : deux `### X` sous des `## A` et `## B` différents étaient faussement détectés comme doublons et fusionnés via LLM, corrompant la bank à chaque consolidation. Fix : chemin hiérarchique complet (`## Parent A > ### Child > #### Grandchild`), supportant la profondeur arbitraire.
- **Optimisation performance dédup** — Ajout de 2 fast-paths dans `_deduplicate_content()` qui évitent l'appel LLM quand c'est inutile : (1) versions identiques → garder la dernière, (2) sous-ensemble de lignes → garder la version la plus complète. Comparaison au niveau des lignes (`issubset`) et non des sous-chaînes (`in`) pour éviter les faux positifs.
- **Tests obsolètes corrigés** — 7 tests dans `test_bank_compact.py` mis à jour pour refléter la limite universelle `BANK_FILE_MAX_SIZE=15360` et les instructions de compaction génériques (v1.4.0+).

### Ajouté
- **14 tests unitaires de détection hiérarchique** dans `test_dedup_fix.py` — couvrent : faux doublons (### sous ## différents), vrais doublons (même parent), profondeur 3 niveaux, mix vrais/faux, algorithme itératif, préservation du contenu non-dupliqué.
- **Template Product Management Memory Bank v1.1.0** (PR #4) — Nouveau modèle de rules `RULES/product.management.memory.bank.md` (390 lignes) pour les équipes Produit (Product Management, Product Design, UX Writing). Hiérarchie de 10+ fichiers obligatoires (`productVision`, `portfolio`, `marketIntelligence`, `userKnowledge`, `stakeholders`, `designSystem`, `communicationGuide`, `engineeringContext`, `discoveryPlaybook`, `activeContext`, `roadmapProgress`) + fichiers dynamiques (`persona-[name].md`, `framework-[name].md`). **6 templates de rules** disponibles dans `RULES/` (était 5).

### Amélioré
- **CLI : unwrap ExceptionGroup/TaskGroup** (PR #5) — Le SDK MCP utilise des `anyio.TaskGroup` qui encapsulent les erreurs HTTP (ex: 401) dans un `ExceptionGroup`. L'erreur réelle était masquée par un message générique. La CLI déroule désormais récursivement les `BaseExceptionGroup` pour afficher la cause racine.
- **CLI : acceptation du statut `degraded`** (PR #5) — `_run_tool()` considère désormais `degraded` comme un statut de succès (en plus de `ok`, `healthy`, `created`, etc.), évitant un faux message d'erreur quand le health check retourne un service partiellement disponible.

### Fichiers modifiés (8)
- `src/live_mem/core/consolidator.py` — `_detect_duplicates()` hiérarchique, `_deduplicate_content()` fast-paths
- `scripts/test_dedup_fix.py` — 14 tests unittest (réécriture complète)
- `scripts/test_bank_compact.py` — 7 tests corrigés (limites universelles)
- `scripts/cli/client.py` — Unwrap `BaseExceptionGroup` dans le handler d'erreur MCP (PR #5)
- `scripts/cli/commands.py` — Ajout de `degraded` dans les statuts de succès (PR #5)
- `RULES/product.management.memory.bank.md` — Nouveau template Product Management (PR #4)
- `RULES/README.md` — Ajout du template Product Management dans le catalogue
- `VERSION`, `__init__.py`, `CHANGELOG.md`, `README.md`, `README.en.md`

---

## [1.5.0] — 2026-04-15

### Ajouté
- **Permission `manage`** — 4ème niveau de permission dans la hiérarchie : `admin ⊃ manage ⊃ write ⊃ read`.
  - `manage` donne accès aux opérations de maintenance : `bank_write`, `bank_delete`, `bank_repair`, `bank_compact`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete`.
  - Un agent standard (`write`) ne peut plus manipuler directement les fichiers bank ni supprimer des espaces.
  - `admin` reste requis pour la gestion des tokens et le GC.
- **`check_manage_permission()`** dans `auth/context.py` — nouveau helper de vérification.
- **Migration automatique v1.5.0** au démarrage du serveur — les tokens non-admin ayant `space_ids=[]` se voient assigner tous les espaces existants.
- **Timeout 600s documenté** dans `GUIDE_INTEGRATION_CLINE.md` — toutes les configurations MCP (Cline et Claude Desktop) incluent désormais `"timeout": 600`.

### Modifié
- **Sémantique de `space_ids=[]`** — signifie désormais "aucun accès" pour les non-admin (au lieu de "tous"). Un token fraîchement créé n'a accès à rien d'existant — il crée ses propres espaces (auto-ajoutés via `add_space_to_token`).
- **`add_space_to_token()`** — ajoute toujours le space, même si `space_ids` est vide (anciennement skippé).
- **`space_list`** — retourne une liste vide pour les non-admin avec `space_ids=[]` (au lieu de tout lister).
- **`backup_list`** — filtrage adapté pour les non-admin avec `space_ids=[]`.
- **8 outils remontés en `manage`** :
  - De `write` → `manage` : `bank_delete`, `bank_repair`, `bank_compact`
  - De `admin` → `manage` : `bank_write`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete`
- **CLI et shell** — support complet du niveau `manage` dans la validation des permissions et l'autocomplétion.

### Fichiers modifiés (15)
- `src/live_mem/auth/context.py` — `check_manage_permission()`, docstring 4 niveaux, `check_access()` inversé
- `src/live_mem/core/tokens.py` — `VALID_PERMISSIONS` + `manage`, `migrate_empty_space_ids()`, `add_space_to_token()` simplifié
- `src/live_mem/tools/bank.py` — 4 outils passés en `check_manage`
- `src/live_mem/tools/space.py` — `space_delete` et `space_update_rules` en `check_manage`, `space_list` filtrage
- `src/live_mem/tools/backup.py` — `backup_restore` et `backup_delete` en `check_manage`, `backup_list` filtrage
- `src/live_mem/server.py` — migration v1.5.0 au démarrage
- `scripts/cli/commands.py` — `VALID_PERMISSIONS` mis à jour
- `scripts/cli/shell.py` — `_VALID_PERMS`, autocomplétion, messages d'aide
- `VERSION`, `__init__.py`, `CHANGELOG.md`, `GUIDE_INTEGRATION_CLINE.md`

---

## [1.4.1] — 2026-04-11

### Corrigé
- **Anti-doublon sémantique dans le consolidateur** — Après une compaction, le consolidateur ne reconnaissait pas que les entrées résumées (format court) et les nouvelles notes (format détaillé) décrivaient le même travail. Résultat : doublons massifs dans `progress.md` (ex: "Phase B — LiveMemoryService créé" ET "Session du 10/04 — Phase B COMPLÈTE"). Ajout d'une instruction explicite dans le `SYSTEM_PROMPT` pour détecter les jalons sémantiquement équivalents et enrichir l'existant au lieu de créer de nouvelles sections.
- **Migration du modèle LLM par défaut** — Remplacement de `qwen3-2507:235b` par `qwen3.5:27b` dans toute la codebase (config, descriptions MCP, documentation). Les descriptions MCP utilisent désormais des références génériques (`LLMAAS_MODEL`) au lieu de noms de modèles en dur.

---

## [1.4.0] — 2026-04-11

### Ajouté — Bank Compaction (auto-compaction + outil MCP `bank_compact`)

#### Outil MCP `bank_compact` (39ème outil, admin only)
Expose la mécanique de compaction (implémentée dans le consolidateur depuis v1.4.0-beta) comme outil MCP autonome. Analyse chaque fichier bank et compare sa taille à la limite configurée (`activeContext.md`: 8KB, `progress.md`: 20KB, autres: 15KB).

- Mode **dry-run** (par défaut) : rapporte les fichiers surdimensionnés et leur ratio, sans modification.
- Mode **apply** : compacte effectivement via appel LLM dédié, protégé par le lock de consolidation.
- Permission **admin** requise (cohérent avec `bank_write` et `bank_repair` qui modifient la bank directement).
- **CLI Click** : `bank compact <space_id> [--apply] [--json]`.
- **Shell interactif** : `bank compact <space> [--apply]` avec autocomplétion.
- **Affichage Rich** (`show_bank_compact_result`) : panel résumé + tableau détaillé par fichier (taille, limite, ratio coloré vert/jaune/rouge, statut de compaction avec % de réduction).
- Catégorie Bank : 7 → **8 outils MCP**.

#### Auto-compaction intégrée au pipeline de consolidation
- Déclenchement automatique si la bank dépasse `compact_threshold` (60%) du `max_tokens` avant consolidation.
- Méthode publique `compact_bank(space_id, dry_run)` dans `ConsolidatorService`.
- 5 nouveaux paramètres de configuration : `compact_threshold`, `bank_file_max_size`, `bank_active_context_max_size`, `bank_progress_max_size`.
- **Budget de sortie dynamique** (`_call_llm`) : `output_budget = max(8192, context_window - estimated_input_tokens)` — évite les dépassements de context window.
- **SYSTEM_PROMPT anti-accumulation** : instructions explicites pour nettoyer l'obsolète et résumer les sections anciennes.
- Tests automatisés : `scripts/test_bank_compact.py` — 20/20 PASS.

### Corrigé
- **Bug CLI `--json` : ANSI pollution** — `show_json()` utilisait `Rich.Syntax` qui injectait des codes ANSI dans le JSON, rendant la sortie `--json` non-parseable quand redirigée ou pipée. Corrigé par un `print(json.dumps(...))` brut sur stdout. Le JSON est désormais machine-readable et pipeable (`| jq`, `| python -c "import json..."`, etc.).

---

## [1.3.1] — 2026-04-01

### Corrigé
- **Bug `IndexError: list index out of range` dans `_deduplicate_content()`** — La méthode de déduplication des sections dupliquées crashait quand un fichier bank contenait **plusieurs headings dupliqués différents** (ex: 5 doublons dans `activeContext.md`). La cause : les indices des doublons étaient calculés une seule fois au début (`_detect_duplicates`), puis utilisés dans une boucle `for` qui modifiait la liste de sections (`pop()`). Après le traitement du premier doublon, les indices des doublons suivants pointaient vers des positions invalides dans la liste raccourcie → `IndexError`.
- **Fix** : remplacement de la boucle `for` par une boucle `while` qui **re-détecte les doublons** sur le contenu mis à jour à chaque itération. Chaque itération ne traite qu'un seul doublon, reconstruisant le contenu entre chaque fusion. Sécurité anti-boucle infinie (max 50 itérations) et vérification défensive des indices avant accès.

### Ajouté
- **Script de test `scripts/test_dedup_fix.py`** — 17 tests unitaires reproduisant le bug exact (5 doublons simultanés, heading triplé, fichier sans doublons) et validant le nouveau comportement. Confirme que l'ancien algorithme crashe et que le nouveau fonctionne sans perte de contenu.

---

## [1.3.0] — 2026-03-28

### Ajouté
- **Fix anti-doublons consolidateur** (3 niveaux de protection) :
  - **Fix A — Prévention** : `_op_add_section()` vérifie si le heading existe déjà et convertit automatiquement en `replace_section` avec WARNING dans les logs. Empêche la création de doublons à la source.
  - **Fix B — Détection + Fusion LLM** : nouvelles méthodes `_deduplicate_content()` et `_merge_sections_via_llm()` dans `ConsolidatorService`. Après chaque action `edit` ou `rewrite`, détecte les sections dupliquées et les fusionne intelligemment via un appel LLM dédié (prompt court, température 0.1). Fallback mécanique (garder la dernière occurrence) si le LLM échoue.
  - **Fix C — Guidance LLM** : instruction explicite dans le `SYSTEM_PROMPT` interdisant `add_section` sur un heading déjà existant.
- Fonction utilitaire `_detect_duplicates()` : détecte les headings dupliqués dans un fichier Markdown.

### Modifié
- `test_recette.py` : mise à jour des références de version v0.7.5 → v1.2.0, 32/33 → 38 outils MCP.

### Corrigé
- **Bug récurrent de doublons de sections** dans les Memory Banks : les sections comme "État technique V2" ou les phases dans `progress.md` pouvaient être dupliquées par le consolidateur LLM lors d'opérations `add_section` sur des headings existants. Le bug était auto-renforçant (les doublons dans la bank étaient reproduits par le LLM lors des consolidations suivantes).

---

## [1.2.0] — 2026-03-27

### Ajouté
- **Outil MCP `space_update_rules`** (38ème outil, admin only) : permet de mettre à jour les rules d'un espace sans le supprimer/recréer. Implémenté dans `core/space.py`, `tools/space.py`, CLI Click, shell interactif et affichage Rich.
- **Template RULES v1.2.0** (`RULES/live-mem.standard.memory.bank.md`) : 3 nouvelles règles de consolidation anti-duplication :
  - Règle 7 : "Mettre à jour, ne pas dupliquer" (remplace "Enrichir, ne pas écraser")
  - Règle 9 : "Nettoyer l'obsolète" (retirer les items terminés des backlogs, corriger les métriques)
  - Règle 10 : "Garder les fichiers concis" (activeContext < 8 KB, autres < 15 KB)
- Limites de taille dans les descriptions de fichiers bank : taille cible pour `activeContext.md`, instruction de remplacement pour `systemPatterns.md`, items terminés à retirer dans `progress.md`.

### Modifié
- Catégorie Space : 8 → 9 outils MCP.
- Règle de consolidation n°1 nuancée : "Ne jamais perdre d'information **pertinente**" — les données obsolètes, remplacées ou dupliquées DOIVENT être nettoyées.

---

## [1.1.0] — 2026-03-26

### Ajouté
- **Rules par défaut (`DEFAULT_RULES_FILE`)** — Nouveau paramètre `.env` permettant de spécifier un fichier de rules Markdown utilisé par défaut quand `space_create` est appelé sans paramètre `rules`. Élimine le besoin de passer manuellement les rules à chaque création d'espace.
- **Paramètre `rules` optionnel dans `space_create`** — Si vide, le serveur charge automatiquement les rules depuis le fichier configuré dans `DEFAULT_RULES_FILE`. Message d'erreur explicite si aucun fichier par défaut n'est configuré.
- **Dossier `RULES/` inclus dans l'image Docker** — Ajout de `COPY RULES/ RULES/` dans le Dockerfile pour que les templates de rules soient disponibles dans le conteneur.

### Modifié
- `src/live_mem/config.py` — Ajout du champ `default_rules_file: str = ""` dans `Settings`.
- `src/live_mem/tools/space.py` — `rules` rendu optionnel avec fallback sur `DEFAULT_RULES_FILE`.
- `.env.example` — Documentation du nouveau paramètre `DEFAULT_RULES_FILE`.
- `Dockerfile` — Copie du dossier `RULES/` dans l'image.

---

## [1.0.0] — 2026-03-24

### Sécurité — Audit complet et 15 remédiations

**Audit de sécurité complet** réalisé sur la v0.9.0, couvrant 10 domaines (authentification, validation des entrées, S3, LLM, web, réseau, cryptographie, configuration, gestion d'erreurs, supply chain). Rapport : `DESIGN/live-mem/AUDIT_SECURITE_2026-03-24.md` (27 constats, correspondance OWASP API Security Top 10).

**15 vulnérabilités corrigées** — 56/56 tests PASS.

#### 🔴 Critiques (3)
- **VULN-01 — Race condition tokens.json** — `validate_token()` ne fait plus de `_save_store()` pour `last_used_at`. Le champ est mis en cache mémoire (`_last_used_cache`), éliminant la race condition avec `create_token()`/`revoke_token()` qui sont sous lock.
- **VULN-02 — API REST sans contrôle d'accès par espace** — `check_access(space_id)` ajouté dans les 5 endpoints `/api/*` (`_api_space_info`, `_api_live_notes`, `_api_bank_list`, `_api_bank_file`). Un token restreint ne peut plus lire les données d'un autre espace via l'interface web.
- **VULN-07 — Validation de taille sur content/rules/description** — Limites implémentées : `MAX_NOTE_CONTENT_SIZE=100000` (live_note), `MAX_RULES_SIZE=50000` (space_create), `MAX_DESCRIPTION_SIZE=500` (space_create). Empêche le DoS par épuisement S3.

#### 🟠 Élevés (6)
- **VULN-03 — Correspondance hash tokens sécurisée** — Nouveau helper `_find_token_by_hash()` avec minimum 16 caractères de préfixe et détection d'ambiguïté (erreur si plusieurs tokens matchent). Appliqué à `revoke_token`, `delete_token`, `update_token`.
- **VULN-08 — Validation space_id dans check_access()** — Regex `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` vérifiée dans `check_access()` avant la vérification des permissions. Empêche les path traversal via `_system`, `_backups`, `../`.
- **VULN-12 — Token Graph Memory masqué** — Le token Graph Memory dans `_meta.json` est masqué dans les réponses API (8 premiers caractères + `...`). Empêche l'escalade de privilèges read → write sur Graph Memory.
- **VULN-17 — CORS supprimé** — Le header `Access-Control-Allow-Origin: *` a été supprimé de `_send_json()`. L'interface `/live` est servie par le même serveur (même origine), aucun CORS nécessaire.
- **VULN-25 — Bootstrap key obligatoire** — Le serveur refuse de démarrer si `ADMIN_BOOTSTRAP_KEY` est dans la liste des clés faibles (`change_me_in_production`, `changeme`, `admin`, `password`, vide) ou fait moins de 32 caractères (warning).

#### 🟡 Moyens (5)
- **VULN-04 — Comparaison constant-time bootstrap key** — `hmac.compare_digest()` remplace `==` pour la comparaison du bootstrap key.
- **VULN-09 — Validation filename contre path traversal** — Rejet des filenames contenant `..` ou commençant par `/` dans `_api_bank_file`.
- **VULN-10 — Paramètre limit borné** — `live_read` limite le `limit` à `MAX_LIVE_READ_LIMIT=500`.
- **VULN-13 — Logging des erreurs dans delete_many()** — Les erreurs de suppression S3 sont loggées (`logger.warning`) au lieu d'être ignorées silencieusement.
- **VULN-27 — Erreurs masquées en production** — Nouveau helper `safe_error()` dans `auth/context.py` : message générique en prod (`MCP_SERVER_DEBUG=false`), message complet en debug. 34 blocs `except` remplacés dans 6 fichiers tools.

#### 🟢 Faible (1)
- **VULN-11 — bank_relpath dans API REST** — `_api_bank_list` utilise `bank_relpath()` au lieu de `split("/")[-1]` pour supporter les sous-dossiers.

### Fichiers modifiés
| Fichier                                        | Changements                                                                                                                  |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `src/live_mem/core/tokens.py`                  | VULN-01 (`_last_used_cache`), VULN-03 (`_find_token_by_hash`, min 16 chars)                                                  |
| `src/live_mem/auth/context.py`                 | VULN-08 (regex space_id), VULN-27 (`safe_error()` helper)                                                                    |
| `src/live_mem/auth/middleware.py`              | VULN-02 (check_access API), VULN-04 (hmac), VULN-09 (filename), VULN-11 (bank_relpath), VULN-12 (mask token), VULN-17 (CORS) |
| `src/live_mem/core/live.py`                    | VULN-07 (MAX_NOTE_CONTENT_SIZE), VULN-10 (MAX_LIVE_READ_LIMIT)                                                               |
| `src/live_mem/core/space.py`                   | VULN-07 (MAX_RULES_SIZE, MAX_DESCRIPTION_SIZE)                                                                               |
| `src/live_mem/core/storage.py`                 | VULN-13 (logging delete_many)                                                                                                |
| `src/live_mem/server.py`                       | VULN-25 (bootstrap key check au démarrage)                                                                                   |
| `src/live_mem/tools/*.py` (×6)                 | VULN-27 (34 blocs `safe_error()`)                                                                                            |
| `DESIGN/live-mem/AUDIT_SECURITE_2026-03-24.md` | Rapport d'audit complet (nouveau)                                                                                            |

---

## [0.9.0] — 2026-03-19

### Changé — Support natif des sous-dossiers dans la Memory Bank

**Refonte architecturale** — La bank supporte désormais les fichiers dans des sous-dossiers (ex: `personaProfiles/acheteur.md`). Auparavant, tous les `split("/")[-1]` dans le code ne gardaient que le basename des clés S3, ce qui causait des doublons quand le LLM créait des fichiers dans des sous-répertoires définis par les rules.

- **Cause racine identifiée** — Bug découvert sur le space `presales` : les rules mentionnent `personaProfiles/` comme dossier et `1.MEMORY_BANK/` comme répertoire racine. Le LLM créait des fichiers aux chemins `presales/bank/personaProfiles/acheteur.md` et `presales/bank/1.MEMORY_BANK/personaProfiles/acheteur.md`, mais le code extrayait uniquement `acheteur.md` → doublons avec perte de correspondance → `bank_read("acheteur.md")` retournait "not_found".
- **`bank_relpath(s3_key, space_id)`** — Nouvelle fonction utilitaire dans `storage.py`. Extrait le chemin relatif complet depuis le préfixe `{space_id}/bank/`. Ex: `presales/bank/personaProfiles/acheteur.md` → `personaProfiles/acheteur.md`.
- **21 occurrences de `split("/")[-1]` remplacées** par `bank_relpath()` dans 6 fichiers : consolidator.py, bank.py (tools), space.py, graph_bridge.py.
- **`_sanitize_filename()` enrichi** — Garde les `/` (sous-dossiers légitimes). Supprime les préfixes parasites que le LLM invente en lisant les rules (`1.MEMORY_BANK/`, `MEMORY_BANK/`, `bank/`). Nettoie les `/` en début/fin et les doubles `//`.
- **Nettoyage auto des doublons** — Lors de chaque écriture bank (create/edit/rewrite), le consolidateur supprime automatiquement les anciennes clés S3 qui sanitisent vers le même nom de fichier.
- **`bank_read` avec fallback** — Si la clé directe n'existe pas, scanne les clés S3 réelles et cherche par correspondance sanitisée.

### Ajouté — 2 nouveaux outils MCP : `bank_write` et `bank_delete`

- **`bank_write`** 👑 (admin) — Écrit ou remplace un fichier bank directement, sans passer par la consolidation LLM. Utile pour les corrections manuelles, les migrations, et les cas où la consolidation échoue. Nettoie automatiquement les doublons Unicode.
- **`bank_delete`** 👑 (admin) — Supprime un fichier bank et tous ses doublons (clés S3 avec le même nom sanitisé). Irréversible.
- **37 outils MCP** (était 35) — catégorie Bank passe de 5 à 7 outils.

### Fichiers modifiés
| Fichier                             | Changements                                                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/live_mem/core/storage.py`      | + `bank_relpath()` — extraction chemin relatif bank depuis clé S3                                                                                            |
| `src/live_mem/core/consolidator.py` | `_sanitize_filename()` : garde `/`, supprime préfixes parasites. `_build_prompt()` + `_write_results()` : utilisent `bank_relpath`. Nettoyage auto doublons. |
| `src/live_mem/tools/bank.py`        | `bank_read_all`/`bank_list` : retournent chemins relatifs. + `bank_write` et `bank_delete` (admin). `bank_read` avec fallback Unicode. 7 outils (était 5).   |
| `src/live_mem/core/space.py`        | `get_info()` et `get_summary()` : utilisent `bank_relpath`                                                                                                   |
| `src/live_mem/core/graph_bridge.py` | `push()` : utilise `bank_relpath`                                                                                                                            |
| `VERSION`                           | 0.8.2 → 0.9.0                                                                                                                                                |

### ⚠️ À compléter (follow-up)
- CLI Click : ajouter commandes `bank write`, `bank delete`, `bank repair`
- Shell interactif : ajouter handlers correspondants
- Web UI bank.js : affichage raccourci des noms longs dans les onglets (cosmétique, fonctionnel en l'état)

---

## [0.8.2] — 2026-03-16

### Ajouté — Nouveau template de rules `book.memory.bank.md` et fix shell `space create`

- **`RULES/book.memory.bank.md`** — Nouveau modèle de rules pour **l'écriture de livres**. 6 fichiers obligatoires (bookbrief, bookContext, narrativeDesign, writingContext, activeContext, progress). Conçu pour les agents IA assistant d'écriture : suivi narratif, voix et ton, compteurs de mots, tracking par chapitre, retours de relecture. Instructions de consolidation spécialisées avec mapping adapté (ex: `decision` → `narrativeDesign.md` si c'est un choix structurant).
- **Renommage `standard.memory.bank.md` → `live-mem.standard.memory.bank.md`** — Le modèle standard porte désormais un nom plus explicite.
- **5 templates de rules** disponibles dans `RULES/` (était 3) : standard, medical, presales, book, live-mem.standard.

### Amélioré — Template Custom Instructions (lecture des notes non consolidées au démarrage)
- **Étape 3 ajoutée dans la procédure de démarrage** — `live_read(space_id="{SPACE}")` est désormais obligatoire au lancement de chaque tâche. Permet de récupérer les notes écrites entre deux sessions qui n'ont pas encore été consolidées dans la bank.
- **Justification** : sans cette étape, l'agent rate du contexte récent (notes d'autres agents, notes de sessions précédentes non consolidées). Risque de refaire du travail déjà fait ou de rater des décisions récentes.
- **Procédure de démarrage** : 5 étapes (était 4) — `space_rules` → `bank_read_all` → **`live_read`** → lire le contenu → identifier le focus.
- **Note explicative** ajoutée sous le bloc d'avertissement pour expliquer le "pourquoi" aux agents.

### Corrigé — Shell interactif `space create` (parsing des options)
- **Bug : `space create -d "desc" -r rules.md id` échouait** — Le shell utilisait un parsing purement positionnel (`args[1]` = space_id, `args[2]` = description, `args[3:]` = rules). Les options nommées (`-d`, `-r`) étaient interprétées comme le space_id → erreur `"space_id invalide : '-d'"`.
- **Nouveau parsing** — Support complet des options nommées, aligné sur la CLI Click :
  - `-d` / `--description` — Description de l'espace
  - `-r` / `--rules-file` — Chemin vers un fichier rules (.md), lu automatiquement
  - `--rules` — Contenu rules en ligne (inline)
  - `-o` / `--owner` — Propriétaire
- **Rétrocompatibilité** — La forme positionnelle `space create <id> <desc> <rules>` fonctionne toujours.
- **Autocomplétion enrichie** — `-d`, `-r`, `-o`, `--description`, `--rules-file`, `--rules`, `--owner`, `--email`, `-e` ajoutés aux mots-clés du shell.

### Fichiers modifiés
| Fichier                                  | Changements                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------- |
| `RULES/book.memory.bank.md`              | Nouveau — Modèle écriture de livre (6 fichiers, suivi narratif, compteurs mots) |
| `RULES/live-mem.standard.memory.bank.md` | Renommé — Ancien `standard.memory.bank.md`                                      |
| `RULES/README.md`                        | Table des templates mise à jour (5 templates)                                   |
| `scripts/cli/shell.py`                   | Handler `space create` refactoré (options nommées), aide et autocomplétion MAJ  |
| `.clinerules/standard.memory.bank.md`    | Étape 3 `live_read` ajoutée au démarrage + note explicative                     |
| `clinerules.md`                          | Idem — template racine mis à jour avec `live_read` au démarrage                 |
| `scripts/README.md`                      | Version v0.8.1 → v0.8.2                                                         |
| `scripts/README.en.md`                   | Version v0.7.5 → v0.8.2                                                         |
| `GUIDE_INTEGRATION_CLINE.md`             | v0.7.4 → v0.8.2 : template + workflow + minimaliste + 30→35 outils              |

---

## [0.8.1] — 2026-03-16

### Changé — Token = Agent (suppression du paramètre `agent` dans `live_note`)

**Inversion de la décision v0.2.0** — Le découplage Token / Agent (v0.2.0) permettait de passer un `agent` libre dans `live_note`, indépendamment du token utilisé. Cette liberté causait des problèmes critiques à la consolidation :

- **Notes orphelines silencieuses** — Si l'agent écrivait sous un nom différent du `client_name` de son token, le consolidateur (qui filtre par pattern `_{agent}_` dans le nom de fichier S3) ne trouvait jamais ces notes. Aucune erreur affichée → perte de données invisible.
- **Usurpation d'identité** — Un agent pouvait écrire des notes sous le nom d'un autre agent.
- **Notes éparpillées** — Un agent écrivant parfois avec `agent=""` et parfois avec `agent="mon-nom"` créait deux identités distinctes.

**Nouveau comportement (v0.8.1)** :
- Le paramètre `agent` est **supprimé** de `live_note` (outil MCP + core + CLI)
- L'identité de l'agent est **toujours** le `client_name` du token d'authentification
- Chaque token = une identité unique = un agent
- `live_read(agent=...)` conserve son paramètre de filtre (utile pour lire les notes d'autres agents)
- `bank_consolidate(agent=...)` inchangé (admin peut cibler un agent spécifique)

### Fichiers modifiés
| Fichier                                     | Changements                                                         |
| ------------------------------------------- | ------------------------------------------------------------------- |
| `src/live_mem/tools/live.py`                | Paramètre `agent` supprimé de `live_note`                           |
| `src/live_mem/core/live.py`                 | Paramètre `agent` supprimé de `write_note()`, auto-détection forcée |
| `scripts/cli/commands.py`                   | Option `--agent/-a` retirée de `live note` CLI                      |
| `DESIGN/live-mem/AUTH_AND_COLLABORATION.md` | Section 1.5 réécrite : Token = Agent (v0.8.1)                       |
| `DESIGN/live-mem/MCP_TOOLS_SPEC.md`         | Signature `live_note` mise à jour (sans `agent`)                    |

---

## [0.8.0] — 2026-03-13

### Ajouté — Consolidation par lots et protection Unicode

- **Consolidation par lots (batches)** — Les notes sont désormais traitées par lots de `CONSOLIDATION_BATCH_SIZE` (défaut 5) au lieu d'être envoyées toutes en une seule passe au LLM. Chaque lot relit la bank à jour depuis S3 (intégration incrémentale). Si un lot échoue, les précédents sont déjà intégrés (résilience). Avec 60 notes → 12 batches de 5 → 12 appels LLM courts au lieu d'1 énorme.
- **Sanitisation des filenames LLM (`_sanitize_filename`)** — Supprime automatiquement 20 types de caractères Unicode invisibles (ZWSP, BOM, Soft Hyphen…) et normalise 10 types de tirets Unicode vers le tiret ASCII standard, avant chaque écriture S3. Corrige le bug de "drift Unicode" du LLM sur les réponses JSON longues (fichiers bank illisibles par `bank_read` et l'interface `/live`).
- **Outil `bank_repair`** 👑 (admin) — 35ème outil MCP. Scanne les fichiers bank existants, détecte les noms corrompus par des caractères Unicode invisibles, et les répare (dry_run par défaut).
- **Test de cohérence bank** dans `test_recette.py` — Après consolidation, vérifie que chaque fichier retourné par `bank_list` est lisible via `bank_read` (étape 7/8 de la suite recette).
- **`CONSOLIDATION_BATCH_SIZE`** dans `config.py` — Nouvelle variable d'environnement configurable (défaut 5).
- **Nouvelles métriques de consolidation** : `batches_total`, `batches_completed`, `batch_size` dans la réponse de `bank_consolidate`.

### Corrigé

- **Bug filenames Unicode invisibles** — Le LLM `qwen3.5:27b` insère parfois des caractères Unicode invisibles dans les noms de fichiers à partir du ~8ème fichier dans les réponses JSON longues, rendant ces fichiers illisibles. Corrigé par la sanitisation systématique + la consolidation par lots qui produit des réponses plus courtes.

### Modifié

- **`_write_results()` accepte `skip_meta=True`** — En mode batch, le meta est mis à jour une seule fois à la fin de la consolidation (pas à chaque lot).
- **35 outils MCP** (était 34) — catégorie Bank passe de 4 à 5 outils.

---

## [0.7.7] — 2026-03-13

### Ajouté — Outil MCP `space_update` (modification des métadonnées d'un espace)
- **Nouvel outil `space_update`** ✏️ (write) — Permet de modifier la description et/ou le owner d'un espace existant. Les rules restent immuables.
- **34 outils MCP** (était 33) — catégorie Space passe de 7 à 8 outils.
- Méthode `SpaceService.update()` dans `core/space.py` : GET + PUT sur `_meta.json`, modification sélective des champs fournis.

### Amélioré — CLI et affichage
- **CLI Click** : `space update <id> -d "desc" [-o "owner"]` avec aide contextuelle et exemples
- **Shell interactif** : `space update <id> -d "desc" [-o "owner"]` avec parsing flags nommés, autocomplétion, aide contextuelle
- **Affichage Rich** : `show_space_updated()` — panel avec champs modifiés
- **Colonne Owner dans `space list`** — le champ owner était absent de l'affichage (corrigé)
- **Owner dans `space info`** — ajouté entre Description et Notes live
- **Test de recette** : `space_update` ajouté dans la suite qualité (21/21 PASS)

### Fichiers modifiés
| Fichier                       | Changements                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| `src/live_mem/core/space.py`  | Nouvelle méthode `update()` — modification sélective de `_meta.json`                       |
| `src/live_mem/tools/space.py` | Nouvel outil `space_update` — check_access + check_write, 3 params annotés                 |
| `scripts/cli/commands.py`     | Commande Click `space update` avec `--description/-d`, `--owner/-o`                        |
| `scripts/cli/shell.py`        | Handler `space update` + SHELL_COMMANDS + import `show_space_updated`                      |
| `scripts/cli/display.py`      | `show_space_updated()`, colonne Owner dans `show_space_list`, Owner dans `show_space_info` |
| `scripts/test_recette.py`     | Test `space_update` ajouté dans la suite qualité                                           |

---

## [0.7.6] — 2026-03-13

### Ajouté — Répertoire `RULES/` : modèles de rules pour la création d'espaces
- **Nouveau répertoire `RULES/`** avec des modèles de rules (templates) prêts à l'emploi pour créer des espaces mémoire via `space_create`.
- **`RULES/standard.memory.bank.md`** — Modèle **general purpose** pour tout projet logiciel. 6 fichiers obligatoires (projectbrief, productContext, activeContext, systemPatterns, techContext, progress). C'est le modèle utilisé par le space `live-mem`.
- **`RULES/medical.memory.bank.md`** — Modèle **suivi médical**. 7 fichiers obligatoires (profilGeneral, histoireDiagnostic, contexteSante, medicamentationTraitements, specialistesSuivi, profilSante, progression) + 2 optionnels (visualisationDonnees, protocoleUrgence). Inclut une **règle de fiabilité absolue** pour les données biologiques (double vérification, fidélité parfaite, unités conservées).
- **`RULES/presales.memory.bank.md`** — Modèle **avant-vente B2B**. 5 fichiers de base (proposalContext, activeAnalysis, analysisProgress, rulesLearned, methodologieAnalyse) + fichiers **personas dynamiques** (un par décideur : dirigeant, acheteur, DSI, RSSI, expert). Gestion des contradictions, capitalisation des patterns argumentaires, tracking visuel avec ✅🔄⏱️❓.
- **`RULES/README.md`** — Documentation complète : explication du rôle des rules, catalogue des modèles, guide d'utilisation, instructions pour créer un modèle personnalisé.
- **Section "Pourquoi les Rules sont critiques"** dans le README — Explique que les rules sont **injectées mot pour mot dans le prompt du LLM consolidateur** à chaque `bank_consolidate`. Ce n'est pas de la documentation passive — c'est un contrat direct avec le modèle.

### Fichiers ajoutés/modifiés
| Fichier                         | Changements                                                                                                   |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `RULES/standard.memory.bank.md` | Nouveau — Copie des rules du space `live-mem` (general purpose)                                               |
| `RULES/medical.memory.bank.md`  | Nouveau — Modèle médical adapté pour Live Memory (7+2 fichiers, fiabilité absolue, mapping consolidation)     |
| `RULES/presales.memory.bank.md` | Nouveau — Modèle avant-vente B2B (5+N fichiers, personas dynamiques, gestion contradictions, tracking visuel) |
| `RULES/README.md`               | Nouveau — Documentation des templates de rules avec explication du lien rules → LLM                           |
| `README.md`                     | Badge version 0.7.6, mention du répertoire RULES/ dans la structure du projet                                 |

---

## [0.7.5] — 2026-03-13

### Ajouté — Outil MCP `system_whoami` (identité du token courant)
- **Nouvel outil `system_whoami`** — Permet à tout agent ou utilisateur de connaître l'identité avec laquelle il contacte le serveur MCP. Retourne : `client_name`, `auth_type` (bootstrap/token), `permissions`, `allowed_spaces`, et pour les tokens S3 : `email`, `token_hash`, `created_at`, `expires_at`, `last_used_at`.
- **CLI Click** : `python scripts/mcp_cli.py whoami` (avec `--json` pour le JSON brut)
- **Shell interactif** : `whoami` (avec autocomplétion)
- **Affichage Rich** : panel coloré `👤 Qui suis-je ?` avec icônes de permissions (🔑 read, ✏️ write, 👑 admin)
- **33 outils MCP** (était 32) — catégorie System passe de 2 à 3 outils

### Fichiers modifiés
| Fichier                        | Changements                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/live_mem/tools/system.py` | Nouvel outil `system_whoami` — lit le contextvar `current_token_info`, enrichit avec les métadonnées du TokenService pour les tokens S3 |
| `scripts/cli/display.py`       | `show_whoami_result()` — panel Rich avec identité, type, droits, espaces, métadonnées token                                             |
| `scripts/cli/commands.py`      | Commande Click `whoami` au niveau racine (comme `health` et `about`)                                                                    |
| `scripts/cli/shell.py`         | Commande `whoami` dans le dispatcher, SHELL_COMMANDS et autocomplétion                                                                  |

---

## [0.7.4] — 2026-03-13

### Corrigé — Sécurité `bank_consolidate` (incohérence permissions)
- **`agent=""` avec write consolidait TOUTES les notes** — Un token `write` (non-admin) pouvait consolider les notes de tous les agents en passant `agent=""`, contournant l'isolation par agent. C'était un fallback de rétrocompatibilité v0.2.0 qui créait une incohérence de sécurité.
- **Nouveau comportement** :
  - `write` + `agent=""` → auto-détecte le `client_name` du token et consolide **uniquement ses propres notes**
  - `write` + `agent=caller` → OK (même chose explicitement)
  - `write` + `agent=autre` → REFUSÉ (admin requis)
  - `admin` + `agent=""` → consolide TOUTES les notes (inchangé)
  - `admin` + `agent=xxx` → consolide les notes de l'agent xxx (inchangé)
- **Matrice des permissions** clarifiée dans le code avec commentaires détaillés.

### Amélioré — Template Custom Instructions simplifié (suppression de `{AGENT}`)
- **Le paramètre `agent` n'est plus nécessaire** dans le template — il est auto-détecté depuis le token d'authentification, tant pour `live_note` (déjà en place) que pour `bank_consolidate` (nouveau).
- Le template ne contient plus qu'**une seule variable** : `{SPACE}` (le nom du space).
- Suppression de la règle "toujours passer agent=..." — l'agent est implicite.
- Simplification de la documentation : les utilisateurs sont invités à copier le template directement dans leurs Custom Instructions globales, sans mentionner explicitement l'arborescence locale `.clinerules`.

### Fichiers modifiés
| Fichier                                     | Changements                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `src/live_mem/tools/bank.py`                | Logique d'autorisation `bank_consolidate` réécrite — auto-set `agent=caller` pour les tokens write non-admin |
| `GUIDE_INTEGRATION_CLINE.md`                | Mise à jour v0.7.4, template simplifié sans agent, focus sur les Custom Instructions                         |
| `README.md` et `README.en.md`               | Nettoyage des exemples, lien direct vers le guide d'intégration                                              |
| `scripts/test_recette.py`                   | +3 tests isolation (consolidation permissions) : write+agent='', write+agent=autre, reader consolidate       |
| `DESIGN/live-mem/AUTH_AND_COLLABORATION.md` | Matrice permissions mise à jour (bank_consolidate auto-détection)                                            |
| `DESIGN/live-mem/MCP_TOOLS_SPEC.md`         | Spec bank_consolidate mise à jour (v0.7.4 agent auto-détecté)                                                |

---

## [0.7.3] — 2026-03-13

### Amélioré — Template `.clinerules/standard.memory.bank.md` (DRY)
- **Centralisation de la configuration** — Le nom du space (`SPACE`) et de l'agent (`AGENT`) ne sont plus hardcodés à chaque ligne. Ils sont définis **une seule fois** dans un bloc de configuration en haut du fichier, puis référencés partout via les placeholders `{SPACE}` et `{AGENT}`.
- **Avant** : `live-mem` apparaissait 12 fois et `cline-dev` 9 fois — chaque exemple, règle et commande devait être modifié manuellement pour réutiliser le template.
- **Après** : 2 lignes à modifier pour adapter le template à n'importe quel projet/agent.
- **Exemples simplifiés** — Les 6 exemples `live_note` répétitifs (un par catégorie) sont remplacés par un seul exemple générique avec `<catégorie>`.
- **Guide d'intégration Cline** (`GUIDE_INTEGRATION_CLINE.md`) mis à jour pour référencer le nouveau format template avec `{SPACE}/{AGENT}`.

### Fichiers modifiés
| Fichier                               | Changements                                                                               |
| ------------------------------------- | ----------------------------------------------------------------------------------------- |
| `.clinerules/standard.memory.bank.md` | Refactoring complet : config centralisée + placeholders `{SPACE}`/`{AGENT}`               |
| `GUIDE_INTEGRATION_CLINE.md`          | Version 0.7.3, section Custom Instructions mise à jour avec le template `{SPACE}/{AGENT}` |
| `README.md`                           | Badge version 0.7.3                                                                       |
| `README.en.md`                        | Badge version 0.7.3                                                                       |

---

## [0.7.2] — 2026-03-12

### Corrigé — Bug CLI `token create` (parsing des options)
- **`permissions` transformé de `click.argument` (positionnel) en `click.option` (nommé)** — Quand on tapait `token create KSE --email kevin@... --permissions read,write`, Click interprétait `--email` comme la valeur positionnelle de `permissions` → erreur `"Permissions invalides : '--email'"`. Le paramètre est maintenant une option nommée `--permissions/-p` (required), cohérente avec `token update`.
- **Shell interactif corrigé** — Le handler `token create` du shell parsait `args[2]` en dur comme permissions. Réécrit avec un parsing de flags nommés (`--permissions/-p`, `--email/-e`, `--space-ids/-s`, `--expires-in-days`) — même pattern que `token update`. Rétrocompatibilité préservée : la forme positionnelle `token create KSE read,write` fonctionne encore dans le shell.
- **Aide enrichie** — Exemples ajoutés dans le help de `token create` (CLI et shell).

### Nouvelle syntaxe
```bash
# CLI Click
token create KSE -p read,write --email kevin@cloud-temple.com
token create bot-ci --permissions read
token create admin-ops -p read,write,admin

# Shell interactif (rétrocompat positionnelle)
token create KSE -p read,write --email kevin@cloud-temple.com
token create KSE read,write    # ← fonctionne encore
```

### Fichiers modifiés
| Fichier                   | Changements                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------- |
| `scripts/cli/commands.py` | `permissions` : `click.argument` → `click.option("--permissions", "-p", required=True)` |
| `scripts/cli/shell.py`    | Handler `token create` réécrit avec parsing de flags nommés                             |
| `scripts/README.md`       | Syntaxe `token create` mise à jour (v0.7.2)                                             |
| `scripts/README.en.md`    | Syntaxe `token create` mise à jour (v0.7.2)                                             |

---

## [0.7.1] — 2026-03-12

### Sécurité — Alignement des droits avec Graph Memory
- **Auto-ajout du space au token à la création** — Quand un client restreint (`space_ids: ["A"]`) crée un space "B", le space B est automatiquement ajouté à ses `space_ids` dans `tokens.json`. Élimine le deadlock UX où le client ne pouvait pas accéder au space qu'il venait de créer. Nouvelle méthode `TokenService.add_space_to_token()`.
- **Filtrage `backup_list` par space_ids du token** — Un client ne voit plus que les backups des spaces auxquels il a accès. Corrige une fuite d'information où un client pouvait lister tous les backups de tous les espaces.
- **Confirmation `backup_download` sécurisé** — Vérifié que `check_access(space_id)` est déjà en place (extrait le space_id du backup_id). Aucune modification nécessaire.
- **Script de recette unifié** — `scripts/test_recette.py` refait avec 4 suites sélectionnables par CLI (`--suite recette,isolation,qualite,graph`). Suite `isolation` : ~20 tests vérifiant l'isolation multi-tenant (accès inter-espaces refusé, filtrage backup_list, écriture read-only refusée, auto-ajout space au token).
- **Champ `email` dans les tokens** — Alignement Graph Memory : `admin_create_token(email=)` optionnel pour la traçabilité. Affiché dans `token list` (colonnes : Nom, Email, Hash, Permissions, Espaces, Créé le, Expire). CLI : `--email/-e`, Shell : `--email`.
- **CLI complète (32/32 outils)** — Ajouté : `space summary`, `space export`, `backup download`, `gc` en Click et Shell interactif.
- **WAF rate limits ×3** — MCP 200→600 req/min, API 60→120, Global 500→1500 (résout les TaskGroup errors).
- **Nettoyage scripts/** — 5 scripts supprimés (test_qualite, test_multi_agents, test_gc, test_graph_bridge, test_markdown_engine), tout intégré dans `test_recette.py`.

---

## [0.6.0] — 2026-03-11

### Changé — Consolidation chirurgicale (édition par section Markdown)
- **Refonte majeure du consolidateur LLM** — Passage du mode "réécriture complète" au mode "édition chirurgicale". Le LLM produit désormais des **opérations d'édition par section Markdown** (`replace_section`, `append_to_section`, `prepend_to_section`, `add_section`, `delete_section`) au lieu de réécrire les fichiers entiers.
- **Zéro perte de matière** — Ce qui n'est pas touché explicitement reste intact byte-for-byte. Test A/B validé : l'ancien mode perdait 28 lignes, le nouveau mode n'en perd aucune (hors `replace_section` attendu sur le focus).
- **Moteur d'édition Markdown** — Nouveau moteur dans `consolidator.py` : `_parse_sections()`, `_find_section_index()` (matching flexible 3 niveaux : exact → sans # → case-insensitive), `_reconstruct_from_sections()`, `_apply_operation()`.
- **Prompts LLM mis à jour** — Le prompt système et utilisateur demandent des opérations d'édition au format JSON structuré, avec 3 actions par fichier : `edit` (opérations chirurgicales), `create` (nouveau fichier), `rewrite` (fallback justifié).
- **Rétrocompatibilité** — Si le LLM retourne l'ancien format `bank_files`, conversion automatique via `_convert_legacy_format()`.

### Ajouté
- **Métriques de consolidation enrichies** — `operations_applied` et `operations_failed` dans le retour de `bank_consolidate` et dans le front-matter de `_synthesis.md`.
- **77 tests unitaires** — `scripts/test_markdown_engine.py` couvre le moteur d'édition : parsing, reconstruction, idempotence, toutes les opérations, cas limites, scénarios réalistes.
- **Test E2E consolidation chirurgicale** — `test_surgical_consolidation.py` : 7 phases (création, consolidation create, snapshot, notes supplémentaires, consolidation chirurgicale, comparaison avant/après, nettoyage).
- **Test A/B** — `run_ab_test.py` : compare production (ancien mode) vs local (nouveau mode) sur les mêmes données.

### Gains mesurés (test A/B)
| Métrique                     | Ancien mode (réécriture) | Nouveau mode (chirurgical)      |
| ---------------------------- | ------------------------ | ------------------------------- |
| Lignes perdues (progress.md) | 10                       | **0**                           |
| Lignes perdues (total)       | 28                       | **1** (replace_section attendu) |
| Tokens completion LLM        | 4850                     | **3993** (-18%)                 |
| Durée consolidation          | 29s                      | **14.4s** (-50%)                |

### Fichiers modifiés
| Fichier                                | Changements                                                    |
| -------------------------------------- | -------------------------------------------------------------- |
| `src/live_mem/core/consolidator.py`    | Moteur d'édition Markdown + prompts chirurgicaux + rétrocompat |
| `DESIGN/live-mem/CONSOLIDATION_LLM.md` | Design doc v0.6.0 complet                                      |
| `scripts/test_markdown_engine.py`      | 77 tests unitaires (nouveau)                                   |

---

## [0.5.3] — 2026-03-09

### Corrigé — Validation des permissions tokens
- **Bug "permissions all"** — Le système acceptait n'importe quel texte comme permission (ex: `"all"`), mais `check_write_permission()` et `check_admin_permission()` ne reconnaissaient que `"read"`, `"write"` et `"admin"` individuellement. Un token créé avec `permissions="all"` était donc inutilisable pour les opérations write/admin.
- **Validation côté serveur** — `VALID_PERMISSIONS = {"read", "write", "admin"}` défini dans `core/tokens.py`. Les méthodes `create_token()` et `update_token()` rejettent désormais les permissions invalides avec un message explicite.
- **Validation côté CLI** — `token create` utilise `click.Choice(["read", "read,write", "read,write,admin"])` : plus de texte libre, Click rejette immédiatement les valeurs invalides.
- **Validation côté shell** — Le shell interactif valide aussi les permissions avant l'appel MCP.

### Ajouté — Commande `token update`
- **CLI Click** : `token update <hash> --permissions read,write --space-ids "p1,p2"` — permissions contraintes par `click.Choice`
- **Shell interactif** : `token update sha256:a8c5 --permissions read,write` avec parsing des flags `-p`/`-s`
- **Autocomplétion** enrichie dans le shell : `--permissions`, `--space-ids`, `read`, `read,write`, `read,write,admin`

### Fichiers modifiés
| Fichier                       | Changements                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| `scripts/cli/commands.py`     | `VALID_PERMISSIONS` (click.Choice), `token_create_cmd` contraint, `token_update_cmd` ajouté |
| `scripts/cli/shell.py`        | `_VALID_PERMS`, `_validate_permissions()`, handler `token update`, autocomplétion étendue   |
| `src/live_mem/core/tokens.py` | `VALID_PERMISSIONS`, validation dans `create_token()` et `update_token()`                   |

---

## [0.5.2] — 2026-03-09

### Ajouté — Suppression physique des tokens
- **`admin_delete_token`** 👑 — Supprime physiquement un token du registre `tokens.json` sur S3
- **`admin_purge_tokens`** 👑 — Purge en masse : tokens révoqués seuls (`revoked_only=True`) ou tous (`revoked_only=False`)
- **32 outils MCP** (était 30) — 7 catégories (admin passe de 5 à 7 outils)
- **Script `scripts/delete_tokens.py`** — Utilitaire CLI pour lister, révoquer et purger les tokens à distance
  - `list` : liste les tokens
  - `revoke_all` : révoque tous les tokens actifs
  - `purge` : supprime physiquement les tokens révoqués
  - `purge_all` : supprime physiquement TOUS les tokens

### Notes
- Le **bootstrap key** (variable d'environnement `ADMIN_BOOTSTRAP_KEY`) n'est jamais stocké dans `tokens.json` et ne peut pas être supprimé
- Les 2 nouveaux outils utilisent le pattern `Annotated[type, Field(description="...")]` pour les descriptions Cline
- Méthodes `delete_token()` et `purge_tokens()` ajoutées dans `TokenService` (`core/tokens.py`)
