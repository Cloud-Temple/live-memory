# 🖥️ Live Memory CLI, Shell & Tests

> CLI scriptable, shell interactif et scripts de test pour Live Memory MCP v2.4.0.

🇬🇧 [English version](README.md)

---

## Prérequis

```bash
pip install click rich prompt-toolkit mcp[cli]>=1.8.0
```

Variables d'environnement :

```bash
export MCP_URL=http://localhost:8080    # URL du serveur (via WAF)
export MCP_TOKEN=votre_token_secret     # Token d'authentification
```

---

## Parité avec `/admin` et `/live`

| Surface          | Expose                                              | Notes                                                                                                                                                |
| ---------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mcp_cli.py`     | Les **43 outils MCP** (parité opérationnelle totale) | Commandes Click + shell interactif. Ce README est la référence.                                                                                       |
| Web `/admin`     | Les mêmes 43 outils MCP via proxy `POST /api/tool`  | Console web authentifiée (cookie HttpOnly). Dashboard, Spaces, Tokens, Explorer, Backups, Graph Bridge, Stale Banks, Maintenance.                     |
| Web `/live`      | Visualisation read-only des spaces / notes / bank   | Utilise des endpoints REST dédiés (`/api/spaces`, `/api/live/<id>`, `/api/bank/<id>`), PAS le protocole MCP.                                          |

La CLI est la surface canonique — tout ce qui se fait depuis `/admin` est faisable depuis `mcp_cli.py` (et inversement). `/live` est une UI read-only de confort ; ses capacités sont un sous-ensemble de `live read`, `bank read`, `bank list`, `space info`.

---

## CLI scriptable (Click)

Chaque outil MCP correspond à une commande Click. Aide complète : `python scripts/mcp_cli.py --help` ou `... <group> --help`.

### System (3 outils)

```bash
python scripts/mcp_cli.py health                              # Santé du service (probes S3 + LLM)
python scripts/mcp_cli.py whoami                              # Identité du token courant
python scripts/mcp_cli.py about                               # Version, capacités du service
```

### Space (9 outils)

```bash
python scripts/mcp_cli.py space list                          # Liste les spaces accessibles
python scripts/mcp_cli.py space create my-proj -d "Desc"      # Crée un space (auto-attaché au token créateur)
python scripts/mcp_cli.py space info my-proj                  # Détails (counts, owner, dates, queue summary)
python scripts/mcp_cli.py space rules my-proj                 # Rules Memory Bank de ce space
python scripts/mcp_cli.py space summary my-proj               # Synthèse complète (rules + bank + notes counts)
python scripts/mcp_cli.py space update my-proj -d "Nouv desc" # Modifie description / owner
python scripts/mcp_cli.py space update-rules my-proj -f rules.md  # Remplace les rules (manage)
python scripts/mcp_cli.py space export my-proj                # Export tar.gz
python scripts/mcp_cli.py space delete my-proj --confirm      # Irréversible (manage)
```

### Live notes (3 outils)

```bash
python scripts/mcp_cli.py live note my-proj observation "Trouvé X"   # Append une note (agent = token)
python scripts/mcp_cli.py live read my-proj                          # Liste les notes récentes non consolidées
python scripts/mcp_cli.py live search my-proj "mot-clé"              # Recherche full-text dans les notes
```

### Bank (11 outils)

```bash
python scripts/mcp_cli.py bank list my-proj                          # Liste les fichiers bank
python scripts/mcp_cli.py bank read my-proj activeContext.md         # Lit un fichier bank
python scripts/mcp_cli.py bank read-all my-proj                      # Lit toute la bank (démarrage agent)
python scripts/mcp_cli.py bank consolidate my-proj                   # 🧠 Enfile une consolidation LLM async (fire-and-forget)
python scripts/mcp_cli.py bank consolidation-status <job_id>         # Check de statut manuel (NE PAS poller automatiquement)
python scripts/mcp_cli.py bank consolidation-queues                  # Résumé des lanes sur tous les spaces accessibles
python scripts/mcp_cli.py bank stale-spaces                          # 🚨 Spaces ≥5 notes / plus ancienne ≥5 jours
python scripts/mcp_cli.py bank stale-spaces --min-notes 10 --min-age-days 7 --consolidate  # Déclenche bulk consolidation
python scripts/mcp_cli.py bank compact my-proj                       # Dry-run des fichiers surdimensionnés
python scripts/mcp_cli.py bank compact my-proj --apply               # Découpe lossless en octets UTF-8 (manage)
python scripts/mcp_cli.py bank repair my-proj                        # Dry-run (Unicode / préfixes parasites)
python scripts/mcp_cli.py bank repair my-proj --apply                # Applique les fixes (manage)
python scripts/mcp_cli.py bank write my-proj activeContext.md -f ./ctx.md   # Bypass LLM (manage)
python scripts/mcp_cli.py bank delete my-proj progress.md --confirm  # Supprime fichier + doublons Unicode (manage)
```

### Graph Bridge (4 outils)

```bash
python scripts/mcp_cli.py graph connect my-proj <url> <token> <memory_id> [ontology]
python scripts/mcp_cli.py graph push my-proj                         # Push bank → graphe (delete + re-ingest)
python scripts/mcp_cli.py graph status my-proj                       # État connexion + stats graphe
python scripts/mcp_cli.py graph disconnect my-proj
```

### Backup (5 outils)

```bash
python scripts/mcp_cli.py backup create my-proj -d "avant migration"
python scripts/mcp_cli.py backup create --all                        # Backup TOUS les spaces accessibles (admin)
python scripts/mcp_cli.py backup list [my-proj]                      # Liste les backups (filtre par space optionnel)
python scripts/mcp_cli.py backup download <backup_id>                # Télécharge l'archive
python scripts/mcp_cli.py backup restore <backup_id> --confirm       # Restaure (space ne doit pas exister)
python scripts/mcp_cli.py backup delete <backup_id> --confirm        # Permanent
```

### Admin — tokens & GC (8 outils)

```bash
python scripts/mcp_cli.py token create agent-cline -p read,write --email cline@team.io
python scripts/mcp_cli.py token list                                 # Liste les tokens (filtrable)
python scripts/mcp_cli.py token update <hash> --add-spaces my-proj   # Mise à jour delta (add/remove spaces, perms, email)
python scripts/mcp_cli.py token bulk-update --name-contains agent --add-spaces my-proj --confirm   # Mise à jour de masse
python scripts/mcp_cli.py token revoke <hash>                        # Soft-revoke (préserve audit trail)
python scripts/mcp_cli.py token delete <hash>                        # Hard-delete (admin)
python scripts/mcp_cli.py token purge [--all]                        # Purge les tokens revoked (ou --all)
python scripts/mcp_cli.py gc --space-id my-proj --confirm            # Nettoyage des notes orphelines (âge 7j défaut)
```

---

## Shell interactif

```bash
python scripts/mcp_cli.py shell
```

Le shell offre :

- **Autocomplétion** (Tab) sur toutes les commandes et sous-commandes
- **Historique** persistant (`~/.live_mem_shell_history`)
- **Aide contextuelle** : `help`, `help <verbe>` (ex : `help bank`)
- **Affichage Rich** coloré (tables, panels, Markdown)
- **Flag `--json`** sur n'importe quelle commande pour sortie JSON brute

---

## 🧪 Scripts de test

### Tests anti-hallucination — `test_hallucination.py`

Reproduit et détecte les hallucinations du consolidateur LLM (Issue #17). 5 scénarios, 25 assertions.

```bash
python scripts/test_hallucination.py                       # Tous les scénarios
python scripts/test_hallucination.py --scenario D          # Un seul scénario (A, B, C, ABC, D, E, ALL)
python scripts/test_hallucination.py -v --keep             # Verbose + conserver les spaces de test
```

| Scénario | Détecte                                                       |
| -------- | ------------------------------------------------------------- |
| A        | Structure de fichiers inventée (Next.js pour un projet Rails) |
| B        | Métriques inventées (LoC absent des notes)                    |
| C        | Réinterprétation de termes métier (Group, Lens)               |
| D        | Plan remplacé sans suppression du backlog                     |
| E        | Statut obsolète malgré des notes progress plus récentes       |

---

### Recette globale — `test_recette.py`

Script unifié avec **4 suites sélectionnables** :

```bash
python scripts/test_recette.py --list                       # Liste les suites disponibles
python scripts/test_recette.py --url http://localhost:8085  # TOUTES les suites
python scripts/test_recette.py --suite recette              # Pipeline agent (7 tests)
python scripts/test_recette.py --suite isolation            # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite              # Outils MCP (19 tests)
python scripts/test_recette.py --suite recette,isolation    # Plusieurs suites
python scripts/test_recette.py --suite isolation -v --step  # Pas-à-pas
python scripts/test_recette.py --no-cleanup                 # Conserver les données
```

#### Suites disponibles

| Suite       | Tests | Description                                                                                                              |
| ----------- | ----- | ------------------------------------------------------------------------------------------------------------------------ |
| `recette`   | 7     | Pipeline complet : token → space → notes → consolidation LLM → bank → cleanup                                            |
| `isolation` | 18    | Multi-tenant : accès inter-espaces refusé, filtrage backup, read-only, auto-ajout space au token                         |
| `qualite`   | 19    | Outils MCP : system, admin, space, live, bank, backup, GC                                                                |
| `graph`     | ~8    | Pont Graph Memory : connect, push, status, disconnect (optionnel, nécessite `--graph-url` et `--graph-token`)            |

```bash
# Suite graph (nécessite Graph Memory en cours d'exécution)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token TOKEN
```

> ⚠️ Lorsque Live Memory tourne dans Docker, utilisez `host.docker.internal` au lieu de `localhost` pour les URLs Graph Memory.

### Test compaction bank — `test_bank_compact.py`

Test unitaire direct du moteur de compaction. Exécution : `python scripts/test_bank_compact.py`.

---

## Options communes

| Option          | Description                                                                  |
| --------------- | ---------------------------------------------------------------------------- |
| `--url`         | URL du serveur Live Memory (défaut : `$MCP_URL` ou `http://localhost:8080`)  |
| `--token`       | Bootstrap key admin (défaut : `$ADMIN_BOOTSTRAP_KEY` ou `.env`)              |
| `--json` / `-j` | Sortie JSON brute sur n'importe quelle commande (bypasse Rich)               |
| `--suite`       | Suites à exécuter, séparées par virgules (défaut : toutes)                   |
| `--graph-url`   | URL Graph Memory (pour `--suite graph`)                                      |
| `--graph-token` | Token Graph Memory (pour `--suite graph`)                                    |
| `--step`        | Mode pas-à-pas (pause entre chaque étape)                                    |
| `--no-cleanup`  | Conserver les données après le test                                          |
| `-v`            | Affichage détaillé                                                           |
| `--list`        | Liste les suites disponibles et quitte                                       |

---

## Architecture

```
scripts/
├── mcp_cli.py                # Point d'entrée CLI Click + Shell interactif
├── test_recette.py           # 🧪 Recette globale (4 suites, ~44 tests)
├── test_hallucination.py     # 🧪 Tests anti-hallucination (Issue #17, 5 scénarios)
├── test_bank_compact.py      # 🧪 Tests unitaires compaction bank
├── README.md                 # Documentation (Anglais)
├── README.fr.md              # Documentation (Français) ← Vous êtes ici
└── cli/
    ├── __init__.py           # Config (BASE_URL, TOKEN)
    ├── client.py             # MCPClient Streamable HTTP (SDK MCP)
    ├── commands.py           # Commandes Click (1 par outil MCP)
    ├── display.py            # Affichage Rich (tables, panels)
    └── shell.py              # Shell interactif (prompt_toolkit)
```

---

*Live Memory CLI v2.4.0*
