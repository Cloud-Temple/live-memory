# 🔌 Guide d'intégration Live Memory avec Cline (VS Code / VSCodium)

> **Version** : 1.2.0 | **Date** : 2026-03-27

Ce guide détaille pas à pas comment connecter **Cline** (l'agent IA dans VS Code ou VSCodium) à **Live Memory** pour lui donner une mémoire de travail partagée et persistante.

---

## 📋 Table des matières

- [Prérequis](#-prérequis)
- [Étape 1 — Démarrer Live Memory](#-étape-1--démarrer-live-memory)
- [Étape 2 — Créer un token pour Cline](#-étape-2--créer-un-token-pour-cline)
- [Étape 3 — Configurer Cline dans VS Code / VSCodium](#-étape-3--configurer-cline-dans-vs-code--vscodium)
- [Étape 4 — Créer un espace mémoire](#-étape-4--créer-un-espace-mémoire)
- [Étape 5 — Donner les instructions à Cline](#-étape-5--donner-les-instructions-à-cline)
- [Workflow recommandé](#-workflow-recommandé)
- [Instructions personnalisées pour Cline](#-instructions-personnalisées-pour-cline)
- [Multi-agent : Cline + Claude + autres](#-multi-agent--cline--claude--autres)
- [Troubleshooting](#-troubleshooting)
- [Avec Claude Desktop](#-avec-claude-desktop)

---

## 📦 Prérequis

| Composant                   | Version            | Vérification                          |
| --------------------------- | ------------------ | ------------------------------------- |
| **Docker**                  | ≥ 24.0             | `docker --version`                    |
| **Docker Compose**          | v2                 | `docker compose version`              |
| **VS Code** ou **VSCodium** | Récent             | —                                     |
| **Extension Cline**         | Récente            | Installée depuis le marketplace       |
| **Live Memory**             | Déployé et démarré | `curl http://localhost:8080/health`   |

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

## 🔑 Étape 2 — Créer un token pour Cline

Cline a besoin d'un **Bearer Token** avec les permissions `read,write` pour lire et écrire dans la mémoire.

### Option A — Via la CLI

```bash
cd /chemin/vers/live-memory
export MCP_TOKEN=<votre_ADMIN_BOOTSTRAP_KEY>

# Créer un token « write » pour Cline
python scripts/mcp_cli.py token create cline-agent read,write
```

La CLI affichera quelque chose comme :

```
Token created successfully!
  Name   : cline-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  This token will NEVER be displayed again. Copy it now!
```

> **⚠️ IMPORTANT** : copiez ce token immédiatement ! Il ne sera plus jamais affiché (seul le hash SHA-256 est stocké).

### Option B — Via la clé bootstrap (temporaire)

Pour un test rapide, vous pouvez utiliser directement l'`ADMIN_BOOTSTRAP_KEY` définie dans votre `.env`. Mais **en production**, créez toujours un token dédié avec des permissions minimales.

---

## ⚙️ Étape 3 — Configurer Cline dans VS Code / VSCodium

### 3.1 Ouvrir les paramètres MCP de Cline

1. Ouvrez VS Code / VSCodium
2. Ouvrez le panneau Cline (icône Cline dans la barre latérale)
3. Cliquez sur l'icône **⚙️ Settings** (engrenage) en haut du panneau Cline
4. Cherchez **« MCP Servers »** ou cliquez sur l'onglet **MCP**
5. Cliquez sur **« Edit MCP Settings »** (ou le bouton pour éditer le JSON)

### 3.2 Ajouter Live Memory comme serveur MCP

Dans le fichier `cline_mcp_settings.json` qui s'ouvre, ajoutez la configuration suivante :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      },
      "timeout": 1800
    }
  }
}
```

> **Remplacez** `lm_YOUR_TOKEN_HERE` par le token obtenu à l'étape 2.
> **⚠️ Le paramètre `timeout` est critique** : la consolidation LLM peut prendre plus de 60 secondes (timeout par défaut de Cline). Réglez-le à 1800 secondes, en cohérence avec le défaut serveur.

### 3.3 Où se trouve le fichier de configuration ?

| OS                 | Emplacement typique                                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| **macOS**          | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`      |
| **Linux**          | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`                          |
| **VSCodium macOS** | `~/Library/Application Support/VSCodium/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`  |
| **VSCodium Linux** | `~/.config/VSCodium/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`                      |

### 3.4 Vérifier la connexion

Après avoir enregistré le fichier de config :

1. **Redémarrez Cline** (ou rechargez VS Code avec `Ctrl+Shift+P` → « Developer: Reload Window »)
2. Dans le panneau Cline, cliquez sur l'onglet **MCP**
3. Vous devriez voir **« live-memory »** avec un indicateur vert ✅
4. Cliquez dessus pour voir les **38 outils disponibles**

### 3.5 Serveur distant (production)

Si Live Memory est déployé sur un serveur avec HTTPS :

```json
{
  "mcpServers": {
    "live-memory": {
      "url": "https://live-mem.votre-domaine.com/mcp",
      "headers": {
        "Authorization": "Bearer lm_YOUR_TOKEN_HERE"
      },
      "timeout": 1800
    }
  }
}
```

---

## 📁 Étape 4 — Créer un espace mémoire

Avant que Cline puisse écrire des notes, il vous faut un **espace mémoire** avec des **rules** qui définissent la structure de la Memory Bank.

### Via la CLI

```bash
python scripts/mcp_cli.py space create mon-projet \
  --rules-file ./rules/standard.md \
  -d "Mon projet de développement"
```

### Via Cline directement

Vous pouvez aussi demander à Cline de créer l'espace. Dites-lui simplement :

> *« Utilise l'outil `space_create` pour créer un space 'mon-projet' avec les rules standards Memory Bank (projectbrief, activeContext, progress, techContext, systemPatterns, productContext). »*

Cline utilisera l'outil MCP `space_create` pour le faire.

### Exemple de rules standards

```markdown
# Memory Bank Rules

## Fichiers à maintenir

### projectbrief.md
Vision, objectifs, périmètre du projet.

### activeContext.md  
Focus courant, travail en cours, décisions récentes, prochaines étapes.

### progress.md
Ce qui marche, ce qui reste à construire, problèmes connus.

### techContext.md
Technologies utilisées, configuration, contraintes techniques.

### systemPatterns.md
Architecture, patterns, décisions techniques, composants.

### productContext.md
Pourquoi ce projet existe, problèmes résolus, expérience utilisateur.
```

---

## 📝 Étape 5 — Donner les instructions à Cline

Pour que Cline utilise automatiquement Live Memory, ajoutez des **Custom Instructions** dans ses paramètres.

### 5.1 Où configurer les Custom Instructions

Dans Cline : **Settings** → **Custom Instructions**, ou mieux, placez un fichier `WORKSPACE_CLINE_RULES.md` à la racine de votre projet (Cline le charge automatiquement comme instructions au niveau workspace).

Le dépôt fournit **deux** templates prêts à l'emploi — choisissez celui qui correspond à votre workspace :

| Template                                                                  | Quand l'utiliser                                                                |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md)                    | Workspaces avec **Live Memory uniquement**.                                     |
| [`WORKSPACE_CLINE_ADVANCE_RULES.md`](WORKSPACE_CLINE_ADVANCE_RULES.md)    | Workspaces également connectés à un serveur MCP **Graph Memory** (incidents, RFC, runbooks, rappel cross-documents). Ajoute la politique Graph-first, la discipline de compaction et l'ingestion explicite côté agent. |

Copiez le template choisi à la racine de votre projet et personnalisez les placeholders (`SPACE`, et pour le template avancé `LIVE_MCP_SERVER` / `GRAPH_MCP_SERVER` / `GRAPH_MEMORY_ID`).

> ℹ️ **Le template avancé est strictement additif** : le consolidateur Live Memory ne change pas — il ne pousse jamais rien dans Graph Memory. L'ingestion Graph reste une action explicite côté agent/outillage, partant des fichiers canoniques du dépôt. Aucun token ni endpoint ne doit figurer dans un template.

### 5.2 Instructions recommandées (template avec `{SPACE}`)

Copiez le contenu ci-dessous dans les **Custom Instructions** de votre agent (ou dans un fichier `.clinerules` à la racine de votre projet). Ce template utilise le placeholder `{SPACE}` — vous n'avez qu'**une seule valeur** à définir :


```markdown
# Memory Bank de Cline — Live Memory MCP

Ma mémoire se réinitialise complètement entre les sessions. Je dépends ENTIÈREMENT de la Memory Bank pour comprendre le projet et continuer efficacement.

## 🔌 Configuration (à personnaliser par projet)

Ma mémoire persistante est gérée par le serveur MCP **Live Memory** (`my-live-mem`).

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
> 💡 **Pourquoi lire les notes live ?** Entre les sessions, des notes peuvent avoir été écrites (par moi ou par d'autres agents) sans avoir été consolidées dans la bank. Ces notes contiennent du contexte récent qui n'apparaît pas encore dans les fichiers bank. Les ignorer = risque de refaire un travail déjà fait ou de manquer une décision récente.

## 📝 Pendant le travail

Écrire des notes atomiques fréquentes avec `live_note` :

live_note(space_id="{SPACE}", category="<catégorie>", content="...")

Le paramètre `agent` est **auto-détecté** depuis le token — pas besoin de le passer.

**Catégories** :
- `observation` — constats factuels, sorties de commandes
- `decision` — choix techniques et leur justification
- `progress` — avancement, ce qui est terminé
- `issue` — problèmes rencontrés, bugs
- `todo` — tâches identifiées à faire
- `insight` — apprentissages, patterns découverts
- `question` — points à clarifier, décisions en attente

## 🧠 En fin de session (ou après un bloc de travail significatif)

bank_consolidate(space_id="{SPACE}")

Le LLM va consolider **mes propres notes** (agent auto-détecté depuis le token) en mettant à jour les fichiers bank selon les rules du space.

> ℹ️ Seul un utilisateur manage+ peut consolider les notes de tous les agents (`agent=""`).
>
> 🔕 `bank_consolidate` est **fire-and-forget** : il retourne un accusé async (`running` / `queued`) avec `next_action="return_to_user_without_polling"`. **Appelez-le une seule fois et rendez la main à l'utilisateur.** Ne surveillez pas et ne pollez pas. `bank_consolidation_status(job_id)` existe uniquement pour des **checks manuels explicites**.

## ⚠️ Règles obligatoires

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
| Lire tout le contexte           | `bank_read_all("{SPACE}")`                                                |
| Lire les rules                  | `space_rules("{SPACE}")`                                                  |
| Écrire une note                 | `live_note(space_id="{SPACE}", category="...", content="...")`            |
| Consolider                      | `bank_consolidate(space_id="{SPACE}")`                                    |
| Voir les notes récentes         | `live_read(space_id="{SPACE}")`                                           |
| Voir les notes d'un autre agent | `live_read(space_id="{SPACE}", agent="autre-agent")`                      |
| Infos space                     | `space_info("{SPACE}")`                                                   |
```

> 💡 **Pour un nouveau projet** : copiez ce fichier, changez la ligne `SPACE`, et c'est tout !

---

## 🔄 Workflow recommandé

### Workflow type d'une session de développement

```
┌────────────────────────────────────────────────┐
│  1. DÉMARRAGE                                  │
│     space_rules("mon-projet")                  │
│     bank_read_all("mon-projet")                │
│     live_read("mon-projet")                    │
│     → Cline lit rules + bank + notes live      │
├────────────────────────────────────────────────┤
│  2. TRAVAIL (boucle)                           │
│     • Cline code, analyse, répond              │
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

| Situation                    | Recommandation                           |
| ---------------------------- | ---------------------------------------- |
| Session courte (< 10 notes)  | Consolider en fin de session             |
| Session longue (> 20 notes)  | Consolider toutes les 15-20 notes        |
| Changement de contexte       | Consolider avant de changer de sujet     |
| Fin de journée               | Toujours consolider                      |

### Visualisation en temps réel

Pendant que Cline travaille, ouvrez l'interface web pour suivre en direct :

```
http://localhost:8080/live
```

Vous verrez les notes apparaître en temps réel dans la **Live Timeline** et la **Bank** se mettre à jour après chaque consolidation.

---

## 📋 Instructions personnalisées pour Cline

### Version template (recommandée)

Copiez [`WORKSPACE_CLINE_RULES.md`](WORKSPACE_CLINE_RULES.md) à la racine de votre projet. Cline charge automatiquement ce fichier comme instructions au niveau workspace.

Modifiez ensuite **uniquement la valeur `SPACE`** pour correspondre à votre projet. Le nom d'agent est auto-détecté.

### Version minimaliste (copier-coller dans les Custom Instructions)

Si vous voulez une version ultra-courte, ajoutez ceci dans les Custom Instructions globales :

```
Vous avez accès à Live Memory (serveur MCP).
- Au démarrage : space_rules("{SPACE}"), bank_read_all("{SPACE}"), live_read("{SPACE}")
- Pendant le travail : live_note(space_id="{SPACE}", category="...", content="...")
- En fin de session : bank_consolidate(space_id="{SPACE}") — appeler une seule fois et rendre la main sans poller
Où {SPACE} = "mon-projet". L'agent est auto-détecté depuis le token.
```

---

## 👥 Multi-agent : Cline + Claude + autres

Live Memory permet à **plusieurs agents** de collaborer sur le même espace mémoire.

### Scénario : Cline (dev) + Claude (review)

Pour que deux agents collaborent, créez simplement **deux tokens différents** :

1. Créer le token pour Cline (`admin_create_token name="cline-dev"`)
2. Créer le token pour Claude (`admin_create_token name="claude-review"`)
3. Configurer chaque agent avec son propre token

L'identité de l'agent est **automatiquement inférée depuis son token** chaque fois qu'il appelle `live_note` ou `bank_consolidate`. Ils n'ont pas besoin de la spécifier.

### Communication inter-agents

Les agents ne se parlent pas directement. Ils communiquent **via l'espace partagé** :

```
Cline  → live_note(category="question", content="Faut-il supporter le CSV ?")
Claude → live_read(category="question")  ← voit la question de Cline
Claude → live_note(category="decision", content="Non, JSON uniquement")
Cline  → live_read(category="decision")  ← voit la réponse de Claude
```

### Consolidation par agent

Chaque agent consolide **ses propres notes** sans interférer avec les autres :

```
Cline  → bank_consolidate(space_id="mon-projet")  # Consolide seulement les notes de cline-dev
Claude → bank_consolidate(space_id="mon-projet")  # Consolide seulement les notes de claude-review
```

Si un agent a des permissions **admin**, il peut consolider les notes de tout le monde en appelant `bank_consolidate` (qui par défaut traite tous les agents pour un admin).

---

## 🔍 Troubleshooting

### Cline ne voit pas les outils Live Memory

1. Vérifiez que le serveur est lancé : `curl http://localhost:8080/health`
2. Vérifiez la syntaxe JSON dans `cline_mcp_settings.json` (pas de virgule traînante)
3. Rechargez VS Code (`Ctrl+Shift+P` → « Developer: Reload Window »)
4. Dans l'onglet MCP de Cline, vérifiez si `live-memory` apparaît en rouge (erreur de connexion)

### Erreur « 401 Unauthorized »

- Le token est incorrect ou révoqué
- Vérifiez que le header est bien `"Authorization": "Bearer lm_..."` (avec le préfixe `lm_`)
- La clé bootstrap fonctionne pour tester, mais créez un vrai token pour un usage régulier

### Erreur « Access Denied to Space »

Le token est restreint à certains spaces (`space_ids`). Soit :
- Créez un token sans restriction de space (paramètre `space_ids` vide)
- Soit ajoutez le space au token : `admin_update_token(token_hash, space_ids="mon-projet", action="add")`

### Cline n'utilise pas Live Memory spontanément

Ajoutez des **Custom Instructions** explicites (voir [Étape 5](#-étape-5--donner-les-instructions-à-cline)). Sans instructions, Cline ne sait pas qu'il doit utiliser ces outils.

### Erreur de timeout / la consolidation échoue après 60 secondes

Par défaut, Cline et Claude Desktop interrompent les requêtes MCP après 60 secondes, ce qui est souvent insuffisant pour une consolidation (le LLM peut prendre plusieurs minutes).

1. Vérifiez que vous avez ajouté `"timeout": 1800` dans la configuration MCP de votre agent, en cohérence avec le timeout serveur dans votre fichier `.env`.
2. Vous pouvez suivre la progression en temps réel côté serveur dans les logs :

```bash
docker compose logs -f live-mem-service --tail 20
```

### MCP ne se connecte pas derrière un VPN

Si Live Memory est sur un serveur distant, vérifiez :
- Que le port 443 (HTTPS) ou 8080 (HTTP) est accessible
- Que l'URL dans la config Cline est correcte (avec `/mcp` à la fin)
- Testez manuellement : `curl -H "Authorization: Bearer lm_..." https://votre-serveur/mcp`

---

## 🖥️ Avec Claude Desktop

La configuration est similaire. Éditez le fichier `claude_desktop_config.json` :

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
      "timeout": 1800
    }
  }
}
```

> **⚠️ N'oubliez pas le paramètre `timeout`** pour autoriser les temps de traitement longs de la consolidation.

Redémarrez Claude Desktop après la modification. Les 38 outils Live Memory apparaîtront dans la liste des outils disponibles.

---

## 📊 Récapitulatif

| Étape     | Action                                            | Temps      |
| --------- | ------------------------------------------------- | ---------- |
| 1         | Démarrer Live Memory (`docker compose up -d`)     | 1 min      |
| 2         | Créer un token (`mcp_cli.py token create`)        | 30 sec     |
| 3         | Configurer Cline (`cline_mcp_settings.json`)      | 2 min      |
| 4         | Créer un space (`space_create`)                   | 30 sec     |
| 5         | Ajouter les Custom Instructions                   | 2 min      |
| **Total** | **Prêt à l'emploi**                               | **~6 min** |

---

*Guide d'intégration Live Memory v1.2.0 — [Documentation complète](README.fr.md)*
