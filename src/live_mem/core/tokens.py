# -*- coding: utf-8 -*-
"""
Service Tokens — Gestion des tokens d'authentification.

Les tokens sont stockés dans _system/tokens.json sur S3.
Chaque token est hashé en SHA-256 avant stockage (jamais en clair).

Architecture :
    tools/admin.py → TokenService (ce fichier) → StorageService (S3)
    auth/middleware.py → TokenService.validate_token()

Concurrence :
    Protégé par asyncio.Lock (via LockManager.tokens) pour les
    opérations read-modify-write sur tokens.json.

Voir AUTH_AND_COLLABORATION.md pour le modèle complet.
"""

import json
import logging
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from .storage import get_storage
from .locks import get_lock_manager
from .models import TokenInfo, TokensStore

# Logger dédié pour les événements d'audit (consommé par AuditMiddleware
# en parallèle ; voir middleware.py). Émettre ici garantit une trace même
# si le retour MCP est perdu côté client (review PR #14, point #4).
_audit_logger = logging.getLogger("live_mem.audit")


# Préfixe des tokens générés
TOKEN_PREFIX = "lm_"

# Chemin S3 du registre de tokens
TOKENS_KEY = "_system/tokens.json"

# Permissions reconnues par le système d'authentification
# Hiérarchie inclusive : admin ⊃ manage ⊃ write ⊃ read
VALID_PERMISSIONS = {"read", "write", "manage", "admin"}


