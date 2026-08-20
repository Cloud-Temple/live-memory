# 🧠 Live Memory — MCP Knowledge Live memory Service

> **Mémoire de travail partagée pour agents IA collaboratifs**

[![CI](https://github.com/Cloud-Temple/live-memory/actions/workflows/build.yml/badge.svg)](https://github.com/Cloud-Temple/live-memory/actions/workflows/build.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-cloud--temple%2Flive--memory-blue?logo=docker)](https://ghcr.io/cloud-temple/live-memory)
[![Version](https://img.shields.io/badge/version-2.9.4-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)]()
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)]()
[![Python](https://img.shields.io/badge/python-3.11+-yellow.svg)]()

🇬🇧 [English version](README.md)

---

## 📋 Table des matières

- [Concept](#-concept)
- [Architecture](#-architecture)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Démarrage rapide](#-démarrage-rapide)
- [Outils MCP](#-outils-mcp)
- [Graph Bridge](#-graph-bridge--pont-vers-graph-memory)
- [Interface web](#-interface-web)
- [Intégration MCP](#-intégration-mcp)
- [CLI et shell](#-cli-et-shell)
- [Tests](#-tests)
- [Sécurité](#-sécurité)
- [Structure du projet](#-structure-du-projet)
- [Troubleshooting](#-troubleshooting)
- [Contribuer](#-contribuer)

---

## 🎯 Concept

**Live Memory** est un serveur MCP (Model Context Protocol) qui fournit une **Memory Bank as a Service** pour les agents IA. Plusieurs agents collaborent sur le même projet en partageant une mémoire de travail commune.

```
graph-memory  = mémoire LONG TERME (documents → Knowledge Graph → RAG vectoriel)
live-memory   = mémoire DE TRAVAIL (notes live → LLM → Memory Bank structurée)
```

### Deux modes complémentaires

| Mode         | Description                                                              | Analogie                |
| ------------ | ------------------------------------------------------------------------ | ----------------------- |
| **🔴 Live** | Notes temps réel (observations, décisions, todos...) append-only         | Tableau blanc partagé   |
| **📘 Bank** | Consolidation LLM en fichiers Markdown structurés selon les rules        | Journal projet structuré |

### Pourquoi Live Memory ?

| Problème                                  | Solution Live Memory                                       |
| ----------------------------------------- | ---------------------------------------------------------- |
| Les agents perdent le contexte entre sessions | `bank_read_all` → contexte complet en 1 appel          |
| La collaboration multi-agent est impossible | Notes append-only, zéro conflit, visibilité croisée      |
| La consolidation manuelle est fastidieuse | Le LLM transforme les notes brutes en doc structurée      |
| Mémoire éparpillée dans des fichiers locaux | Point central S3, accessible de partout                  |
| Pas de lien avec la mémoire long terme    | 🌉 Le Graph Bridge pousse la bank dans un knowledge graph |

### 🧠 Collaboration multi-agent et architecture mémoire à deux niveaux

Les recherches récentes sur les systèmes multi-agent basés LLM ([Tran et al., 2025 — *Multi-Agent Collaboration Mechanisms: A Survey of LLMs*](https://arxiv.org/abs/2501.06322)) identifient la **mémoire partagée** comme un composant fondamental. Dans leur cadre formel, un système multi-agent est défini par des **agents** (A), un **environnement partagé** (E) et des **canaux de collaboration** (C). Les auteurs soulignent que les LLM sont intrinsèquement des algorithmes isolés, non conçus pour collaborer — ils ont besoin d'une **infrastructure de mémoire partagée** pour coordonner leurs actions.

Live Memory + Graph Memory met directement en œuvre cette architecture :

```
┌─────────────────────────────────────────────────────────────┐
│                  Environnement partagé E                    │
│                                                             │
│  ┌──────────────────┐   LLM   ┌──────────────────────┐      │
│  │   Live           │ ──────► │   Bank               │      │
│  │  Notes temps réel│ consoli-│  Mémoire de travail  │      │
│  │  (append-only)   │   de    │  structurée          │      │
│  └──────────────────┘         └──────────┬───────────┘      │
│                                          │                  │
│                                     graph_push              │
│                                     (MCP Streamable HTTP)   │
│                                          │                  │
│                               ┌──────────▼───────────┐      │
│                               │  🌐 Graph Memory     │      │
│                               │  Knowledge Graph     │      │
│                               │  (entités, relations,│      │
│                               │   embeddings, RAG)   │      │
│                               └──────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

| Niveau                | Service      | Durée               | Contenu                                  | Usage                                              |
| --------------------- | ------------ | ------------------- | ---------------------------------------- | -------------------------------------------------- |
| **Mémoire de travail** | Live Memory  | Session / projet    | Notes brutes + bank Markdown consolidée  | Contexte opérationnel, coordination quotidienne    |
| **Mémoire long terme** | Graph Memory | Permanent           | Entités + relations + embeddings vectoriels | Base de connaissances interrogeable en langue naturelle |

**Le Graph Bridge** (`graph_push`) est le canal de collaboration entre ces deux niveaux. Suivant le pattern de **late-stage collaboration** décrit dans la littérature (partage des sorties consolidées comme entrées d'un autre système), il transforme la documentation de travail (Markdown) en connaissance structurée (graphe d'entités/relations).

**Pourquoi deux niveaux ?** Un seul niveau ne suffit pas :
- La mémoire de travail seule est **éphémère** — elle disparaît à la fin du projet
- Le knowledge graph seul est **trop lourd** pour des notes quotidiennes rapides
- Le pont entre les deux permet aux agents de **travailler vite** (notes live) tout en **capitalisant** la connaissance (graphe)

Concrètement, les agents peuvent :
1. **Écrire vite** sans friction (live-memory, append-only, ~50ms)
2. **Consolider automatiquement** via LLM en documentation structurée (bank, ~15s)
3. **Persister la connaissance** dans un graphe interrogeable (graph-memory, ~2 min)
4. **Interroger le graphe** en langage naturel pour retrouver l'information des projets passés

---

## 🏗️ Architecture

```
     Agent Cline        Agent Claude        Agent X
          │                   │                │
          └────────┬──────────┘                │
                   │                           │
                   ▼  Protocole MCP (Streamable HTTP)  ▼
          ┌────────────────────────────────────────┐
          │   Caddy WAF (Coraza CRS)               │
          │   Rate Limiting • TLS • OWASP CRS      │
          └────────────┬───────────────────────────┘
                       │
          ┌────────────┴───────────────────┐
          │   Live Memory MCP (:8002)      │
          │   44 outils • Auth Bearer      │
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

**Stack minimale** : S3 + LLM. Aucune base de données locale.
**Optionnel** : connexion à Graph Memory pour la mémoire long terme (knowledge graph).

---

## 📦 Prérequis

- **Docker** >= 24.0 + **Docker Compose** v2
- **Python 3.11+** (pour la CLI, optionnel)
- Un **stockage S3** compatible (Cloud Temple Dell ECS, AWS, MinIO)
- Un **LLM** compatible API OpenAI (Cloud Temple LLMaaS, OpenAI, etc.)

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

Éditez `.env` avec vos valeurs (voir [Configuration](#-configuration)).

### 3a. Démarrage Docker (recommandé)

```bash
# Construire les images (WAF + serveur MCP)
docker compose build

# Démarrer les services
docker compose up -d

# Vérifier le statut
docker compose ps

# Health check
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

# Ou test E2E complet (crée un space, écrit des notes, consolide)
python scripts/test_recette.py
```

### Ports exposés

| Service    | Port   | Description                                       |
| ---------- | ------ | ------------------------------------------------- |
| **WAF**    | `8080` | Seul port exposé — Caddy WAF → Live Memory        |
| Serveur MCP | `8002` | Réseau Docker interne uniquement                |

---

## ⚙️ Configuration

Éditez `.env`. Toutes les variables sont documentées dans `.env.example`.

### Variables obligatoires

| Variable               | Description                       | Exemple                                     |
| ---------------------- | --------------------------------- | ------------------------------------------- |
| `S3_ENDPOINT_URL`      | URL du endpoint S3                | `https://takinc5acc.s3.fr1.cloud-temple.com` |
| `S3_ACCESS_KEY_ID`     | Clé d'accès S3                    | `AKIA...`                                   |
| `S3_SECRET_ACCESS_KEY` | Clé secrète S3                    | `wJal...`                                   |
| `S3_BUCKET_NAME`       | Nom du bucket                     | `live-mem`                                  |
| `S3_REGION_NAME`       | Région S3                         | `fr1`                                       |
| `LLMAAS_API_URL`       | URL de l'API LLM (avec `/v1`)     | `https://api.ai.cloud-temple.com/v1`        |
| `LLMAAS_API_KEY`       | Clé d'API LLM                     | `sk-...`                                    |
| `ADMIN_BOOTSTRAP_KEY`  | Clé bootstrap admin (≥ 32 chars)  | `ma-cle-secrete-a-changer`                  |

### Variables optionnelles — LLM

Le service peut utiliser deux modèles compatibles OpenAI distincts pour la
consolidation et le compactage hiérarchique.

| Variable                  | Défaut            | Description                     |
| ------------------------- | ----------------- | ------------------------------- |
| `LLMAAS_MODEL`            | `qwen3.5:27b`     | Modèle utilisé pour la consolidation des notes |
| `LLMAAS_COMPACTION_MODEL` | `LLMAAS_MODEL`    | Modèle Map/Reduce dédié au compactage. `mistral-small4:119b` est recommandé pour la 2.8.0 |
| `LLMAAS_CONTEXT_WINDOW`   | `131072`          | Context window TOTAL du modèle (input + output combinés, en tokens). Qwen3 235B = 128K |
| `LLMAAS_MAX_TOKENS`       | `16384`           | Budget de SORTIE max par requête (en tokens). Le consolidateur l'ajuste dynamiquement : `output = min(MAX_TOKENS, CONTEXT_WINDOW - input)` |
| `LLMAAS_TEMPERATURE`      | `0.3`             | Créativité du LLM (0.0 = déterministe, 1.0 = très créatif) |
| `PROXY_URL`               | _(aucun)_         | Proxy HTTP sortant (ex. `http://10.0.0.1:3128`). **Variable maison** (pas `HTTP_PROXY`) — injectée manuellement dans boto3 (S3) et httpx (LLM). Non supportée pour les connexions Graph Memory. |

### Variables optionnelles — Consolidation et compaction

| Variable                  | Défaut            | Description                     |
| ------------------------- | ----------------- | ------------------------------- |
| `MCP_SERVER_PORT`         | `8002`            | Port d'écoute du serveur MCP    |
| `MCP_SERVER_DEBUG`        | `false`           | Logs détaillés (messages d'erreur complets) |
| `CONSOLIDATION_TIMEOUT`   | `1800`            | Timeout par appel LLM (secondes) |
| `CONSOLIDATION_MAX_NOTES` | `200`             | Max de notes par consolidation  |
| `CONSOLIDATION_BATCH_SIZE`| `5`               | Notes par batch LLM (petit = précis, grand = plus rapide) |
| `CONSOLIDATION_COOLDOWN_SECONDS` | `60`      | Cooldown anti-spam par space pour `bank_consolidate` (`0` désactive) |
| `CONSOLIDATION_VALIDATION_ENABLED` | `false` | Vérification optionnelle post-consolidation des claims non sourcés |
| `CONSOLIDATION_VALIDATION_MAX_EXAMPLES` | `20` | Nombre max d'exemples retournés par la validation |
| `COMPACT_THRESHOLD`       | `0.6`             | Paramètre historique ; la compaction suit désormais la limite logique par fichier en octets UTF-8 |
| `BANK_FILE_MAX_SIZE`      | `15360`           | Cible en octets UTF-8 d'un fichier Bank logique, pas un veto : une compaction sûre peut rester au-dessus si le contenu protégé rend la cible impossible |
| `RESPONSE_MAX_BYTES`      | `524288`          | Taille max des réponses non-MCP avant troncature |
| `API_TOOL_MAX_BODY_BYTES` | `1048576`         | Taille max du corps accepté par `/api/tool` |

Pendant une consolidation, les sections Markdown dupliquées ne sont fusionnées
que si le résultat est non vide. Si le modèle échoue ou renvoie un contenu
vide, Live Memory conserve toutes les occurrences courantes, arrête seulement
la déduplication de ce fichier, poursuit le lot et expose l'événement via
`dedup_failures_count`.

---

## ▶️ Démarrage rapide

```bash
docker compose up -d
docker compose ps       # Vérifier le statut
docker compose logs -f live-mem-service --tail 50  # Logs
```

---

## 🔧 Outils MCP

44 outils exposés via le protocole MCP (Streamable HTTP), répartis en 7 catégories.

### System (3 outils)

| Outil           | Paramètres | Description                                              |
| --------------- | ---------- | -------------------------------------------------------- |
| `system_health` | —          | Statut de santé (S3, LLMaaS, nombre de spaces)           |
| `system_whoami` | —          | 👤 Identité du token courant (nom, permissions, spaces) |
| `system_about`  | —          | Identité du service (version, outils, capacités)         |

### Space (10 outils)

| Outil                | Paramètres                                   | Description                                                  |
| -------------------- | -------------------------------------------- | ------------------------------------------------------------ |
| `space_create`       | `space_id`, `description`, `rules`, `owner?` | Crée un space avec ses rules (structure de la bank)          |
| `space_badge_mint`   | `space_id`, `client_name`                    | Frappe/remplace le badge restreint d'un agent de mission     |
| `space_update`       | `space_id`, `description?`, `owner?`         | Met à jour la description et/ou l'owner                      |
| `space_update_rules` | `space_id`, `rules`                          | 📜 Met à jour les rules du space (manage)                    |
| `space_list`         | —                                            | Liste les spaces accessibles par le token courant            |
| `space_info`         | `space_id`                                   | Infos détaillées (notes, bank, consolidation)                |
| `space_rules`        | `space_id`                                   | Lit les rules immuables du space                             |
| `space_summary`      | `space_id`                                   | Résumé complet : rules + bank + stats (démarrage agent)      |
| `space_export`       | `space_id`                                   | Export tar.gz en base64                                      |
| `space_delete`       | `space_id`, `confirm`                        | Supprime le space (⚠️ irréversible, manage requis)          |

#### Badges de space de mission (v2.9.0)

`space_badge_mint` n'est volontairement pas une ACL générique. Seul le token
standard exact ayant créé le space peut frapper un badge pour une instance
d'agent. Le badge est limité à ce seul space et à `system_whoami`,
`live_read` et `live_note`; sa durée de vie est fixe : 24 heures. Refrapper le
même `client_name` révoque le badge précédent, et la suppression du space
révoque d'abord tous ses badges.

Le flux prévu est le suivant : `mcp-mission` détient le token créateur et
demande un badge après authentification de la mission et réservation de
l'identité runtime de l'agent ; `mcp-agent` garde le secret reçu privé et ne
l'utilise que pour le space de mission. Les badges ne peuvent appeler ni l'API
web ni la console d'administration.

### Live (3 outils)

| Outil         | Paramètres                                  | Description                                                                                                                |
| ------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `live_note`   | `space_id`, `category`, `content`, `tags?`  | Écrit une note horodatée (agent = nom du token). Catégories : observation, decision, todo, insight, question, progress, issue |
| `live_read`   | `space_id`, `limit?`, `category?`, `agent?` | Lit les notes live (filtres optionnels)                                                                                    |
| `live_search` | `space_id`, `query`, `limit?`               | Recherche full-text dans les notes                                                                                         |

### Bank (11 outils)

| Outil                       | Paramètres                        | Description                                                                                                       |
| --------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `bank_read`                 | `space_id`, `filename`            | Lit un fichier bank (supporte les sous-dossiers : `personaProfiles/acheteur.md`)                                  |
| `bank_read_all`             | `space_id`                        | Lit toute la bank en une requête (🚀 démarrage agent)                                                            |
| `bank_list`                 | `space_id`                        | Liste les fichiers bank avec chemins relatifs (sans contenu)                                                      |
| `bank_consolidate`          | `space_id`, `agent?`              | 🧠 Enfile une consolidation LLM async. Appeler une seule fois ; ne pas surveiller/poller sauf demande explicite   |
| `bank_consolidation_status` | `job_id`                          | Check de statut manuel uniquement pour un job retourné par `bank_consolidate` ou un `bank_compact` appliqué        |
| `bank_consolidation_queues` | `space_ids?`                      | Résumé read-only des files de consolidation par space                                                             |
| `bank_stale_spaces`         | `min_notes?=5`, `min_age_days?=5`, `space_ids?` | 🚨 Liste les spaces avec ≥N notes non consolidées dont la plus ancienne a ≥D jours (supervision) |
| `bank_compact`              | `space_id`, `dry_run?`            | 🔧 Scanne ou enfile une compaction LLM stricte avec contrôles UTF-8, backup, rollback et empreintes d'audit. `dry_run=True` par défaut (manage) |
| `bank_repair`               | `space_id`, `dry_run?`            | 🔧 Répare les noms de fichiers corrompus (Unicode, préfixes parasites). `dry_run=True` par défaut (manage)        |
| `bank_write`                | `space_id`, `filename`, `content` | ✏️ Écrit/remplace un fichier bank directement — contourne la consolidation LLM (manage)                          |
| `bank_delete`               | `space_id`, `filename`            | 🗑️ Supprime un fichier bank + ses doublons Unicode (manage, irréversible)                                        |

Un `bank_compact` appliqué est asynchrone : il rejoint la même file FIFO par
space que la consolidation et retourne un `job_id`. Pour chaque fichier
logique dépassant `BANK_FILE_MAX_SIZE`, des Maps bornées créent des fiches
éphémères pour des unités Markdown source complètes, puis un Reduce écrit un
digest Markdown compact et non exhaustif. Le serveur valide ce digest, remplace
toutes les unités historiques éligibles par un unique conteneur code-owned et
recompactable, et exige un candidat strictement plus petit que la source. Si le
contenu protégé rend la cible impossible, un digest sûr peut rester au-dessus de
la limite configurée et le rapport porte `target_met=false`; sinon la cible reste
obligatoire. Le contenu récent,
non daté, avec code ou HTML, ainsi que l'extérieur, reste byte-identique. En mode
daté, le digest utilise au maximum 75 % de la place restant après le contenu
protégé seulement si la cible est atteignable ; les 25 % restants constituent
une marge de croissance. En best-effort, tout le budget de réduction sûr est
utilisable.
Tous les candidats sont validés avant la création du backup complet du space.
Le contenu persisté est relu et vérifié ; un échec déclenche un rollback vérifié
de `bank/`. Si ce rollback échoue aussi, le job expose le `backup_id` nécessaire à une restauration
manuelle. Aucun nouvel objet `*.part-NNN.md` n'est créé. Les anciennes familles
multipart v2.7.x restent lisibles sans perte, puis sont réassemblées sous leur
unique nom canonique par une compaction, une consolidation ou une restauration
explicite via `bank_write`.

Depuis la v2.7.1, la consolidation valide l'intégralité du plan d'édition LLM
avant la première écriture. La bank et la synthèse (ainsi que les métadonnées
hors du mode batch normal) sont restaurées et vérifiées comme un seul lot en
cas d'échec ; les notes sources ne sont supprimées qu'après toutes les
opérations faillibles de ce lot. Les I/O finales de métadonnées et d'audit ont
lieu après les lots commités, mais ne peuvent que retourner `partial` et ne les
annulent jamais. Une suppression partielle expose les métriques vérifiées de
restauration et de perte. Le rollback d'une compaction multi-fichier ne
restaure que `bank/`, sans pouvoir
supprimer une note live concurrente. Les résultats terminaux des jobs sont
persistés pour l'audit après redémarrage ; les jobs actifs/en attente restent
dans une FIFO en mémoire.

Lorsqu'une compaction 2.8+ a légitimement absorbé un ancien heading, une
opération chirurgicale `replace_section`, `append_to_section` ou
`prepend_to_section` peut le recréer uniquement sous la forme d'un heading ATX
strict avec contenu non vide, à la fin du fichier logique existant. Un
`delete_section` déjà absent est idempotent. Cette compatibilité ne crée aucun
fichier, ne devine aucun parent Markdown, n'assouplit aucun autre contrôle du
plan et reste observable : le résultat terminal expose
`recovered_operations`, et le fichier récupéré est relu exactement avant la
suppression des notes source.

Depuis la 2.9.3, la pré-compaction automatique est un avertissement lorsqu'un
refus laisse la Bank intacte ou lorsqu'une écriture échouée est suivie d'un
rollback exact vérifié : le résultat est exposé dans `compaction` et la
consolidation normale des notes live continue. Depuis la 2.9.4,
`BANK_FILE_MAX_SIZE` est aussi une cible pour la compaction manuelle comme
automatique : un candidat sûr strictement plus petit que sa source peut
seulement rester au-dessus si le contenu protégé rend cette cible impossible ;
`target_met` rend ce résultat visible. Seuls une famille legacy split
incohérente ou un rollback de compaction non vérifié bloquent
`bank_consolidate` ; `bank_compact` reste strict sur ses contrôles d'intégrité.

> **2.8.0 prête à publier — acceptée par le propriétaire produit, non déployée :** les
> Maps bornées et le Reduce unique ont franchi les gates mécaniques sur les
> corpus réels. La comparaison a retenu `mistral-small4:119b` comme modèle de
> compactage recommandé : il préserve mieux le sens global et les points
> opérationnels importants que les modèles Qwen testés. `gpt-oss:120b` n'est
> pas supporté pour ce chemin : il termine par `finish_reason=length` avec le
> plafond Map produit de 4 000 tokens et reste plus lent et moins fidèle lors
> du rejeu R&D à 8 000 tokens. La compaction est volontairement avec perte et
> un canari manuel reste obligatoire avant la production. Voir le
> [design du compactage hiérarchique 2.8.0](DESIGN/live-mem/COMPACTION_EXTRACTIVE_V2_8.md).

### Graph (4 outils) — 🌉 Pont vers Graph Memory

| Outil              | Paramètres                                           | Description                                                                                                  |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `graph_connect`    | `space_id`, `url`, `token`, `memory_id`, `ontology?` | Connecte un space à Graph Memory. Teste la connexion, crée la mémoire si besoin. Ontologie par défaut : `general` |
| `graph_push`       | `space_id`                                           | Synchronise bank → graphe. Delete + re-ingest intelligent, nettoyage orphelins. ~30s/fichier                 |
| `graph_status`     | `space_id`                                           | Statut de connexion + stats du graphe (documents, entités, relations, top entités, liste de documents)       |
| `graph_disconnect` | `space_id`                                           | Déconnecte (les données restent dans le graphe)                                                              |

### Backup (5 outils)

| Outil             | Paramètres                 | Description                                       |
| ----------------- | -------------------------- | ------------------------------------------------- |
| `backup_create`   | `space_id`, `description?` | Crée un snapshot complet sur S3                   |
| `backup_list`     | `space_id?`                | Liste les backups disponibles                     |
| `backup_restore`  | `backup_id`                | Restaure un backup (l'espace ne doit pas exister) |
| `backup_download` | `backup_id`                | Télécharge en tar.gz base64                       |
| `backup_delete`   | `backup_id`                | Supprime un backup                                |

### Admin (8 outils)

| Outil                | Paramètres                                                        | Description                                                                                                    |
| -------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `admin_create_token` | `name`, `permissions`, `space_ids?`, `expires_in_days?`, `email?` | Crée un token (⚠️ affiché une seule fois). Permissions : read, write, manage, admin. Email optionnel pour traçabilité |
| `admin_list_tokens`  | —                                                                 | Liste les tokens actifs                                                                                        |
| `admin_revoke_token` | `token_hash`                                                      | Révoque un token (le rend inutilisable)                                                                        |
| `admin_delete_token` | `token_hash`                                                      | Supprime physiquement un token du registre (⚠️ irréversible)                                                  |
| `admin_purge_tokens` | `revoked_only?`                                                   | Purge en masse : révoqués seuls (défaut) ou tous les tokens                                                    |
| `admin_update_token` | `token_hash`, `space_ids`, `action`                               | Modifie les spaces d'un token (add/remove/set)                                                                 |
| `admin_bulk_update_tokens` | `filtres`, `delta`, `confirm?`                            | Mise à jour en masse des tokens avec filtres et opérations add/remove/set                                       |
| `admin_gc_notes`     | `space_id?`, `max_age_days?`, `confirm?`, `delete_only?`          | Garbage Collector : nettoie les notes orphelines                                                               |

---

## 🌉 Graph Bridge — Pont vers Graph Memory

> ⚠️ **Note d'architecture (v2.5.0) — Séparation des responsabilités Live Memory + Graph Memory**
>
> - **Memory Bank** (Live Memory) = bootstrap compact de session. `activeContext.md` est un instantané volatile du focus, `progress.md` est un journal récent borné. Le consolidateur réécrit et compacte continuellement ces fichiers.
> - **Graph Memory** = index sémantique durable pour des **documents canoniques stables** (RFC, incidents, runbooks, docs de design, inventaires d'infrastructure).
> - **Fichiers du dépôt** = autorité finale.
>
> **Graph Memory complète la bank, il ne la remplace pas. Graph Memory localise, les fichiers canoniques du dépôt confirment.**
>
> En conséquence, **`graph_push` n'est PAS une action de routine** : pousser la bank entière dans le graphe lui apprend du contenu transitoire qu'une compaction ultérieure laissera bloqué en état obsolète. Les flux de routine doivent ingérer **les documents canoniques du dépôt** directement dans Graph Memory côté agent/outillage, en utilisant des clés `source_path` stables. `graph_push` reste disponible pour un bootstrap unique et pour des opérations de debug/migration explicites.
>
> En particulier, `activeContext.md` et `progress.md` ne doivent **jamais** finir dans Graph Memory. Une évolution future (suivie dans [`DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md`](DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md)) en fera un garde-fou serveur. Voir [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) pour le template côté agent.

Live Memory peut pousser sa Memory Bank dans une instance [Graph Memory](https://github.com/Cloud-Temple/graph-memory) pour la mémoire long terme. Le knowledge graph extrait les entités, relations et embeddings des fichiers bank.

### Workflow

```
1. graph_connect(space_id, url, token, memory_id, ontology="general")
   └─ Teste la connexion, crée le Graph Memory si besoin

2. bank_consolidate(space_id)
   └─ Enfile une consolidation async ; appelez une seule fois et ne surveillez/pollez pas sauf demande explicite

3. graph_push(space_id)
   ├─ Liste les documents dans Graph Memory
   ├─ Pour chaque fichier bank modifié :
   │   ├─ document_delete (supprime les entités orphelines)
   │   └─ memory_ingest (recalcul complet du graphe)
   ├─ Nettoie les documents bank supprimés
   └─ Met à jour les métriques (last_push, push_count)

4. graph_status(space_id)
   └─ Stats : 79 entités, 61 relations, top entités, documents...
```

### Push intelligent (delete + re-ingest)

Chaque push est un **refresh complet** du graphe pour ce fichier. Les fichiers existants sont supprimés puis ré-ingérés pour que Graph Memory recalcule les entités, relations et embeddings avec le contenu à jour.

### Ontologies disponibles

| Ontologie           | Usage                                       |
| ------------------- | ------------------------------------------- |
| `general` (défaut)  | Polyvalente : FAQ, specs, certifications, RSE |
| `legal`             | Documents juridiques, contrats              |
| `cloud`             | Infrastructure cloud, fiches produit        |
| `managed-services`  | Services managés, infogérance               |
| `presales`          | Avant-vente, RFP/RFI, propositions          |

---

## 🖥️ Interface web

Live Memory expose une **interface web** sur `/live` pour visualiser les espaces mémoire en temps réel.

### Accès

```
http://localhost:8080/live
```

### Fonctionnalités

| Zone                                | Contenu                                                                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **📊 Dashboard** (gauche)          | Infos space, consolidation (date + compteurs), stats live/bank, agents colorés, catégories avec %, rules Markdown, Graph Memory |
| **🔴 Live Timeline** (haut-droite) | Notes live groupées par date (Aujourd'hui/Hier/date), cartes avec agent + catégorie + Markdown                                  |
| **📘 Bank Viewer** (bas-droite)    | Onglets de fichiers consolidés, rendu Markdown via marked.js                                                                    |

### Layout

```
┌──────────────┬────────────────────────────┐
│  📊 Dashboard│  🔴 Live Timeline          │
│  (infos,     │  (auto-refresh, groupé date)│
│   agents,    ├────────────────────────────┤
│   rules...)  │  📘 Bank (onglets Markdown)│
└──────────────┴────────────────────────────┘
```

### Auto-refresh intelligent

- Configurable : 3s / 5s / 10s / 30s / manuel
- **Anti-flicker** : ne re-render le DOM que si les données ont changé
- Point vert pulsant avec timestamp du dernier refresh
- Sélection d'un space → chargement immédiat (pas de bouton à cliquer)

### API REST (5 endpoints)

| Endpoint                        | Description                                              |
| ------------------------------- | -------------------------------------------------------- |
| `GET /api/spaces`               | Liste des spaces                                         |
| `GET /api/space/{id}`           | Infos complètes (meta + rules + stats + graph-memory)    |
| `GET /api/live/{id}`            | Notes live (filtres : `?agent=`, `?category=`, `?limit=`) |
| `GET /api/bank/{id}`            | Liste des fichiers bank                                  |
| `GET /api/bank/{id}/{filename}` | Contenu d'un fichier bank                                |

Les endpoints `/api/*` nécessitent un Bearer Token standard. Les badges de
mission sont réservés à MCP et refusés, y compris par `/api/login`. La page
`/live` et les fichiers `/static/*` sont publics.

### Console d'administration (`/admin`)

Une **console d'administration** complète est disponible sur `/admin`, exposant les 44 outils MCP via une interface web :

```
http://localhost:8080/admin
```

| Section | Fonctionnalités |
| --- | --- |
| **📊 Dashboard** | Statut de santé (cliquable → détails service), nombre de spaces, tokens actifs, version/uptime, barre d'identité |
| **📂 Spaces** | CRUD, modales info/rules, lien explorer, suppression avec confirmation |
| **🔑 Tokens** | Création/mise à jour/révocation/suppression, chips de spaces visuels avec calcul de delta |
| **🔍 Explorer** | Notes live + fichiers bank côte à côte pour n'importe quel space |
| **💾 Backups** | Création/restauration/suppression, « Backup All », colonnes dynamiques |
| **🌉 Graph Bridge** | Check de statut, push, déconnexion par space |
| **🧹 Maintenance** | Consolider, compacter, réparer, GC, purger — sélecteur de space unique, liste d'actions compacte |

- **Auth** : nécessite un token valide (comme `/live`), session via cookie HttpOnly
- **Compatible CSP** : zéro handler inline, tout via `data-action` + délégation d'événements
- **Upload Rules** : file picker (`.md`) ou paste direct depuis la modale Rules

---

## 🔌 Intégration MCP

> 📖 **Guide complet** : voir [`CLINE_INTEGRATION_GUIDE.fr.md`](CLINE_INTEGRATION_GUIDE.fr.md) pour le guide pas à pas (configuration Cline, custom instructions, workflow, multi-agents, troubleshooting). Des guides équivalents existent pour [`CLAUDE_CODE_INTEGRATION.fr.md`](CLAUDE_CODE_INTEGRATION.fr.md) et [`CODEX_INTEGRATION.fr.md`](CODEX_INTEGRATION.fr.md).

### Avec Cline (VS Code / VSCodium)

Dans les paramètres MCP de Cline (`cline_mcp_settings.json`) :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN"
      }
    }
  }
}
```

Pour configurer les **Custom Instructions** de votre agent, copiez l'un des deux templates de règles workspace dans vos Custom Instructions globales Cline (ou dans un dossier `.clinerules/` à la racine du projet) :

| Template                                                                | Quand l'utiliser                                                                                            |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md)                  | Workspaces avec **Live Memory uniquement**.                                                                 |
| [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md)  | Workspaces également connectés à **Graph Memory** (politique Graph-first, discipline de compaction, ingestion côté agent). |

Personnalisez quelques placeholders (`{LIVE_MCP_SERVER}`, `{SPACE}`, et pour le template avancé `{GRAPH_MCP_SERVER}` / `{GRAPH_MEMORY_ID}`). Le nom d'agent est **auto-détecté** depuis le token d'authentification — rien d'autre à configurer.

> 💡 **Templates prêts à l'emploi** : [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md) (Live seul) et [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) (Live + Graph) — copier et personnaliser les placeholders.
>
> 📖 **Guides d'intégration détaillés** : [`CLINE_INTEGRATION_GUIDE.fr.md`](CLINE_INTEGRATION_GUIDE.fr.md), [`CLAUDE_CODE_INTEGRATION.fr.md`](CLAUDE_CODE_INTEGRATION.fr.md), [`CODEX_INTEGRATION.fr.md`](CODEX_INTEGRATION.fr.md).

### Avec Claude Desktop

Dans `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN"
      }
    }
  }
}
```

### Via Python (client MCP)

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def example():
    headers = {"Authorization": "Bearer your_token"}
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
                "content": "Build qui passe en CI"
            })
```

---

## 💻 CLI et shell

### Installation de la CLI

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

Script de tests unifié avec **4 suites sélectionnables** via `--suite` :

```bash
docker compose up -d   # Prérequis

# Toutes les suites (44 tests, ~60s)
python scripts/test_recette.py --url http://localhost:8080

# Une seule suite
python scripts/test_recette.py --suite recette     # Pipeline agent (7 tests)
python scripts/test_recette.py --suite isolation    # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite      # Outils MCP (19 tests)

# Suite Graph Memory (optionnelle, nécessite un graph-memory démarré)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token votre_token

# Lister les suites disponibles
python scripts/test_recette.py --list

# Pas à pas + verbose
python scripts/test_recette.py --suite isolation -v --step --no-cleanup
```

| Suite       | Tests | Description                                                                              |
| ----------- | ----- | ---------------------------------------------------------------------------------------- |
| `recette`   | 7     | Pipeline complet : token → notes → consolidation LLM → bank                              |
| `isolation` | 18    | Isolation multi-tenant v0.7.1 : accès cross-space, filtrage backup, ajout auto au token  |
| `qualite`   | 19    | Test des 35 outils MCP : system, admin, space, live, bank, backup, GC                    |
| `graph`     | ~8    | Pont Graph Memory : connect, push, status, disconnect (optionnel)                        |

---

## 🔒 Sécurité

### Authentification

- **Bearer Token** obligatoire sur toutes les requêtes MCP
- **Clé bootstrap** pour créer le premier token admin
- **Tokens SHA-256** stockés sur S3 (jamais en clair)
- **3 niveaux** : read, write, admin
- **Portée par space** : un token peut être limité à des spaces précis
- **Badge de mission** : aucune permission générale ; un seul space de mission
  et seulement `system_whoami` et les opérations MCP live en lecture/écriture.
  Refusé par l'API web et la console d'administration.

### WAF (Caddy + Coraza)

- **OWASP CRS** : injection SQL/XSS, path traversal, SSRF
- **Rate Limiting** : 200 MCP/min (Streamable HTTP)
- **TLS automatique** : Let's Encrypt en production (`SITE_ADDRESS=domaine.com`)
- **Conteneur non-root** : utilisateur `mcp`

---

## 📂 Structure du projet

```
live-memory/
├── src/live_mem/              # Code source (44 outils MCP + interface web)
│   ├── server.py              # Serveur FastMCP + middlewares
│   ├── config.py              # Configuration pydantic-settings
│   ├── auth/                  # Authentification
│   │   ├── middleware.py      #   Auth + Logging + StaticFiles
│   │   └── context.py         #   check_access, check_write, check_admin
│   ├── static/                # Interface web /live
│   │   ├── live.html          #   SPA (Dashboard + Live + Bank)
│   │   ├── css/live.css       #   Styles (thème Cloud Temple)
│   │   ├── js/                #   7 modules JS (config, api, app, dashboard, timeline, bank, sidebar)
│   │   └── img/               #   Logo SVG Cloud Temple
│   ├── core/                  # Services métier
│   │   ├── storage.py         #   S3 dual SigV2/SigV4 (Dell ECS)
│   │   ├── space.py           #   CRUD des espaces mémoire
│   │   ├── live.py            #   Notes live (append-only)
│   │   ├── consolidator.py    #   Pipeline LLM (4 étapes)
│   │   ├── graph_bridge.py    #   🌉 Pont vers Graph Memory
│   │   ├── tokens.py          #   Gestion des tokens SHA-256
│   │   ├── backup.py          #   Snapshots S3
│   │   ├── gc.py              #   Garbage Collector
│   │   ├── locks.py           #   Locks asyncio par space
│   │   └── models.py          #   Modèles Pydantic
│   └── tools/                 # Outils MCP (7 modules)
│       ├── system.py          #   3 outils (health, whoami, about)
│       ├── space.py           #   10 outils (CRUD spaces + badge mission)
│       ├── live.py            #   3 outils (notes)
│       ├── bank.py            #   11 outils (bank + consolidation + supervision + maintenance)
│       ├── graph.py           #   4 outils (Graph Bridge)
│       ├── backup.py          #   5 outils (snapshots)
│       └── admin.py           #   8 outils (tokens + GC + purge + bulk)
├── scripts/                   # CLI + Shell + Tests
├── waf/                       # Caddy + Coraza WAF
├── WORKSPACE_CLINE_RULES.md           # 📋 Template Custom Instructions Cline — Live Memory uniquement
├── WORKSPACE_CLINE_ADVANCE_RULES.md   # 📋 Template Custom Instructions Cline — Live Memory + Graph Memory
├── RULES/                     # 📜 Modèles de rules Memory Bank (général, livre, médical, avant-vente, product management, pilotage d'entreprise)
├── DESIGN/live-mem/           # 9 documents d'architecture
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml             # Dépendances et config projet (uv)
├── uv.lock                    # lockfile uv
├── VERSION                    # 2.9.4
├── CHANGELOG.md
└── FAQ.md
```

---

## 🔍 Troubleshooting

### Le service ne démarre pas

```bash
docker compose logs live-mem-service --tail 50
docker compose logs waf --tail 20
```

### 401 Unauthorized

- Vérifiez votre token : `Authorization: Bearer VOTRE_TOKEN`
- La clé bootstrap n'est pas un token — créez d'abord un token via `admin_create_token`

### La consolidation échoue

- Vérifiez les credentials LLMaaS dans `.env`
- Le timeout par défaut est de 1800s (30 minutes) pour accepter les modèles de consolidation plus lents mais plus qualitatifs
- `bank_consolidate` retourne un accusé de job async (`running` ou `queued`) avec `next_action="return_to_user_without_polling"` ; appelez-le une seule fois et ne surveillez/pollez pas sauf demande explicite
- `bank_consolidation_status(job_id)` reste disponible pour des checks de statut manuels uniquement

---

## 🤝 Contribuer

Le développement se pilote **entièrement via GitHub** — issues, branches, pull
requests, revues de code et statut projet y vivent tous. Cela rend le projet
facile à **piloter à distance depuis le terminal** avec la CLI `gh` (y compris
par des agents IA de code) : créer une issue, brancher, ouvrir une PR, relire
et merger sans jamais quitter la ligne de commande ou l'interface GitHub.

Le workflow complet et obligatoire est documenté dans
**[`WORKSPACE_WORKFLOW_GIT.md`](WORKSPACE_WORKFLOW_GIT.md)** :

- **Branche + PR uniquement** — aucun merge local dans `main` ; chaque
  changement arrive via une pull request mergée sur GitHub.
- **Cycle de vie de l'issue** — auto-assignation, passage du statut Projects à
  *In Progress*, discussion de conception conservée dans l'issue.
- **Lien PR ↔ issue** — un mot-clé `Closes #N` dans le **corps** de la PR
  ferme l'issue automatiquement au merge.
- **Revues dans le canal PR** — dès qu'une PR est ouverte, la discussion de
  revue passe dans la PR ; toute conclusion de revue est publiée sur GitHub
  (`gh pr review` / `gh pr comment`), pas seulement en chat.

Suivre ce fichier garde les historiques d'issues et de PR propres et
auditables, et permet à un contributeur (ou un agent) de dérouler tout le
cycle de façon reproductible via `gh`.

---

## 🔗 Projets liés

| Projet           | Description                                | Lien                                                                                  |
| ---------------- | ------------------------------------------ | ------------------------------------------------------------------------------------- |
| **graph-memory** | Mémoire long terme (Knowledge Graph + RAG) | [github.com/Cloud-Temple/graph-memory](https://github.com/Cloud-Temple/graph-memory)  |

---

## 📄 Licence

Apache License 2.0

---

## 👤 Auteur

**Cloud Temple** — [cloud-temple.com](https://www.cloud-temple.com)

Développé par **Christophe Lesur**.

---

*Live Memory v2.9.4 — Mémoire de travail partagée pour agents IA collaboratifs*
