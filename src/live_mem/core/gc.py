# -*- coding: utf-8 -*-
"""
Service Garbage Collector — Nettoyage des notes orphelines.

Les notes live sont normalement consolidées puis supprimées par l'agent.
Si un agent disparaît sans consolider, ses notes restent indéfiniment.

Le GC :
1. Identifie les notes plus vieilles qu'un seuil (défaut 7 jours)
2. Par défaut : CONSOLIDE les vieilles notes dans la bank (via LLM)
   → ajoute une note "GC notice" pour tracer la consolidation forcée
3. Optionnel : supprime les notes sans consolider (delete_only=True)

Architecture :
    tools/admin.py → GCService (ce fichier) → ConsolidatorService + StorageService
"""

import re
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta

from .storage import get_storage

logger = logging.getLogger("live_mem.gc")


# LM2-10 fix : helper interne pour écrire une note "GC notice" en imitant
# l'identité de l'agent orphelin. live.write_note() auto-détecte le caller
# depuis le token courant (v0.8.1 : Token = Agent) et ne permet plus de
# choisir un agent libre — c'est volontaire pour la sécurité, mais cela
# casse le pattern du GC qui doit attacher la notice à l'agent disparu
# (sinon la consolidation forcée par agent ne les inclura pas).
#
# Solution : écrire le fichier directement sur S3 avec le format standard
# d'une note live (front-matter YAML + corps Markdown), en utilisant le
# nom d'agent passé. Cet appel est protégé par le pipeline (GC = admin only).
async def _write_gc_notice(
    space_id: str,
    agent_name: str,
    content: str,
) -> str:
    """
    Écrit directement une note ``observation`` au nom d'un agent donné.

    Bypass volontaire de ``live.write_note()`` pour conserver l'identité
    de l'agent orphelin (cf. v0.8.1 — Token = Agent).

    Returns:
        Le nom de fichier S3 créé.
    """
    storage = get_storage()
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%dT%H%M%S")
    uuid8 = uuid.uuid4().hex[:8]
    safe_agent = re.sub(r"[^a-zA-Z0-9_-]", "", agent_name) or "agent"
    filename = f"{timestamp_str}_{safe_agent}_observation_{uuid8}.md"

    front_matter = (
        "---\n"
        f'timestamp: "{now.isoformat()}"\n'
        f'agent: "{agent_name}"\n'
        'category: "observation"\n'
        f"tags: {json.dumps(['gc', 'forced-consolidation'])}\n"
        f'space_id: "{space_id}"\n'
        "---\n\n"
    )
    await storage.put(f"{space_id}/live/{filename}", front_matter + content)
    return filename


