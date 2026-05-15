# ❓ FAQ — Live Memory

---

## Concepts généraux

### Quelle est la différence entre Live Memory et graph-memory ?

|                  | **Live Memory**                  | **graph-memory**                   |
| ---------------- | -------------------------------- | ---------------------------------- |
| **Type**         | Mémoire de travail               | Mémoire long terme                 |
| **Données**      | Notes live + bank Markdown       | Knowledge Graph + embeddings       |
| **Stockage**     | S3 (fichiers)                    | Neo4j + Qdrant                     |
| **Intelligence** | LLM consolide les notes en bank  | RAG vectoriel pour la recherche    |
| **Analogie**     | Tableau blanc → Cahier de projet | Bibliothèque → Moteur de recherche |

Les deux sont complémentaires. Live Memory est pour le travail quotidien, graph-memory pour la connaissance persistante.

### C'est quoi un "espace" (space) ?

Un espace mémoire isolé = un projet. Il contient :
- **Rules** : template Markdown qui définit la structure de la bank
- **Notes live** : observations, décisions, todos... des agents (append-only)
- **Bank** : fichiers Markdown consolidés par le LLM selon les rules

### C'est quoi les "rules" ?

Les rules définissent la structure de la Memory Bank. Elles sont écrites en Markdown à la création de l'espace et sont **immuables**. Le LLM les utilise pour créer et maintenir les fichiers bank.

Exemple de rules (standard Memory Bank) :
```markdown
### projectbrief.md
Objectifs, périmètre, critères de succès.

### activeContext.md
Focus actuel, changements récents, prochaines étapes.

### progress.md
Ce qui fonctionne, ce qui reste, problèmes connus.
```

---

## Agents et tokens

### Quelle est la relation entre un token et un agent ?

Depuis **v0.8.1**, chaque token **est** un agent. Le `client_name` du token est automatiquement utilisé comme identité de l'agent — il n'y a plus de paramètre `agent=` dans `live_note`.

|                        | **Token = Agent**                             |
| ---------------------- | --------------------------------------------- |
| **Rôle**               | Authentification **et** identité              |
| **Exemple**            | Token `cline-dev` → agent `cline-dev`         |
| **Partageable ?**      | Non — 1 token = 1 agent = 1 identité          |
| **Où est-il fourni ?** | Header `Authorization: Bearer` (auto-détecté) |

**Pourquoi ce changement ?** L'ancien modèle (Token ≠ Agent) permettait de passer un nom d'agent libre, ce qui causait des notes orphelines (agent non reconnu à la consolidation), de l'usurpation d'identité, et de l'éparpillement.

### Un agent peut-il lire les notes d'un autre agent ?

Oui ! `live_read(space_id="mon-projet")` retourne les notes de TOUS les agents. C'est le principe de la collaboration : chaque agent voit le travail des autres. Vous pouvez aussi filtrer par agent : `live_read(space_id="mon-projet", agent="claude-review")`.

---

## Permissions et sécurité

### Quels sont les niveaux de permission ?

Depuis **v1.5.0**, il y a 4 niveaux **hiérarchiques et cumulatifs** :