class TokenService:
    """
    Service de gestion des tokens d'authentification.

    Toutes les opérations de modification (create, revoke, update)
    sont protégées par un asyncio.Lock pour éviter les conflits.
    """

    def __init__(self):
        # VULN-01 fix : cache en mémoire pour last_used_at
        # Évite la race condition d'écriture S3 dans validate_token()
        self._last_used_cache: dict[str, str] = {}

    def _find_token_by_hash(self, store: "TokensStore", token_hash: str) -> tuple:
        """
        Trouve un token par préfixe de hash (VULN-03 fix).

        Retourne (index, token) ou (-1, None) si introuvable.
        Retourne (-2, None) si le préfixe est ambigu (multiple matches).

        Exige un minimum de 16 caractères pour le préfixe (hex pur ou avec
        préfixe ``sha256:``). Le préfixe ``sha256:`` est optionnel — il est
        accepté tel quel ou ajouté implicitement si l'utilisateur fournit
        uniquement le hex (issue #11).
        """
        # Issue #11 fix : normaliser l'entrée pour accepter les deux formes
        # ("sha256:abc..." comme retourné par admin_list_tokens, ou juste "abc..."
        # qui est ce que les utilisateurs copient naturellement).
        normalized = (
            token_hash if token_hash.startswith("sha256:") else "sha256:" + token_hash
        )

        # La validation min 16 chars s'applique sur le hex pur (8 octets de hash),
        # pas sur la longueur incluant le préfixe.
        hex_only = normalized[len("sha256:"):]
        if len(hex_only) < 16:
            return (-3, None)  # Préfixe trop court

        matches = [
            (i, t) for i, t in enumerate(store.tokens) if t.hash.startswith(normalized)
        ]

        if len(matches) == 0:
            return (-1, None)
        if len(matches) > 1:
            return (-2, None)
        return matches[0]

    def _token_not_found_or_ambiguous(self, idx: int, token_hash: str) -> dict | None:
        """Retourne un message d'erreur si le token n'est pas trouvé, ou None si OK."""
        if idx == -3:
            # Review #12 fix : afficher la longueur du hex pur (pas du préfixé),
            # car la validation min 16 chars s'applique sur le hex.
            hex_part = (
                token_hash[len("sha256:") :]
                if token_hash.startswith("sha256:")
                else token_hash
            )
            return {
                "status": "error",
                "message": (
                    f"Hash hex trop court ({len(hex_part)} chars). "
                    "Minimum 16 caractères hex requis."
                ),
            }
        if idx == -2:
            return {
                "status": "error",
                "message": "Préfixe de hash ambigu — plusieurs tokens correspondent. Fournissez un hash plus long.",
            }
        if idx == -1:
            return {"status": "not_found", "message": "Token introuvable"}
        return None

    async def _resolve_space_ids(self, space_ids: str) -> tuple[list[str], bool]:
        """
        Résout l'argument ``space_ids`` en liste matérialisée.

        Gère le sucre syntaxique ``"*"`` / ``"all"`` (snapshot des espaces
        existants au moment de l'appel) — partagé entre ``create_token`` et
        ``update_token`` pour garantir une UX cohérente (review #12).

        Args:
            space_ids: Chaîne d'entrée. Une liste séparée par virgules,
                ou ``"*"``/``"all"`` (snapshot), ou vide.

        Returns:
            Tuple ``(sid_list, snapshot_used)`` :

            - ``sid_list`` : liste matérialisée des space_ids
            - ``snapshot_used`` : ``True`` si le sucre ``*``/``all`` a été
              utilisé (la réponse appelante ajoutera des champs informatifs).
        """
        space_ids_stripped = (space_ids or "").strip()
        if space_ids_stripped.lower() in ("*", "all"):
            from .space import get_space_service  # import local pour éviter cycles

            spaces_result = await get_space_service().list_spaces()
            if spaces_result.get("status") == "ok":
                return (
                    [s["space_id"] for s in spaces_result.get("spaces", [])],
                    True,
                )
            return ([], True)
        return ([s.strip() for s in space_ids.split(",") if s.strip()], False)

    @staticmethod
    def _invalidate_in_fresh_store(token_hashes: list[str]) -> None:
        """
        LM2-07 fix : invalide une liste de tokens dans le store global.

        Délégation à ``auth.context.invalidate_token_in_store`` pour
        chaque hash. Import local pour éviter un cycle (auth importe
        core indirectement).

        Idempotent et best-effort : un échec silencieux ne casse pas
        la mutation S3 déjà persistée.
        """
        try:
            from ..auth.context import invalidate_token_in_store
        except Exception:
            return
        for h in token_hashes:
            if not h:
                continue
            try:
                invalidate_token_in_store(h)
            except Exception:
                # Logging best-effort, on n'interrompt pas le flux mutateur
                pass

    @staticmethod
    def _muted_token_warning() -> str:
        """Message standard pour les tokens "muets" (issue #11)."""
        return (
            "⚠️ Ce token n'a accès à aucun espace existant (space_ids=[]). "
            "Depuis v1.5.0, c'est la sémantique stricte par défaut. "
            "Utilisez space_ids='*' pour un snapshot de tous les espaces "
            "actuels, ou listez-les explicitement (ex: 'space-a,space-b'). "
            "Le token peut tout de même créer ses propres nouveaux spaces."
        )


    async def create_token(
        self,
        name: str,
        permissions: str,
        space_ids: str = "",
        expires_in_days: int = 0,
        email: str = "",
    ) -> dict:
        """
        Crée un nouveau token d'authentification.

        Le token en clair est retourné UNE SEULE FOIS. Seul le hash
        SHA-256 est stocké dans tokens.json.

        Args:
            name: Nom descriptif (ex: "agent-cline")
            permissions: "read", "read,write", ou "read,write,admin"
            space_ids: Espaces autorisés séparés par virgules.
                Sémantique v1.5.0+ pour les non-admin :

                - ``""`` (vide) → **aucun accès** aux espaces existants
                  (le token ne pourra que créer ses propres nouveaux spaces).
                - ``"a,b,c"`` → accès uniquement à ces espaces.
                - ``"*"`` ou ``"all"`` → snapshot des espaces existants au
                  moment de la création (pas les futurs spaces ; aligné
                  avec la sémantique stricte v1.5.0).

                Pour les tokens admin, ``space_ids`` est ignoré (accès à tout).
            expires_in_days: Durée en jours (0 = jamais)

        Returns:
            ``{"status": "created", "token": "lm_...", ...}``.
            Si le token résultant n'a accès à aucun espace existant et n'est
            pas admin, un champ ``warning_no_access`` explicite est ajouté à
            la réponse (issue #11).
        """
        # Générer le token : préfixe + 32 bytes base64url = 46 chars
        raw_token = TOKEN_PREFIX + secrets.token_urlsafe(32)

        # Hasher le token
        token_hash = "sha256:" + hashlib.sha256(raw_token.encode()).hexdigest()

        # Parser et valider les permissions
        perm_list = [p.strip() for p in permissions.split(",") if p.strip()]
        if not perm_list:
            return {"status": "error", "message": "Permissions requises"}
        invalid = [p for p in perm_list if p not in VALID_PERMISSIONS]
        if invalid:
            return {
                "status": "error",
                "message": (
                    f"Permissions invalides : {invalid}. "
                    f"Valeurs acceptées : {sorted(VALID_PERMISSIONS)}"
                ),
            }

        # Issue #11 fix + review #12 : logique partagée avec update_token
        # via _resolve_space_ids (sucre "*"/"all" → snapshot).
        space_ids_stripped = (space_ids or "").strip()
        sid_list, snapshot_used = await self._resolve_space_ids(space_ids)

        # Calculer l'expiration
        now = datetime.now(timezone.utc)
        expires_at = None
        if expires_in_days > 0:
            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        # Créer l'entrée token
        token_info = TokenInfo(
            hash=token_hash,
            name=name,
            email=email,
            permissions=perm_list,
            space_ids=sid_list,
            created_at=now.isoformat(),
            expires_at=expires_at,
        )

        # Sauvegarder sous lock
        async with get_lock_manager().tokens:
            store = await self._load_store()
            store.tokens.append(token_info)
            await self._save_store(store)

        response = {
            "status": "created",
            "name": name,
            "token": raw_token,
            "permissions": perm_list,
            "space_ids": sid_list,
            "expires_at": expires_at,
            "warning": "⚠️ Ce token ne sera PLUS JAMAIS affiché !",
        }

        # Issue #11 fix : signaler explicitement les tokens "muets"
        # (non-admin avec aucun space autorisé) — ces tokens recevraient un 403
        # sur tout espace existant. Ils peuvent toutefois créer leurs propres
        # spaces (auto-ajoutés via add_space_to_token).
        is_admin = "admin" in perm_list
        if not is_admin and not sid_list:
            response["warning_no_access"] = self._muted_token_warning()

        if snapshot_used:
            response["snapshot_taken"] = True
            response["info"] = (
                f"space_ids='{space_ids_stripped}' interprété comme snapshot "
                f"des {len(sid_list)} espace(s) existant(s) au moment de la création. "
                "Les futurs nouveaux espaces ne seront PAS automatiquement ajoutés."
            )

        return response

    async def list_tokens(
        self,
        name_contains: str = "",
        has_space: str = "",
        include_revoked: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """
        Liste les tokens (métadonnées seulement, jamais le hash complet).

        Filtres optionnels (issue #13) appliqués in-memory sur la liste
        chargée depuis S3. Tous les defaults reproduisent le comportement
        antérieur (rétrocompat stricte).

        La pagination via ``limit``/``offset`` garantit que la réponse
        reste sous le seuil de troncature du middleware (512 KB) même
        avec des registres de grande taille.

        Args:
            name_contains: Sous-chaîne recherchée dans ``token.name``
                (insensible à la casse). Vide = pas de filtre.
            has_space: Filtre les tokens dont ``space_ids`` contient
                exactement ce ``space_id`` (match exact, sensible à la casse).
                Vide = pas de filtre.
            include_revoked: Si ``False``, exclut les tokens révoqués
                du résultat. Défaut ``True`` (comportement historique).
            limit: Nombre max de tokens à retourner (défaut 100, max 1000).
            offset: Décalage 0-based dans la liste filtrée (défaut 0).

        Returns:
            ``{"status": "ok", "tokens": [...], "total": N,
            "limit": L, "offset": O, "has_more": bool, "filters": {...}}``
            — ``total`` reflète le nombre de tokens après filtres (avant
            pagination) ; ``has_more`` indique si une page suivante existe.
            Le bloc ``filters`` n'est ajouté que si au moins un filtre actif.
        """
        store = await self._load_store()

        # Préparation des filtres
        needle = name_contains.strip().lower() if name_contains else ""
        space_needle = has_space.strip() if has_space else ""

        tokens_list = []
        for t in store.tokens:
            # Filtre revoked
            if not include_revoked and t.revoked:
                continue
            # Filtre name_contains (case-insensitive)
            if needle and needle not in t.name.lower():
                continue
            # Filtre has_space (match exact)
            if space_needle and space_needle not in t.space_ids:
                continue

            tokens_list.append(
                {
                    "hash": t.hash,
                    "name": t.name,
                    "email": t.email,
                    "permissions": t.permissions,
                    "space_ids": t.space_ids,
                    "created_at": t.created_at,
                    "expires_at": t.expires_at,
                    "last_used_at": t.last_used_at,
                    "revoked": t.revoked,
                }
            )

        total_filtered = len(tokens_list)
        page = tokens_list[offset : offset + limit]

        response = {
            "status": "ok",
            "tokens": page,
            "total": total_filtered,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total_filtered,
        }

        # Trace des filtres appliqués (utile pour debug / audit)
        active_filters = {}
        if name_contains:
            active_filters["name_contains"] = name_contains
        if has_space:
            active_filters["has_space"] = has_space
        if not include_revoked:
            active_filters["include_revoked"] = False
        if active_filters:
            response["filters"] = active_filters

        return response

    async def revoke_token(self, token_hash: str) -> dict:
        """
        Révoque un token (le rend inutilisable).

        VULN-03 fix : utilise _find_token_by_hash pour une correspondance
        sécurisée (min 16 chars, détection d'ambiguïté).

        LM2-07 fix : purge aussi le ``_fresh_token_store`` global pour
        empêcher toute opération longue (consolidation, push graph) en
        cours de continuer à voir les anciennes permissions.

        Args:
            token_hash: Hash SHA-256 du token (min 16 chars de préfixe)

        Returns:
            {"status": "ok"} ou erreur
        """
        async with get_lock_manager().tokens:
            store = await self._load_store()
            idx, token = self._find_token_by_hash(store, token_hash)
            err = self._token_not_found_or_ambiguous(idx, token_hash)
            if err:
                return err

            token.revoked = True
            full_hash = token.hash
            await self._save_store(store)

        # LM2-07 fix : invalider dans le store global après save_store
        self._invalidate_in_fresh_store([full_hash])

        return {"status": "ok", "message": f"Token '{token.name}' révoqué"}

    async def delete_token(self, token_hash: str) -> dict:
        """
        Supprime physiquement un token du registre.

        VULN-03 fix : utilise _find_token_by_hash pour une correspondance
        sécurisée (min 16 chars, détection d'ambiguïté).

        Args:
            token_hash: Hash SHA-256 du token (min 16 chars de préfixe)

        Returns:
            {"status": "deleted", "name": "..."} ou erreur
        """
        async with get_lock_manager().tokens:
            store = await self._load_store()
            idx, token = self._find_token_by_hash(store, token_hash)
            err = self._token_not_found_or_ambiguous(idx, token_hash)
            if err:
                return err

            deleted_name = token.name
            deleted_hash = token.hash
            store.tokens.pop(idx)
            await self._save_store(store)

        # LM2-07 fix : purge du store global après save_store
        self._invalidate_in_fresh_store([deleted_hash])

        return {
            "status": "deleted",
            "name": deleted_name,
            "message": f"Token '{deleted_name}' supprimé physiquement",
            "remaining": len(store.tokens),
        }

    async def purge_tokens(self, revoked_only: bool = True) -> dict:
        """
        Supprime physiquement plusieurs tokens du registre.

        Args:
            revoked_only: Si True, ne supprime que les tokens révoqués.
                         Si False, supprime TOUS les tokens.

        Returns:
            {"status": "ok", "deleted": N, "remaining": M}
        """
        async with get_lock_manager().tokens:
            store = await self._load_store()
            original_count = len(store.tokens)

            # LM2-07 fix : collecter les hashes supprimés AVANT mutation
            # pour pouvoir purger le store global après save_store.
            if revoked_only:
                deleted_hashes = [t.hash for t in store.tokens if t.revoked]
                store.tokens = [t for t in store.tokens if not t.revoked]
            else:
                deleted_hashes = [t.hash for t in store.tokens]
                store.tokens = []

            deleted_count = original_count - len(store.tokens)
            await self._save_store(store)

        # LM2-07 fix : purge en masse du store global
        self._invalidate_in_fresh_store(deleted_hashes)

        return {
            "status": "ok",
            "deleted": deleted_count,
            "remaining": len(store.tokens),
            "mode": "revoked_only" if revoked_only else "all",
            "message": f"{deleted_count} token(s) supprimé(s) physiquement",
        }

    # ─────────────────────────────────────────────────────────
    # Helpers privés pour les opérations de mise à jour (issue #13)
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_csv_spaces(value: str) -> list[str]:
        """Parse une chaîne CSV en liste dédupliquée, ordre préservé."""
        if not value:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for raw in value.split(","):
            sid = raw.strip()
            if not sid:
                continue
            if sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
        return out

    @staticmethod
    def _validate_update_mutex(
        space_ids: str, space_ids_add: str, space_ids_remove: str
    ) -> dict | None:
        """
        Vérifie l'exclusion mutuelle entre `space_ids` (remplacement) et
        `space_ids_add`/`space_ids_remove` (delta additif) — issue #13.

        Le sucre ``"*"``/``"all"`` reste valable uniquement pour
        ``space_ids`` (remplacement par snapshot). Il est interdit dans
        ``_add``/``_remove`` (un delta "tout ajouter / tout retirer" n'a
        pas de sémantique claire et serait piégeur).

        Retourne ``None`` si OK, sinon un dict d'erreur.
        """
        replace_active = bool((space_ids or "").strip())
        delta_active = bool((space_ids_add or "").strip()) or bool(
            (space_ids_remove or "").strip()
        )

        if replace_active and delta_active:
            return {
                "status": "error",
                "message": (
                    "Paramètres incompatibles : `space_ids` (remplacement) "
                    "et `space_ids_add`/`space_ids_remove` (delta additif) "
                    "ne peuvent pas être combinés. Choisissez l'un ou l'autre."
                ),
            }

        # Interdiction du sucre "*"/"all" dans les deltas (décision issue #13).
        for label, value in (
            ("space_ids_add", space_ids_add),
            ("space_ids_remove", space_ids_remove),
        ):
            stripped = (value or "").strip().lower()
            if stripped in ("*", "all"):
                return {
                    "status": "error",
                    "message": (
                        f"`{label}` n'accepte pas le sucre '*' / 'all' "
                        "(sémantique ambiguë sur un delta). Listez les "
                        "espaces explicitement ou utilisez `space_ids='*'` "
                        "pour un remplacement complet."
                    ),
                }

        return None

    @staticmethod
    def _apply_space_delta(
        current: list[str], to_add: list[str], to_remove: list[str]
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """
        Applique un delta additif sur une liste de space_ids.

        Sémantique :
        - ``to_add`` : chaque entrée non déjà présente est ajoutée.
        - ``to_remove`` : chaque entrée présente est retirée.
        - Idempotent : appels répétés ⇒ même résultat.
        - L'ordre relatif des entrées existantes est préservé.
        - ``_remove`` est appliqué AVANT ``_add`` (permet "remplacer X par Y"
          via `_add=Y,_remove=X` même si X==Y → effet net = présent).

        Returns:
            Tuple ``(new_list, actually_added, actually_removed, noop)`` :

            - ``new_list`` : liste résultante
            - ``actually_added`` : entrées effectivement ajoutées
            - ``actually_removed`` : entrées effectivement retirées
            - ``noop`` : entrées demandées mais sans effet (déjà
              présentes pour ``_add`` ou absentes pour ``_remove``)
        """
        actually_removed: list[str] = []
        noop: list[str] = []

        # Phase 1 : retraits
        working = list(current)
        for sid in to_remove:
            if sid in working:
                working.remove(sid)
                actually_removed.append(sid)
            else:
                noop.append(f"remove:{sid}")

        # Phase 2 : ajouts (en tête de liste préservée, append en queue)
        actually_added: list[str] = []
        for sid in to_add:
            if sid in working:
                noop.append(f"add:{sid}")
            else:
                working.append(sid)
                actually_added.append(sid)

        return working, actually_added, actually_removed, noop

    async def update_token(
        self,
        token_hash: str,
        space_ids: str = "",
        permissions: str = "",
        email: str = "",
        space_ids_add: str = "",
        space_ids_remove: str = "",
    ) -> dict:
        """
        Met à jour un token : permissions, email, et/ou ``space_ids``.

        **Trois modes pour ``space_ids``** (issue #13) :

        1. **Pas de changement** : aucun des trois paramètres
           ``space_ids``/``space_ids_add``/``space_ids_remove`` n'est fourni.
        2. **Remplacement complet** (legacy) : ``space_ids`` non vide.
           Accepte ``"*"``/``"all"`` (snapshot) ou une liste CSV.
        3. **Delta additif** (issue #13) : ``space_ids_add`` et/ou
           ``space_ids_remove`` non vides. Idempotent : ajouter un space
           déjà présent (ou retirer un absent) est un no-op. ``_remove``
           est appliqué avant ``_add``.

        Les modes (2) et (3) sont **mutuellement exclusifs** (erreur 400 si
        on les combine). Le sucre ``"*"``/``"all"`` n'est PAS supporté
        dans ``_add``/``_remove`` (sémantique ambiguë sur un delta).

        VULN-03 fix : ``_find_token_by_hash`` (min 16 chars, ambiguïté
        détectée). Review #12 : ``warning_no_access`` ajouté si le token
        résultant est muet (non-admin avec space_ids=[]).

        Args:
            token_hash: Hash du token (min 16 chars de préfixe)
            space_ids: Mode remplacement. ``""`` = pas de changement.
            permissions: Nouvelles permissions (vide = pas de changement)
            email: Nouvel email (vide = pas de changement)
            space_ids_add: Mode delta — espaces à ajouter (CSV).
            space_ids_remove: Mode delta — espaces à retirer (CSV).

        Returns:
            ``{"status": "ok", ...}`` avec, en mode delta, les champs
            ``space_ids_added``, ``space_ids_removed``, ``space_ids_noop``,
            ``space_ids_before``, ``space_ids_after``. ``warning_no_access``
            si le token devient muet.
        """
        # Validation de l'exclusion mutuelle (avant toute lecture S3).
        mutex_err = self._validate_update_mutex(
            space_ids, space_ids_add, space_ids_remove
        )
        if mutex_err:
            return mutex_err

        # Pré-résoudre le sucre "*"/"all" hors du lock pour éviter
        # de tenir le verrou pendant un appel S3 (list_spaces).
        space_ids_stripped = (space_ids or "").strip()
        new_space_ids: Optional[list[str]] = None  # mode remplacement
        snapshot_used = False
        if space_ids_stripped:
            new_space_ids, snapshot_used = await self._resolve_space_ids(space_ids)

        # Parse des deltas (mode additif)
        add_list = self._parse_csv_spaces(space_ids_add)
        remove_list = self._parse_csv_spaces(space_ids_remove)
        delta_mode = bool(add_list) or bool(remove_list)

        async with get_lock_manager().tokens:
            store = await self._load_store()

            # Valider les permissions avant modification
            if permissions:
                perm_list = [p.strip() for p in permissions.split(",") if p.strip()]
                invalid = [p for p in perm_list if p not in VALID_PERMISSIONS]
                if invalid:
                    return {
                        "status": "error",
                        "message": (
                            f"Permissions invalides : {invalid}. "
                            f"Valeurs acceptées : {sorted(VALID_PERMISSIONS)}"
                        ),
                    }

            idx, token = self._find_token_by_hash(store, token_hash)
            err = self._token_not_found_or_ambiguous(idx, token_hash)
            if err:
                return err

            # Snapshot du before (pour traçabilité delta)
            before_space_ids = list(token.space_ids)

            actually_added: list[str] = []
            actually_removed: list[str] = []
            noop_entries: list[str] = []

            if permissions:
                token.permissions = [
                    p.strip() for p in permissions.split(",") if p.strip()
                ]
            if new_space_ids is not None:
                # Mode remplacement complet
                token.space_ids = new_space_ids
            elif delta_mode:
                # Mode delta additif
                (
                    token.space_ids,
                    actually_added,
                    actually_removed,
                    noop_entries,
                ) = self._apply_space_delta(token.space_ids, add_list, remove_list)
            if email:
                token.email = email

            await self._save_store(store)
            # Snapshot des champs nécessaires pour la réponse (avant sortie du lock)
            updated_name = token.name
            updated_hash = token.hash
            updated_space_ids = list(token.space_ids)
            updated_perms = list(token.permissions)

        # LM2-07 fix : purger le store global si les droits effectifs ont
        # été modifiés (permissions ou space_ids). L'email seul n'affecte
        # pas l'autorisation runtime → pas d'invalidation nécessaire.
        if permissions or new_space_ids is not None or delta_mode:
            self._invalidate_in_fresh_store([updated_hash])

        response = {
            "status": "ok",
            "message": f"Token '{updated_name}' mis à jour",
        }

        space_ids_touched = (new_space_ids is not None) or delta_mode

        # Review #12 : signaler un token muet (cohérent avec create_token)
        # uniquement si space_ids a été touché par cet appel.
        if space_ids_touched:
            is_admin = "admin" in updated_perms
            if not is_admin and not updated_space_ids:
                response["warning_no_access"] = self._muted_token_warning()

        if snapshot_used:
            response["snapshot_taken"] = True
            response["info"] = (
                f"space_ids='{space_ids_stripped}' interprété comme snapshot "
                f"des {len(updated_space_ids)} espace(s) existant(s) au moment "
                "de la mise à jour. Les futurs nouveaux espaces ne seront PAS "
                "automatiquement ajoutés."
            )

        if delta_mode:
            response["mode"] = "delta"
            response["space_ids_before"] = before_space_ids
            response["space_ids_after"] = updated_space_ids
            response["space_ids_added"] = actually_added
            response["space_ids_removed"] = actually_removed
            if noop_entries:
                response["space_ids_noop"] = noop_entries

        return response

    async def bulk_update_tokens(
        self,
        names: str = "",
        name_contains: str = "",
        has_space: str = "",
        permissions: str = "",
        email: str = "",
        space_ids_add: str = "",
        space_ids_remove: str = "",
        include_revoked: bool = False,
    ) -> dict:
        """
        Met à jour plusieurs tokens en une seule opération (issue #13).

        **Atomicité** : tokens.json est un fichier S3 unique chargé/sauvé
        sous lock asyncio. Toutes les modifications sont appliquées en
        mémoire, validées, puis une seule écriture finale. En cas d'erreur
        de validation (ex: permissions invalides), AUCUNE modification
        n'est persistée. ⚠️ Atomicité garantie *au sein d'une instance
        MCP* — un déploiement HA multi-instances nécessiterait un verrou
        externe (Redis/etcd), non implémenté (déploiement single-instance).

        **Filtres** (au moins un de ``names``/``name_contains``/``has_space``
        requis) :

        - ``names`` : liste CSV de noms exacts à matcher.
        - ``name_contains`` : sous-chaîne dans le nom (case-**insensitive**).
        - ``has_space`` : space_id présent dans ``token.space_ids``
          (match exact, case-**sensitive**, cohérent avec ``list_tokens``).
          ⚠️ Asymétrie volontaire : les noms sont libres et le matching
          tolérant à la casse aide l'opérateur ; les ``space_ids`` sont
          des identifiants techniques et la casse est significative.

        ⚠️ **Tous les filtres fournis sont combinés en AND** : un token
        doit satisfaire **chacun**. Exemple piège : ``names="a,b,c"`` +
        ``name_contains="agent"`` n'inclura PAS un token nommé ``"c"``
        s'il ne contient pas ``"agent"``. Pour une logique OR, faites
        plusieurs appels.

        **Filtre sécurité — ``include_revoked``** (review PR #14) :

        - Défaut ``False`` : les tokens révoqués matchés par les filtres
          sont **sautés** et listés dans ``skipped_revoked``. Asymétrie
          volontaire avec ``list_tokens(include_revoked=True)`` — la
          sémantique d'usage diffère : on **observe** vs on **mute**.
          Modifier un token révoqué n'a aucun effet pratique mais peut
          créer des permissions fantômes en cas de ré-activation.
        - ``True`` : opt-in explicite pour modifier aussi les révoqués
          (ex: réhabilitation avant ré-activation).

        **Opérations** (au moins une requise, sinon erreur 400) :

        - ``permissions`` : nouvelles permissions à appliquer.
        - ``email`` : nouvel email.
        - ``space_ids_add`` / ``space_ids_remove`` : deltas additifs
          idempotents (mêmes règles que ``update_token`` en mode delta).
          Le cas dégénéré ``_add=X, _remove=X`` retire puis ré-ajoute X :
          effet net = X présent en queue de liste.

        ⚠️ Volontairement, ``bulk_update_tokens`` n'expose **pas** le
        mode remplacement ``space_ids`` (trop dangereux à propager sur N
        tokens — risque de révocation silencieuse en masse).

        **Audit** (review PR #14, point #4) : un événement structuré
        ``event="bulk_update_tokens"`` est émis sur le logger
        ``live_mem.audit`` après l'écriture S3 (succès garanti). Permet
        la rejouabilité même si le retour MCP est perdu côté client.

        Args:
            names: Noms exacts à filtrer (CSV).
            name_contains: Sous-chaîne case-insensitive dans le nom.
            has_space: Space_id présent dans space_ids (match exact).
            permissions: Nouvelles permissions (CSV) à appliquer.
            email: Nouvel email à appliquer.
            space_ids_add: Spaces à ajouter (CSV).
            space_ids_remove: Spaces à retirer (CSV).
            include_revoked: Inclure les tokens révoqués (défaut False).

        Returns:
            ``{"status": "ok", "updated": N, "tokens": [...],
            "skipped_revoked": [{"name", "hash"}], "filters": {...},
            "operations": {...}}``.
            ``skipped_revoked`` n'est présent que si au moins un token
            révoqué a été matché par les filtres (mais pas modifié).
            Si aucun token ne matche : ``updated=0``, statut ``ok``.
        """
        # ─── Validation des filtres ───
        names_list = [n.strip() for n in (names or "").split(",") if n.strip()]
        name_contains_norm = (name_contains or "").strip()
        has_space_norm = (has_space or "").strip()
        if not names_list and not name_contains_norm and not has_space_norm:
            return {
                "status": "error",
                "message": (
                    "Au moins un filtre requis : `names` (liste exacte), "
                    "`name_contains` (sous-chaîne) ou `has_space` (space_id)."
                ),
            }

        # ─── Validation des opérations ───
        # Note : `space_ids` (remplacement) volontairement absent — voir docstring.
        op_perm = (permissions or "").strip()
        op_email = (email or "").strip()
        add_list = self._parse_csv_spaces(space_ids_add)
        remove_list = self._parse_csv_spaces(space_ids_remove)

        if not (op_perm or op_email or add_list or remove_list):
            return {
                "status": "error",
                "message": (
                    "Aucune opération demandée. Fournissez au moins "
                    "`permissions`, `email`, `space_ids_add` ou `space_ids_remove`."
                ),
            }

        # Valider le sucre interdit "*"/"all" dans les deltas (avant lock).
        mutex_err = self._validate_update_mutex("", space_ids_add, space_ids_remove)
        if mutex_err:
            return mutex_err

        # Valider les permissions à plat (avant lock).
        if op_perm:
            perm_list = [p.strip() for p in op_perm.split(",") if p.strip()]
            invalid = [p for p in perm_list if p not in VALID_PERMISSIONS]
            if invalid:
                return {
                    "status": "error",
                    "message": (
                        f"Permissions invalides : {invalid}. "
                        f"Valeurs acceptées : {sorted(VALID_PERMISSIONS)}"
                    ),
                }
        else:
            perm_list = None  # signal "ne pas toucher"

        # ─── Application sous lock ───
        needle = name_contains_norm.lower()
        async with get_lock_manager().tokens:
            store = await self._load_store()

            # Sélection des tokens matchant les filtres (AND-combinés).
            # Les révoqués matchés sont mis à part dans `skipped_revoked`
            # quand include_revoked=False (review PR #14, point #3).
            selected: list[TokenInfo] = []
            skipped_revoked: list[dict] = []
            for t in store.tokens:
                if names_list and t.name not in names_list:
                    continue
                if needle and needle not in t.name.lower():
                    continue
                if has_space_norm and has_space_norm not in t.space_ids:
                    continue
                # Filtres satisfaits : décider de l'inclusion selon revoked.
                if t.revoked and not include_revoked:
                    skipped_revoked.append({"name": t.name, "hash": t.hash})
                    continue
                selected.append(t)

            filters_block = {
                "names": names_list,
                "name_contains": name_contains_norm,
                "has_space": has_space_norm,
                "include_revoked": include_revoked,
            }

            if not selected:
                response: dict = {
                    "status": "ok",
                    "updated": 0,
                    "tokens": [],
                    "filters": filters_block,
                }
                if skipped_revoked:
                    response["skipped_revoked"] = skipped_revoked
                    response["message"] = (
                        f"Aucun token actif ne correspond — "
                        f"{len(skipped_revoked)} token(s) révoqué(s) "
                        "matché(s) mais sautés (utilisez include_revoked=True "
                        "pour les inclure)."
                    )
                else:
                    response["message"] = "Aucun token ne correspond aux filtres."
                return response

            # Application en mémoire (atomique : aucune écriture S3 tant que
            # toutes les modifs ne sont pas faites).
            report: list[dict] = []
            for t in selected:
                before_space_ids = list(t.space_ids)
                before_perms = list(t.permissions)
                before_email = t.email

                if perm_list is not None:
                    t.permissions = list(perm_list)
                if op_email:
                    t.email = op_email

                added: list[str] = []
                removed: list[str] = []
                noop: list[str] = []
                if add_list or remove_list:
                    t.space_ids, added, removed, noop = self._apply_space_delta(
                        t.space_ids, add_list, remove_list
                    )

                entry: dict = {
                    "name": t.name,
                    "hash": t.hash,
                    "before": {
                        "space_ids": before_space_ids,
                        "permissions": before_perms,
                        "email": before_email,
                    },
                    "after": {
                        "space_ids": list(t.space_ids),
                        "permissions": list(t.permissions),
                        "email": t.email,
                    },
                }
                if add_list or remove_list:
                    entry["space_ids_added"] = added
                    entry["space_ids_removed"] = removed
                    if noop:
                        entry["space_ids_noop"] = noop
                report.append(entry)

            # Une seule écriture S3 ⇒ atomicité naturelle
            await self._save_store(store)

        # LM2-07 fix : purger le store global pour tous les tokens dont les
        # droits ont été modifiés (permissions ou space_ids touchés). L'email
        # seul n'affecte pas l'autorisation runtime → skip pour économiser.
        if perm_list is not None or add_list or remove_list:
            self._invalidate_in_fresh_store([entry["hash"] for entry in report])

        # ─── Audit logging (review PR #14, point #4) ───
        # Émis APRÈS le save_store : on ne loggue que les opérations
        # effectivement persistées. Les échecs de validation ne polluent
        # pas l'audit (ils ont leur retour MCP côté client).
        self._emit_bulk_update_audit(
            filters=filters_block,
            operations={
                "permissions": perm_list,
                "email": op_email or None,
                "space_ids_add": add_list,
                "space_ids_remove": remove_list,
            },
            updated=len(report),
            token_hashes=[entry["hash"] for entry in report],
            skipped_revoked=skipped_revoked,
        )

        response = {
            "status": "ok",
            "updated": len(report),
            "tokens": report,
            "filters": filters_block,
            "operations": {
                "permissions": perm_list,
                "email": op_email or None,
                "space_ids_add": add_list,
                "space_ids_remove": remove_list,
            },
        }
        if skipped_revoked:
            response["skipped_revoked"] = skipped_revoked
        return response

    @staticmethod
    def _emit_bulk_update_audit(
        *,
        filters: dict,
        operations: dict,
        updated: int,
        token_hashes: list[str],
        skipped_revoked: list[dict],
    ) -> None:
        """
        Émet un événement d'audit structuré sur le logger ``live_mem.audit``.

        Appelé après une opération ``bulk_update_tokens`` réussie. Le
        contenu permet de rejouer/auditer l'opération a posteriori :
        identité du caller, filtres, opérations, cibles, sautés.

        L'identité du caller et le request_id sont récupérés depuis les
        ``ContextVar`` du middleware (best effort — fallback "system" si
        appel hors-requête HTTP, par ex. via tests unitaires ou CLI).
        """
        # Imports locaux pour éviter les cycles et permettre les tests
        # qui n'instancient pas le middleware stack complet.
        try:
            from ..auth.context import current_token_info
            from ..middleware import current_request_id

            tinfo = current_token_info.get()
            caller = tinfo.get("client_name", "unknown") if tinfo else "system"
            req_id = current_request_id.get()
        except Exception:
            caller = "system"
            req_id = "-"

        entry = {
            "event": "bulk_update_tokens",
            "request_id": req_id,
            "caller": caller,
            "filters": filters,
            "operations": operations,
            "updated": updated,
            "token_hashes": token_hashes,
            "skipped_revoked_count": len(skipped_revoked),
        }
        # Best effort : un échec de logging ne doit pas casser l'opération
        # (le store S3 est déjà sauvé à ce stade).
        try:
            _audit_logger.info(json.dumps(entry, ensure_ascii=False))
        except Exception:
            pass

    async def add_space_to_token(self, token_hash: str, space_id: str) -> dict:
        """
        Ajoute un space_id à la liste des espaces autorisés d'un token.

        Appelé automatiquement par space_create quand un client crée un
        nouvel espace. Sans cet ajout, le client ne pourrait pas accéder
        au space qu'il vient de créer (deadlock UX).

        Depuis v1.5.0, space_ids=[] signifie "aucun accès" (pas "tous").
        Cette méthode ajoute toujours le space, même si la liste est vide.

        Args:
            token_hash: Hash SHA-256 du token courant
            space_id: ID du space à ajouter

        Returns:
            {"status": "ok"} ou {"status": "skipped"} ou erreur
        """
        async with get_lock_manager().tokens:
            store = await self._load_store()

            for t in store.tokens:
                if t.hash == token_hash:
                    # Si le space est déjà dans la liste, rien à faire
                    if space_id in t.space_ids:
                        return {
                            "status": "skipped",
                            "message": f"Space '{space_id}' already in token",
                        }
                    # Ajouter le space
                    t.space_ids.append(space_id)
                    await self._save_store(store)
                    return {
                        "status": "ok",
                        "message": f"Space '{space_id}' added to token",
                        "space_ids": t.space_ids,
                    }

            return {"status": "not_found", "message": "Token not found"}

    async def validate_token(self, raw_token: str) -> Optional[dict]:
        """
        Valide un token brut et retourne ses infos.

        Appelé par le middleware d'authentification à chaque requête.

        VULN-01 (audit v1.0.0) : l'écriture de last_used_at a été supprimée
        de cette méthode pour éliminer la race condition avec les opérations
        sous lock (create/revoke/update). last_used_at est désormais mis à
        jour de manière différée via _update_last_used().

        Args:
            raw_token: Token en clair (ex: "lm_a1B2c3...")

        Returns:
            Dict avec client_name, permissions, allowed_resources
            ou None si le token est invalide/révoqué/expiré
        """
        # Calculer le hash
        token_hash = "sha256:" + hashlib.sha256(raw_token.encode()).hexdigest()

        # Charger le store
        store = await self._load_store()
        now = datetime.now(timezone.utc).isoformat()

        for t in store.tokens:
            if t.hash != token_hash:
                continue

            # Vérifier révocation
            if t.revoked:
                return None

            # Vérifier expiration
            if t.expires_at and t.expires_at < now:
                return None

            # Token valide — mise à jour last_used_at différée (en mémoire)
            # VULN-01 fix : on ne fait plus _save_store() ici pour éviter
            # la race condition avec create/revoke/update qui sont sous lock.
            self._last_used_cache[token_hash] = now

            return {
                "type": "token",
                "client_name": t.name,
                "permissions": t.permissions,
                "allowed_resources": t.space_ids,
                "token_hash": t.hash,
            }

        return None  # Token inconnu

    async def migrate_empty_space_ids(self, all_space_ids: list[str]) -> dict:
        """
        Migration v1.5.0 : peuple les tokens avec space_ids=[] existants.

        Depuis v1.5.0, space_ids=[] signifie "aucun accès" (au lieu de "tous").
        Cette migration assigne à chaque token non-admin ayant space_ids=[]
        la liste complète des espaces existants, pour préserver leur accès.

        Les tokens admin ne sont pas affectés (admin bypass check_access).

        Args:
            all_space_ids: Liste de tous les space_ids existants

        Returns:
            {"status": "ok", "migrated": N, "skipped": M}
        """
        async with get_lock_manager().tokens:
            store = await self._load_store()
            migrated = 0
            skipped = 0

            for t in store.tokens:
                if t.revoked:
                    skipped += 1
                    continue
                # Admin tokens n'ont pas besoin de space_ids (bypass)
                if "admin" in t.permissions:
                    skipped += 1
                    continue
                # Déjà peuplé → rien à faire
                if t.space_ids:
                    skipped += 1
                    continue
                # Token avec space_ids=[] (ancien "accès à tous")
                # → leur donner tous les espaces existants
                t.space_ids = list(all_space_ids)
                migrated += 1

            if migrated > 0:
                await self._save_store(store)

        return {
            "status": "ok",
            "migrated": migrated,
            "skipped": skipped,
            "total_spaces": len(all_space_ids),
        }

    # ─────────────────────────────────────────────────────────
    # Helpers internes
    # ─────────────────────────────────────────────────────────

    async def _load_store(self) -> TokensStore:
        """Charge le registre de tokens depuis S3."""
        storage = get_storage()
        data = await storage.get_json(TOKENS_KEY)
        if data is None:
            return TokensStore()
        return TokensStore(**data)

    async def _save_store(self, store: TokensStore) -> None:
        """Sauvegarde le registre de tokens sur S3."""
        storage = get_storage()
        await storage.put_json(TOKENS_KEY, store.model_dump())


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_token_service: TokenService | None = None


def get_token_service() -> TokenService:
    """Retourne le singleton TokenService."""
    global _token_service
    if _token_service is None:
        _token_service = TokenService()
    return _token_service
