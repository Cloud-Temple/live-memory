# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Graph (4 outils).

Pont entre Live Memory et Graph Memory : connecter un space à une
instance de graphe de connaissances et y pousser la memory bank.

Permissions :
    - graph_connect     ✏️ (write) — Connecte un space à Graph Memory
    - graph_push        ✏️ (write) — Pousse la bank dans Graph Memory
    - graph_status      🔑 (read)  — Statut de la connexion + stats graphe
    - graph_disconnect  ✏️ (write) — Déconnecte le space de Graph Memory

Le push utilise une synchronisation intelligente :
    - Les fichiers existants sont supprimés puis ré-ingérés (recalcul du graphe)
    - Les fichiers disparus de la bank sont nettoyés dans le graphe
    - Les métriques de push sont tracées dans _meta.json

Voir core/graph_bridge.py pour la logique métier et le client MCP Streamable HTTP.
"""

import ipaddress
from typing import Annotated, Optional
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


# LM2-02 fix : validation anti-SSRF du paramètre `url` de graph_connect.
# Sans cette validation, n'importe quel token `write` pouvait faire émettre
# une requête HTTP depuis le pod live-mem vers une URL arbitraire (IP privée,
# metadata cloud 169.254.169.254, ...). L'URL persiste ensuite dans
# `_meta.json` et est ré-utilisée à chaque graph_push.
_ALLOWED_GM_SCHEMES = ("http", "https")


def _validate_gm_url(url: str) -> Optional[str]:
    """
    Valide une URL de Graph Memory pour prévenir le SSRF.

    Retourne None si l'URL est sûre, sinon un message d'erreur explicite
    qui sera renvoyé tel quel à l'appelant (pas de fuite d'info sensible
    — on dit juste ce qui est invalide).

    Politique :
    - scheme : http ou https uniquement (interdit file://, gopher://, ...)
    - hostname : présent et non vide
    - si hostname est une IP littérale :
      - les IPs privées (RFC 1918) sont bloquées
      - les IPs loopback (127.0.0.0/8) sont bloquées
      - les IPs link-local (169.254.0.0/16 → metadata cloud AWS/GCP/Azure)
        sont bloquées
      - les IPs unspecified (0.0.0.0) sont bloquées
      - les IPs multicast sont bloquées
    - si hostname est un DNS : accepté tel quel (la résolution est confiée
      au DNS du conteneur ; pour un anti-SSRF plus strict il faudrait
      résoudre le DNS et valider l'IP résolue, mais cela introduit une
      TOCTOU et n'est pas couvert par cette mitigation initiale).
    """
    if not url or not url.strip():
        return "URL Graph Memory requise"

    try:
        u = urlparse(url.strip())
    except Exception:
        return f"URL Graph Memory invalide : '{url[:80]}'"

    if u.scheme not in _ALLOWED_GM_SCHEMES:
        return (
            f"Scheme non autorisé pour Graph Memory : '{u.scheme}'. "
            f"Attendu : {', '.join(_ALLOWED_GM_SCHEMES)}."
        )

    if not u.hostname:
        return "Hostname requis dans l'URL Graph Memory"

    # Si c'est une IP littérale, on bloque les ranges sensibles.
    try:
        ip = ipaddress.ip_address(u.hostname)
    except ValueError:
        # Hostname DNS — accepté (cf. note TOCTOU plus haut).
        return None

    # Ordre des checks : du plus spécifique au plus général. Important pour
    # le message d'erreur — loopback et link-local sont aussi dans is_private
    # (127.0.0.1.is_private == True, 169.254.x.is_private == True). On veut
    # un message qui informe précisément l'opérateur sur LA raison du refus.
    if ip.is_loopback:
        return f"IP loopback interdite pour Graph Memory : {u.hostname}"
    if ip.is_link_local:
        return (
            f"IP link-local interdite pour Graph Memory : {u.hostname} "
            "(metadata cloud potentiellement exposée)"
        )
    if ip.is_unspecified:
        return f"IP non spécifiée interdite pour Graph Memory : {u.hostname}"
    if ip.is_multicast:
        return f"IP multicast interdite pour Graph Memory : {u.hostname}"
    if ip.is_reserved:
        return f"IP réservée interdite pour Graph Memory : {u.hostname}"
    # is_private est intentionnellement en dernier : couvre RFC 1918
    # (10/8, 172.16/12, 192.168/16) — un opérateur qui voit ce message
    # sait qu'il s'agit bien d'une plage privée RFC, pas d'un loopback.
    if ip.is_private:
        return f"IP privée interdite pour Graph Memory : {u.hostname}"

    return None


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 4 outils graph sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (4)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def graph_connect(
        space_id: Annotated[
            str, Field(description="Identifiant du space live-memory à connecter")
        ],
        url: Annotated[
            str,
            Field(
                description="URL de Graph Memory (ex: 'http://localhost:8080/mcp' ou 'http://localhost:8080')"
            ),
        ],
        token: Annotated[
            str, Field(description="Bearer token pour l'authentification Graph Memory")
        ],
        memory_id: Annotated[
            str, Field(description="Identifiant de la mémoire cible dans Graph Memory")
        ],
        ontology: Annotated[
            str,
            Field(
                default="general",
                description="Ontologie pour l'extraction : general|legal|cloud|managed-services|presales",
            ),
        ] = "general",
    ) -> dict:
        """
        Connecte un space Live Memory à une instance Graph Memory.

        Teste la connexion, crée la mémoire dans Graph Memory si elle
        n'existe pas encore, puis sauvegarde la configuration dans le space.

        Une fois connecté, utilisez graph_push pour synchroniser la bank.

        Args:
            space_id: Identifiant du space live-memory
            url: URL de Graph Memory (ex: "http://localhost:8080/mcp"
                 ou "http://localhost:8080")
            token: Bearer token pour Graph Memory
            memory_id: Identifiant de la mémoire cible dans Graph Memory
            ontology: Ontologie à utiliser pour l'extraction
                      (défaut: "general"). Ontologies disponibles :
                      general, legal, cloud, managed-services, presales

        Returns:
            Statut de connexion, détails de la mémoire Graph Memory
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.graph_bridge import get_graph_bridge

        try:
            # Vérifier accès au space + permission write
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            # LM2-02 fix : valider l'URL pour bloquer le SSRF (IP privées,
            # metadata cloud, schemes non HTTP). Doit être fait AVANT toute
            # tentative de connexion réseau ET avant la persistance S3.
            url_err = _validate_gm_url(url)
            if url_err:
                return {"status": "error", "message": url_err}

            return await get_graph_bridge().connect(
                space_id=space_id,
                url=url,
                token=token,
                memory_id=memory_id,
                ontology=ontology,
            )
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "graph")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def graph_push(
        space_id: Annotated[
            str, Field(description="Identifiant du space live-memory à synchroniser")
        ],
    ) -> dict:
        """
        ⚠️ **Advanced / debug tool — NOT for routine flows.**

        Pushes the Memory Bank into Graph Memory.

        Synchronisation intelligente :
        1. Les fichiers bank déjà présents dans le graphe sont supprimés
           puis ré-ingérés (le graphe est recalculé avec le contenu à jour)
        2. Les nouveaux fichiers sont simplement ingérés
        3. Les fichiers supprimés de la bank sont nettoyés du graphe

        ⚠️ L'ingestion dans Graph Memory prend du temps (extraction LLM
        d'entités/relations + embeddings). Comptez ~10-30s par fichier.

        Le space doit d'abord être connecté via graph_connect.

        ## Why this is NOT a routine action (architecture note, v2.5.0)

        The Memory Bank is a **compact session bootstrap** by design:
        `activeContext.md` is a volatile focus snapshot, `progress.md` is
        a bounded recent journal, sub-files are compact fact sheets. The
        Live Memory consolidator continuously rewrites, compacts, and
        prunes these files.

        Graph Memory, on the other hand, must index **stable, canonical
        documents** (RFCs, incidents, runbooks, design docs, billing
        rules, infrastructure inventories). Indexing the bank teaches the
        graph transient or already-superseded content, and a later
        compaction strands those documents as stale.

        Therefore the recommended flow is:

        - **Memory Bank** = compact session bootstrap (Live Memory).
        - **Graph Memory** = durable semantic index for canonical
          repository documents (agent-side ingestion).
        - **Repository files** = final authority.

        Graph Memory complements the bank; it does not replace it.
        Graph Memory localizes; canonical repository files confirm.

        Routine flows **should not call `graph_push`**. Instead, the
        agent or tooling layer ingests canonical repository documents
        directly into Graph Memory (e.g. with the project's ingestion
        script), using stable `source_path` keys.

        `graph_push` remains available for:
        - one-off bootstrap of a brand-new Graph Memory tied to a
          stabilised bank,
        - explicit debug / migration scenarios under operator control.

        In particular, `activeContext.md` and `progress.md` **must not**
        end up in Graph Memory. A future revision (tracked in
        `DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md`) will turn this
        into a server-side guardrail. For now, the contract is doctrinal:
        do not invoke this tool as part of session-end consolidation.

        See `WORKSPACE_CLINE_ADVANCE_RULES.md`, README "Live ↔ Graph
        Memory" section, and `DESIGN/live-mem/ARCHITECTURE.md` for the
        full responsibility separation.

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            Métriques de push : fichiers poussés, nettoyés, erreurs, durée
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.graph_bridge import get_graph_bridge

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            return await get_graph_bridge().push(space_id)
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "graph")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def graph_status(
        space_id: Annotated[str, Field(description="Identifiant du space live-memory")],
    ) -> dict:
        """
        Vérifie le statut de la connexion Graph Memory d'un space.

        Teste la connectivité vers Graph Memory et récupère les
        statistiques de la mémoire cible (documents, entités, relations).

        Retourne aussi l'historique des pushs (dernier push, compteur).

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            Statut connexion, config, stats graphe, historique pushs
        """
        from ..auth.context import check_access
        from ..core.graph_bridge import get_graph_bridge

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_graph_bridge().status(space_id)
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "graph")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def graph_disconnect(
        space_id: Annotated[
            str, Field(description="Identifiant du space live-memory à déconnecter")
        ],
    ) -> dict:
        """
        Déconnecte un space de Graph Memory.

        Retire la configuration de connexion du space.
        ⚠️ Les données déjà poussées dans Graph Memory ne sont PAS
        supprimées — elles restent dans le graphe de connaissances.

        Pour supprimer aussi les données dans Graph Memory, utilisez
        les outils de Graph Memory directement (memory_delete).

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            Confirmation de déconnexion, ancienne config
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.graph_bridge import get_graph_bridge

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            return await get_graph_bridge().disconnect(space_id)
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "graph")

    return 4  # Nombre d'outils enregistrés
