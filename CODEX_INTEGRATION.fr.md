# 🔌 Guide d'intégration Live Memory pour OpenAI Codex

> **Version** : 2.1.0 | **Date** : 2026-05-16

Ce guide vous accompagne pas à pas pour connecter **OpenAI Codex** à **Live Memory**, lui offrant une mémoire de travail partagée et persistante entre les sessions de codage.

---

## 📋 Table des matières

- [Prérequis](#-prérequis)
- [Étape 1 — Obtenir un token Live Memory](#-étape-1--obtenir-un-token-live-memory)
- [Étape 2 — Configurer Codex via `.codex/config.toml`](#-étape-2--configurer-codex-via-codexconfigtoml)
- [Étape 3 — Créer un espace mémoire](#-étape-3--créer-un-espace-mémoire)
- [Étape 4 — Donner des instructions à Codex](#-étape-4--donner-des-instructions-à-codex)
- [Workflow recommandé](#-workflow-recommandé)
- [Dépannage](#-dépannage)

---

## 📦 Prérequis

| Composant        | Détail                                                         |
| ---------------- | -------------------------------------------------------------- |
| **OpenAI Codex** | CLI ou environnement avec support des serveurs MCP             |
| **Live Memory**  | Instance active (auto-hébergée ou service managé Cloud Temple) |
| **Token Bearer** | Token `read,write` créé sur votre instance Live Memory         |

---

## 🔑 Étape 1 — Obtenir un token Live Memory

Codex a besoin d'un **Token Bearer** avec au minimum les permissions `read,write`.

### Option A — Via la CLI

```bash
cd /chemin/vers/live-memory
export MCP_TOKEN=<votre_ADMIN_BOOTSTRAP_KEY>

# Créer un token "write" pour Codex
python scripts/mcp_cli.py token create codex-agent read,write
```

La CLI affiche quelque chose comme :

```
Token créé avec succès !
  Nom    : codex-agent
  Token  : lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
  Perms  : read, write

⚠️  Ce token ne sera JAMAIS affiché à nouveau. Copiez-le maintenant !
```

> **⚠️ IMPORTANT** : Copiez ce token immédiatement ! Il ne sera jamais réaffiché (seul le hash SHA-256 est stocké).

### Option B — Via la console d'administration

1. Ouvrez `https://<votre-instance-live-mem>/admin` dans votre navigateur
2. Connectez-vous avec vos identifiants administrateur
3. Naviguez vers **Admin → Tokens**
4. Cliquez sur **Créer un token**, renseignez le nom (`codex-agent`), définissez les permissions à `read,write`
5. Copiez le token affiché

### Option C — Service managé Cloud Temple

Si vous utilisez l'instance **Live Memory managée par Cloud Temple**, votre token a déjà été provisionné. Il ressemble à ceci :

```
lm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ Votre token est confidentiel. Ne l'incluez jamais dans une documentation ou dans un dépôt Git.

---

## ⚙️ Étape 2 — Configurer Codex via `.codex/config.toml`

Codex lit sa configuration de serveurs MCP depuis le fichier `.codex/config.toml` à la racine de votre projet (ou dans votre répertoire personnel pour une configuration globale).

### 2.1 Créer ou éditer le fichier de configuration

```bash
mkdir -p ~/.codex
# ou au niveau du projet :
mkdir -p .codex
```

### 2.2 Ajouter le serveur Live Memory

Ouvrez `.codex/config.toml` et ajoutez la section suivante :

```toml
[mcp_servers.my-live-mem]
http_headers = { "Authorization" = "Bearer lm_VOTRE_TOKEN_ICI" }
enabled = true
url = "https://my.live-mem.mcp.cloud-temple.app/mcp"
```

> **Remplacez** `lm_VOTRE_TOKEN_ICI` par le token obtenu à l'étape 1.

### 2.3 Exemple complet avec le service managé Cloud Temple

```toml
[mcp_servers.my-live-mem]
http_headers = { "Authorization" = "Bearer lm_VOTRE_TOKEN_ICI" }
enabled = true
url = "https://my.live-mem.mcp.cloud-temple.app/mcp"
```

### 2.4 Exemple avec une instance auto-hébergée

```toml
[mcp_servers.live-memory]
http_headers = { "Authorization" = "Bearer lm_VOTRE_TOKEN_ICI" }
enabled = true
url = "https://live-mem.votre-domaine.com/mcp"
```

Pour une instance de développement local :

```toml
[mcp_servers.live-memory]
http_headers = { "Authorization" = "Bearer lm_VOTRE_TOKEN_ICI" }
enabled = true
url = "http://localhost:8080/mcp"
```

### 2.5 Où placer `config.toml`

| Portée         | Emplacement                          | Quand l'utiliser                           |
| -------------- | ------------------------------------ | ------------------------------------------ |
| **Global**     | `~/.codex/config.toml`               | Tous les projets partagent le même serveur |
| **Par projet** | `<racine-projet>/.codex/config.toml` | Configuration MCP spécifique au projet     |

> **Priorité** : la config au niveau du projet remplace la config globale si les deux existent.

### 2.6 Vérifier la connexion

Après avoir sauvegardé `config.toml`, testez la connectivité :

```bash
# Doit retourner {"status": "ok", ...}
curl -s -H "Authorization: Bearer lm_VOTRE_TOKEN_ICI" \
  https://my.live-mem.mcp.cloud-temple.app/health | jq .
```

---

## 📁 Étape 3 — Créer un espace mémoire

Avant que Codex puisse écrire des notes, vous avez besoin d'un **espace mémoire** avec des **rules** qui définissent la structure de la Memory Bank.

### Via la CLI Live Memory

```bash
python scripts/mcp_cli.py space create mon-projet \
  --rules-file ./RULES/live-mem.standard.memory.bank.md \
  -d "Mon projet Codex"
```

### Via Codex directement (outil MCP)

Demandez à Codex de créer l'espace via l'outil MCP `space_create` :

> *« Utilise l'outil `space_create` avec `space_id='mon-projet'` et les rules standard Memory Bank (projectbrief, activeContext, progress, techContext, systemPatterns, productContext). »*

### Modèle de rules standard

```markdown
# Rules Memory Bank

## Fichiers à maintenir

### projectbrief.md
Vision, objectifs, périmètre du projet.

### activeContext.md
Focus actuel, travail en cours, décisions récentes, prochaines étapes.

### progress.md
Ce qui fonctionne, ce qui reste à construire, problèmes connus.

### techContext.md
Technologies utilisées, configuration, contraintes techniques.

### systemPatterns.md
Architecture, patterns, décisions techniques, composants.

### productContext.md
Pourquoi ce projet existe, problèmes résolus, expérience utilisateur.
```

---

## 📝 Étape 4 — Donner des instructions à Codex

Pour que Codex utilise automatiquement Live Memory, ajoutez des instructions dans un fichier `AGENTS.md` à la racine de votre projet (Codex le charge automatiquement comme instructions au niveau de l'agent).

### 4.1 Modèle `AGENTS.md` recommandé

```markdown
# Instructions Agent Codex — Live Memory MCP

Ma mémoire se réinitialise complètement entre les sessions. Je dépends ENTIÈREMENT
de la Memory Bank pour comprendre le projet et continuer efficacement.

## Configuration du serveur MCP

Ma mémoire persistante est gérée par le serveur MCP **Live Memory** (`my-live-mem`).

> **La seule valeur à personnaliser :**
> - **SPACE** = `mon-projet`  ← Remplacez par votre space_id
>
> Toutes les instructions ci-dessous utilisent `{SPACE}`. Le nom de l'agent est auto-détecté depuis le token.

## Au démarrage de CHAQUE tâche (OBLIGATOIRE)

1. Appeler `space_rules("{SPACE}")` pour lire les rules (structure de la bank)
2. Appeler `bank_read_all("{SPACE}")` pour charger TOUT le contexte consolidé
3. Appeler `live_read(space_id="{SPACE}")` pour lire les **notes non consolidées**
4. Lire attentivement le contenu avant de commencer
5. Identifier le focus actuel dans `activeContext.md`

> ⚠️ Ne JAMAIS commencer à travailler sans avoir lu la bank.

## Pendant le travail

Écrire des notes fréquentes et atomiques avec `live_note` :

```
live_note(space_id="{SPACE}", category="<catégorie>", content="...")
```

**Catégories** : `observation`, `decision`, `progress`, `issue`, `todo`, `insight`, `question`

## En fin de session

```
bank_consolidate(space_id="{SPACE}")
```

## Règles impératives

1. **Ne JAMAIS écrire directement dans la bank** — seule la consolidation LLM le fait
2. **Toujours passer `space_id="{SPACE}"`** dans tous les appels
3. **Écrire des notes atomiques après chaque étape importante** — 1 note = 1 fait, 1 décision, ou 1 tâche
4. **Consolider en fin de session** — ne jamais quitter sans consolider
5. **Lire la bank au démarrage** — ne jamais travailler sans contexte
```

### 4.2 Version minimaliste (prompt inline)

```
Tu as accès à Live Memory (serveur MCP : my-live-mem).
- Au démarrage : space_rules("mon-projet"), bank_read_all("mon-projet"), live_read("mon-projet")
- Pendant le travail : live_note(space_id="mon-projet", category="...", content="...")
- En fin de session : bank_consolidate(space_id="mon-projet")
Le nom de l'agent est auto-détecté depuis le token d'authentification.
```

---

## 🔄 Workflow recommandé

```
┌────────────────────────────────────────────────────┐
│  1. DÉMARRAGE                                      │
│     space_rules("mon-projet")                      │
│     bank_read_all("mon-projet")                    │
│     live_read("mon-projet")                        │
│     → Codex lit les rules + bank + notes live      │
├────────────────────────────────────────────────────┤
│  2. TRAVAIL (boucle)                               │
│     • Codex code, analyse, répond                  │
│     • live_note("observation", "Tests OK")         │
│     • live_note("decision", "FastAPI retenu")      │
│     • live_note("todo", "Ajouter l'auth")          │
│     • live_note("progress", "API terminée")        │
├────────────────────────────────────────────────────┤
│  3. FIN DE SESSION                                 │
│     bank_consolidate("mon-projet")                 │
│     → Le LLM synthétise les notes dans la bank     │
│     → Les notes live sont supprimées après succès  │
└────────────────────────────────────────────────────┘
```

### Fréquence de consolidation

| Situation                   | Recommandation                       |
| --------------------------- | ------------------------------------ |
| Session courte (< 10 notes) | Consolider en fin de session         |
| Session longue (> 20 notes) | Consolider toutes les 15–20 notes    |
| Changement de sujet         | Consolider avant de changer de sujet |
| Fin de journée              | Toujours consolider                  |

---

## 👥 Multi-agents : Codex + Cline + autres

Live Memory permet à **plusieurs agents** de collaborer sur le même espace mémoire :

1. Créer un token par agent (`codex-agent`, `cline-agent`, `claude-agent`, etc.)
2. Configurer chaque agent avec son propre token
3. Tous les agents partagent le même `space_id`

L'identité de l'agent est **automatiquement déduite depuis le token** — aucune spécification manuelle n'est nécessaire.

La communication inter-agents se fait **via l'espace partagé** :

```
Codex  → live_note(category="todo", content="Ajouter la pagination sur /users")
Cline  → live_read(category="todo")  ← voit la tâche de Codex
Cline  → live_note(category="progress", content="Pagination implémentée")
Codex  → live_read(category="progress")  ← reprend là où Cline s'est arrêté
```

---

## 🔍 Dépannage

### Codex ne voit pas les outils Live Memory

1. Vérifiez que `config.toml` est au bon emplacement et que la syntaxe TOML est valide
2. Assurez-vous que `enabled = true` est bien présent dans la section `[mcp_servers.my-live-mem]`
3. Confirmez que l'URL se termine par `/mcp`
4. Testez manuellement le token :

```bash
curl -s -H "Authorization: Bearer lm_VOTRE_TOKEN_ICI" \
  https://my.live-mem.mcp.cloud-temple.app/health
```

### Erreur « 401 Unauthorized »

- Le token est incorrect, expiré ou révoqué
- Vérifiez la valeur du header : `"Authorization" = "Bearer lm_..."` (notez le préfixe `lm_`)
- Vérifiez si le token a été révoqué via la console d'administration

### Erreur « Accès refusé à l'espace »

Le token est restreint à certains espaces (`space_ids`). Deux solutions :
- Créer un token sans restriction d'espace
- Ou ajouter l'espace au token :
  ```
  admin_update_token(token_hash, space_ids_add="mon-projet")
  ```

### La consolidation est lente ou expire

La consolidation LLM prend typiquement 30 à 120 secondes. Si Codex expire :

1. Vérifiez si votre environnement Codex permet de configurer un timeout MCP plus long
2. Suivez la progression côté serveur dans les logs :

```bash
docker compose logs -f live-mem-service --tail 20
```

3. Utilisez `bank_consolidate` — il traite les notes par lots de 10 par défaut

### Erreurs de syntaxe TOML

Erreurs courantes dans `config.toml` :

```toml
# ✅ CORRECT
http_headers = { "Authorization" = "Bearer lm_abc123" }

# ❌ FAUX (syntaxe JSON, pas TOML)
http_headers = { "Authorization": "Bearer lm_abc123" }

# ❌ FAUX (valeur sans guillemets)
http_headers = { "Authorization" = Bearer lm_abc123 }
```

---

## 📊 Récapitulatif

| Étape     | Action                                                           | Durée      |
| --------- | ---------------------------------------------------------------- | ---------- |
| 1         | Obtenir un token (`token create codex-agent`)                    | 1 min      |
| 2         | Éditer `.codex/config.toml` avec l'URL + le header Authorization | 2 min      |
| 3         | Créer un espace mémoire (`space_create`)                         | 30 sec     |
| 4         | Ajouter `AGENTS.md` avec les instructions Memory Bank            | 2 min      |
| **Total** | **Prêt à utiliser**                                              | **~6 min** |

---

*Guide d'intégration Live Memory pour OpenAI Codex v1.0.0 — [Documentation complète](README.fr.md)*
