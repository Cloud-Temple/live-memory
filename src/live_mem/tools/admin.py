# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Admin (7 outils).

Gestion des tokens d'authentification et maintenance.

Permissions :
    - admin_create_token  👑 (admin) — Crée un token
    - admin_list_tokens   👑 (admin) — Liste les tokens
    - admin_revoke_token  👑 (admin) — Révoque un token
    - admin_delete_token  👑 (admin) — Supprime physiquement un token
    - admin_purge_tokens  👑 (admin) — Purge en masse les tokens
    - admin_update_token  👑 (admin) — Modifie un token
    - admin_gc_notes      👑 (admin) — GC des notes orphelines

Tous les outils admin requièrent la permission "admin".
Voir AUTH_AND_COLLABORATION.md pour le modèle de tokens.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 7 outils admin sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (7)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def admin_create_token(
        name: Annotated[str, Field(description="Nom descriptif du token (ex: 'agent-cline', 'ci-pipeline')")],
        permissions: Annotated[str, Field(description="Permissions : 'read', 'read,write' ou 'read,write,admin'")],
        space_ids: Annotated[str, Field(default="", description="Espaces autorisés séparés par virgules (vide = tous les espaces)")] = "",
        expires_in_days: Annotated[int, Field(default=0, description="Durée de validité en jours (0 = jamais d'expiration)")] = 0,
        email: Annotated[str, Field(default="", description="Email du propriétaire (optionnel, traçabilité)")] = "",
    ) -> dict:
        """
        Crée un nouveau token d'authentification.

        ⚠️ Le token en clair ne sera affiché qu'UNE SEULE FOIS.
        Seul le hash SHA-256 est stocké.

        Args:
            name: Nom descriptif (ex: "agent-cline")
            permissions: "read", "read,write", ou "read,write,admin"
            space_ids: Espaces autorisés, séparés par virgules (vide = tous)
            expires_in_days: Durée en jours (0 = jamais)

        Returns:
            Token en clair (à sauvegarder !), permissions, expiration
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().create_token(
                name=name,
                permissions=permissions,
                space_ids=space_ids,
                expires_in_days=expires_in_days,
                email=email,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def admin_list_tokens() -> dict:
        """
        Liste tous les tokens (métadonnées seulement, jamais en clair).

        Retourne le nom, les permissions, les espaces autorisés,
        le hash tronqué, et le statut (révoqué, expiré).

        Returns:
            Liste des tokens avec métadonnées
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().list_tokens()
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def admin_revoke_token(
        token_hash: Annotated[str, Field(description="Hash tronqué du token à révoquer (obtenu via admin_list_tokens)")],
    ) -> dict:
        """
        Révoque un token (le rend définitivement inutilisable).

        Args:
            token_hash: Hash tronqué du token (depuis admin_list_tokens)

        Returns:
            Confirmation de révocation
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().revoke_token(token_hash)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def admin_delete_token(
        token_hash: Annotated[str, Field(description="Hash tronqué du token à supprimer (obtenu via admin_list_tokens)")],
    ) -> dict:
        """
        Supprime physiquement un token du registre.

        Contrairement à revoke_token qui marque le token comme inactif,
        cette opération le retire complètement de tokens.json.
        ⚠️ Opération irréversible.

        Note: Le bootstrap key (variable d'environnement) n'est jamais
        dans tokens.json et ne peut donc pas être supprimé.

        Args:
            token_hash: Hash tronqué du token (depuis admin_list_tokens)

        Returns:
            Confirmation de suppression avec nombre de tokens restants
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().delete_token(token_hash)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
    async def admin_purge_tokens(
        revoked_only: Annotated[bool, Field(default=True, description="True = supprime uniquement les tokens révoqués, False = supprime TOUS les tokens")] = True,
    ) -> dict:
        """
        Purge en masse les tokens du registre.

        Par défaut, ne supprime que les tokens révoqués (nettoyage).
        Avec revoked_only=False, supprime TOUS les tokens (reset complet).

        ⚠️ Opération irréversible. Le bootstrap key (env var) n'est pas affecté.

        Args:
            revoked_only: True = tokens révoqués seulement, False = tous

        Returns:
            Nombre de tokens supprimés et restants
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().purge_tokens(revoked_only=revoked_only)
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def admin_update_token(
        token_hash: Annotated[str, Field(description="Hash tronqué du token à modifier (obtenu via admin_list_tokens)")],
        space_ids: Annotated[str, Field(default="", description="Nouveaux espaces autorisés séparés par virgules (vide = pas de changement)")] = "",
        permissions: Annotated[str, Field(default="", description="Nouvelles permissions : 'read', 'read,write' ou 'read,write,admin' (vide = pas de changement)")] = "",
        email: Annotated[str, Field(default="", description="Nouvel email du propriétaire (vide = pas de changement)")] = "",
    ) -> dict:
        """
        Met à jour les permissions ou espaces autorisés d'un token.

        Args:
            token_hash: Hash tronqué du token (depuis admin_list_tokens)
            space_ids: Nouveaux espaces (vide = pas de changement)
            permissions: Nouvelles permissions (vide = pas de changement)

        Returns:
            Confirmation de mise à jour
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().update_token(
                token_hash=token_hash,
                space_ids=space_ids,
                permissions=permissions,
                email=email,
            )
        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def admin_gc_notes(
        space_id: Annotated[str, Field(default="", description="Espace cible (vide = scanner TOUS les espaces)")] = "",
        max_age_days: Annotated[int, Field(default=7, description="Seuil d'âge en jours pour considérer une note comme orpheline (défaut 7)")] = 7,
        confirm: Annotated[bool, Field(default=False, description="False = dry-run (scan seul), True = exécution réelle")] = False,
        delete_only: Annotated[bool, Field(default=False, description="Si True + confirm=True : supprime SANS consolider (perte de données)")] = False,
    ) -> dict:
        """
        Garbage Collector : consolide ou supprime les notes orphelines.

        Les notes live non consolidées par un agent disparu s'accumulent.
        Cet outil les identifie (plus vieilles que max_age_days).

        3 modes :
        - confirm=False (défaut) : DRY-RUN — scanne et rapporte
        - confirm=True : CONSOLIDE les notes dans la bank via LLM
          (ajoute une notice "⚠️ GC consolidation forcée" dans chaque bank)
        - confirm=True, delete_only=True : SUPPRIME sans consolider

        Args:
            space_id: Espace cible (vide = scanner TOUS les espaces)
            max_age_days: Seuil en jours (défaut 7)
            confirm: False = dry-run, True = exécution
            delete_only: Si True + confirm, supprime SANS consolider

        Returns:
            Rapport : nombre de notes, taille, répartition par agent
        """
        from ..auth.context import check_admin_permission
        from ..core.gc import get_gc_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            gc = get_gc_service()

            if confirm and delete_only:
                # Mode suppression sans consolidation (perte de données)
                return await gc.delete_old_notes(
                    space_id=space_id,
                    max_age_days=max_age_days,
                )
            elif confirm:
                # Mode consolidation (défaut avec confirm)
                return await gc.consolidate_old_notes(
                    space_id=space_id,
                    max_age_days=max_age_days,
                )
            else:
                # Mode dry-run : scanner seulement
                result = await gc.scan_old_notes(
                    space_id=space_id,
                    max_age_days=max_age_days,
                )
                for sid in result.get("spaces", {}):
                    if "keys" in result["spaces"][sid]:
                        count = len(result["spaces"][sid]["keys"])
                        del result["spaces"][sid]["keys"]
                        result["spaces"][sid]["keys_count"] = count
                result["mode"] = "dry-run"
                result["message"] = (
                    f"Dry-run : {result['total_old_notes']} notes orphelines "
                    f"trouvées. confirm=True pour consolider, "
                    f"confirm=True+delete_only=True pour supprimer."
                )
                return result

        except Exception as e:
            from ..auth.context import safe_error
            return safe_error(e, "admin")

    return 7  # Nombre d'outils enregistrés
