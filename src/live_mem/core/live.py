# -*- coding: utf-8 -*-
"""
Service Live — Gestion des notes en temps réel.

Ce service encapsule les opérations sur les notes live :
    - write_note  : écrire une note (append-only, zéro conflit)
    - read_notes  : lire les notes avec filtres
    - search_notes : rechercher du texte dans les notes

Les notes live sont le cœur de la collaboration multi-agents.
Chaque note = 1 fichier S3 unique → aucun conflit possible entre agents.

Architecture :
    tools/live.py → LiveService (ce fichier) → StorageService (S3)

Voir S3_DATA_MODEL.md pour le format des notes (front-matter YAML + contenu).
Voir MCP_TOOLS_SPEC.md pour les catégories et le format de retour.
"""

import re
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from .storage import get_storage


# ─────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────

# VULN-07 fix : limites de taille pour les contenus
MAX_NOTE_CONTENT_SIZE = 100_000  # 100K caractères max par note
MAX_LIVE_READ_LIMIT = 500  # VULN-10 fix : limite max pour live_read

# Catégories de notes autorisées (cf. MCP_TOOLS_SPEC.md)
VALID_CATEGORIES = [
    "observation",  # Constat factuel ("Le build passe")
    "decision",  # Choix technique ("On part sur S3")
    "todo",  # Tâche à faire ("Implémenter le backup")
    "insight",  # Pattern découvert ("Le pattern X marche")
    "question",  # Question ouverte ("Supporter le CSV ?")
    "progress",  # Avancement ("Module auth : 80%")
    "issue",  # Problème, bug ("Timeout LLM > 60s")
]


class LiveService:
    """
    Service de gestion des notes live.

    Toutes les méthodes sont async et retournent un dict
    avec un champ "status" conforme à la convention MCP.
    """

    async def write_note(
        self,
        space_id: str,
        category: str,
        content: str,
        tags: str = "",
    ) -> dict:
        """
        Écrit une note live (append-only, aucun conflit possible).

        Crée un fichier Markdown avec front-matter YAML + contenu.
        Le nom de fichier est unique : {timestamp}_{agent}_{category}_{uuid8}.md

        L'identité de l'agent est TOUJOURS le client_name du token
        d'authentification (v0.8.1 — Token = Agent). Pas de paramètre
        agent pour garantir la cohérence avec le consolidateur.

        Args:
            space_id: Espace cible
            category: Type de note (observation, decision, todo, etc.)
            content: Corps de la note (texte libre)
            tags: Tags séparés par des virgules (optionnel)

        Returns:
            {"status": "created", "filename": "...", ...}
        """
        # VULN-07 fix : valider la taille du contenu
        if len(content) > MAX_NOTE_CONTENT_SIZE:
            return {
                "status": "error",
                "message": (
                    f"Contenu trop long ({len(content)} chars, "
                    f"max {MAX_NOTE_CONTENT_SIZE})"
                ),
            }

        # Valider la catégorie
        if category not in VALID_CATEGORIES:
            return {
                "status": "error",
                "message": (
                    f"Catégorie invalide : '{category}'. "
                    f"Valides : {', '.join(VALID_CATEGORIES)}"
                ),
            }

        storage = get_storage()

        # Vérifier que l'espace existe
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Agent = client_name du token (toujours, jamais de paramètre libre)
        from ..auth.context import get_current_agent_name

        agent = get_current_agent_name()

        # Construire le nom de fichier unique
        # Format : {YYYYMMDD}T{HHMMSS}_{agent}_{category}_{uuid8}.md
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%dT%H%M%S")
        uuid8 = uuid.uuid4().hex[:8]
        # Nettoyer le nom d'agent (garder uniquement alphanum + tirets)
        safe_agent = re.sub(r"[^a-zA-Z0-9_-]", "", agent) or "agent"
        filename = f"{timestamp_str}_{safe_agent}_{category}_{uuid8}.md"

        # Parser les tags depuis la chaîne CSV
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        # Construire le front-matter YAML + contenu Markdown
        front_matter = (
            f"---\n"
            f'timestamp: "{now.isoformat()}"\n'
            f'agent: "{agent}"\n'
            f'category: "{category}"\n'
            f"tags: {json.dumps(tag_list)}\n"
            f'space_id: "{space_id}"\n'
            f"---\n\n"
        )
        full_content = front_matter + content

        # Écrire sur S3 — 1 seul PUT, aucun lock nécessaire
        key = f"{space_id}/live/{filename}"
        await storage.put(key, full_content)

        return {
            "status": "created",
            "space_id": space_id,
            "filename": filename,
            "category": category,
            "agent": agent,
            "size": len(full_content.encode("utf-8")),
            "timestamp": now.isoformat(),
        }

    async def read_notes(
        self,
        space_id: str,
        limit: int = 50,
        category: str = "",
        agent: str = "",
        since: str = "",
    ) -> dict:
        """
        Lit les notes live récentes avec filtres optionnels.

        Les notes sont retournées du plus récent au plus ancien.

        Args:
            space_id: Espace cible
            limit: Nombre max de notes (défaut 50)
            category: Filtrer par catégorie (optionnel)
            agent: Filtrer par agent (optionnel)
            since: ISO datetime — notes après cette date (optionnel)

        Returns:
            {"status": "ok", "notes": [...], "total": N,
             "matched_total": M, "has_more": bool}
        """
        # VULN-10 fix : borner le limit
        limit = min(limit, MAX_LIVE_READ_LIMIT)

        storage = get_storage()
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Lire toutes les notes live depuis S3
        all_notes = await storage.list_and_get(f"{space_id}/live/")

        # Parser et filtrer les notes
        parsed = []
        for item in all_notes:
            note = _parse_note(item["key"], item["content"])
            if note is None:
                continue  # Note mal formée → skip silencieux

            # Appliquer les filtres
            if category and note["category"] != category:
                continue
            if agent and note["agent"] != agent:
                continue
            if since and note["timestamp"] < since:
                continue

            parsed.append(note)

        # Trier par timestamp décroissant (plus récent d'abord)
        parsed.sort(key=lambda n: n["timestamp"], reverse=True)

        # Appliquer la limite
        total = len(parsed)
        notes = parsed[:limit]

        return {
            "status": "ok",
            "space_id": space_id,
            "notes": notes,
            "total": len(notes),
            "matched_total": total,
            "has_more": total > limit,
        }

    async def search_notes(
        self,
        space_id: str,
        query: str,
        limit: int = 20,
    ) -> dict:
        """
        Recherche texte (case-insensitive) dans les notes live.

        Args:
            space_id: Espace cible
            query: Texte à chercher
            limit: Nombre max de résultats (défaut 20)

        Returns:
            {"status": "ok", "notes": [...], "total": N, "has_more": bool}
        """
        storage = get_storage()
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        all_notes = await storage.list_and_get(f"{space_id}/live/")
        query_lower = query.lower()

        matched = []
        for item in all_notes:
            note = _parse_note(item["key"], item["content"])
            if note is None:
                continue

            # Recherche case-insensitive dans le contenu
            if query_lower in note["content"].lower():
                matched.append(note)

        # Trier par pertinence (plus récent d'abord)
        matched.sort(key=lambda n: n["timestamp"], reverse=True)

        total = len(matched)
        notes = matched[:limit]

        return {
            "status": "ok",
            "space_id": space_id,
            "query": query,
            "notes": notes,
            "total": len(notes),
            "has_more": total > limit,
        }


# ─────────────────────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────────────────────


def _parse_note(key: str, raw_content: str) -> Optional[dict]:
    """
    Parse une note live depuis son contenu brut (front-matter YAML + body).

    Le front-matter est parsé sans librairie YAML externe (format simple).

    Args:
        key: Clé S3 complète (ex: "my-space/live/20260220T180000_cline_obs_a1b2.md")
        raw_content: Contenu brut du fichier (front-matter + body)

    Returns:
        Dict {filename, timestamp, agent, category, tags, content}
        ou None si le format est invalide
    """
    filename = key.split("/")[-1]

    # Séparer front-matter YAML et corps Markdown
    if raw_content.startswith("---"):
        parts = raw_content.split("---", 2)
        if len(parts) >= 3:
            front_matter_str = parts[1].strip()
            body = parts[2].strip()
        else:
            return None  # Front-matter mal formé
    else:
        # Pas de front-matter → corps brut
        body = raw_content.strip()
        front_matter_str = ""

    # Parser le front-matter (YAML simple, ligne par ligne)
    fm = {}
    for line in front_matter_str.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            fm[k.strip()] = v

    # Parser les tags (format JSON dans le YAML : tags: ["tag1", "tag2"])
    tags = []
    tags_raw = fm.get("tags", "")
    if tags_raw.startswith("["):
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []

    return {
        "filename": filename,
        "timestamp": fm.get("timestamp", ""),
        "agent": fm.get("agent", ""),
        "category": fm.get("category", ""),
        "tags": tags,
        "content": body,
    }


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_live_service: LiveService | None = None


def get_live_service() -> LiveService:
    """Retourne le singleton LiveService."""
    global _live_service
    if _live_service is None:
        _live_service = LiveService()
    return _live_service