| Niveau     | Inclut                | Accès                                                                                                                                             |
| ---------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **read**   | —                     | Lecture : `bank_read`, `live_read`, `space_info`, `backup_list`, etc.                                                                             |
| **write**  | read                  | Écriture : `live_note`, `bank_consolidate`, `space_create`, etc.                                                                                  |
| **manage** | write + read          | Maintenance : `bank_write`, `bank_delete`, `bank_repair`, `bank_compact`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete` |
| **admin**  | manage + write + read | Administration : `admin_create_token`, `admin_gc_notes`, etc.                                                                                     |

Un token `write` ne peut **pas** modifier directement les fichiers bank ni supprimer des espaces — il faut `manage` ou `admin`.

### Pourquoi les permissions sont-elles cumulatives ?

Chaque niveau **inclut automatiquement** tous les niveaux inférieurs. Il n'est pas nécessaire de spécifier `read,write` si vous donnez `manage` — `manage` contient déjà `write` et `read`.

```
read < write < manage < admin
```

En pratique, lors de la création ou mise à jour d'un token, spécifiez toujours la **liste complète** des permissions (ex : `"read,write,manage"`), car le champ `permissions` est une **liste explicite** stockée sur S3, pas un niveau unique. Le serveur vérifie la présence du niveau requis dans cette liste.

### Quel type de token créer selon mon cas d'usage ?

| Cas d'usage | Permissions recommandées | `space_ids` |
| --- | --- | --- |
| Agent IA en mode travail (Cline, Claude) | `read,write` | Espaces du projet |
| Agent IA + maintenance (compaction, repair) | `read,write,manage` | Espaces du projet |
| Opérateur humain (maintenance multi-projets) | `read,write,manage` | Tous les espaces concernés |
| Administrateur | `read,write,manage,admin` | Vide (admin voit tout) |
| Lecteur / dashboard de monitoring | `read` | Espaces à surveiller |

### Comment restreindre un token à certains espaces ?

Chaque token a un champ `space_ids` qui liste les espaces autorisés :

```bash
# Restreindre KSE à 3 espaces
python scripts/mcp_cli.py token update sha256:363... -p "read,write" -s "live-mem,graph-mem,mcp-office"
```

**Sémantique de `space_ids` (v1.5.0+)** :
- `space_ids = ["a", "b"]` → accès uniquement à ces espaces
- `space_ids = []` pour un **non-admin** → **aucun accès** (changed in v1.5.0, avant = tout)
- `space_ids = []` pour un **admin** → accès à **tout** (inchangé)

À la **création** d'un token via `admin_create_token`, vous pouvez utiliser :
- `space_ids=""` (défaut) → token "muet" (aucun accès aux espaces existants). La réponse contient un champ `warning_no_access` pour vous le signaler explicitement.
- `space_ids="a,b,c"` → liste explicite.
- `space_ids="*"` ou `space_ids="all"` → **snapshot** de tous les espaces existants au moment de la création (pas les futurs spaces, c'est volontaire pour rester aligné avec la sémantique stricte v1.5.0).

### Le hash retourné par `admin_list_tokens` contient `sha256:` — faut-il le passer tel quel ?

Depuis l'issue #11, **les deux formes sont acceptées** par `admin_revoke_token`, `admin_delete_token` et `admin_update_token` :
```bash
admin_update_token(token_hash="sha256:f172084ef03...", space_ids="x")  # OK
admin_update_token(token_hash="f172084ef03...", space_ids="x")          # OK aussi
```

Le minimum reste 16 caractères hex (8 octets de hash) pour éviter les collisions accidentelles.

### Que se passe-t-il quand un token crée un nouveau space ?

Le space est **automatiquement ajouté** au `space_ids` du token (via `add_space_to_token()`). Ainsi un token restreint à `["projet-a"]` qui crée `projet-b` se retrouve avec `["projet-a", "projet-b"]`. Pas de deadlock UX.

### Comment ajouter la permission `manage` à un token ?

```bash
python scripts/mcp_cli.py token update sha256:xxx -p "read,write,manage"
```

⚠️ La mise à jour des permissions **remplace** la liste complète — il faut toujours inclure `read,write` en plus de `manage`.

### Que s'est-il passé lors de la migration v1.5.0 ?

Avant v1.5.0, `space_ids=[]` signifiait "accès à tout". Depuis v1.5.0, ça signifie "aucun accès" (pour les non-admin).

**Migration automatique au démarrage** : tous les tokens non-admin ayant `space_ids=[]` se sont vu assigner automatiquement la liste de **tous les espaces existants**. Aucune perte d'accès.

### Puis-je donner les droits admin à un token ?

Oui, mais avec prudence :
```bash
python scripts/mcp_cli.py token update sha256:xxx -p "read,write,manage,admin"
```

Un token admin peut gérer les tokens des autres, consolider les notes de tous les agents, et exécuter le GC. Il voit tous les espaces quel que soit son `space_ids`.

---

## Consolidation

### Comment fonctionne la consolidation ?

1. Le LLM (qwen3.5:27b) lit les **rules**, la **bank actuelle**, la **synthèse précédente**, et les **notes live**
2. Il produit des fichiers bank mis à jour (Markdown pur)
3. Les notes consolidées sont **supprimées** de `live/`
4. Une synthèse résiduelle est sauvegardée

### Que se passe-t-il si 2 agents consolident en même temps ?

Un `asyncio.Lock` par espace empêche les consolidations simultanées :
- Le premier agent acquiert le lock → consolidation LLM (15-30s)
- Le second reçoit `{"status": "conflict"}` → doit réessayer

C'est voulu : les deux agents écrivent dans les mêmes fichiers bank. La consolidation séquentielle permet à chaque agent de voir le travail du précédent.

### Puis-je consolider les notes de TOUS les agents d'un coup ?

Oui ! `bank_consolidate(space_id="mon-projet")` sans paramètre `agent=` consolide toutes les notes de tous les agents en une seule fois.

⚠️ **Permissions** : consolider les notes d'un autre agent ou de tous les agents nécessite un token **manage** (ou admin). Un token write ne peut consolider que ses propres notes (`agent="mon-nom"`).

### Que deviennent les notes après consolidation ?

Elles sont **supprimées** de `live/`. Leur contenu est intégré dans les fichiers bank. C'est irréversible (d'où l'intérêt des backups).

### Le consolidateur peut-il inventer du contenu (halluciner) ?

Depuis la **v1.9.0**, le consolidateur intègre **7 règles anti-hallucination** dans son prompt système :

1. **Attribution stricte aux sources** — tout fait dans la bank DOIT provenir d'une note. Si une section n'a pas de source, elle reste vide ou marquée "À définir".
2. **Préservation du vocabulaire métier** — les termes spécifiques au projet sont utilisés verbatim, jamais ré-interprétés via les priors du LLM.
3. **Gating des métriques** — les chiffres n'apparaissent que s'ils sont explicitement sourcés dans une note.
4. **Pas de structure inventée** — les arborescences de fichiers ne sont PAS générées si les notes ne les décrivent pas.
5. **Isolation par agent/tâche** — les faits de différents agents ou tâches indépendantes ne sont jamais fusionnés dans la même phrase.
6. **Retrait des éléments remplacés** — quand une note `decision` remplace un plan, les anciens items sont retirés.
7. **Inférence transitive sur les statuts** — si l'étape N+1 est terminée, l'étape N est marquée terminée.

De plus, chaque note est transmise au LLM avec ses **métadonnées** `[agent, catégorie, tags]`, permettant une isolation correcte des sources.

**Si vous constatez encore du contenu halluciné**, signalez-le sur l'[Issue #17](https://github.com/Cloud-Temple/live-memory/issues/17) avec les notes et la bank produite.

### Qu'est-ce que la compaction de bank (`bank_compact`) ?

Quand les fichiers bank deviennent trop volumineux (> `BANK_FILE_MAX_SIZE`, 15 KB par défaut), ils peuvent causer des échecs de consolidation (dépassement du context window LLM) ou des performances dégradées.

`bank_compact` résume les fichiers surdimensionnés via un appel LLM dédié, en préservant les décisions clés et les jalons tout en supprimant les détails obsolètes.

```bash
# Scan seul (dry-run, par défaut)
python scripts/mcp_cli.py bank compact mon-espace

