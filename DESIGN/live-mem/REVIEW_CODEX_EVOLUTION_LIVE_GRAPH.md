# Review codex — Évolution Live ↔ Graph Memory

## 1. Lecture du document

J’ai lu le document complet, sections 1 à 7 et annexes, puis confronté les hypothèses aux zones de code concernées : `graph_push`, `GraphBridgeService.push`, `_meta.json`, `bank_compact`, `bank_repair`, `backup_restore` et les docs de concurrence.

Diagnostic général : la direction est bonne. La séparation Live Memory = bootstrap compact, Graph Memory = index sémantique durable, dépôt Git = autorité finale est saine.

Mais le document sous-estime un point critique : aujourd’hui `graph_push` ne fait pas seulement un push, il fait aussi un **nettoyage d’orphelins** dans Graph Memory. Donc tout document Graph dont le `filename` n’est plus dans la bank peut être supprimé. C’est acceptable pour une projection “bank only”, dangereux si le même `memory_id` contient aussi des documents canoniques.

## 2. Tranchage des 5 questions ouvertes (B-Q1 à C-Q2)

### B-Q1 — Refus silencieux vs erreur explicite

Je valide **B-Q1.a**, mais je refuse le terme “silencieux”.

Recommandation : `status="ok"` avec `skipped_volatile`, mais aussi un champ explicite type `message` / `warning` / `volatile_policy`. Le comportement doit être non bloquant, pas invisible.

Justification technique :

- Une erreur serait trop cassante pour les clients existants qui appellent déjà `graph_push`.
- Le garde-fou vise à empêcher l’ingestion volatile, pas à casser les workflows.
- En revanche, la réponse doit rendre le filtrage impossible à manquer.

Point à corriger dans le document : la réponse proposée `{ pushed: [...] }` est potentiellement breaking, car le code actuel retourne `pushed` comme entier. Je garderais `pushed: int` et j’ajouterais `pushed_files: [...]`.

Durcissement recommandé : `include_volatile=True` devrait exiger `manage`, pas seulement `write`. Le debug/migration explicite est une opération de maintenance, pas une opération writer standard.

### B-Q2 — Noms exacts vs glob patterns

Je valide **B-Q2.a**, avec une précision importante : filtre par chemins relatifs normalisés, pas par chaîne brute.

Justification :

- Les globs introduisent trop vite des suppressions surprenantes.
- Le besoin réel v1 est très étroit : `activeContext.md` et `progress.md`.
- La bank supporte des sous-dossiers et `bank_repair` montre qu’il existe des cas de noms corrompus ou préfixés. Un filtre exact naïf peut donc rater `1.MEMORY_BANK/activeContext.md` ou un nom avec caractères invisibles.

Recommandation concrète : appliquer le filtre après `bank_relpath`, trim, normalisation Unicode si déjà utilisée ailleurs, et idéalement la même logique de sanitation que `bank_repair` pour détecter les variantes évidentes des deux fichiers volatiles.

### B-Q3 — Aucun fichier non volatile après filtrage

Je valide `status="ok", pushed=0`, mais avec une nuance forte.

Si seuls `activeContext.md` et `progress.md` restent après filtrage, le serveur ne doit pas juste retourner tôt. Il doit décider explicitement ce qu’il fait des documents déjà présents dans Graph.

Ma recommandation :

- `status="ok"`
- `pushed=0`
- `skipped_volatile=[...]`
- `message="No non-volatile bank files to push"`
- et surtout : si Graph contient déjà ces fichiers volatiles, les supprimer ou les lister dans `cleaned_volatile`.

Justification : sinon Vague B empêche les nouveaux pushs volatiles, mais laisse en place la dette existante. Or le problème initial est aussi la présence stale de ces documents dans Graph.

### C-Q1 — Config dans `_meta.json` vs YAML dépôt

Je ne valide pas **C-Q1.a** comme cible produit. Je recommande **C-Q1.c** dès la v1, mais avec un périmètre minimal.

Raisonnement :

- Les `canonical_sources` décrivent des chemins de dépôt. C’est une configuration repo, donc elle doit être versionnable, relue, reviewée, et alignée avec les PR.
- Stocker uniquement dans `_meta.json` crée un état caché côté S3. C’est pratique serveur, mais mauvais pour l’audit et le drift.
- `backup_restore` restaurerait aussi une ancienne config `canonical_sources`, potentiellement désynchronisée du dépôt actuel.

Recommandation : YAML dépôt comme source recommandée, `_meta.json` comme snapshot actif côté serveur. Si on veut aller vite, on peut commencer par `_meta.json`, mais il faut l’assumer comme étape transitoire, pas comme architecture cible.

### C-Q2 — Live Memory planifie vs Live Memory pousse

Je valide **C-Q2.a** : Live Memory planifie, l’agent pousse.

Justification technique :

