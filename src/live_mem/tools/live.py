# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Live (3 outils).

Notes en temps réel : écrire, lire, rechercher.

Permissions :
    - live_note   ✏️ (write) — Écrit une note (append-only, zéro conflit)
    - live_read   🔑 (read)  — Lit les notes récentes avec filtres
    - live_search 🔑 (read)  — Recherche texte dans les notes

Les notes live sont l'outil principal utilisé par les agents pendant
leur travail. Chaque note = 1 fichier S3 unique → aucun conflit
entre agents écrivant simultanément.

Catégories standard :
    observation — Constat factuel ("Le build passe")
    decision    — Choix technique ("On part sur S3")
    todo        — Tâche à faire ("Implémenter le backup")
    insight     — Pattern découvert ("Le pattern X marche")
    question    — Question ouverte ("Supporter le CSV ?")
    progress    — Avancement ("Module auth : 80%")
    issue       — Problème, bug ("Timeout LLM > 60s")
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 3 outils live sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (3)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def live_note(
        space_id: Annotated[str, Field(description="Identifiant de l'espace cible")],
        category: Annotated[str, Field(description="Catégorie : observation|decision|todo|insight|question|progress|issue")],
        content: Annotated[str, Field(description="Contenu de la note (texte libre)")],
        tags: Annotated[str, Field(default="", description="Tags séparés par des virgules (ex: 'auth,security,urgent')")] = "",
    ) -> dict:
        """
        Écrit une note dans l'espace mémoire.

        C'est l'outil principal utilisé par les agents pendant leur travail.
        Chaque note est un fichier S3 unique (append-only) — aucun conflit
        possible entre agents écrivant simultanément.

        L'identité de l'agent est TOUJOURS le client_name du token
        d'authentification. Pas de paramètre agent — garantit la cohérence
        avec le consolidateur et empêche les notes orphelines.

        Args:
            space_id: Espace cible
            category: observation|decision|todo|insight|question|progress|issue
            content: Contenu de la note (texte libre)
            tags: Tags séparés par des virgules (optionnel)

        Returns:
            Nom du fichier créé, taille, timestamp
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.live import get_live_service

        try:
            # Vérifier accès à l'espace + permission write
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            return await get_live_service().write_note(
                space_id=space_id,
                category=category,
                content=content,
                tags=tags,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "live")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def live_read(
        space_id: Annotated[str, Field(description="Identifiant de l'espace cible")],
        limit: Annotated[int, Field(default=50, description="Nombre max de notes à retourner (défaut 50)")] = 50,
        category: Annotated[str, Field(default="", description="Filtrer par catégorie : observation|decision|todo|insight|question|progress|issue")] = "",
        agent: Annotated[str, Field(default="", description="Filtrer par identifiant d'agent")] = "",
        since: Annotated[str, Field(default="", description="Notes après cette date ISO 8601 (ex: '2026-03-08T10:00:00')")] = "",
    ) -> dict:
        """
        Lit les notes live récentes d'un espace.

        Permet de filtrer par catégorie, agent, et date. Les notes sont
        retournées du plus récent au plus ancien.

        Args:
            space_id: Espace cible
            limit: Nombre max de notes (défaut 50)
            category: Filtrer par catégorie (optionnel)
            agent: Filtrer par agent (optionnel)
            since: Notes après cette date ISO (optionnel)

        Returns:
            Liste des notes avec métadonnées et contenu
        """
        from ..auth.context import check_access
        from ..core.live import get_live_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_live_service().read_notes(
                space_id=space_id,
                limit=limit,
                category=category,
                agent=agent,
                since=since,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "live")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def live_search(
        space_id: Annotated[str, Field(description="Identifiant de l'espace cible")],
        query: Annotated[str, Field(description="Texte à chercher dans les notes (case-insensitive)")],
        limit: Annotated[int, Field(default=20, description="Nombre max de résultats (défaut 20)")] = 20,
    ) -> dict:
        """
        Recherche texte dans les notes live d'un espace.

        Effectue une recherche case-insensitive dans le contenu de toutes
        les notes. Les résultats sont triés du plus récent au plus ancien.

        Args:
            space_id: Espace cible
            query: Texte à chercher (case-insensitive)
            limit: Nombre max de résultats (défaut 20)

        Returns:
            Notes correspondant à la recherche
        """
        from ..auth.context import check_access
        from ..core.live import get_live_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_live_service().search_notes(
                space_id=space_id,
                query=query,
                limit=limit,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "live")

    return 3  # Nombre d'outils enregistrés