# Appliquer la compaction
python scripts/mcp_cli.py bank compact mon-espace --apply
```

L'**auto-compaction** est également déclenchée automatiquement avant la consolidation si la bank dépasse `COMPACT_THRESHOLD` (60% par défaut) du budget de sortie du LLM.

### Puis-je utiliser un proxy HTTP pour les connexions sortantes ?

Oui ! Depuis la **v1.8.1**, définissez `PROXY_URL` dans `.env` :

```env
PROXY_URL=http://10.0.0.1:3128
```

Cela route le trafic S3 (boto3) et LLM (httpx) via le proxy. C'est une **variable custom** (pas `HTTP_PROXY`) pour ne pas affecter les autres bibliothèques Python. Les connexions Graph Memory ne sont pas supportées via le proxy.

---

## Garbage Collector

### Pourquoi un Garbage Collector ?

Si un agent écrit des notes mais ne consolide jamais (crash, suppression, oubli), les notes s'accumulent sans fin dans `live/`. Le GC identifie et traite ces notes orphelines.

### Comment fonctionne le GC ?

3 modes via `admin_gc_notes` :

| Mode              | Paramètres                       | Action                                                                 |
| ----------------- | -------------------------------- | ---------------------------------------------------------------------- |
| **Dry-run**       | `confirm=False` (défaut)         | Scanne et rapporte                                                     |
| **Consolidation** | `confirm=True`                   | Consolide les notes dans la bank via LLM + ajoute une notice "⚠️ GC" |
| **Suppression**   | `confirm=True, delete_only=True` | Supprime sans consolider (perte de données)                            |

Par défaut, le GC **consolide** (ne supprime pas) pour ne pas perdre de données.

### Le GC laisse-t-il une trace dans la bank ?

Oui ! Le GC écrit une note spéciale avant chaque consolidation :
```
⚠️ GARBAGE COLLECTOR — Consolidation forcée
Le GC a détecté X notes orphelines de l'agent 'nom-agent' (> 7 jours).
Ces notes n'ont jamais été consolidées par l'agent.
```

Le LLM voit cette note et l'intègre dans la bank, assurant la traçabilité.

---

## Docker et déploiement

### Comment tester en local ?

```bash
# 1. Configurer l'environnement
cp .env.example .env
nano .env  # Remplir S3, LLMaaS, ADMIN_BOOTSTRAP_KEY