- Live Memory ne lit pas le dépôt Git de l’agent.
- Le transformer en proxy de blobs augmente la surface : payloads base64 lourds, retries, timeouts, stockage temporaire, sécurité, responsabilité sur les contenus.
- L’agent est le mieux placé pour calculer SHA-256, résoudre les chemins, appliquer les exclusions et confirmer le fichier canonique dans Git.

Conséquence : le nom `canonical_ingest` est un peu ambitieux si la v1 ne fait que planifier. Je cadrerais la v1 comme outil de plan/check, pas d’apply serveur.

## 3. Points aveugles identifiés

- **Orphan cleanup dangereux** : `graph_push` supprime les documents Graph absents de la bank. Si des documents canoniques partagent le même `memory_id`, ils peuvent être effacés. Il faut documenter ou empêcher ce mélange.

- **Réponse breaking** : changer `pushed` de `int` vers `list` casserait des clients. Ajouter des champs, ne pas remplacer les existants.

- **Permission insuffisante pour opt-in volatile** : `include_volatile=True` ne devrait pas être accessible à tout token `write`.

- **Race condition bank / graph_push** : `bank_compact` et `bank_consolidate` prennent un lock, mais `graph_push` lit sans lock. Il peut pousser un snapshot intermédiaire. Le document doit assumer ce risque ou prendre le lock en lecture/maintenance.

- **Multi-réplica** : les locks actuels sont in-process. En multi-réplica, `_meta.json` et la bank peuvent subir des read-modify-write concurrents. Vague B ne crée pas le problème, mais l’accentue si on ajoute config et métriques.

- **CacheService roadmap** : si `_meta.json`, bank list ou bank content sont cachés, il faudra invalider après `graph_connect`, `graph_disconnect`, `graph_push`, update `canonical_sources`, `bank_compact`, `bank_repair`, `backup_restore`.

- **`bank_compact`** : Graph ne doit pas devenir l’archive pré-compaction. Le document est cohérent avec ça, mais il faut éviter qu’un `graph_push` post-compaction efface des documents Graph d’archive ou canoniques.

- **`bank_repair`** : les noms corrompus peuvent contourner un filtre exact naïf. Les tests Vague B doivent inclure variantes Unicode/préfixes parasites.

- **`backup_restore`** : restaure `_meta.json`, donc restaure aussi `graph_memory` et potentiellement `canonical_sources`. Il ne restaure pas Graph Memory lui-même. Après restore, un `graph_push` peut agir sur une config ancienne.

- **`check-remote` Vague C** : je doute que l’API Graph Memory actuelle expose déjà le SHA-256 par document. Sans hash distant, `SKIP / UPDATE / INGEST` fiable n’est pas possible, sauf à stocker cette métadonnée ailleurs ou à réduire l’ambition.

- **`source_path` vs `filename`** : le code actuel ingère avec `filename`. Le document parle de `source_path`. Il faut confirmer que Graph Memory supporte bien cette clé stable, ou mapper explicitement `source_path` vers `filename`.

## 4. Séquencement Vagues B et C

Les travaux de design peuvent avancer en parallèle, mais l’implémentation ne devrait pas.

Je recommande une dépendance opérationnelle : **Vague B d’abord**, puis Vague C.

Raison : tant que `graph_push` peut pousser ou nettoyer sans garde-fou clair, introduire une ingestion canonique augmente le risque d’effacer ou de polluer le graphe. La Vague B stabilise le contrat serveur. La Vague C construit ensuite au-dessus.

Exception : on peut préparer en parallèle le schéma `canonical_sources` et les tests de planification, sans brancher d’apply.

## 5. Recommandation finale d’implémentation

Ordre recommandé :

1. **Vague B stricte et courte**
   - Filtrer les volatiles par défaut.
   - Garder la réponse rétrocompatible.
   - Ajouter `skipped_volatile`, `pushed_files`, éventuellement `cleaned_volatile`.
   - Exiger `manage` pour `include_volatile=True`.
   - Tester le nettoyage des volatiles déjà présents dans Graph.

2. **Clarification Graph Memory avant Vague C**
   - Confirmer support de `source_path` ou mapping vers `filename`.
   - Confirmer disponibilité d’un hash distant pour `check-remote`.
   - Décider si canonical docs et bank bootstrap peuvent partager un `memory_id`. Ma réponse actuelle : non, sauf namespace/origin fiable.

3. **Vague C v1 plan/check uniquement**
   - Pas de proxy blob.
   - Agent propriétaire du contenu et du SHA.
   - YAML dépôt recommandé, `_meta.json` snapshot serveur.
   - Pas d’`apply` serveur tant que l’identité documentaire Graph n’est pas fiable.

Critères pour passer de B à C :

- Aucun `graph_push` sans opt-in ne pousse `activeContext.md` ou `progress.md`.
- Les anciens volatiles déjà présents sont détectés/nettoyés ou explicitement reportés.
- Les tests couvrent noms normaux, noms corrompus, config env, opt-in audité, et cas “only volatile”.
- La documentation prévient clairement que `graph_push` ne doit pas être utilisé sur un Graph `memory_id` contenant des documents canoniques, sauf mécanisme de séparation confirmé.
