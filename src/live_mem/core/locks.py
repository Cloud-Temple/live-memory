# -*- coding: utf-8 -*-
"""
Gestionnaire centralisé des locks — Live Memory.

Le serveur MCP est un processus unique (une seule instance Python).
Toutes les requêtes passent par le même event loop asyncio.
Les asyncio.Lock sont donc suffisants pour la concurrence.

Voir CONCURRENCY.md pour l'analyse complète des risques de concurrence.

Deux types de locks :
1. Bank (un lock par espace) — sérialise consolidation, compaction et maintenance
2. Tokens (un lock unique) — protège _system/tokens.json

Usage :
    from .locks import get_lock_manager
    locks = get_lock_manager()

    # Vérifier si une consolidation est en cours
    if locks.consolidation("mon-espace").locked():
        return {"status": "conflict", ...}

    # Acquérir le lock pour consolider
    async with locks.consolidation("mon-espace"):
        await do_consolidation()

    # Modifier les tokens de façon atomique
    async with locks.tokens:
        data = await load_tokens()
        data = modify(data)
        await save_tokens(data)
"""

import asyncio
from collections import defaultdict


class LockManager:
    """Gestionnaire centralisé des locks asyncio."""

    def __init__(self):
        # Un lock par space_id pour toutes les mutations de la bank.
        # defaultdict crée automatiquement un nouveau Lock
        # la première fois qu'on accède à un space_id.
        self._consolidation_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Lock unique pour le fichier _system/tokens.json.
        # Protège les opérations read-modify-write sur le registre de tokens.
        self._tokens_lock = asyncio.Lock()

    def consolidation(self, space_id: str) -> asyncio.Lock:
        """
        Retourne le lock de consolidation pour un espace donné.

        Deux espaces différents ont des locks indépendants →
        ils peuvent être consolidés en parallèle.
        """
        return self._consolidation_locks[space_id]

    @property
    def tokens(self) -> asyncio.Lock:
        """
        Retourne le lock unique pour _system/tokens.json.

        Toute modification du registre de tokens (create, revoke, update)
        doit se faire sous ce lock.
        """
        return self._tokens_lock


# =============================================================================
# Singleton
# =============================================================================

_lock_manager: LockManager | None = None


def get_lock_manager() -> LockManager:
    """Retourne le singleton LockManager."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager
