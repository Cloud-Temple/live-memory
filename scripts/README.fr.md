# 🖥️ Live Memory CLI, Shell & Tests

> CLI scriptable, shell interactif et scripts de test pour Live Memory MCP v1.9.0.

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

## CLI scriptable (Click)

```bash
python scripts/mcp_cli.py health                      # État de santé
python scripts/mcp_cli.py whoami                       # Identité du token courant
python scripts/mcp_cli.py about                        # Informations service
python scripts/mcp_cli.py space list                   # Lister les espaces
python scripts/mcp_cli.py space create id desc rules   # Créer un espace
python scripts/mcp_cli.py space update id -d "desc"    # Modifier description/owner
python scripts/mcp_cli.py space summary id             # Synthèse complète
python scripts/mcp_cli.py space export id              # Exporter en tar.gz
python scripts/mcp_cli.py live note space obs "msg"    # Écrire une note
python scripts/mcp_cli.py bank consolidate space       # Consolider via LLM
python scripts/mcp_cli.py token create nom -p read,write --email u@ex.com  # Créer un token
python scripts/mcp_cli.py token update sha256:a8c5 --email u@ex.com    # Modifier un token
python scripts/mcp_cli.py token list                                    # Lister les tokens
python scripts/mcp_cli.py graph push space             # Pousser vers Graph Memory
python scripts/mcp_cli.py bank compact space            # Analyser les fichiers surdimensionnés (dry-run)
python scripts/mcp_cli.py bank compact space --apply    # Compacter via LLM (admin)
python scripts/mcp_cli.py backup create space           # Créer un backup
python scripts/mcp_cli.py backup create --all           # Backup TOUS les espaces (admin)
python scripts/mcp_cli.py backup download id           # Télécharger un backup
python scripts/mcp_cli.py gc --space-id id --confirm   # Garbage Collector
```

Pour l'aide complète : `python scripts/mcp_cli.py --help`

---

## Shell interactif

```bash
python scripts/mcp_cli.py shell
```

Le shell offre :
- **Autocomplétion** (Tab) sur toutes les commandes
- **Historique** persistant (`~/.live_mem_shell_history`)
- **Affichage Rich** coloré (tables, panels, Markdown)

---

## 🧪 Scripts de test

### Test de recette global — `test_recette.py`

Script unifié avec **4 suites sélectionnables** par ligne de commande :

```bash
# Lister les suites disponibles
python scripts/test_recette.py --list

# TOUTES les suites (50 tests, ~75s)
python scripts/test_recette.py --url http://localhost:8085

# Juste une suite
python scripts/test_recette.py --suite recette     # Pipeline agent (7 tests)
python scripts/test_recette.py --suite isolation    # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite      # Outils MCP (19 tests)

# Plusieurs suites
python scripts/test_recette.py --suite recette,isolation

# Options
python scripts/test_recette.py --suite isolation -v --step  # Verbose + pas-à-pas
python scripts/test_recette.py --no-cleanup                  # Conserver les données
```

#### Suites disponibles

| Suite | Tests | Description |
|---|---|---|
| `recette` | 7 | Pipeline complet : token → espace → notes → consolidation LLM → bank → cleanup |
| `isolation` | 18 | Tests d'isolation multi-tenant v0.7.1 : accès inter-espaces refusé, filtrage backup_list, read-only, auto-ajout space au token |
| `qualite` | 19 | Tests des outils MCP : system, admin, space, live, bank, backup, GC |
| `graph` | ~10 | Pont vers Graph Memory : connect, push, status, disconnect (optionnel, nécessite `--graph-url` et `--graph-token`) |

**Résultat attendu** : 50 PASS, 0 FAIL (sans graph). Avec graph : ~54 PASS.

```bash
# Suite graph (nécessite Graph Memory en cours d'exécution)
python scripts/test_recette.py --suite graph \
  --graph-url https://graph-mem.mcp.cloud-temple.app \
  --graph-token TOKEN
```

---

## Options communes

| Option | Description |
|---|---|
| `--url` | URL du serveur Live Memory (défaut: `$MCP_URL` ou `http://localhost:8080`) |
| `--token` | Bootstrap key admin (défaut: `$ADMIN_BOOTSTRAP_KEY` ou `.env`) |
| `--step` | Mode pas-à-pas (pause entre chaque étape) |
| `--no-cleanup` | Conserver les données après le test |
| `-v` | Affichage détaillé |

---

## Architecture

```
scripts/
├── mcp_cli.py                # Point d'entrée CLI Click + Shell interactif
├── test_recette.py           # 🧪 Script de recette global (4 suites, ~50 tests)
├── README.md                 # Documentation (English)
├── README.fr.md              # Documentation (Français) ← Vous êtes ici
├── test_bank_compact.py      # 🧪 Tests compaction bank
├── test_dedup_fix.py         # 🧪 Tests fix déduplication
└── cli/
    ├── __init__.py           # Config (BASE_URL, TOKEN)
    ├── client.py             # MCPClient Streamable HTTP (SDK MCP)
    ├── commands.py           # Commandes Click
    ├── display.py            # Affichage Rich (tables, panels)
    └── shell.py              # Shell interactif prompt_toolkit
```

---

*Live Memory CLI v1.9.0*
