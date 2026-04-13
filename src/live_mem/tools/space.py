# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Space (9 outils).

Gestion des espaces mémoire : créer, lister, inspecter, exporter, supprimer.

Permissions :
    - space_create        ✏️ (write)  — Crée un nouvel espace
    - space_update        ✏️ (write)  — Met à jour description/owner
    - space_update_rules  👑 (admin)  — Met à jour les rules d'un espace
    - space_list          🔑 (read)   — Liste les espaces accessibles
    - space_info          🔑 (read)   — Infos détaillées d'un espace
    - space_rules         🔑 (read)   — Lit les rules
    - space_summary       🔑 (read)   — Synthèse complète (rules + bank)
    - space_export        🔑 (read)   — Export tar.gz en base64
    - space_delete        👑 (admin)  — Supprime un espace (irréversible)

Chaque outil délègue au SpaceService (core/space.py) après vérification
des permissions via les helpers auth/context.py.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 9 outils space sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (9)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def space_create(
        space_id: Annotated[str, Field(description="Identifiant unique de l'espace (alphanum + tirets, max 64 chars)")],
        description: Annotated[str, Field(description="Description courte de l'espace")],
        rules: Annotated[str, Field(default="", description="Contenu Markdown des rules définissant la structure de la Memory Bank. Si vide, utilise les rules par défaut (DEFAULT_RULES_FILE)")] = "",
        owner: Annotated[str, Field(default="", description="Propriétaire de l'espace (optionnel, informatif)")] = "",
    ) -> dict:
        """
        Crée un nouvel espace mémoire avec ses rules.

        Les rules définissent la structure de la Memory Bank (quels fichiers,
        quel contenu). Elles sont immuables après création.

        Si rules est vide, le serveur charge les rules par défaut depuis
        le fichier configuré dans DEFAULT_RULES_FILE (.env).

        Args:
            space_id: Identifiant unique (alphanum + tirets, max 64 chars)
            description: Description courte de l'espace
            rules: Contenu Markdown des rules (vide = rules par défaut)
            owner: Propriétaire (optionnel, informatif)

        Returns:
            Détails de l'espace créé
        """
        from pathlib import Path
        from ..auth.context import check_write_permission, current_token_info
        from ..config import get_settings
        from ..core.space import get_space_service
        from ..core.tokens import get_token_service

        try:
            # Vérifier la permission write
            write_err = check_write_permission()
            if write_err:
                return write_err

            # Si rules vide, charger les rules par défaut
            effective_rules = rules
            if not effective_rules.strip():
                settings = get_settings()
                if settings.default_rules_file:
                    rules_path = Path(settings.default_rules_file)
                    if rules_path.is_file():
                        effective_rules = rules_path.read_text(encoding="utf-8")
                    else:
                        return {
                            "status": "error",
                            "message": f"Fichier de rules par défaut introuvable : {settings.default_rules_file}",
                        }
                else:
                    return {
                        "status": "error",
                        "message": (
                            "Paramètre 'rules' requis. "
                            "Aucun fichier de rules par défaut configuré (DEFAULT_RULES_FILE)."
                        ),
                    }

            result = await get_space_service().create(
                space_id=space_id,
                description=description,
                rules=effective_rules,
                owner=owner,
            )

            # Auto-ajout du space au token (alignement Graph Memory)
            # Si le token est restreint à certains spaces, on ajoute
            # automatiquement le nouveau space pour éviter le deadlock UX.
            if result.get("status") == "created":
                token_info = current_token_info.get()
                if token_info and token_info.get("token_hash"):
                    add_result = await get_token_service().add_space_to_token(
                        token_hash=token_info["token_hash"],
                        space_id=space_id,
                    )
                    if add_result.get("status") == "ok":
                        result["token_auto_updated"] = True
                        result["token_message"] = add_result["message"]

            return result
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def space_update(
        space_id: Annotated[str, Field(description="Identifiant de l'espace à modifier")],
        description: Annotated[str, Field(default="", description="Nouvelle description (vide = pas de changement)")] = "",
        owner: Annotated[str, Field(default="", description="Nouveau propriétaire (vide = pas de changement)")] = "",
    ) -> dict:
        """
        Met à jour les métadonnées d'un espace (description, owner).

        Les rules restent immuables. Seuls les champs fournis (non vides)
        sont modifiés.

        Args:
            space_id: Identifiant de l'espace à modifier
            description: Nouvelle description (vide = pas de changement)
            owner: Nouveau propriétaire (vide = pas de changement)

        Returns:
            Champs modifiés et nouvelles valeurs
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            return await get_space_service().update(
                space_id=space_id,
                description=description if description else None,
                owner=owner if owner else None,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def space_update_rules(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
        rules: Annotated[str, Field(description="Nouveau contenu Markdown des rules")],
    ) -> dict:
        """
        Met à jour les rules d'un espace (admin only).

        ⚠️ Les rules sont normalement immuables après création.
        Cet outil permet de les mettre à jour sans devoir
        supprimer/recréer l'espace. Réservé aux administrateurs.

        Cas d'usage : correction de rules, migration vers une
        nouvelle version du template, ajout de règles de consolidation.

        Args:
            space_id: Identifiant de l'espace
            rules: Nouveau contenu Markdown des rules

        Returns:
            Taille des nouvelles rules
        """
        from ..auth.context import check_access, check_admin_permission
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_space_service().update_rules(
                space_id=space_id,
                rules=rules,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def space_list() -> dict:
        """
        Liste tous les espaces mémoire accessibles par le token courant.

        Retourne les métadonnées, le nombre de notes live et de fichiers bank
        pour chaque espace.

        Returns:
            Liste des espaces avec statistiques
        """
        from ..auth.context import current_token_info
        from ..core.space import get_space_service

        try:
            # Récupérer les space_ids autorisés depuis le token
            token_info = current_token_info.get()
            if token_info is None:
                return {"status": "error", "message": "Authentification requise"}

            allowed = token_info.get("allowed_resources", [])
            # allowed vide = accès à tous les espaces
            allowed_ids = allowed if allowed else None

            return await get_space_service().list_spaces(
                allowed_space_ids=allowed_ids
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def space_info(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
    ) -> dict:
        """
        Informations détaillées sur un espace mémoire.

        Retourne les métadonnées, les stats des notes live (nombre, taille),
        les stats de la bank (fichiers, taille), et le statut de consolidation.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Infos complètes de l'espace
        """
        from ..auth.context import check_access
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_space_service().get_info(space_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def space_rules(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
    ) -> dict:
        """
        Lit les rules de l'espace (immuables après création).

        Les rules définissent la structure souhaitée de la Memory Bank.
        Le LLM les utilise lors de la consolidation pour créer/maintenir
        les fichiers bank correspondants.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Contenu Markdown des rules
        """
        from ..auth.context import check_access
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_space_service().get_rules(space_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def space_summary(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
    ) -> dict:
        """
        Synthèse complète d'un espace : rules + bank + stats.

        C'est l'outil idéal pour qu'un agent charge TOUT le contexte
        d'un projet en une seule requête au démarrage.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Rules, fichiers bank complets, synthèse résiduelle
        """
        from ..auth.context import check_access
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_space_service().get_summary(space_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def space_export(
        space_id: Annotated[str, Field(description="Identifiant de l'espace à exporter")],
    ) -> dict:
        """
        Exporte un espace complet en archive tar.gz (base64).

        L'archive contient tous les fichiers de l'espace : _meta.json,
        _rules.md, notes live, fichiers bank, synthèse.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Archive base64, taille et nombre de fichiers
        """
        from ..auth.context import check_access
        from ..core.space import get_space_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_space_service().export_space(space_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
    async def space_delete(
        space_id: Annotated[str, Field(description="Identifiant de l'espace à supprimer")],
        confirm: Annotated[bool, Field(default=False, description="Doit être True pour confirmer la suppression (sécurité)")] = False,
    ) -> dict:
        """
        Supprime un espace et TOUTES ses données (irréversible).

        ⚠️ ATTENTION : cette opération est destructive et ne peut pas être annulée.
        Le paramètre confirm doit être True pour confirmer la suppression.
        Seuls les tokens admin peuvent utiliser cet outil.

        Args:
            space_id: Identifiant de l'espace à supprimer
            confirm: Doit être True pour confirmer (sécurité)

        Returns:
            Confirmation de suppression avec nombre de fichiers supprimés
        """
        from ..auth.context import check_access, check_admin_permission
        from ..core.space import get_space_service

        try:
            # Double vérification : accès + admin
            access_err = check_access(space_id)
            if access_err:
                return access_err

            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            # Sécurité : confirm obligatoire
            if not confirm:
                return {
                    "status": "error",
                    "message": (
                        "Suppression refusée : confirm=True requis. "
                        "⚠️ Cette opération est irréversible !"
                    ),
                }

            return await get_space_service().delete(space_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "space")

    return 9  # Nombre d'outils enregistrés
