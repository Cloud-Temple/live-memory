# 🔌 Guide d'intégration Live Memory avec Claude Code

> **Version** : 1.0.0 | **Date** : 2026-05-16

Ce guide détaille pas à pas comment connecter **Claude Code** (le CLI d'Anthropic, ou son extension IDE) à **Live Memory** pour lui donner une mémoire de travail partagée et persistante.

---

## 📋 Table des matières

- [Prérequis](#-prérequis)
- [Étape 1 — Démarrer Live Memory](#-étape-1--démarrer-live-memory)
- [Étape 2 — Créer un token pour Claude Code](#-étape-2--créer-un-token-pour-claude-code)
- [Étape 3 — Connecter Claude Code à Live Memory](#-étape-3--connecter-claude-code-à-live-memory)
- [Étape 4 — Créer un espace mémoire](#-étape-4--créer-un-espace-mémoire)
- [Étape 5 — Donner ses instructions à Claude Code](#-étape-5--donner-ses-instructions-à-claude-code)
- [Workflow recommandé](#-workflow-recommandé)
- [Multi-agent : Claude Code + Cline + Claude Desktop + autres](#-multi-agent--claude-code--cline--claude-desktop--autres)
- [Troubleshooting](#-troubleshooting)
- [Avec Claude Desktop](#-avec-claude-desktop)
- [Récapitulatif](#-récapitulatif)

---

## 📦 Prérequis

| Composant            | Version            | Vérification                        |
| -------------------- | ------------------ | ----------------------------------- |
| **Docker**           | ≥ 24.0             | `docker --version`                  |
| **Docker Compose**   | v2                 | `docker compose version`            |
| **Claude Code**      | ≥ 2.1              | `claude --version`                  |
| **Live Memory**      | Déployé et démarré | `curl http://localhost:8080/health` |

> 💡 Si Claude Code n'est pas installé : `npm install -g @anthropic-ai/claude-code` (macOS/Linux/Windows) ou utilisez l'installateur dédié — voir la documentation officielle Anthropic. Claude Code fournit la commande `claude` dans le terminal et propose des extensions IDE (VS Code, JetBrains) qui partagent la même configuration.

---

## 🚀 Étape 1 — Démarrer Live Memory

Si Live Memory n'est pas encore démarré :

```bash
cd /chemin/vers/live-memory
cp .env.example .env
# Éditer .env avec vos credentials S3, LLMaaS et ADMIN_BOOTSTRAP_KEY
docker compose build
docker compose up -d
```

**Vérification** :

```bash
# Doit retourner {"status": "ok", ...}
curl -s http://localhost:8080/health | jq .
```

---

## 🔑 Étape 2 — Créer un token pour Claude Code

Claude Code a besoin d'un **Bearer Token** avec les permissions `read,write` pour lire et écrire dans la mémoire.

### Option A — Via la CLI

```bash
cd /chemin/vers/live-memory
export MCP_TOKEN=<votre_ADMIN_BOOTSTRAP_KEY>

# Créer un token « read,write » pour Claude Code
python scripts/mcp_cli.py token create claude-code-agent read,write
```

La CLI affichera quelque chose comme :

```
Token created successfully!
  Name   : claude-code-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  This token will NEVER be displayed again. Copy it now!
```

> **⚠️ IMPORTANT** : copiez ce token immédiatement ! Il ne sera plus jamais affiché (seul le hash SHA-256 est stocké).

### Option B — Via la clé bootstrap (temporaire)

Pour un test rapide, vous pouvez utiliser directement l'`ADMIN_BOOTSTRAP_KEY` définie dans votre `.env`. Mais **en production**, créez toujours un token dédié avec des permissions minimales.

---

## ⚙️ Étape 3 — Connecter Claude Code à Live Memory

Claude Code stocke sa configuration MCP dans un fichier JSON. Trois portées sont disponibles :

| Portée    | Emplacement                                    | Portée effective                   |
| --------- | ---------------------------------------------- | ---------------------------------- |
| `local`   | `~/.claude.json` (clé `projects.<cwd>`)        | Répertoire courant uniquement      |
| `user`    | `~/.claude.json` (clé `mcpServers` au top)     | Tous les projets de l'utilisateur  |
| `project` | `.mcp.json` à la racine du projet              | Commitée au repo (équipes)         |

Pour un usage personnel multi-projets, la portée `user` est généralement la plus pratique.

### 3.1 — Méthode CLI (recommandée)

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  https://votre-serveur/mcp \
  --header "Authorization: Bearer lm_YOUR_TOKEN_HERE"
```

Pour un serveur local en HTTP :

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  http://localhost:8080/mcp \
  --header "Authorization: Bearer lm_YOUR_TOKEN_HERE"
```

### 3.2 — Édition manuelle

Si vous préférez éditer le JSON directement, ajoutez le bloc suivant à `~/.claude.json` (portée `user`, sous la clé `mcpServers` au top) :

```json
{
  "mcpServers": {
    "live-memory": {
      "type": "http",
      "url": "https://votre-serveur/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

> **Remplacez** `lm_YOUR_TOKEN_HERE` par le token de l'étape 2 et `votre-serveur` par votre domaine (ou `localhost:8080` en local).

Pour la portée `project` (config partagée avec l'équipe), créez un fichier `.mcp.json` à la racine du projet avec le même format.

### 3.3 — Vérifier la connexion

Après configuration :

```bash
claude mcp list
```

Vous devriez voir `live-memory` avec un statut connecté. Lancez ensuite Claude Code dans un projet et demandez :

> *« Appelle `system_health` sur live-memory et montre-moi la réponse. »*

Si Claude répond avec `{"status": "ok", ...}`, la connexion fonctionne.

### 3.4 — Whitelister les outils (éviter les prompts de permission)

Claude Code demande confirmation à chaque appel d'outil MCP non autorisé. Pour éviter ces interruptions, ajoutez les outils Live Memory à l'allow-list du projet (ou de l'utilisateur).

Créez ou éditez `.claude/settings.local.json` à la racine du projet :

```json
{
  "permissions": {
    "allow": [
      "mcp__live-memory__space_list",
      "mcp__live-memory__space_info",
      "mcp__live-memory__space_rules",
      "mcp__live-memory__bank_read_all",
      "mcp__live-memory__bank_read",
      "mcp__live-memory__live_read",
      "mcp__live-memory__live_note",
      "mcp__live-memory__live_search",
      "mcp__live-memory__bank_consolidate",
      "mcp__live-memory__system_health"
    ]
  }
}
```

> 💡 **Convention de nommage** : Claude Code expose chaque outil MCP sous la forme `mcp__<nom-serveur>__<nom-outil>`. Si vous avez nommé votre serveur `live-memory-prod` à l'étape 3.1, ajustez le préfixe en conséquence.

Alternative interactive : tapez `/permissions` dans une session Claude Code pour ouvrir l'éditeur de permissions.

Pour une configuration globale (tous projets), utilisez `~/.claude/settings.json` à la place.

### 3.5 — Serveur HTTPS distant

Pour un déploiement en production, l'URL et le bloc JSON sont identiques — seul le schéma change (`https://` au lieu de `http://`). Aucune option supplémentaire requise côté Claude Code.

---

## 📁 Étape 4 — Créer un espace mémoire

Avant que Claude Code puisse écrire des notes, il vous faut un **espace mémoire** avec des **rules** qui définissent la structure de la Memory Bank.

### Via la CLI

```bash
python scripts/mcp_cli.py space create mon-projet \
  --rules-file ./RULES/standard.memory.bank.md \
  -d "Mon projet de développement"
```

Plusieurs templates de rules sont fournis dans le dossier `RULES/` du repo :

| Template                                  | Cas d'usage                                           |
| ----------------------------------------- | ----------------------------------------------------- |
| `RULES/standard.memory.bank.md`           | Memory Bank Cline classique (6 fichiers projet)       |
| `RULES/product.management.memory.bank.md` | Équipe produit (vision, portfolio, personas, features) |
| `RULES/medical.memory.bank.md`            | Suivi patient / dossier clinique                      |
| `RULES/presales.memory.bank.md`           | Avant-vente, qualification de prospect, RFP           |
| `RULES/book.memory.bank.md`               | Écriture de livre / projet éditorial                  |
| `RULES/live-mem.standard.memory.bank.md`  | Développement du serveur Live Memory lui-même         |

### Via Claude Code directement

Vous pouvez aussi demander à Claude de créer l'espace. Dites-lui simplement :

> *« Utilise l'outil `space_create` pour créer un space `mon-projet` avec les rules standards Memory Bank (projectbrief, activeContext, progress, techContext, systemPatterns, productContext). »*

Claude Code invoquera l'outil MCP `space_create`.

### Exemple de rules standards

```markdown
# Memory Bank Rules

## Fichiers à maintenir

### projectbrief.md
Vision, objectifs, périmètre du projet.

### activeContext.md
Focus courant, travail en cours, décisions récentes, prochaines étapes.

### progress.md
Ce qui marche, ce qui reste à faire, problèmes connus.

### techContext.md
Technologies utilisées, configuration, contraintes techniques.

### systemPatterns.md
Architecture, patterns, décisions techniques, composants.

### productContext.md
Pourquoi ce projet existe, problèmes résolus, expérience utilisateur.
```

---

## 📝 Étape 5 — Donner ses instructions à Claude Code

> 🔭 **Workspace également connecté à Graph Memory ?** Si le même workspace utilise à la fois Live Memory **et** un serveur MCP Graph Memory (index sémantique durable pour incidents, RFC, runbooks, rappel cross-documents), partez du template avancé [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md) plutôt que du bloc standard ci-dessous pour votre `CLAUDE.md`. Il ajoute la politique Graph-first, la discipline de compaction de la bank et l'ingestion explicite côté agent. **Invariants** (valables quel que soit l'agent) : le consolidateur Live Memory ne pousse jamais rien dans Graph Memory ; l'ingestion Graph reste une action agent explicite et scopée, à partir des fichiers canoniques du dépôt ; ne jamais mettre de tokens ni d'endpoints dans les règles.

Claude Code lit automatiquement les fichiers `CLAUDE.md` au démarrage. Deux emplacements possibles :

| Emplacement                | Portée                                              | Recommandé pour                       |
| -------------------------- | --------------------------------------------------- | ------------------------------------- |
| `<racine-projet>/CLAUDE.md` | Le projet courant (committé avec le repo)          | Workflow spécifique au projet         |
| `~/.claude/CLAUDE.md`      | Tous les projets de l'utilisateur courant (privé)   | Préférences globales, identité, style |

Pour Live Memory, le `CLAUDE.md` au niveau projet est l'emplacement idéal car `{SPACE}` est spécifique au projet.

### Template recommandé (à coller dans `CLAUDE.md`)

Ce template utilise le placeholder `{SPACE}` — vous n'avez qu'**une seule valeur** à configurer :

```markdown
# Memory Bank — Live Memory MCP

Ma mémoire se réinitialise complètement entre les sessions. Je dépends ENTIÈREMENT de la Memory Bank pour comprendre le projet et continuer efficacement.

## 🔌 Configuration (à personnaliser par projet)

Ma mémoire persistante est gérée par le serveur MCP **Live Memory** (`live-memory`).

> **⚙️ La seule valeur à personnaliser :**
>
> - **SPACE** = `mon-projet`       ← Remplacez par votre space_id
>
> Toutes les instructions ci-dessous utilisent `{SPACE}` — je le remplace automatiquement par la valeur ci-dessus.
> Le nom d'agent est **auto-détecté** depuis le token d'authentification (aucune configuration nécessaire).

## 📖 Au début de CHAQUE tâche (OBLIGATOIRE)

1. Appeler `space_rules("{SPACE}")` pour lire les rules (structure de la bank)
2. Appeler `bank_read_all("{SPACE}")` pour charger TOUT le contexte consolidé
3. Appeler `live_read(space_id="{SPACE}")` pour lire les **notes non consolidées**
4. Lire attentivement le contenu avant de commencer
5. Identifier le focus courant dans `activeContext.md`

> ⚠️ NE JAMAIS commencer à travailler sans avoir lu la bank.
>
> 💡 **Pourquoi lire les notes live ?** Entre les sessions, des notes peuvent avoir été écrites (par moi ou par d'autres agents) sans avoir été consolidées. Ces notes contiennent du contexte récent qui n'apparaît pas encore dans les fichiers bank. Les ignorer = risque de refaire un travail déjà fait ou de manquer une décision récente.

## 📝 Pendant le travail

Écrire des notes atomiques fréquentes via `live_note` :

    live_note(space_id="{SPACE}", category="<catégorie>", content="...")

Le paramètre `agent` est **auto-détecté** depuis le token — pas besoin de le passer.

**Catégories** :
- `observation` — constats factuels, résultats de commandes
- `decision` — choix techniques et leur justification
- `progress` — avancement, travail terminé
- `issue` — problèmes rencontrés, bugs
- `todo` — tâches identifiées à faire
- `insight` — apprentissages, patterns découverts
- `question` — points à clarifier, décisions en attente

## 🧠 En fin de session (ou après un bloc de travail significatif)

    bank_consolidate(space_id="{SPACE}")

Le LLM va consolider **mes propres notes** (agent auto-détecté depuis le token) en mettant à jour les fichiers bank selon les rules du space.

> ℹ️ Seul un admin peut consolider les notes de tous les agents (`agent=""`).
>
> 🔕 `bank_consolidate` est **fire-and-forget** : il retourne un accusé async (`running` / `queued`) avec `next_action="return_to_user_without_polling"`. **Appelez-le une seule fois et rendez la main à l'utilisateur.** Ne surveillez pas et ne pollez pas. `bank_consolidation_status(job_id)` existe uniquement pour des **checks manuels explicites**.

## ⚠️ Règles strictes

1. **NE JAMAIS écrire directement dans la bank** — seule la consolidation LLM le fait
2. **Toujours passer `space_id="{SPACE}"`** dans chaque appel
3. **Écrire des notes atomiques après chaque étape significative** — 1 note = 1 fait, 1 décision, ou 1 tâche
4. **Consolider en fin de session** — appelez `bank_consolidate` une seule fois et rendez la main à l'utilisateur sans poller (pas de boucle automatique sur `bank_consolidation_status`)
5. **Lire la bank au démarrage** — ne jamais travailler sans contexte

## 🔄 Quand demander une mise à jour

Si l'utilisateur dit **« update memory bank »** :
1. Écrire des notes `live_note` résumant l'état actuel du travail
2. Appeler `bank_consolidate(space_id="{SPACE}")`
3. Vérifier le résultat avec `bank_read_all("{SPACE}")`

## 📊 Commandes utiles

| Action                          | Commande                                                                  |
| ------------------------------- | ------------------------------------------------------------------------- |
| Lire le contexte complet        | `bank_read_all("{SPACE}")`                                                |
| Lire les rules                  | `space_rules("{SPACE}")`                                                  |
| Écrire une note                 | `live_note(space_id="{SPACE}", category="...", content="...")`            |
| Consolider                      | `bank_consolidate(space_id="{SPACE}")`                                    |
| Voir les notes récentes         | `live_read(space_id="{SPACE}")`                                           |
| Voir les notes d'un autre agent | `live_read(space_id="{SPACE}", agent="autre-agent")`                      |
| Infos space                     | `space_info("{SPACE}")`                                                   |
```

> 💡 **Pour un nouveau projet** : copiez ce fichier dans `<racine-projet>/CLAUDE.md`, changez la ligne `SPACE`, et c'est tout !

### Version minimaliste (`~/.claude/CLAUDE.md` global)

Si vous préférez ne pas committer les instructions Live Memory dans chaque projet, ajoutez ce court bloc à `~/.claude/CLAUDE.md` :

```
Vous avez accès à Live Memory (serveur MCP « live-memory »).
- Au démarrage : space_rules("{SPACE}"), bank_read_all("{SPACE}"), live_read("{SPACE}")
- Pendant le travail : live_note(space_id="{SPACE}", category="...", content="...")
- En fin de session : bank_consolidate(space_id="{SPACE}") — appeler une seule fois et rendre la main sans poller
`{SPACE}` est défini dans le CLAUDE.md du projet courant. L'agent est auto-détecté depuis le token.
```

Chaque projet déclare alors uniquement sa valeur `{SPACE}` dans son propre `CLAUDE.md`.

---

## 🔄 Workflow recommandé

### Workflow type d'une session de développement

```
┌────────────────────────────────────────────────┐
│  1. DÉMARRAGE                                  │
│     space_rules("mon-projet")                  │
│     bank_read_all("mon-projet")                │
│     live_read("mon-projet")                    │
│     → Claude lit rules + bank + notes live     │
├────────────────────────────────────────────────┤
│  2. TRAVAIL (boucle)                           │
│     • Claude code, analyse, répond             │
│     • live_note("observation", "Build OK")     │
│     • live_note("decision", "On part sur X")   │
│     • live_note("todo", "Tests à écrire")      │
│     • live_note("progress", "Auth terminée")   │
├────────────────────────────────────────────────┤
│  3. FIN DE SESSION                             │
│     bank_consolidate("mon-projet")             │
│     → Le LLM synthétise les notes dans la bank │
│     → Les notes live sont supprimées si OK     │
└────────────────────────────────────────────────┘
```

### Fréquence de consolidation

| Situation                   | Recommandation                       |
| --------------------------- | ------------------------------------ |
| Session courte (< 10 notes) | Consolider en fin de session         |
| Session longue (> 20 notes) | Consolider toutes les 15–20 notes    |
| Changement de contexte      | Consolider avant de changer de sujet |
| Fin de journée              | Toujours consolider                  |

### Visualisation en temps réel

Pendant que Claude Code travaille, ouvrez l'interface web pour suivre en direct :

```
http://localhost:8080/live
```

Les notes apparaîtront en temps réel dans la **Live Timeline** et la **Bank** se mettra à jour après chaque consolidation.

---

## 👥 Multi-agent : Claude Code + Cline + Claude Desktop + autres

Live Memory permet à **plusieurs agents** de collaborer sur le même espace mémoire.

### Scénario : Claude Code (dev) + Cline (review) + Claude Desktop (synthèse)

Pour que plusieurs agents collaborent, créez **un token par identité** :

1. `admin_create_token name="claude-code-dev"`
2. `admin_create_token name="cline-review"`
3. `admin_create_token name="claude-desktop-synth"`
4. Configurer chaque agent avec son propre token

L'identité de l'agent est **automatiquement dérivée de son token** chaque fois qu'il appelle `live_note` ou `bank_consolidate`. Aucun paramètre `agent` à passer.

### Communication inter-agents

Les agents ne se parlent pas directement. Ils communiquent **via l'espace partagé** :

```
Claude Code   → live_note(category="question", content="Faut-il supporter le CSV ?")
Cline         → live_read(category="question")   ← voit la question
Cline         → live_note(category="decision", content="Non, JSON uniquement")
Claude Code   → live_read(category="decision")   ← voit la réponse
```

### Consolidation par agent

Chaque agent consolide **ses propres notes** sans interférer avec les autres. Si un agent a des droits **admin**, il peut consolider les notes de tous les agents en appelant `bank_consolidate` (qui, pour un admin, traite tout le monde par défaut).

---

## 🔍 Troubleshooting

### `claude mcp list` n'affiche pas live-memory

1. Vérifiez que le serveur est lancé : `curl http://localhost:8080/health`
2. Vérifiez la syntaxe JSON dans `~/.claude.json` (pas de virgule traînante, accolades fermées)
3. Quittez complètement Claude Code et relancez — le fichier n'est lu qu'au démarrage
4. Inspectez les logs : `claude --debug` puis lancez une session courte

### Erreur « 401 Unauthorized »

- Le token est incorrect, expiré ou révoqué
- Vérifiez que le header est bien `"Authorization": "Bearer lm_..."` (avec le préfixe `lm_`)
- Attention aux espaces ou retours à la ligne parasites lors du copier-coller du token
- La clé bootstrap fonctionne pour les tests, mais créez un vrai token pour un usage normal

### Erreur « Access denied to space »

Le token est restreint à certains spaces (`space_ids`). Soit :
- Créez un token sans restriction de space (paramètre `space_ids` vide)
- Soit ajoutez le space au token : `admin_update_token(token_hash, space_ids="mon-projet", action="add")`

### Claude Code demande une permission à chaque appel

Whitelistez les outils via `.claude/settings.local.json` (voir Étape 3.4), ou tapez `/permissions` en session pour les ajouter interactivement.

### Claude Code n'utilise pas Live Memory tout seul

Sans un `CLAUDE.md` explicite, Claude Code ne sait pas qu'il doit appeler ces outils au démarrage d'une session. Ajoutez le template de l'étape 5 dans `<racine-projet>/CLAUDE.md` ou `~/.claude/CLAUDE.md`.

### MCP ne se connecte pas derrière un VPN ou un proxy

Si Live Memory est sur un serveur distant, vérifiez que :
- Le port 443 (HTTPS) ou 8080 (HTTP) est accessible
- L'URL dans la config Claude Code est correcte (avec `/mcp` à la fin)
- Test manuel : `curl -H "Authorization: Bearer lm_..." https://votre-serveur/mcp`

### Suivre une consolidation en cours

Côté serveur, suivez les logs :

```bash
docker compose logs -f live-mem-service --tail 20
```

Claude Code maintient la connexion HTTP ouverte pendant tout l'appel, donc une consolidation longue ne provoque généralement pas de timeout côté client.

---

## 🖥️ Avec Claude Desktop

La configuration est similaire à Claude Code, mais le fichier change. Éditez `claude_desktop_config.json` :

| OS          | Emplacement                                                       |
| ----------- | ----------------------------------------------------------------- |
| **macOS**   | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json`                     |
| **Linux**   | `~/.config/Claude/claude_desktop_config.json`                     |

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      },
      "timeout": 600
    }
  }
}
```

> **⚠️ Pour Claude Desktop** : ajoutez `"timeout": 600` pour autoriser les consolidations longues. Claude Code n'a pas besoin de ce paramètre.

Redémarrez Claude Desktop après la modification. Les outils Live Memory apparaîtront dans la liste des outils disponibles.

> ℹ️ **Note** : Claude Desktop ne propose pas de système d'allow-list par outil (contrairement à Claude Code). Les permissions sont gérées au niveau application.

---

## 📊 Récapitulatif

| Étape     | Action                                                  | Temps      |
| --------- | ------------------------------------------------------- | ---------- |
| 1         | Démarrer Live Memory (`docker compose up -d`)           | 1 min      |
| 2         | Créer un token (`mcp_cli.py token create`)              | 30 sec     |
| 3         | Configurer Claude Code (`claude mcp add`)               | 1 min      |
| 3.4       | Whitelister les outils (`.claude/settings.local.json`)  | 1 min      |
| 4         | Créer un space (`space_create`)                         | 30 sec     |
| 5         | Ajouter le `CLAUDE.md` du projet                        | 2 min      |
| **Total** | **Prêt à l'emploi**                                     | **~6 min** |

---

*Guide d'intégration Live Memory ↔ Claude Code v1.0.0 — [Documentation complète](README.fr.md)*
