# Compactage extractif hiérarchique — Live Memory 2.8.0

**Status: local product gate passed — production remains frozen**

## Décision

La Memory Bank possède déjà trois rôles complémentaires :

- `activeContext.md` est l'autorité de l'état courant et n'est jamais compacté ;
- `systemPatterns.md` est l'autorité des connaissances techniques durables ;
- `progress.md` est un historique borné qui complète ces deux autorités.

Qwen 35B ne génère plus le Markdown compacté. Il classe uniquement des IDs
d'unités Markdown complètes. Le serveur conserve les unités importantes dans
leurs octets source exacts et supprime les autres. Un résumé fidèle n'est donc
pas exhaustif : il conserve le sens global et les points utiles à la reprise,
sans conserver chaque répétition, métrique ou état intermédiaire.

## Algorithme unique

```mermaid
flowchart LR
    A["Banque logique complète"] --> B["Classement des H3 de systemPatterns"]
    B --> C["Candidat systemPatterns exact"]
    C --> D["Classement de progress avec activeContext + systemPatterns"]
    D --> E["Candidats complets en mémoire"]
    E --> F["Backup global"]
    F --> G["Écritures canoniques vérifiées"]
    G --> H["Rollback global au moindre échec"]
```

1. `markdown-it-py` produit l'unique vue Markdown.
2. `systemPatterns.md`, seulement s'il dépasse la limite, est découpé en
   sections H3 indivisibles, bornées par le prochain H1, H2 ou H3.
3. Qwen retourne un classement d'IDs. Le code retient gloutonnement les
   sections exactes qui tiennent sous la limite.
4. `progress.md`, seulement s'il dépasse la limite, est découpé en entrées
   datées complètes : item de liste de premier niveau ou H3 avec son corps.
5. Le dernier jour, les entrées non datées, fences, blocs indentés et HTML sont
   hors sélection. Le budget historique utilise 75 % de la place disponible.
6. Qwen classe ces IDs avec `activeContext.md` et le candidat exact de
   `systemPatterns.md` comme autorités.
7. Tous les candidats sont validés en mémoire avant le premier backup ou write.
8. La transaction 2.7.3 existante assure backup, écriture canonique, relecture,
   rollback global et FIFO par espace.

## Contrat LLM

- modèle configuré, qualifié avec `qwen3.6:35b` ;
- température zéro et thinking désactivé ;
- maximum 2 000 tokens de sortie ;
- un appel par fichier surdimensionné, donc deux appels maximum ;
- sortie utilisée uniquement comme classement d'IDs ;
- IDs inconnus et doublons ignorés, au moins un ID connu obligatoire ;
- aucun retry, modèle secondaire, JSON d'édition ou prose persistée.

## Échecs fermés

Avant tout backup et toute écriture, l'ensemble du job échoue si :

- `activeContext.md` dépasse la limite ;
- un fichier hors `systemPatterns.md` ou `progress.md` dépasse la limite ;
- une autorité de `progress.md` manque ;
- un prompt dépasse la fenêtre du modèle ;
- Qwen ne retourne aucun ID connu ou une réponse complète ;
- un candidat dépasse la limite finale.

Une famille legacy split sous la limite est toujours réassemblée exactement,
sans Qwen. Un échec d'écriture après le backup déclenche le rollback global
existant. L'auto-compaction en échec bloque la consolidation suivante : aucune
note live n'est consommée et aucune autre mutation n'est engagée.

## Preuves acquises

Le prototype isolé, avec une limite de 35 000 octets, a passé les deux banques
réelles et leur revue humaine :

| Banque | Appels | `systemPatterns.md` | `progress.md` | `activeContext.md` |
| --- | ---: | ---: | ---: | ---: |
| `mcp-agent` | 2 | 37 133 → 34 399 o | 120 534 → 28 068 o | 7 723 o exact |
| `agentic-platform` | 1 | 32 894 o exact | 166 512 → 27 253 o | 15 625 o exact |

L'intégration serveur a ensuite reproduit ces résultats sur le Docker local,
avec `BANK_FILE_MAX_SIZE=35000`, S3 disponible et le vrai
`qwen3.6:35b`. Chaque passe a commencé par une restauration byte-exacte de la
fixture :

| Banque | Passes | Résultat | Hashes de sortie stables |
| --- | ---: | --- | --- |
| `mcp-agent` | 3/3 | succès, 2 appels, 0 fichier en échec | `progress.md` `280df41c...6e99`, `systemPatterns.md` `71bf12d2...a8b4` |
| `agentic-platform` | 3/3 | succès, 1 appel, 0 fichier en échec | `progress.md` `29570b5c...4dffd` |

La séparation finale place le contrat et le budget dans le message `system` ;
le message `user` ne contient que les données non fiables. Après ce changement,
les résultats ont été relus comme une banque combinée : les faits retirés de
`progress.md` mais déjà présents dans `systemPatterns.md` restent byte-exacts,
notamment le contrat `sub_agent_ids` et le risque `BROKER_SIGNING_ENC_KEY`.
Le nombre d'appels est borné, mais la latence des services externes reste
variable. Pendant une coupure VPN, deux timeouts et un `AccessDenied` S3 DEV
antérieurs à tout appel Qwen ont échoué fermés, sans backup ni mutation. Après
retour du VPN et du healthcheck, les passes manquantes ont été rejouées depuis
les fixtures exactes et ont réussi. Les backups ont précédé les écritures
canoniques à chaque passe réussie. La suite complète passe avec
`496 passed, 1 xfailed`; le lint et les contrôles de diff/compilation sont
verts.

Ce gate autorise la finalisation locale du code et de sa revue. Il n'autorise
ni bump de version, ni push, ni PR, ni activation en production. Ces actions
restent soumises aux gates de livraison et au canari manuel convenus.

## Non-objectifs 2.8.0

- archive hot/cold, RAG, Graph Memory ou recherche sémantique ;
- résumé génératif persisté ;
- second compacteur, modèle de secours, retry ou option de stratégie ;
- éditeur Markdown générique ;
- changement du backup, du stockage S3, de la queue ou de la FIFO ;
- activation automatique en production avant un canari manuel validé.

## Références de recherche

- Ladhak et al., *Faithful or Extractive?*, ACL 2022 :
  <https://aclanthology.org/2022.acl-long.100/>
- Zhang et al., *Extractive is not Faithful*, ACL 2023 :
  <https://aclanthology.org/2023.acl-long.120/>
- Liu et al., *Lost in the Middle*, TACL 2024 :
  <https://arxiv.org/abs/2307.03172>
- Xu et al., *RECOMP*, ICLR 2024 :
  <https://openreview.net/forum?id=mlJLVigNHp>
