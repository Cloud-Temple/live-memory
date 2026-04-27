# 🧠 Live Memory — MCP Knowledge Live memory Service

> **Mémoire de travail partagée pour agents IA collaboratifs**

[![Version](https://img.shields.io/badge/version-1.7.0-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)]()
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)]()
[![Python](https://img.shields.io/badge/python-3.11+-yellow.svg)]()

---

## 📋 Table des matières

- [Concept](#-concept)
- [Architecture](#-architecture)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Démarrage](#-démarrage)
- [Outils MCP](#-outils-mcp)
- [Graph Bridge](#-graph-bridge--pont-vers-graph-memory)
- [README English](#-readme-english)
- [Interface Web](#-interface-web)
- [Intégration MCP](#-intégration-mcp)
- [CLI et Shell](#-cli-et-shell)
- [Tests](#-tests)
- [Sécurité](#-sécurité)
- [Structure du projet](#-structure-du-projet)
- [Dépannage](#-dépannage)

---

## 🎯 Concept

**Live Memory** est un serveur MCP (Model Context Protocol) qui fournit une **Memory Bank as a Service** pour agents IA. Plusieurs agents collaborent sur un même projet en partageant une mémoire de travail commune.

```
graph-memory  = Mémoire LONG TERME (documents → Knowledge Graph → RAG vectoriel)
live-memory   = Mémoire de TRAVAIL (notes live → LLM → Memory Bank structurée)
```

### Deux modes complémentaires

| Mode         | Description                                                       | Analogie                   |
| ------------ | ----------------------------------------------------------------- | -------------------------- |
| **🔴 Live** | Notes temps réel (observations, décisions, todos...) append-only  | Tableau blanc partagé      |
| **📘 Bank** | Consolidation LLM en fichiers Markdown structurés selon des rules | Cahier de projet structuré |

### Pourquoi Live Memory ?

| Problème                                    | Solution Live Memory                                            |
| ------------------------------------------- | --------------------------------------------------------------- |
| Agents perdent leur contexte entre sessions | `bank_read_all` → contexte complet en 1 appel                   |
| Collaboration multi-agents impossible       | Notes append-only, pas de conflit, visibilité croisée           |
| Consolidation manuelle fastidieuse          | LLM transforme les notes brutes en documentation structurée     |
| Mémoire dispersée en fichiers locaux        | Point central S3, accessible de partout                         |
| Pas de lien avec la mémoire long terme      | 🌉 Graph Bridge pousse la bank dans un graphe de connaissances |

### 🧠 Collaboration multi-agents et architecture mémoire à deux niveaux

La recherche récente sur les systèmes multi-agents à base de LLM ([Tran et al., 2025 — *Multi-Agent Collaboration Mechanisms: A Survey of LLMs*](https://arxiv.org/abs/2501.06322)) identifie la **mémoire partagée** comme un composant fondamental. Dans leur cadre formel, un système multi-agents est défini par des **agents** (A), un **environnement partagé** (E) et des **canaux de collaboration** (C). Les auteurs soulignent que les LLM sont intrinsèquement des algorithmes isolés, non conçus pour collaborer — ils ont besoin d'une **infrastructure de mémoire partagée** pour coordonner leurs actions.

Live Memory + Graph Memory implémente directement cette architecture :

```
┌─────────────────────────────────────────────────────────────┐
│                  Environnement partagé E                    │
│                                                             │
│  ┌──────────────────┐   LLM    ┌─────────────────────┐      │
│  │   Live           │ ──────►  │   Bank              │      │
│  │  Notes temps réel│ consolide│  Mémoire de travail │      │
│  │  (append-only)   │          │  structurée         │      │
│  └──────────────────┘          └──────────┬──────────┘      │
│                                          │                  │
│                                     graph_push              │
│                                     (MCP Streamable HTTP)   │
│                                          │                  │
│                               ┌──────────▼───────────┐      │
│                               │     Graph Memory     │      │
│                               │  Knowledge Graph     │      │
│                               │  (entités, relations,│      │
│                               │   embeddings, RAG)   │      │
│                               └──────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

| Niveau                 | Service      | Durée            | Contenu                                     | Usage                                                  |
| ---------------------- | ------------ | ---------------- | ------------------------------------------- | ------------------------------------------------------ |
| **Mémoire de travail** | Live Memory  | Session / projet | Notes brutes + bank consolidée Markdown     | Contexte opérationnel, coordination quotidienne        |
| **Mémoire long terme** | Graph Memory | Permanent        | Entités + relations + embeddings vectoriels | Base de connaissances interrogeable en langage naturel |

**Le Graph Bridge** (`graph_push`) est le canal de collaboration entre ces deux niveaux. Conformément au pattern **late-stage collaboration** décrit dans la littérature (partage des outputs consolidés comme inputs d'un autre système), il transforme la documentation de travail (Markdown) en connaissances structurées (graphe d'entités/relations).

**Pourquoi deux niveaux ?** Un seul niveau ne suffit pas :
- La mémoire de travail seule est **éphémère** — elle disparaît quand le projet se termine
- Le graphe de connaissances seul est **trop lourd** pour des notes quotidiennes rapides
- Le pont entre les deux permet aux agents de **travailler vite** (notes live) tout en **capitalisant** les connaissances (graphe)

Concrètement, les agents peuvent :
1. **Écrire rapidement** des notes sans friction (live-memory, append-only, ~50ms)
2. **Consolider automatiquement** via LLM en documentation structurée (bank, ~15s)
3. **Pérenniser les connaissances** dans un graphe interrogeable (graph-memory, ~2min)
4. **Interroger le graphe** en langage naturel pour retrouver des informations de projets passés

---

## 🏗️ Architecture

```
     Agent Cline        Agent Claude        Agent X
          │                   │                │
          └────────┬──────────┘                │
                   │                           │
                   ▼  MCP Protocol (Streamable HTTP)  ▼
          ┌────────────────────────────────────────┐
          │   Caddy WAF (Coraza CRS)               │
          │   Rate Limiting • TLS • OWASP CRS      │
          └────────────┬───────────────────────────┘
                       │
          ┌────────────┴───────────────────┐
          │   Live Memory MCP (:8002)      │
          │   39 outils • Auth Bearer      │
          │   Consolidation LLM            │
          └──────┬──────────┬──────┬───────┘
                 │          │      │
          ┌──────┴──┐  ┌────┴───┐  │
          │   S3    │  │ LLMaaS │  │  MCP Streamable HTTP
          │Dell ECS │  │ CT API │  │  (optionnel)
          └─────────┘  └────────┘  │
                       ┌───────────┴────────────┐
                       │   Graph Memory         │
                       │   (mémoire long terme) │
                       │   Neo4j + Qdrant       │
                       └────────────────────────┘
```

**Stack minimale** : S3 + LLM. Pas de base de données locale.
**Optionnel** : connexion à Graph Memory pour la mémoire long terme (graphe de connaissances).

---

## 📦 Prérequis

- **Docker** >= 24.0 + **Docker Compose** v2
- **Python 3.11+** (pour la CLI, optionnel)
- Un **stockage S3** compatible (Cloud Temple Dell ECS, AWS, MinIO)
- Un **LLM** compatible OpenAI API (Cloud Temple LLMaaS, OpenAI, etc.)

---

## 🚀 Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/Cloud-Temple/live-memory.git
cd live-memory
```

### 2. Configurer l'environnement

```bash
cp .env.example .env
```

Éditez `.env` avec vos valeurs (voir section [Configuration](#-configuration)).

### 3a. Démarrage Docker (recommandé)

```bash
# Construire les images (WAF + serveur MCP)
docker compose build

# Démarrer les services
docker compose up -d

# Vérifier que tout tourne
docker compose ps

# Vérifier la santé
curl -s http://localhost:8080/health
```

### 3b. Démarrage local (développement)

```bash
# Installer les dépendances
uv pip install -e .

# Lancer le serveur
python -m live_mem
```

### 4. Installer la CLI (optionnel)

```bash
uv pip install -e .
```

### 5. Vérifier l'installation

```bash
# Health check via la CLI
python scripts/mcp_cli.py health

# Ou test E2E complet (crée un espace, écrit des notes, consolide)
python scripts/test_recette.py
```

### Ports exposés

| Service    | Port   | Description                                |
| ---------- | ------ | ------------------------------------------ |
| **WAF**    | `8080` | Seul port exposé — Caddy WAF → Live Memory |
| MCP Server | `8002` | Réseau Docker interne uniquement           |

---

## ⚙️ Configuration

Éditez `.env`. Toutes les variables sont documentées dans `.env.example`.

### Variables obligatoires

| Variable               | Description              | Exemple                                      |
| ---------------------- | ------------------------ | -------------------------------------------- |
| `S3_ENDPOINT_URL`      | URL endpoint S3          | `https://takinc5acc.s3.fr1.cloud-temple.com` |
| `S3_ACCESS_KEY_ID`     | Access key S3            | `AKIA...`                                    |
| `S3_SECRET_ACCESS_KEY` | Secret key S3            | `wJal...`                                    |
| `S3_BUCKET_NAME`       | Nom du bucket            | `live-mem`                                   |
| `S3_REGION_NAME`       | Région S3                | `fr1`                                        |
| `LLMAAS_API_URL`       | URL API LLM (doit inclure `/v1`)  | `https://api.ai.cloud-temple.com/v1` |
| `LLMAAS_API_KEY`       | Clé API LLM                       | `sk-...`                             |
| `ADMIN_BOOTSTRAP_KEY`  | Clé admin bootstrap (≥ 32 chars)  | `ma-cle-secrete-changez-moi`        |

### Variables optionnelles — LLM

Le consolidateur utilise un LLM (API compatible OpenAI) pour transformer les notes live en fichiers bank structurés.

| Variable                  | Défaut            | Description                      |
| ------------------------- | ----------------- | -------------------------------- |
| `LLMAAS_MODEL`            | `qwen3.5:27b` | Nom du modèle LLM tel qu'exposé par le provider |
| `LLMAAS_CONTEXT_WINDOW`   | `131072`          | Fenêtre de contexte TOTALE du modèle (entrée + sortie combinés, en tokens). Qwen3 235B = 128K |
| `LLMAAS_MAX_TOKENS`       | `16384`           | Budget de SORTIE max par requête (en tokens). Le consolidateur l'ajuste dynamiquement : `output = min(MAX_TOKENS, CONTEXT_WINDOW - input)` |
| `LLMAAS_TEMPERATURE`      | `0.3`             | Créativité du LLM (0.0 = déterministe, 1.0 = très créatif) |

### Variables optionnelles — Consolidation et compaction

| Variable                  | Défaut            | Description                      |
| ------------------------- | ----------------- | -------------------------------- |
| `MCP_SERVER_PORT`         | `8002`            | Port d'écoute du serveur MCP     |
| `MCP_SERVER_DEBUG`        | `false`           | Logs détaillés (messages d'erreur complets) |
| `CONSOLIDATION_TIMEOUT`   | `600`             | Timeout par appel LLM (secondes) |
| `CONSOLIDATION_MAX_NOTES` | `500`             | Max notes traitées par consolidation |
| `CONSOLIDATION_BATCH_SIZE`| `5`               | Notes par lot LLM (petit = précis, grand = rapide) |
| `COMPACT_THRESHOLD`       | `0.6`             | Seuil auto-compaction (0.6 = compacte si bank > 60% du budget) |
| `BANK_FILE_MAX_SIZE`      | `15360`           | Taille max par fichier bank (bytes, 15 KB). Au-delà = compaction |

---

## ▶️ Démarrage

```bash
docker compose up -d
docker compose ps       # Vérifier le statut
docker compose logs -f live-mem-service --tail 50  # Logs
```

---

## 🔧 Outils MCP

39 outils exposés via le protocole MCP (Streamable HTTP), répartis en 7 catégories.

### System (3 outils)

| Outil           | Paramètres | Description                                               |
| --------------- | ---------- | --------------------------------------------------------- |
| `system_health` | —          | État de santé (S3, LLMaaS, nombre d'espaces)              |
| `system_whoami` | —          | 👤 Identité du token courant (nom, permissions, espaces) |
| `system_about`  | —          | Identité du service (version, outils, capacités)          |

### Space (9 outils)

| Outil                | Paramètres                                   | Description                                                |
| -------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `space_create`       | `space_id`, `description`, `rules`, `owner?` | Crée un espace avec ses rules (structure de la bank)       |
| `space_update`       | `space_id`, `description?`, `owner?`         | Met à jour la description et/ou le owner                   |
| `space_update_rules` | `space_id`, `rules`                          | 📜 Met à jour les rules d'un espace (admin only)          |
| `space_list`         | —                                            | Liste les espaces accessibles par le token courant         |
| `space_info`    | `space_id`                                   | Infos détaillées (notes, bank, consolidation)              |
| `space_rules`   | `space_id`                                   | Lit les rules immuables de l'espace                        |
| `space_summary` | `space_id`                                   | Synthèse complète : rules + bank + stats (démarrage agent) |
| `space_export`  | `space_id`                                   | Export tar.gz en base64                                    |
| `space_delete`  | `space_id`, `confirm`                        | Supprime l'espace (⚠️ irréversible, admin requis)        |

### Live (3 outils)

| Outil         | Paramètres                                  | Description                                                                                                                 |
| ------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `live_note`   | `space_id`, `category`, `content`, `tags?`  | Écrit une note horodatée (agent = token name). Catégories : observation, decision, todo, insight, question, progress, issue |
| `live_read`   | `space_id`, `limit?`, `category?`, `agent?` | Lit les notes live (filtres optionnels)                                                                                     |
| `live_search` | `space_id`, `query`, `limit?`               | Recherche plein texte dans les notes                                                                                        |

### Bank (7 outils)

| Outil              | Paramètres                            | Description                                                                                                |
| ------------------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `bank_read`        | `space_id`, `filename`                | Lit un fichier bank (supporte les sous-dossiers : `personaProfiles/acheteur.md`)                           |
| `bank_read_all`    | `space_id`                            | Lit toute la bank en une requête (🚀 démarrage agent)                                                     |
| `bank_list`        | `space_id`                            | Liste les fichiers bank avec chemins relatifs (sans contenu)                                               |
| `bank_consolidate` | `space_id`, `agent?`                  | 🧠 Consolide les notes via LLM. `agent` vide = toutes les notes (admin). `agent=nom` = notes de cet agent |
| `bank_repair`      | `space_id`, `dry_run?`                | 🔧 Répare les noms corrompus (Unicode, préfixes parasites). `dry_run=True` par défaut (admin)              |
| `bank_write`       | `space_id`, `filename`, `content`     | ✏️ Écrit/remplace un fichier bank directement — contourne la consolidation LLM (admin)                    |
| `bank_delete`      | `space_id`, `filename`                | 🗑️ Supprime un fichier bank + ses doublons Unicode (admin, irréversible)                                  |

### Graph (4 outils) — 🌉 Pont vers Graph Memory

| Outil              | Paramètres                                           | Description                                                                                                  |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `graph_connect`    | `space_id`, `url`, `token`, `memory_id`, `ontology?` | Connecte un space à Graph Memory. Teste la connexion, crée la mémoire si besoin. Ontologie défaut: `general` |
| `graph_push`       | `space_id`                                           | Synchronise la bank → graphe. Delete + re-ingest intelligent, nettoyage orphelins. ~30s/fichier              |
| `graph_status`     | `space_id`                                           | Statut connexion + stats graphe (documents, entités, relations, top entités, liste documents)                |
| `graph_disconnect` | `space_id`                                           | Déconnecte (les données restent dans le graphe)                                                              |

### Backup (5 outils)

| Outil             | Paramètres                 | Description                                       |
| ----------------- | -------------------------- | ------------------------------------------------- |
| `backup_create`   | `space_id`, `description?` | Crée un snapshot complet sur S3                   |
| `backup_list`     | `space_id?`                | Liste les backups disponibles                     |
| `backup_restore`  | `backup_id`                | Restaure un backup (l'espace ne doit pas exister) |
| `backup_download` | `backup_id`                | Télécharge en tar.gz base64                       |
| `backup_delete`   | `backup_id`                | Supprime un backup                                |

### Admin (7 outils)

| Outil                | Paramètres                                                        | Description                                                                                                    |
| -------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `admin_create_token` | `name`, `permissions`, `space_ids?`, `expires_in_days?`, `email?` | Crée un token (⚠️ affiché une seule fois). Permissions: read, write, admin. Email optionnel pour traçabilité |
| `admin_list_tokens`  | —                                                                 | Liste les tokens actifs                                                                                        |
| `admin_revoke_token` | `token_hash`                                                      | Révoque un token (le rend inutilisable)                                                                        |
| `admin_delete_token` | `token_hash`                                                      | Supprime physiquement un token du registre (⚠️ irréversible)                                                 |
| `admin_purge_tokens` | `revoked_only?`                                                   | Purge en masse : révoqués seuls (défaut) ou tous les tokens                                                    |
| `admin_update_token` | `token_hash`, `space_ids`, `action`                               | Modifie les espaces d'un token (add/remove/set)                                                                |
| `admin_gc_notes`     | `space_id?`, `max_age_days?`, `confirm?`, `delete_only?`          | Garbage Collector : nettoie les notes orphelines                                                               |

---

## 🌉 Graph Bridge — Pont vers Graph Memory

Live Memory peut pousser sa Memory Bank dans une instance [Graph Memory](https://github.com/Cloud-Temple/graph-memory) pour la mémoire long terme. Le graphe de connaissances extrait les entités, relations et embeddings des fichiers bank.

---

## 🇬🇧 README English

Une version anglaise de cette documentation est disponible ici : [README.en.md](README.en.md)

---

## 🖥️ Interface Web

Live Memory expose une **interface web** sur `/live` pour visualiser les espaces mémoire en temps réel.

### Accès

```
http://localhost:8080/live
```

### Fonctionnalités

| Zone                                | Contenu                                                                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **📊 Dashboard** (gauche)          | Infos espace, consolidation (date + compteurs), stats live/bank, agents colorés, catégories avec %, rules Markdown, Graph Memory |
| **🔴 Live Timeline** (haut-droite) | Notes live groupées par date (Aujourd'hui/Hier/date), cards avec agent + catégorie + Markdown                                    |
| **📘 Bank Viewer** (bas-droite)    | Onglets de fichiers consolidés, rendu Markdown avec marked.js                                                                    |

### Layout

```
┌──────────────┬────────────────────────────┐
│  📊 Dashboard│  🔴 Live Timeline          │
│  (infos,     │  (auto-refresh, groupé/date)│
│   agents,    ├────────────────────────────┤
│   rules...)  │  📘 Bank (onglets Markdown) │
└──────────────┴────────────────────────────┘
```

### Auto-refresh intelligent

- Configurable : 3s / 5s / 10s / 30s / manuel
- **Anti-flicker** : ne re-rend le DOM que si les données ont changé
- Pastille verte pulsante avec timestamp du dernier refresh
- Sélection d'espace → chargement immédiat (pas de bouton)

### API REST (5 endpoints)

| Endpoint                        | Description                                              |
| ------------------------------- | -------------------------------------------------------- |
| `GET /api/spaces`               | Liste des espaces                                        |
| `GET /api/space/{id}`           | Info complète (meta + rules + stats + graph-memory)      |
| `GET /api/live/{id}`            | Notes live (filtres: `?agent=`, `?category=`, `?limit=`) |
| `GET /api/bank/{id}`            | Liste des fichiers bank                                  |
| `GET /api/bank/{id}/{filename}` | Contenu d'un fichier bank                                |

Les endpoints `/api/*` nécessitent un Bearer Token. La page `/live` et les fichiers `/static/*` sont publics.

---

## 🔌 Intégration MCP

> 📖 **Guide complet** : Voir [GUIDE_INTEGRATION_CLINE.md](GUIDE_INTEGRATION_CLINE.md) pour le guide pas-à-pas détaillé (configuration Cline, custom instructions, workflow, multi-agents, dépannage).

### Avec Cline (VS Code / VSCodium)

Dans les settings MCP de Cline (`cline_mcp_settings.json`) - n'oubliez pas /mcp :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_VOTRE_TOKEN"
      }
    }
  }
}
```

Pour configurer les **Custom Instructions** de votre agent, copiez le fichier [`clinerules.md`](clinerules.md) dans vos Custom Instructions globales Cline (ou dans un `.clinerules/` de votre projet). Il suffit de modifier **deux valeurs** :
- Le **nom du serveur MCP** (tel que configuré dans `cline_mcp_settings.json`, ex: `my-live-mem`)
- Le **nom de votre espace mémoire** (l'identifiant passé à `space_create`, ex: `mon-projet`)

Le nom de l'agent est **auto-détecté** depuis le token d'authentification — rien d'autre à configurer.

> 💡 **Template prêt à l'emploi :** [`clinerules.md`](clinerules.md) — copier et personnaliser les 2 valeurs en gras
>
> 📖 **Guide détaillé :** [Guide d'intégration Cline & Custom Instructions](GUIDE_INTEGRATION_CLINE.md)

### Avec Claude Desktop

Dans `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_VOTRE_TOKEN"
      }
    }
  }
}
```

### Via Python (client MCP)

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def exemple():
    headers = {"Authorization": "Bearer votre_token"}
    async with streamablehttp_client("http://localhost:8080/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Charger tout le contexte
            result = await session.call_tool("bank_read_all", {
                "space_id": "mon-projet"
            })

            # Écrire une note
            await session.call_tool("live_note", {
                "space_id": "mon-projet",
                "category": "observation",
                "content": "Le build passe en CI"
            })
```

---

## 💻 CLI et Shell

### Installation CLI

```bash
pip install click rich prompt-toolkit mcp[cli]>=1.8.0
export MCP_URL=http://localhost:8080
export MCP_TOKEN=votre_token
```

### Commandes CLI (Click)

```bash
python scripts/mcp_cli.py health
python scripts/mcp_cli.py whoami                       # Identité du token courant
python scripts/mcp_cli.py about
python scripts/mcp_cli.py space list
python scripts/mcp_cli.py space create mon-projet --rules-file rules.md
python scripts/mcp_cli.py live note mon-projet observation "Build OK"
python scripts/mcp_cli.py bank consolidate mon-projet
python scripts/mcp_cli.py bank read-all mon-projet
python scripts/mcp_cli.py token create agent-cline read,write
python scripts/mcp_cli.py graph connect mon-projet URL TOKEN MEM-ID -o general
python scripts/mcp_cli.py graph push mon-projet
python scripts/mcp_cli.py graph status mon-projet
python scripts/mcp_cli.py graph disconnect mon-projet
```

### Shell interactif

```bash
python scripts/mcp_cli.py shell
```

Autocomplétion, historique, affichage Rich. Voir [scripts/README.md](scripts/README.md) pour la référence complète.

---

## 🧪 Tests

Script de recette **unifié** avec 4 suites sélectionnables par `--suite` :

```bash
docker compose up -d   # Prérequis

# Toutes les suites (44 tests, ~60s)
python scripts/test_recette.py --url http://localhost:8080

# Juste une suite
python scripts/test_recette.py --suite recette     # Pipeline agent (7 tests)
python scripts/test_recette.py --suite isolation    # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite      # Outils MCP (19 tests)

# Suite Graph Memory (optionnelle, nécessite graph-memory en cours)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token votre_token

# Lister les suites disponibles
python scripts/test_recette.py --list

# Mode pas-à-pas + verbose
python scripts/test_recette.py --suite isolation -v --step --no-cleanup
```

| Suite       | Tests | Description                                                                             |
| ----------- | ----- | --------------------------------------------------------------------------------------- |
| `recette`   | 7     | Pipeline complet : token → notes → consolidation LLM → bank                             |
| `isolation` | 18    | Isolation multi-tenant v0.7.1 : accès inter-espaces, filtrage backups, auto-ajout token |
| `qualite`   | 19    | Tests des 32 outils MCP : system, admin, space, live, bank, backup, GC                  |
| `graph`     | ~8    | Pont Graph Memory : connect, push, status, disconnect (optionnel)                       |

Voir [scripts/README.md](scripts/README.md) pour le détail complet.

---

## 🔒 Sécurité

### Authentification

- **Bearer Token** obligatoire sur toutes les requêtes MCP
- **Bootstrap key** pour créer le premier token admin
- **Tokens SHA-256** stockés sur S3 (jamais en clair)
- **3 niveaux** : read, write, admin
- **Scope par espace** : un token peut être limité à certains espaces

### WAF (Caddy + Coraza)

- **OWASP CRS** : injection SQL/XSS, path traversal, SSRF
- **Rate Limiting** : 200 MCP/min (Streamable HTTP)
- **TLS automatique** : Let's Encrypt en production (`SITE_ADDRESS=domaine.com`)
- **Container non-root** : utilisateur `mcp`

### Bonnes pratiques

1. **Changez `ADMIN_BOOTSTRAP_KEY`** en production
2. Ne commitez jamais `.env`
3. Créez des tokens avec les permissions minimales
4. Activez HTTPS via `SITE_ADDRESS`

---

## 📂 Structure du projet

```
live-memory/
├── src/live_mem/              # Code source (39 outils MCP + interface web)
│   ├── server.py              # Serveur FastMCP + middlewares
│   ├── config.py              # Configuration pydantic-settings
│   ├── auth/                  # Authentification
│   │   ├── middleware.py      #   Auth + Logging + StaticFiles
│   │   └── context.py         #   check_access, check_write, check_admin
│   ├── static/                # Interface web /live
│   │   ├── live.html          #   SPA (Dashboard + Live + Bank)
│   │   ├── css/live.css       #   Styles (thème Cloud Temple)
│   │   ├── js/                #   7 modules JS (config, api, app, dashboard, timeline, bank, sidebar)
│   │   └── img/               #   Logo Cloud Temple SVG
│   ├── core/                  # Services métier
│   │   ├── storage.py         #   S3 dual SigV2/SigV4 (Dell ECS)
│   │   ├── space.py           #   CRUD espaces mémoire
│   │   ├── live.py            #   Notes live (append-only)
│   │   ├── consolidator.py    #   Pipeline LLM (4 étapes)
│   │   ├── graph_bridge.py    #   🌉 Pont vers Graph Memory
│   │   ├── tokens.py          #   Gestion tokens SHA-256
│   │   ├── backup.py          #   Snapshots S3
│   │   ├── gc.py              #   Garbage Collector
│   │   ├── locks.py           #   Locks asyncio par espace
│   │   └── models.py          #   Modèles Pydantic
│   └── tools/                 # Outils MCP (7 modules, 57 params documentés)
│       ├── system.py          #   3 outils (health, whoami, about)
│       ├── space.py           #   9 outils (CRUD espaces) — 15 params
│       ├── live.py            #   3 outils (notes) — 13 params
│       ├── bank.py            #   7 outils (bank + consolidation + admin) — 10 params
│       ├── graph.py           #   4 outils (Graph Bridge) — 8 params
│       ├── backup.py          #   5 outils (snapshots) — 8 params
│       └── admin.py           #   7 outils (tokens + GC + purge) — 14 params
├── scripts/                   # CLI + Shell + Tests
│   ├── mcp_cli.py             #   Point d'entrée CLI Click + Shell
│   ├── test_recette.py        #   🧪 Script de recette unifié (4 suites, ~50 tests)
│   └── cli/                   #   Package CLI (client, commands, display, shell)
├── waf/                       # WAF Caddy + Coraza
│   ├── Caddyfile              #   Config WAF + rate limiting
│   └── Dockerfile             #   Image Caddy + Coraza
├── RULES/                     # 📐 Modèles de rules pour créer des espaces (5 templates)
│   ├── README.md              #   Guide d'utilisation + pourquoi les rules sont critiques
│   ├── live-mem.standard.memory.bank.md  # Modèle standard (6 fichiers, dev/archi/projet)
│   ├── book.memory.bank.md    #   Modèle écriture de livre (6 fichiers, suivi narratif)
│   ├── medical.memory.bank.md #   Modèle suivi médical (7+2 fichiers, fiabilité absolue)
│   └── presales.memory.bank.md#   Modèle avant-vente B2B (5+N fichiers, personas dynamiques)
├── clinerules.md              # 📋 Template Custom Instructions Cline (copier + personnaliser)
├── DESIGN/live-mem/           # 9 documents d'architecture
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml             # Dépendances & config projet (uv)
├── uv.lock                    # Lockfile uv
├── VERSION                    # 1.4.1
├── CHANGELOG.md
└── FAQ.md                     # 20 questions/réponses
```

---

## 🔍 Dépannage

### Le service ne démarre pas

```bash
docker compose logs live-mem-service --tail 50
docker compose logs waf --tail 20
```

### Erreur 401 Unauthorized

- Vérifiez votre token : `Authorization: Bearer VOTRE_TOKEN`
- La bootstrap key n'est pas un token — créez d'abord un token via `admin_create_token`

### Consolidation échoue

- Vérifiez les credentials LLMaaS dans `.env`
- Le timeout par défaut est 600s — augmentez `CONSOLIDATION_TIMEOUT` si nécessaire
- Un seul `bank_consolidate` à la fois par espace (lock asyncio)

### Graph Bridge : connexion impossible

- Vérifiez que Graph Memory est accessible : `curl https://votre-graph-memory/mcp`
- Vérifiez le token Graph Memory (Bearer)
- L'URL peut être avec ou sans `/mcp` (normalisée automatiquement)

### Rebuild après modification du code

```bash
docker compose build live-mem-service && docker compose up -d live-mem-service
```

---

## 🔗 Projets liés

| Projet           | Description                                | Lien                                                                         |
| ---------------- | ------------------------------------------ | ---------------------------------------------------------------------------- |
| **graph-memory** | Mémoire long terme (Knowledge Graph + RAG) | [github.com/Cloud-Temple/graph-memory](https://github.com/Cloud-Temple/graph-memory) |

---

## 📄 Licence

Apache License 2.0

---

## 👤 Auteur

**Cloud Temple** — [cloud-temple.com](https://www.cloud-temple.com)

Développé par **Christophe Lesur**.

---

*Live Memory v1.3.0 — Mémoire de travail partagée pour agents IA collaboratifs*
