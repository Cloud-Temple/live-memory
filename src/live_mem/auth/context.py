# -*- coding: utf-8 -*-
"""
Helpers d'authentification basés sur contextvars.

Le middleware ASGI injecte les infos du token dans les contextvars.
Les outils MCP appellent check_access(), check_write_permission(),
check_manage_permission() et check_admin_permission() pour vérifier
les permissions sans dépendre du framework HTTP.

Architecture :
    Middleware ASGI → injecte current_token_info (contextvar)
    Outils MCP → appellent check_xxx() → lisent le contextvar

Voir AUTH_AND_COLLABORATION.md pour la matrice des permissions.

4 niveaux de permission (hiérarchie inclusive) :
    admin ⊃ manage ⊃ write ⊃ read

    - read    (🔑) : lecture des espaces et notes
    - write   (✏️) : écriture de notes + consolidation de ses propres notes
    - manage  (🔧) : maintenance bank (write/delete/repair/compact), space delete,
                      update rules, backup restore/delete
    - admin   (👑) : gestion tokens, GC, accès total sans restriction de space
"""

import re
from contextvars import ContextVar
from typing import Optional

# VULN-08 fix : regex de validation du space_id, appliquée dans check_access()
# Empêche l'utilisation de space_ids malveillants (_system, _backups, ../)
_SPACE_ID_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# ─────────────────────────────────────────────────────────────
# Context variable injectée par le middleware AuthMiddleware
# ─────────────────────────────────────────────────────────────
# Contient un dict avec les champs :
#   - client_name: str (nom du token)
#   - permissions: list[str] (["read"], ["read", "write"], etc.)
#   - allowed_resources: list[str] (space_ids autorisés, [] = tous)
# Ou None si pas de token / token invalide.
current_token_info: ContextVar[Optional[dict]] = ContextVar(
    "current_token_info", default=None
)

# ─────────────────────────────────────────────────────────────
# Fresh token store — contourne le bug des contextvars MCP
# ─────────────────────────────────────────────────────────────
# Le MCP Streamable HTTP crée un task anyio par session. Les tool
# handlers s'exécutent dans ce task, qui a une COPIE FIGÉE du contexte
# asyncio de l'initialisation. Les contextvars du middleware (mis à jour
# à chaque POST) ne sont donc PAS visibles par les tools.
#
# Ce store global est mis à jour par le middleware à chaque requête HTTP,
# et lu par les fonctions check_xxx() pour obtenir les données fraîches
# (permissions, space_ids) même depuis le session task.
_fresh_token_store: dict[str, dict] = {}


def update_fresh_token(token_info: dict) -> None:
    """Met à jour le store global avec les infos fraîches du token.

    Appelé par AuthMiddleware à chaque requête HTTP validée.
    Le token_hash sert de clé (un slot par token distinct).

    LM2-08 fix (doc) : le bootstrap key n'a pas de ``token_hash`` (il
    n'est pas stocké dans ``_system/tokens.json``). Ses infos sont donc
    figées dans le contextvar et ne sont jamais publiées ici — c'est
    volontaire et inoffensif (le bootstrap est toujours admin total).
    """
    token_hash = token_info.get("token_hash")
    if token_hash:
        _fresh_token_store[token_hash] = token_info


def invalidate_token_in_store(token_hash: str) -> None:
    """
    LM2-07 fix : retire un token du store global (révocation effective).

    Doit être appelé par TokenService après revoke_token, delete_token,
    purge_tokens, update_token, bulk_update_tokens. Sans cela, une
    opération longue (consolidation 5 min, push graph 10 min) qui aurait
    démarré juste avant la révocation continuerait à voir l'ancien
    ``permissions``/``allowed_resources`` via ``_get_effective_token_info``
    et pourrait persister une élévation de privilège jusqu'à la fin de
    l'opération.

    Idempotent : no-op si le token n'est pas dans le store (cas typique
    des tokens jamais utilisés depuis le démarrage du process).

    Note : l'invalidation ne casse pas une requête HTTP en cours (le
    contextvar reste figé pour la durée du handler), mais toute requête
    suivante de l'agent obtiendra un 401 sur le pipeline normal.
    """
    _fresh_token_store.pop(token_hash, None)


def _get_effective_token_info() -> Optional[dict]:
    """Retourne le token_info le plus frais disponible.

    Le contextvar peut être stale (figé à l'initialisation de la session
    MCP Streamable HTTP). Le store global est mis à jour par le middleware
    à chaque requête HTTP et contient les données fraîches.

    Priorité : store global (frais) > contextvar (potentiellement stale).
    """
    token_info = current_token_info.get()
    if token_info is None:
        return None

    # Rafraîchir depuis le store global si disponible
    token_hash = token_info.get("token_hash")
    if token_hash and token_hash in _fresh_token_store:
        return _fresh_token_store[token_hash]

    return token_info


