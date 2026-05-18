# 🔌 Guide d'intégration Live Memory avec Claude Code

> **Version** : 1.0.0 | **Date** : 2026-05-16

Ce guide détaille pas à pas comment connecter **Claude Code** (le CLI d'Anthropic, ou son extension IDE) à **Live Memory** pour lui donner une mémoire de travail partagée et persistante.

---

## 📋 Table des matières

- [Prérequis](#-prérequis)
- [Étape 1 — Démarrer Live Memory](#-étape-1--démarrer-live-memory)
- [Étape 2 — Créer un token pour Claude Code](#-étape-2--créer-un-token-pour-claude-code)
- [Étape 3 — Brancher Claude Code sur Live Memory](#-étape-3--brancher-claude-code-sur-live-memory)
- [Étape 4 — Créer un espace mémoire](#-étape-4--créer-un-espace-mémoire)
- [Étape 5 — Donner des instructions à Claude Code](#-étape-5--donner-des-instructions-à-claude-code)
- [Workflow recommandé](#-workflow-recommandé)
- [Multi-agents : Claude Code + Cline + Claude Desktop + autres](#-multi-agents--claude-code--cline--claude-desktop--autres)
- [Dépannage](#-dépannage)
- [Avec Claude Desktop](#-avec-claude-desktop)
- [Récapitulatif](#-récapitulatif)

---

## 📦 Prérequis

| Composant            | Version            | Vérification                        |
| -------------------- | ------------------ | ----------------------------------- |
| **Docker**           | ≥ 24.0             | `docker --version`                  |
| **Docker Compose**   | v2                 | `docker compose version`            |
| **Claude Code**      | ≥ 2.1              | `claude --version`                  |
| **Live Memory**      | Déployé et running | `curl http://localhost:8080/health` |

> 💡 Si Claude Code n'est pas installé : `npm install -g @anthropic-ai/claude-code` (macOS/Linux/Windows) ou via l'installateur dédié — voir la documentation officielle Anthropic. Claude Code expose la commande `claude` dans le terminal et propose des extensions IDE (VS Code, JetBrains) qui partagent la même configuration.

---

## 🚀 Étape 1 — Démarrer Live Memory

Si Live Memory n'est pas encore démarré :

```bash
cd /chemin/vers/live-memory
cp .env.example .env
# Éditer .env avec vos credentials S3, LLMaaS, et ADMIN_BOOTSTRAP_KEY
docker compose build
docker compose up -d
```

**Vérifier** :

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

# Créer un token "read,write" pour Claude Code
python scripts/mcp_cli.py token create claude-code-agent read,write
```

La CLI affichera quelque chose comme :

```
Token créé avec succès !
  Nom    : claude-code-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  Ce token ne sera PLUS JAMAIS affiché. Copiez-le maintenant !
```

> **⚠️ IMPORTANT** : Copiez ce token immédiatement ! Il ne sera plus jamais affiché (seul le hash SHA-256 est stocké).

### Option B — Via la bootstrap key (temporaire)

Pour un test rapide, vous pouvez utiliser directement la `ADMIN_BOOTSTRAP_KEY` définie dans votre `.env`. Mais **en production**, créez toujours un token dédié avec les permissions minimales.

---

## ⚙️ Étape 3 — Brancher Claude Code sur Live Memory

Claude Code stocke sa configuration MCP dans un fichier JSON. Trois scopes sont disponibles :

| Scope     | Emplacement                                  | Portée                              |
| --------- | -------------------------------------------- | ----------------------------------- |
| `local`   | `~/.claude.json` (clé `projects.<cwd>`)      | Le répertoire courant uniquement    |
| `user`    | `~/.claude.json` (clé `mcpServers` globale)  | Tous les projets de l'utilisateur   |
| `project` | `.mcp.json` à la racine du projet            | Commité dans le repo (équipes)      |

Pour une utilisation perso multi-projets, le scope `user` est généralement le plus pratique.

### 3.1 — Méthode CLI (recommandée)

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  https://votre-serveur/mcp \
  --header "Authorization: Bearer lm_VOTRE_TOKEN_ICI"
```

Pour un serveur local en HTTP :

```bash
claude mcp add \
  --transport http \
  --scope user \
  live-memory \
  http://localhost:8080/mcp \
  --header "Authorization: Bearer lm_VOTRE_TOKEN_ICI"
```

### 3.2 — Méthode édition manuelle

Si vous préférez éditer directement le JSON, ajoutez le bloc suivant dans `~/.claude.json` (scope `user`, sous la clé `mcpServers` au premier niveau) :

```json
{
  "mcpServers": {
    "live-memory": {
      "type": "http",
      "url": "https://votre-serveur/mcp",
      "headers": {
        "Authorization": "Bearer lm_VOTRE_TOKEN_ICI"
      }
    }
  }
}
```

> **Remplacez** `lm_VOTRE_TOKEN_ICI` par le token obtenu à l'étape 2 et `votre-serveur` par votre domaine (ou `localhost:8080` en local).

Pour le scope `project` (configuration partagée en équipe), créez plutôt un fichier `.mcp.json` à la racine du projet avec le même format.

### 3.3 — Vérifier la connexion

Après configuration :

```bash
claude mcp list
```

Vous devriez voir `live-memory` avec un statut connecté. Lancez ensuite Claude Code dans un projet et demandez :

> *« Appelle `system_health` sur live-memory et donne-moi le retour. »*

Si Claude répond avec `{"status": "ok", ...}`, la connexion fonctionne.

### 3.4 — Whitelister les outils (éviter les prompts de permission)

Claude Code demande confirmation à chaque appel d'outil MCP non autorisé. Pour éviter ces interruptions, ajoutez les outils Live Memory à la liste blanche du projet (ou de l'utilisateur).

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

> 💡 **Convention de nommage** : Claude Code expose chaque outil MCP sous la forme `mcp__<nom-du-serveur>__<nom-de-l-outil>`. Si vous avez nommé votre serveur `live-memory-prod` à l'étape 3.1, remplacez le préfixe en conséquence.

Alternative interactive : tapez `/permissions` dans une session Claude Code pour ouvrir l'éditeur de permissions.

Pour une configuration globale (tous projets), utilisez plutôt `~/.claude/settings.json`.

### 3.5 — Serveur distant HTTPS

Pour un déploiement production, l'URL et le bloc JSON sont identiques — seul le schéma change (`https://` au lieu de `http://`). Aucune option supplémentaire n'est nécessaire côté Claude Code.

---

## 📁 Étape 4 — Créer un espace mémoire

Avant que Claude Code puisse écrire des notes, il faut un **espace mémoire** avec des **rules** qui définissent la structure de la Memory Bank.

### Via la CLI

```bash
python scripts/mcp_cli.py space create mon-projet \
  --rules-file ./RULES/standard.memory.bank.md \
  -d "Mon projet de développement"
```

Plusieurs templates de rules sont fournis dans le répertoire `RULES/` du repo :

| Template                              | Usage                                                       |
| ------------------------------------- | ----------------------------------------------------------- |
| `RULES/standard.memory.bank.md`       | Memory Bank Cline classique (6 fichiers projet)             |
| `RULES/product.management.memory.bank.md` | Équipe produit (vision, portfolio, personas, features)  |
| `RULES/medical.memory.bank.md`        | Suivi de patient / dossier clinique                         |
| `RULES/presales.memory.bank.md`       | Avant-vente, qualification de prospect, RFP                 |
| `RULES/book.memory.bank.md`           | Écriture de livre / projet éditorial                        |
| `RULES/live-mem.standard.memory.bank.md` | Développement du serveur Live Memory lui-même            |

### Via Claude Code directement

Vous pouvez aussi demander à Claude de créer l'espace. Dites-lui simplement :

> *« Utilise l'outil `space_create` pour créer un espace `mon-projet` avec des rules standard de type Memory Bank (projectbrief, activeContext, progress, techContext, systemPatterns, productContext). »*

Claude Code utilisera l'outil MCP `space_create` pour le faire.

### Exemple de rules standard

```markdown
# Memory Bank Rules

## Fichiers à maintenir

### projectbrief.md
Vision, objectifs, périmètre du projet.

### activeContext.md
Focus actuel, travail en cours, décisions récentes, prochaines étapes.

### progress.md
Ce qui fonctionne, ce qui reste à faire, problèmes connus.

### techContext.md
Technologies utilisées, configuration, contraintes techniques.

### systemPatterns.md
Architecture, patterns, décisions techniques, composants.

### productContext.md
Pourquoi ce projet existe, problèmes résolus, expérience utilisateur.
```

---

## 📝 Étape 5 — Donner des instructions à Claude Code

Claude Code lit automatiquement les fichiers `CLAUDE.md` au démarrage. Deux emplacements possibles :

| Emplacement             | Portée                                                | Recommandé pour                       |
| ----------------------- | ----------------------------------------------------- | ------------------------------------- |
| `<racine-projet>/CLAUDE.md` | Le projet courant (commité avec le repo)          | Workflow spécifique au projet         |
| `~/.claude/CLAUDE.md`   | Tous les projets de l'utilisateur (privé, non commité) | Préférences globales, identité, style |

Pour Live Memory, le `CLAUDE.md` projet est l'endroit idéal car la valeur de `{SPACE}` est spécifique au projet.

### Template recommandé (à coller dans `CLAUDE.md`)

Ce template utilise le placeholder `{SPACE}` — il suffit de configurer **une seule valeur** :

```markdown
# Memory Bank — Live Memory MCP

Ma mémoire se réinitialise complètement entre les sessions. Je dépends ENTIÈREMENT de la Memory Bank pour comprendre le projet et continuer efficacement.

## 🔌 Configuration (à modifier par projet)

Ma mémoire persistante est gérée par le serveur MCP **Live Memory** (`live-memory`).

> **⚙️ La seule valeur à personnaliser :**
>
> - **SPACE** = `mon-projet`       ← Remplacez par votre space_id
>
> Toutes les instructions ci-dessous utilisent `{SPACE}` — je le substitue automatiquement par la valeur ci-dessus.
> Le nom de l'agent est **auto-détecté** depuis le token d'authentification (pas besoin de le configurer).

## 📖 Au démarrage de CHAQUE tâche (OBLIGATOIRE)

1. Appeler `space_rules("{SPACE}")` pour lire les rules (structure de la bank)
2. Appeler `bank_read_all("{SPACE}")` pour charger TOUT le contexte consolidé
3. Appeler `live_read(space_id="{SPACE}")` pour lire les **notes non consolidées**
4. Lire attentivement le contenu avant de commencer
5. Identifier le focus actuel dans `activeContext.md`

> ⚠️ Ne JAMAIS commencer à travailler sans avoir lu la bank.
>
> 💡 **Pourquoi lire les notes live ?** Entre deux sessions, des notes ont pu être écrites (par moi ou par d'autres agents) sans avoir été consolidées dans la bank. Ces notes contiennent du contexte récent qui n'apparaît pas encore dans les fichiers bank. Les ignorer = risquer de refaire du travail déjà fait ou de rater des décisions récentes.

## 📝 Pendant le travail

Écrire des notes fréquentes et atomiques avec `live_note` :

    live_note(space_id="{SPACE}", category="<catégorie>", content="...")

Le paramètre `agent` est **auto-détecté** depuis le token — inutile de le passer.

**Catégories** :
- `observation` — Constats factuels, résultats de commandes
- `decision` — Choix techniques et leur justification
- `progress` — Avancement, ce qui est terminé
- `issue` — Problèmes rencontrés, bugs
- `todo` — Tâches identifiées à faire
- `insight` — Apprentissages, patterns découverts
- `question` — Points à clarifier, décisions en suspens

## 🧠 En fin de session (ou après un bloc de travail significatif)

    bank_consolidate(space_id="{SPACE}")

Le LLM consolidera **mes propres notes** (auto-détection de l'agent depuis le token) en mettant à jour les fichiers de la bank selon les rules du space.

> ℹ️ Seul un admin peut consolider les notes de tous les agents (`agent=""`).

## ⚠️ Règles impératives

1. **Ne JAMAIS écrire directement dans la bank** — seule la consolidation LLM le fait
2. **Toujours passer `space_id="{SPACE}"`** dans tous les appels
3. **Écrire des notes atomiques après chaque étape importante** — 1 note = 1 fait, 1 décision, ou 1 tâche
4. **Consolider en fin de session** — ne jamais quitter sans consolider mais toujours après avoir validé avec l'utilisateur
5. **Lire la bank au démarrage** — ne jamais travailler sans contexte

## 🔄 Quand demander une mise à jour

Si l'utilisateur demande **"update memory bank"** ou **"met à jour la memory bank"** :
1. Écrire des notes `live_note` résumant l'état actuel du travail
2. Appeler `bank_consolidate(space_id="{SPACE}")`
3. Vérifier le résultat avec `bank_read_all("{SPACE}")`

## 📊 Commandes utiles

| Action                          | Commande                                                                  |
| ------------------------------- | ------------------------------------------------------------------------- |
| Lire tout le contexte           | `bank_read_all("{SPACE}")`                                                |
| Lire les rules                  | `space_rules("{SPACE}")`                                                  |
| Écrire une note                 | `live_note(space_id="{SPACE}", category="...", content="...")`            |
| Consolider                      | `bank_consolidate(space_id="{SPACE}")`                                    |
| Voir les notes récentes         | `live_read(space_id="{SPACE}")`                                           |
| Voir les notes d'un autre agent | `live_read(space_id="{SPACE}", agent="autre-agent")`                      |
| Info sur l'espace               | `space_info("{SPACE}")`                                                   |
```

> 💡 **Pour un nouveau projet** : copiez ce fichier dans `<racine-projet>/CLAUDE.md`, changez la ligne `SPACE`, c'est tout !

### Version minimaliste (`~/.claude/CLAUDE.md` global)

Si vous préférez ne pas commiter d'instructions Live Memory dans chaque projet, ajoutez ce bloc court dans `~/.claude/CLAUDE.md` :

```
Tu as accès à Live Memory (serveur MCP "live-memory").
- Au démarrage: space_rules("{SPACE}"), bank_read_all("{SPACE}"), live_read("{SPACE}")
- Pendant le travail: live_note(space_id="{SPACE}", category="...", content="...")
- En fin de session: bank_consolidate(space_id="{SPACE}")
Le `{SPACE}` est défini dans le CLAUDE.md du projet courant. L'agent est auto-détecté depuis le token.
```

Chaque projet déclare ensuite uniquement sa valeur de `{SPACE}` dans son propre `CLAUDE.md`.

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
│     → LLM synthétise les notes en bank         │
│     → Notes live supprimées après succès       │
└────────────────────────────────────────────────┘
```

### Fréquence de consolidation

| Situation                   | Recommandation                       |
| --------------------------- | ------------------------------------ |
| Session courte (< 10 notes) | Consolider en fin de session         |
| Session longue (> 20 notes) | Consolider toutes les 15-20 notes    |
| Changement de contexte      | Consolider avant de changer de sujet |
| Fin de journée              | Toujours consolider                  |

### Visualiser en temps réel

Pendant que Claude Code travaille, ouvrez l'interface web pour suivre en direct :

```
http://localhost:8080/live
```

Vous verrez les notes apparaître en temps réel dans la **Live Timeline** et la **Bank** se mettre à jour après chaque consolidation.

---

## 👥 Multi-agents : Claude Code + Cline + Claude Desktop + autres

Live Memory permet à **plusieurs agents** de collaborer sur le même espace mémoire.

### Scénario : Claude Code (dev) + Cline (review) + Claude Desktop (synthèse)

Pour que plusieurs agents collaborent, il suffit de leur créer **un token par identité** :

1. `admin_create_token name="claude-code-dev"`
2. `admin_create_token name="cline-review"`
3. `admin_create_token name="claude-desktop-synthese"`
4. Configurer chaque agent avec son propre token

L'identité de l'agent est **automatiquement déduite de son token** à chaque fois qu'il appelle `live_note` ou `bank_consolidate`. Aucun paramètre `agent` à préciser.

### Communication entre agents

Les agents ne se parlent pas directement. Ils communiquent **via l'espace partagé** :

```
Claude Code   → live_note(category="question", content="Faut-il supporter le CSV ?")
Cline         → live_read(category="question")   ← voit la question
Cline         → live_note(category="decision", content="Non, JSON uniquement")
Claude Code   → live_read(category="decision")   ← voit la réponse
```

### Consolidation par agent

Chaque agent consolide **ses propres notes** sans interférer avec celles des autres. Si un agent a les droits **admin**, il peut consolider les notes de tous les agents en appelant `bank_consolidate` (qui, pour un admin, traite par défaut tout le monde).

---

## 🔍 Dépannage

### `claude mcp list` ne montre pas live-memory

1. Vérifiez que le serveur est démarré : `curl http://localhost:8080/health`
2. Vérifiez la syntaxe JSON dans `~/.claude.json` (pas de virgule trailing, accolades bien fermées)
3. Quittez complètement Claude Code et relancez-le — le fichier n'est lu qu'au démarrage
4. Inspectez les logs : `claude --debug` puis exécutez une session courte

### Erreur "401 Unauthorized"

- Le token est incorrect, périmé ou révoqué
- Vérifiez que le header est bien `"Authorization": "Bearer lm_..."` (avec le préfixe `lm_`)
- Attention aux espaces / sauts de ligne parasites lors du copier-coller du token
- La bootstrap key fonctionne pour les tests mais créez un vrai token pour l'usage courant

### Erreur "Accès refusé à l'espace"

Le token est restreint à certains espaces (`space_ids`). Soit :
- Créez un token sans restriction d'espace (paramètre `space_ids` vide)
- Soit ajoutez l'espace au token : `admin_update_token(token_hash, space_ids="mon-projet", action="add")`

### Claude Code demande la permission à chaque appel

Whitelistez les outils via `.claude/settings.local.json` (voir Étape 3.4) ou tapez `/permissions` dans la session pour les ajouter interactivement.

### Claude Code n'utilise pas Live Memory spontanément

Sans `CLAUDE.md` explicite, Claude Code ne sait pas qu'il doit appeler ces outils en début de session. Ajoutez le template de l'Étape 5 dans `<racine-projet>/CLAUDE.md` ou `~/.claude/CLAUDE.md`.

### Le MCP ne se connecte pas derrière un VPN ou un proxy

Si Live Memory est sur un serveur distant, vérifiez :
- Que le port 443 (HTTPS) ou 8080 (HTTP) est accessible
- Que l'URL dans la config Claude Code est correcte (avec `/mcp` à la fin)
- Testez manuellement : `curl -H "Authorization: Bearer lm_..." https://votre-serveur/mcp`

### Suivre l'avancement d'une consolidation

Côté serveur, observez les logs :

```bash
docker compose logs -f live-mem-service --tail 20
```

Claude Code maintient la connexion HTTP ouverte pendant tout l'appel, donc une consolidation longue ne pose normalement pas de problème de timeout côté client.

---

## 🖥️ Avec Claude Desktop

La configuration est similaire à Claude Code mais le fichier change. Éditez `claude_desktop_config.json` :

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
        "Authorization": "Bearer lm_VOTRE_TOKEN_ICI"
      },
      "timeout": 600
    }
  }
}
```

> **⚠️ Pour Claude Desktop** : ajoutez `"timeout": 600` pour autoriser les consolidations longues. Claude Code n'a pas besoin de ce paramètre.

Redémarrez Claude Desktop après la modification. Les outils Live Memory apparaîtront dans la liste des outils disponibles.

> ℹ️ **Note** : Claude Desktop ne propose pas de système d'allow-list par outil (contrairement à Claude Code). Les permissions se gèrent au niveau de l'application elle-même.

---

## 📊 Récapitulatif

| Étape     | Action                                                | Temps      |
| --------- | ----------------------------------------------------- | ---------- |
| 1         | Démarrer Live Memory (`docker compose up -d`)         | 1 min      |
| 2         | Créer un token (`mcp_cli.py token create`)            | 30 sec     |
| 3         | Configurer Claude Code (`claude mcp add`)             | 1 min      |
| 3.4       | Whitelister les outils (`.claude/settings.local.json`) | 1 min      |
| 4         | Créer un espace (`space_create`)                      | 30 sec     |
| 5         | Ajouter le `CLAUDE.md` du projet                      | 2 min      |
| **Total** | **Prêt à utiliser**                                   | **~6 min** |

---

*Guide d'intégration Live Memory ↔ Claude Code v1.0.0 — [Documentation complète](README.md)*