class GCService:
    """
    Service de Garbage Collection des notes live.

    Identifie les notes orphelines et les consolide (ou supprime).
    """

    async def scan_old_notes(
        self,
        space_id: str = "",
        max_age_days: int = 7,
    ) -> dict:
        """
        Scanne les notes orphelines dans un ou tous les espaces.

        Args:
            space_id: Espace cible (vide = tous les espaces)
            max_age_days: Seuil en jours (défaut 7)

        Returns:
            Rapport avec nombre de notes par espace et par agent
        """
        storage = get_storage()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_str = cutoff.strftime("%Y%m%dT%H%M%S")

        # Déterminer les espaces à scanner
        if space_id:
            space_ids = [space_id]
        else:
            prefixes = await storage.list_prefixes("")
            space_ids = [p.rstrip("/") for p in prefixes if not p.startswith("_")]

        result = {
            "status": "ok",
            "max_age_days": max_age_days,
            "cutoff_date": cutoff.isoformat(),
            "spaces": {},
            "total_old_notes": 0,
            "total_old_size": 0,
        }

        for sid in space_ids:
            if not await storage.exists(f"{sid}/_meta.json"):
                continue

            objects = await storage.list_objects(f"{sid}/live/")
            notes = [
                o
                for o in objects
                if o["Key"].endswith(".md") and not o["Key"].endswith(".keep")
            ]

            old_notes = []
            by_agent = {}
            oldest = None

            for note_obj in notes:
                key = note_obj["Key"]
                filename = key.split("/")[-1]
                ts = _extract_timestamp(filename)
                if ts is None:
                    continue

                if ts < cutoff_str:
                    old_notes.append(
                        {
                            "key": key,
                            "size": note_obj.get("Size", 0),
                            "timestamp": ts,
                        }
                    )
                    agent = _extract_agent(filename)
                    by_agent[agent] = by_agent.get(agent, 0) + 1
                    if oldest is None or ts < oldest:
                        oldest = ts

            if old_notes:
                total_size = sum(n["size"] for n in old_notes)
                result["spaces"][sid] = {
                    "total_notes": len(notes),
                    "old_notes": len(old_notes),
                    "old_notes_size": total_size,
                    "by_agent": by_agent,
                    "oldest": oldest,
                    "keys": [n["key"] for n in old_notes],
                }
                result["total_old_notes"] += len(old_notes)
                result["total_old_size"] += total_size

        return result

    async def consolidate_old_notes(
        self,
        space_id: str = "",
        max_age_days: int = 7,
    ) -> dict:
        """
        Consolide les notes orphelines dans la Memory Bank via LLM.

        Pour chaque agent ayant des notes orphelines :
        1. Écrit une note "GC notice" avec le nom de l'agent
           (pour que le LLM sache que c'est une consolidation forcée)
        2. Appelle le consolidateur pour cet agent
        3. Les notes sont intégrées dans la bank et supprimées

        Args:
            space_id: Espace cible (vide = tous les espaces)
            max_age_days: Seuil en jours (défaut 7)

        Returns:
            Rapport de consolidation par espace et par agent
        """
        from .consolidator import get_consolidator
        from .locks import get_lock_manager

        # Scanner d'abord
        scan = await self.scan_old_notes(space_id, max_age_days)

        if scan["total_old_notes"] == 0:
            scan["action"] = "consolidate"
            scan["consolidated"] = 0
            scan["message"] = "Aucune note orpheline à consolider"
            return scan

        consolidator = get_consolidator()
        total_consolidated = 0
        consolidation_results = {}

        for sid, space_data in scan["spaces"].items():
            consolidation_results[sid] = {}

            for agent_name, note_count in space_data["by_agent"].items():
                # 1. Écrire une note GC notice avec le nom de l'agent
                #    pour que le LLM voie la trace dans la bank
                gc_notice = (
                    f"⚠️ GARBAGE COLLECTOR — Consolidation forcée\n\n"
                    f"Le Garbage Collector a détecté {note_count} notes "
                    f"orphelines de l'agent '{agent_name}' (> {max_age_days} jours).\n"
                    f"Ces notes n'ont jamais été consolidées par l'agent.\n"
                    f"Le GC force leur intégration dans la Memory Bank.\n\n"
                    f"**Attention** : cette consolidation est automatique. "
                    f"Les notes intégrées peuvent manquer de contexte "
                    f"car l'agent n'est plus actif."
                )

                # LM2-10 fix : live.write_note() ne prend plus de paramètre
                # `agent` depuis v0.8.1 (Token = Agent). On écrit donc
                # directement sur S3 via _write_gc_notice() pour conserver
                # l'identité de l'agent orphelin (sinon la consolidation
                # par agent ne l'inclut pas dans son filtre).
                try:
                    await _write_gc_notice(
                        space_id=sid,
                        agent_name=agent_name,
                        content=gc_notice,
                    )
                except Exception as e:
                    # Best-effort : la notice est informative, son échec
                    # ne doit pas empêcher la consolidation des notes
                    # orphelines elles-mêmes.
                    logger.warning(
                        "GC: échec écriture notice pour '%s' dans '%s': %s",
                        agent_name,
                        sid,
                        e,
                    )

                # 2. Consolider les notes de cet agent
                lock = get_lock_manager().consolidation(sid)
                if lock.locked():
                    consolidation_results[sid][agent_name] = {
                        "status": "skipped",
                        "reason": "consolidation already in progress",
                    }
                    continue

                try:
                    async with lock:
                        r = await consolidator.consolidate(sid, agent=agent_name)

                    consolidation_results[sid][agent_name] = {
                        "status": r.get("status", "error"),
                        "notes_processed": r.get("notes_processed", 0),
                        "bank_files_created": r.get("bank_files_created", 0),
                        "bank_files_updated": r.get("bank_files_updated", 0),
                    }
                    total_consolidated += r.get("notes_processed", 0)

                    logger.info(
                        "GC: consolidated %d notes from '%s' in '%s'",
                        r.get("notes_processed", 0),
                        agent_name,
                        sid,
                    )

                except Exception as e:
                    consolidation_results[sid][agent_name] = {
                        "status": "error",
                        "message": str(e),
                    }

        # Nettoyer les clés du résultat
        for sid in scan.get("spaces", {}):
            if "keys" in scan["spaces"][sid]:
                del scan["spaces"][sid]["keys"]

        scan["action"] = "consolidate"
        scan["consolidated"] = total_consolidated
        scan["consolidation_details"] = consolidation_results
        scan["status"] = "ok"
        scan["message"] = (
            f"GC : {total_consolidated} notes orphelines consolidées "
            f"dans {len(scan['spaces'])} espace(s)"
        )
        return scan

    async def delete_old_notes(
        self,
        space_id: str = "",
        max_age_days: int = 7,
    ) -> dict:
        """
        Supprime les notes orphelines SANS consolider (perte de données).

        ⚠️ Utiliser consolidate_old_notes() de préférence.

        Args:
            space_id: Espace cible (vide = tous les espaces)
            max_age_days: Seuil en jours (défaut 7)

        Returns:
            Nombre de notes supprimées
        """
        scan = await self.scan_old_notes(space_id, max_age_days)

        if scan["total_old_notes"] == 0:
            scan["action"] = "delete"
            scan["deleted"] = 0
            scan["message"] = "Aucune note orpheline à supprimer"
            return scan

        storage = get_storage()
        all_keys = []
        for sid, space_data in scan["spaces"].items():
            all_keys.extend(space_data["keys"])

        await storage.delete_many(all_keys)

        for sid in scan["spaces"]:
            del scan["spaces"][sid]["keys"]

        scan["action"] = "delete"
        scan["deleted"] = len(all_keys)
        scan["status"] = "deleted"
        scan["message"] = (
            f"⚠️ {len(all_keys)} notes supprimées SANS consolidation "
            f"dans {len(scan['spaces'])} espace(s)"
        )
        return scan


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _extract_timestamp(filename: str) -> str | None:
    """Extrait le timestamp du nom de fichier. Format : YYYYMMDDTHHMMSS_..."""
    match = re.match(r"^(\d{8}T\d{6})_", filename)
    return match.group(1) if match else None


def _extract_agent(filename: str) -> str:
    """Extrait le nom de l'agent du nom de fichier."""
    parts = filename.split("_")
    return parts[1] if len(parts) >= 3 else "unknown"


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_gc_service: GCService | None = None


def get_gc_service() -> GCService:
    """Retourne le singleton GCService."""
    global _gc_service
    if _gc_service is None:
        _gc_service = GCService()
    return _gc_service