def check_access(resource_id: str) -> Optional[dict]:
    """
    Vérifie que le token courant a accès à la ressource (espace).

    Un token peut être restreint à certains space_ids.
    Si allowed_resources est vide → accès à tous les espaces.

    Utilise _get_effective_token_info() pour contourner le bug des
    contextvars stale dans les sessions MCP Streamable HTTP.

    Args:
        resource_id: ID de l'espace à vérifier

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = _get_effective_token_info()

    # Pas de token → accès refusé
    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    # VULN-08 fix : valider le format du space_id AVANT de vérifier les permissions
    # Empêche les tentatives de path traversal via _system, _backups, etc.
    if not _SPACE_ID_REGEX.match(resource_id):
        return {
            "status": "error",
            "message": f"Identifiant d'espace invalide : '{resource_id}'",
        }

    # Admin → accès total (pas de restriction par espace)
    if "admin" in token_info.get("permissions", []):
        return None

    # Vérifier que l'espace est dans la liste autorisée
    # IMPORTANT (v1.5.0) : space_ids=[] signifie "aucun accès" pour les non-admin.
    # Un token fraîchement créé n'a accès à rien d'existant — il peut créer
    # ses propres spaces (auto-ajoutés à sa liste via add_space_to_token).
    allowed = token_info.get("allowed_resources", [])
    if not allowed or resource_id not in allowed:
        return {
            "status": "error",
            "message": f"Accès refusé à l'espace '{resource_id}'",
        }

    return None  # OK


def check_write_permission() -> Optional[dict]:
    """
    Vérifie que le token courant a la permission d'écriture.

    Hiérarchie : admin ⊃ manage ⊃ write → tous acceptés.

    Nécessaire pour : live_note, bank_consolidate, space_create,
    space_update, backup_create, graph_*.

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = _get_effective_token_info()

    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    permissions = token_info.get("permissions", [])
    if "write" in permissions or "manage" in permissions or "admin" in permissions:
        return None

    return {
        "status": "error",
        "message": "Permission 'write' requise pour cette opération",
    }


def check_manage_permission() -> Optional[dict]:
    """
    Vérifie que le token courant a la permission de gestion (manage).

    Hiérarchie : admin ⊃ manage → les deux acceptés.

    Nécessaire pour : bank_write, bank_delete, bank_repair, bank_compact,
    space_delete, space_update_rules, backup_restore, backup_delete.

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = _get_effective_token_info()

    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    permissions = token_info.get("permissions", [])
    if "manage" in permissions or "admin" in permissions:
        return None

    return {
        "status": "error",
        "message": "Permission 'manage' requise pour cette opération",
    }


def check_admin_permission() -> Optional[dict]:
    """
    Vérifie que le token courant a la permission admin.

    Nécessaire pour : admin_create_token, admin_list_tokens,
    admin_revoke_token, admin_update_token, admin_gc_notes.

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = _get_effective_token_info()

    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    permissions = token_info.get("permissions", [])
    if "admin" in permissions:
        return None

    return {
        "status": "error",
        "message": "Permission 'admin' requise pour cette opération",
    }


def safe_error(exception: Exception, context: str = "") -> dict:
    """
    VULN-27 fix : retourne un message d'erreur sécurisé.

    En mode debug (MCP_SERVER_DEBUG=true), retourne le message complet.
    En mode production, retourne un message générique et log les détails.

    Args:
        exception: L'exception capturée
        context: Contexte optionnel (nom de l'outil, ex: "live_note")

    Returns:
        {"status": "error", "message": "..."}
    """
    import logging
    from ..config import get_settings

    logger = logging.getLogger("live_mem.tools")
    logger.exception("Erreur dans %s: %s", context or "outil MCP", exception)

    if get_settings().mcp_server_debug:
        return {"status": "error", "message": str(exception)}

    return {"status": "error", "message": "Erreur interne du serveur"}


def get_current_agent_name() -> str:
    """
    Retourne le nom de l'agent (client_name du token courant).

    Utile pour identifier automatiquement l'auteur d'une note live
    quand le paramètre agent n'est pas fourni.

    Returns:
        Nom de l'agent, ou "anonymous" si pas de token
    """
    token_info = current_token_info.get()
    if token_info is None:
        return "anonymous"
    return token_info.get("client_name", "anonymous")