# 2. Lancer le stack
docker compose build
docker compose up -d

# 3. Tester
python scripts/test_recette.py           # Recette simple
python scripts/test_multi_agents.py      # Multi-agents
python scripts/test_gc.py                # Garbage Collector
```

### Comment fonctionne le WAF ?

Caddy + Coraza (OWASP CRS) protège contre les injections, XSS, etc. Les routes MCP (SSE + messages) passent **sans** WAF (authentifiées par token côté serveur). Les autres routes passent par le WAF.

### Pourquoi les routes SSE ne passent pas par le WAF ?

Coraza bufférise les réponses pour les inspecter, ce qui est **incompatible** avec le streaming SSE (connexions longues, flux continu). L'authentification est gérée côté serveur MCP.

### Comment déployer en production ?

1. Mettre `SITE_ADDRESS=mon-domaine.com` dans `.env`
2. Exposer les ports 80+443 dans docker-compose.yml
3. Caddy obtient automatiquement un certificat Let's Encrypt
4. Voir [DEPLOIEMENT_PRODUCTION.md](DESIGN/live-mem/DEPLOIEMENT_PRODUCTION.md) pour les détails

---

## S3 et stockage

### Pourquoi S3 et pas une base de données ?

- Simplicité : pas de schéma, pas de migrations, pas de serveur DB
- Portabilité : tout est fichier Markdown/JSON
- Scalabilité : S3 gère des milliards d'objets
- Coût : stockage S3 très bon marché

### Pourquoi deux clients S3 (SigV2 + SigV4) ?

Contrainte de Dell ECS (S3 Cloud Temple) :
- SigV2 pour les opérations de données (PUT, GET, DELETE)
- SigV4 pour les opérations de métadonnées (HEAD, LIST)

Si vous utilisez AWS S3 ou MinIO, un seul client SigV4 suffit.

### Puis-je utiliser AWS S3 ou MinIO ?

Oui ! Configurez `S3_ENDPOINT_URL` et les credentials. Le dual SigV2/V4 n'est nécessaire que pour Dell ECS. Pour les autres providers S3, modifiez `core/storage.py` pour utiliser un seul client.

---

## CLI et Shell

### Comment configurer la CLI ?

3 façons de passer l'URL et le token :

```bash
# 1. Variables d'environnement
export MCP_URL=http://localhost:8080
export MCP_TOKEN=lm_xxx
python scripts/mcp_cli.py health

