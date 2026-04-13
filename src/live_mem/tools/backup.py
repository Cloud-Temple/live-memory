# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Backup (5 outils).

Sauvegarde et restauration d'espaces mémoire.

Permissions :
    - backup_create   ✏️ (write) — Crée un snapshot d'espace
    - backup_list     🔑 (read)  — Liste les backups disponibles
    - backup_restore  👑 (admin) — Restaure un espace depuis un backup
    - backup_download 🔑 (read)  — Télécharge un backup (tar.gz base64)
    - backup_delete   👑 (admin) — Supprime un backup

Les backups sont des snapshots complets stockés dans _backups/ sur S3.
Voir S3_DATA_MODEL.md pour l'arborescence.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 5 outils backup sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (5)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def backup_create(
        space_id: Annotated[str, Field(description="Identifiant de l'espace à sauvegarder")],
        description: Annotated[str, Field(default="", description="Description du backup (optionnel, ex: 'avant migration')")] = "",
    ) -> dict:
        """
        Crée un snapshot complet d'un espace sur S3.

        Copie tous les fichiers (meta, rules, notes, bank, synthesis)
        dans _backups/{space_id}/{timestamp}/.

        Args:
            space_id: Espace à sauvegarder
            description: Description du backup (optionnel)

        Returns:
            backup_id, nombre de fichiers, taille totale
        """
        from ..auth.context import check_access, check_write_permission
        from ..core.backup import get_backup_service

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            write_err = check_write_permission()
            if write_err:
                return write_err

            return await get_backup_service().create(space_id, description)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "backup")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def backup_list(
        space_id: Annotated[str, Field(default="", description="Filtrer par espace (vide = tous les espaces accessibles)")] = "",
    ) -> dict:
        """
        Liste les backups disponibles.

        Si space_id est fourni, ne liste que les backups de cet espace.
        Sinon, liste tous les backups de tous les espaces accessibles.

        Args:
            space_id: Filtrer par espace (vide = tous)

        Returns:
            Liste des backups avec backup_id et timestamp
        """
        from ..auth.context import current_token_info, check_access
        from ..core.backup import get_backup_service

        try:
            token_info = current_token_info.get()
            if token_info is None:
                return {"status": "error", "message": "Authentification requise"}

            # Si un espace est spécifié, vérifier l'accès
            if space_id:
                access_err = check_access(space_id)
                if access_err:
                    return access_err

            result = await get_backup_service().list_backups(space_id)

            # Filtrage par space_ids du token (alignement Graph Memory v0.7.0)
            # Un client ne doit voir que les backups des spaces autorisés.
            # Admin bypass (allowed_resources vide = accès à tous).
            allowed = token_info.get("allowed_resources", [])
            if allowed and result.get("status") == "ok" and not space_id:
                filtered = [
                    b for b in result.get("backups", [])
                    if b.get("space_id", b.get("backup_id", "").split("/")[0]) in allowed
                ]
                result["backups"] = filtered
                result["total"] = len(filtered)
                result["filtered_by_token"] = True

            return result
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "backup")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False))
    async def backup_restore(
        backup_id: Annotated[str, Field(description="Identifiant du backup au format 'space_id/timestamp'")],
        confirm: Annotated[bool, Field(default=False, description="Doit être True pour confirmer la restauration (sécurité)")] = False,
    ) -> dict:
        """
        Restaure un espace depuis un backup.

        ⚠️ L'espace NE DOIT PAS exister (supprimer d'abord).
        Le paramètre confirm doit être True.

        Args:
            backup_id: Format "space_id/timestamp"
            confirm: Doit être True pour confirmer (sécurité)

        Returns:
            Nombre de fichiers restaurés
        """
        from ..auth.context import check_admin_permission
        from ..core.backup import get_backup_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            if not confirm:
                return {
                    "status": "error",
                    "message": "Restauration refusée : confirm=True requis.",
                }

            return await get_backup_service().restore(backup_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "backup")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def backup_download(
        backup_id: Annotated[str, Field(description="Identifiant du backup au format 'space_id/timestamp'")],
    ) -> dict:
        """
        Télécharge un backup en archive tar.gz (base64).

        Args:
            backup_id: Format "space_id/timestamp"

        Returns:
            Archive base64, taille, nombre de fichiers
        """
        from ..auth.context import current_token_info, check_access
        from ..core.backup import get_backup_service

        try:
            token_info = current_token_info.get()
            if token_info is None:
                return {"status": "error", "message": "Authentification requise"}

            # Extraire le space_id du backup_id ("space_id/timestamp")
            space_id = backup_id.split("/")[0] if "/" in backup_id else backup_id
            access_err = check_access(space_id)
            if access_err:
                return access_err

            return await get_backup_service().download(backup_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "backup")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def backup_delete(
        backup_id: Annotated[str, Field(description="Identifiant du backup au format 'space_id/timestamp'")],
        confirm: Annotated[bool, Field(default=False, description="Doit être True pour confirmer la suppression (sécurité, irréversible)")] = False,
    ) -> dict:
        """
        Supprime un backup (irréversible).

        Args:
            backup_id: Format "space_id/timestamp"
            confirm: Doit être True pour confirmer (sécurité)

        Returns:
            Nombre de fichiers supprimés
        """
        from ..auth.context import check_admin_permission
        from ..core.backup import get_backup_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            if not confirm:
                return {
                    "status": "error",
                    "message": "Suppression refusée : confirm=True requis.",
                }

            return await get_backup_service().delete(backup_id)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "backup")

    return 5  # Nombre d'outils enregistrés
