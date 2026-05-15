# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Admin (8 outils).

Gestion des tokens d'authentification et maintenance.

Permissions :
    - admin_create_token       👑 (admin) — Crée un token
    - admin_list_tokens        👑 (admin) — Liste les tokens (avec filtres)
    - admin_revoke_token       👑 (admin) — Révoque un token
    - admin_delete_token       👑 (admin) — Supprime physiquement un token
    - admin_purge_tokens       👑 (admin) — Purge en masse les tokens
    - admin_update_token       👑 (admin) — Modifie un token (remplacement ou delta)
    - admin_bulk_update_tokens 👑 (admin) — Bulk update : delta sur N tokens
    - admin_gc_notes           👑 (admin) — GC des notes orphelines

Tous les outils admin requièrent la permission "admin".
Voir AUTH_AND_COLLABORATION.md pour le modèle de tokens.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 8 outils admin sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (8)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def admin_create_token(
        name: Annotated[
            str,
            Field(
                description="Nom descriptif du token (ex: 'agent-cline', 'ci-pipeline')"
            ),
        ],
        permissions: Annotated[
            str,
            Field(
                description="Permissions : 'read', 'read,write' ou 'read,write,admin'"
            ),
        ],
        space_ids: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Espaces autorisés, séparés par virgules. Sémantique stricte v1.5.0+ : "
                    "vide = AUCUN accès aux espaces existants (le token ne peut que "
                    "créer ses propres nouveaux spaces). Utilisez '*' ou 'all' pour un "
                    "snapshot des espaces actuels (pas les futurs). Ignoré pour les admins."
                ),
            ),
        ] = "",
        expires_in_days: Annotated[
            int,
            Field(
                default=0,
                description="Durée de validité en jours (0 = jamais d'expiration)",
            ),
        ] = 0,
        email: Annotated[
            str,
            Field(
                default="", description="Email du propriétaire (optionnel, traçabilité)"
            ),
        ] = "",
    ) -> dict:
        """
        Crée un nouveau token d'authentification.

        ⚠️ Le token en clair ne sera affiché qu'UNE SEULE FOIS.
        Seul le hash SHA-256 est stocké.

        Args:
            name: Nom descriptif (ex: "agent-cline")
            permissions: "read", "read,write", ou "read,write,admin"
            space_ids: Espaces autorisés (séparés par virgules). Sémantique
                stricte v1.5.0+ : vide = AUCUN accès pour les non-admin.
                Utilisez "*" ou "all" pour un snapshot des espaces actuels.
                Voir FAQ.md pour les détails.
            expires_in_days: Durée en jours (0 = jamais)

        Returns:
            Token en clair (à sauvegarder !), permissions, expiration.
            Si le token résultant n'a accès à aucun espace existant
            (et n'est pas admin), un champ `warning_no_access` est ajouté.
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
    async def admin_list_tokens(
        name_contains: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Filtre les tokens dont le nom contient cette sous-chaîne "
                    "(insensible à la casse). Vide = pas de filtre. (issue #13)"
                ),
            ),
        ] = "",
        has_space: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Filtre les tokens dont `space_ids` contient ce `space_id` "
                    "(match exact, sensible à la casse). Vide = pas de filtre. "
                    "Utile pour 'qui a accès à <space> ?' (issue #13)"
                ),
            ),
        ] = "",
        include_revoked: Annotated[
            bool,
            Field(
                default=True,
                description=(
                    "Si False, exclut les tokens révoqués du résultat. "
                    "Défaut True (rétrocompat). (issue #13)"
                ),
            ),
        ] = True,
    ) -> dict:
        """
        Liste les tokens (métadonnées seulement, jamais en clair).

        Filtres optionnels (issue #13) appliqués in-memory côté serveur,
        évitant de charger toute la liste côté client juste pour filtrer.

        Args:
            name_contains: Sous-chaîne dans le nom (case-insensitive).
            has_space: Filtre les tokens autorisant ce space_id.
            include_revoked: Inclure les tokens révoqués (défaut True).

        Returns:
            Liste des tokens avec métadonnées. Bloc `filters` ajouté
            si au moins un filtre est actif.
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().list_tokens(
                name_contains=name_contains,
                has_space=has_space,
                include_revoked=include_revoked,
            )
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def admin_revoke_token(
        token_hash: Annotated[
            str,
            Field(
                description=(
                    "Hash du token à révoquer (obtenu via admin_list_tokens). "
                    "Préfixe 'sha256:' optionnel — accepte 'sha256:abc...' ou juste 'abc...'. "
                    "Min 16 caractères hex requis."
                )
            ),
        ],
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
        token_hash: Annotated[
            str,
            Field(
                description=(
                    "Hash du token à supprimer (obtenu via admin_list_tokens). "
                    "Préfixe 'sha256:' optionnel. Min 16 caractères hex requis."
                )
            ),
        ],
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
        revoked_only: Annotated[
            bool,
            Field(
                default=True,
                description="True = supprime uniquement les tokens révoqués, False = supprime TOUS les tokens",
            ),
        ] = True,
        confirm: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "LM2-31 : OBLIGATOIRE quand revoked_only=False (purge totale). "
                    "Garde-fou contre une suppression accidentelle de tous les tokens "
                    "qui laisserait le serveur en mode bootstrap-only."
                ),
            ),
        ] = False,
    ) -> dict:
        """
        Purge en masse les tokens du registre.

        Par défaut, ne supprime que les tokens révoqués (nettoyage).
        Avec revoked_only=False, supprime TOUS les tokens (reset complet)
        ET nécessite ``confirm=True`` depuis v2.0.0 (LM2-31 fix).

        ⚠️ Opération irréversible. Le bootstrap key (env var) n'est pas affecté.

        Args:
            revoked_only: True = tokens révoqués seulement, False = tous
            confirm: Requis (True) si revoked_only=False — sécurité contre
                la perte accidentelle de tous les tokens du service.

        Returns:
            Nombre de tokens supprimés et restants
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            # LM2-31 fix : exiger confirm=True pour la purge totale.
            # La purge des seuls révoqués reste possible sans confirm (nettoyage
            # courant, non-destructeur pour les agents actifs).
            if not revoked_only and not confirm:
                return {
                    "status": "error",
                    "message": (
                        "Purge totale refusée : confirm=True requis quand "
                        "revoked_only=False. Cette opération supprime TOUS les "
                        "tokens et laisserait le serveur accessible uniquement "
                        "via la bootstrap_key. Si c'est bien votre intention, "
                        "rappelez l'outil avec confirm=True."
                    ),
                }

            return await get_token_service().purge_tokens(revoked_only=revoked_only)
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def admin_update_token(
        token_hash: Annotated[
            str,
            Field(
                description=(
                    "Hash du token à modifier (obtenu via admin_list_tokens). "
                    "Préfixe 'sha256:' optionnel. Min 16 caractères hex requis."
                )
            ),
        ],
        space_ids: Annotated[
            str,
            Field(
                default="",
                description=(
                    "MODE REMPLACEMENT — nouveaux espaces autorisés (CSV). "
                    "Vide = pas de changement. Utilisez '*' ou 'all' pour un "
                    "snapshot des espaces existants. ⚠️ Remplace la liste "
                    "complète : risque de révocation silencieuse si on oublie "
                    "un space. Pour un ajout sûr, préférez `space_ids_add`."
                ),
            ),
        ] = "",
        permissions: Annotated[
            str,
            Field(
                default="",
                description="Nouvelles permissions : 'read', 'read,write' ou 'read,write,admin' (vide = pas de changement)",
            ),
        ] = "",
        email: Annotated[
            str,
            Field(
                default="",
                description="Nouvel email du propriétaire (vide = pas de changement)",
            ),
        ] = "",
        space_ids_add: Annotated[
            str,
            Field(
                default="",
                description=(
                    "MODE DELTA — espaces à ajouter (CSV). Idempotent : "
                    "no-op si déjà présent. Incompatible avec `space_ids` "
                    "(remplacement). Sucre '*' / 'all' interdit ici. (issue #13)"
                ),
            ),
        ] = "",
        space_ids_remove: Annotated[
            str,
            Field(
                default="",
                description=(
                    "MODE DELTA — espaces à retirer (CSV). Idempotent : "
                    "no-op si absent. Appliqué AVANT `space_ids_add` quand "
                    "les deux sont fournis. (issue #13)"
                ),
            ),
        ] = "",
    ) -> dict:
        """
        Met à jour un token : permissions, email, et/ou ``space_ids``.

        Trois modes pour les ``space_ids`` (issue #13) :

        1. Pas de changement (aucun des 3 paramètres ``space_ids*`` fournis).
        2. Remplacement complet (legacy) : ``space_ids`` non vide.
        3. Delta additif : ``space_ids_add`` et/ou ``space_ids_remove``.
           Idempotent. ``_remove`` appliqué avant ``_add``.

        Les modes (2) et (3) sont mutuellement exclusifs.

        Args:
            token_hash: Hash du token (depuis admin_list_tokens)
            space_ids: Mode remplacement (CSV ou ``*``/``all``).
            permissions: Nouvelles permissions (vide = pas de changement).
            email: Nouvel email (vide = pas de changement).
            space_ids_add: Mode delta — espaces à ajouter (CSV).
            space_ids_remove: Mode delta — espaces à retirer (CSV).

        Returns:
            Confirmation avec, en mode delta, ``space_ids_before``,
            ``space_ids_after``, ``space_ids_added``, ``space_ids_removed``,
            ``space_ids_noop``. ``warning_no_access`` si le token devient muet.
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
                space_ids_add=space_ids_add,
                space_ids_remove=space_ids_remove,
            )
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def admin_bulk_update_tokens(
        names: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Liste CSV de noms de tokens exacts à matcher "
                    "(ex: 'agent-laptop,agent-desktop,agent-ci'). "
                    "Combinable en AND avec `name_contains` et `has_space`. "
                    "Au moins un des trois filtres est requis."
                ),
            ),
        ] = "",
        name_contains: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Sous-chaîne (case-INSENSITIVE) à matcher dans le nom "
                    "des tokens (ex: 'agent'). Combinable en AND avec `names` "
                    "et `has_space`. Au moins un filtre requis."
                ),
            ),
        ] = "",
        has_space: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Filtre les tokens dont `space_ids` contient ce `space_id` "
                    "(match exact, case-SENSITIVE — cohérent avec `admin_list_tokens`). "
                    "Cas d'usage typique : retirer un space obsolète de tous les "
                    "tokens qui l'ont, en un seul appel. Combinable en AND. "
                    "(review PR #14, point #2)"
                ),
            ),
        ] = "",
        permissions: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Nouvelles permissions à appliquer aux tokens sélectionnés "
                    "(CSV : 'read', 'read,write', 'read,write,admin'). "
                    "Vide = pas de changement."
                ),
            ),
        ] = "",
        email: Annotated[
            str,
            Field(
                default="",
                description="Nouvel email à appliquer (vide = pas de changement).",
            ),
        ] = "",
        space_ids_add: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Spaces à ajouter (CSV). Idempotent. Sucre '*'/'all' interdit."
                ),
            ),
        ] = "",
        space_ids_remove: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Spaces à retirer (CSV). Idempotent. Sucre '*'/'all' interdit."
                ),
            ),
        ] = "",
        include_revoked: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "Inclure les tokens révoqués dans la sélection. "
                    "Défaut FALSE — asymétrie volontaire avec `admin_list_tokens` "
                    "(défaut True) car la sémantique diffère : on MUTE ici, on "
                    "observe là-bas. Modifier un token révoqué peut créer des "
                    "permissions fantômes en cas de ré-activation. Les révoqués "
                    "matchés mais sautés sont listés dans `skipped_revoked`. "
                    "(review PR #14, point #3)"
                ),
            ),
        ] = False,
    ) -> dict:
        """
        Met à jour plusieurs tokens en une seule opération (issue #13).

        Workflow typique : autoriser un nouveau space sur N agents (le même
        agent déployé sur plusieurs postes) sans avoir à reconstruire la
        liste complète des `space_ids` de chacun ⇒ élimine la classe de
        bugs "révocation silencieuse par remplacement complet".

        ⚠️ **Volontairement** : pas de mode "remplacement complet" en bulk
        (trop dangereux à propager sur N tokens). Seul le mode delta est
        exposé pour les `space_ids`.

        **Atomicité** : `tokens.json` est un fichier S3 unique sauvé d'un
        bloc sous lock asyncio. Validation et application en mémoire, puis
        une seule écriture finale. En cas d'erreur, aucune modification
        persistée. Atomique au sein d'une instance MCP — un déploiement
        HA multi-instances nécessiterait un verrou externe (non implémenté).

        **Filtres** (au moins un de `names`/`name_contains`/`has_space` requis) :
            - `names` : liste exacte (CSV).
            - `name_contains` : sous-chaîne (case-insensitive).
            - `has_space` : space_id présent dans `token.space_ids` (case-sensitive).

        ⚠️ **Combinaison AND** : tous les filtres fournis doivent être
        satisfaits par chaque token. Pour OR, faites plusieurs appels.

        **Filtre sécurité** : `include_revoked=False` par défaut — les
        tokens révoqués sont sautés et listés dans `skipped_revoked`.

        **Opérations** (au moins une requise) :
            - `permissions`, `email` : appliqués à tous les tokens matchés.
            - `space_ids_add`, `space_ids_remove` : deltas additifs idempotents.

        **Audit** : un événement structuré est émis sur le logger
        `live_mem.audit` après l'écriture S3 (point #4 review PR #14).

        Returns:
            ``{"status": "ok", "updated": N, "tokens": [{name, hash,
            before: {...}, after: {...}, space_ids_added: [...], ...}],
            "skipped_revoked": [...], "filters": {...}, "operations": {...}}``.
            Si aucun token actif ne matche : `updated=0`, statut `ok`.
        """
        from ..auth.context import check_admin_permission
        from ..core.tokens import get_token_service

        try:
            admin_err = check_admin_permission()
            if admin_err:
                return admin_err

            return await get_token_service().bulk_update_tokens(
                names=names,
                name_contains=name_contains,
                has_space=has_space,
                permissions=permissions,
                email=email,
                space_ids_add=space_ids_add,
                space_ids_remove=space_ids_remove,
                include_revoked=include_revoked,
            )
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "admin")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def admin_gc_notes(
        space_id: Annotated[
            str,
            Field(
                default="", description="Espace cible (vide = scanner TOUS les espaces)"
            ),
        ] = "",
        max_age_days: Annotated[
            int,
            Field(
                default=7,
                description="Seuil d'âge en jours pour considérer une note comme orpheline (défaut 7)",
            ),
        ] = 7,
        confirm: Annotated[
            bool,
            Field(
                default=False,
                description="False = dry-run (scan seul), True = exécution réelle",
            ),
        ] = False,
        delete_only: Annotated[
            bool,
            Field(
                default=False,
                description="Si True + confirm=True : supprime SANS consolider (perte de données)",
            ),
        ] = False,
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

    return 8  # Nombre d'outils enregistrés