# 2. Paramètres CLI
python scripts/mcp_cli.py --url http://mon-serveur:8080 --token lm_xxx health

# 3. Automatique (lit .env)
python scripts/mcp_cli.py health   # URL défaut 8080, token depuis .env
```

### Comment avoir l'aide sur une commande ?

```bash
# CLI Click (--help natif)
python scripts/mcp_cli.py space --help
python scripts/mcp_cli.py bank consolidate --help

# Shell interactif
live-mem> help           # aide globale
live-mem> help space     # sous-commandes de space
live-mem> space          # idem
live-mem> help bank      # sous-commandes de bank
```

### Puis-je utiliser la CLI en mode JSON pour le scripting ?

Oui ! Ajoutez `--json` (CLI) ou `--json` (shell) à n'importe quelle commande :

```bash
python scripts/mcp_cli.py space list --json | jq '.spaces[].space_id'
```

---

## Troubleshooting — Problèmes courants

### J'ai un 403 sur tous les espaces

**Cause la plus fréquente** : votre token a `space_ids=[]` (aucun accès). Depuis v1.5.0, un token non-admin sans `space_ids` ne peut accéder à rien.

**Diagnostic** :
```bash
python scripts/mcp_cli.py token list --json | jq '.tokens[] | select(.name=="mon-token") | .space_ids'
```

**Solution** : demander à un admin de mettre à jour vos espaces :
```bash
python scripts/mcp_cli.py token update sha256:xxx -s "espace-a,espace-b"
```

### Mon token `manage` ne peut rien faire

Un token `manage` sans `space_ids` est un "mainteneur sans rien à maintenir". Il peut uniquement créer de nouveaux espaces (qui seront auto-ajoutés à ses `space_ids`).

**Solution** : ajouter les espaces à gérer :
```bash
python scripts/mcp_cli.py token update sha256:xxx -s "espace-a,espace-b"
```

### La consolidation échoue avec "LLM returned invalid JSON"

Cause probable : la bank est trop volumineuse. Le LLM a un context window limité et peut échouer sur les réponses JSON longues.

**Solutions** :
1. Compacter la bank : `bank_compact mon-espace --apply`
2. Vérifier les tailles : `bank_list mon-espace` — si un fichier dépasse 15 KB, c'est un candidat à la compaction
3. Relancer la consolidation après compaction

### `bank_consolidate` retourne "conflict"

Un autre agent (ou vous-même dans un autre terminal) est en train de consolider le même espace. Le lock `asyncio` protège contre les écritures concurrentes.

**Solution** : attendre 15-30 secondes et réessayer.

### Je ne retrouve plus mes notes après consolidation

C'est normal ! Les notes sont **supprimées** de `live/` après consolidation. Leur contenu est intégré dans les fichiers bank. Utilisez `bank_read_all` pour retrouver le contenu consolidé.

Si vous pensez que des notes ont été perdues, vérifiez la synthèse résiduelle : `space_summary mon-espace`.

---

## Limites et performances

### Combien de notes peut-on écrire ?

Pas de limite théorique. Chaque note = 1 fichier S3 (~200-500 octets). La consolidation traite jusqu'à 500 notes à la fois (`CONSOLIDATION_MAX_NOTES`).

### Quelle est la latence ?

| Opération                     | Latence typique |
| ----------------------------- | --------------- |
| `live_note` (écriture)        | ~50ms           |
| `live_read` (lecture)         | ~100ms          |
| `bank_consolidate` (12 notes) | ~15-30s         |
| `bank_read_all` (6 fichiers)  | ~200ms          |
| `system_health`               | ~500ms          |

### Combien d'agents simultanés ?

Pas de limite sur le nombre d'agents écrivant en parallèle (append-only, zéro conflit). La consolidation est séquentielle par espace (1 à la fois).
