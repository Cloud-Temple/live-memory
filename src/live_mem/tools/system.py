# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie System (3 outils).

Outils publics (pas d'authentification) :
    - system_health : vérifie S3, LLMaaS, compte les espaces
    - system_about  : version, outils disponibles, infos système

Outils authentifiés :
    - system_whoami : identité du token courant (nom, permissions, espaces)
"""

import time
import platform
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ToolAnnotations


def register(mcp: FastMCP) -> int:
    """
    Enregistre les outils system sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (3)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def system_health() -> dict:
        """
        Vérifie l'état de santé du service Live Memory.

        Teste la connectivité S3 et LLMaaS, retourne le statut de chaque service.
        Cet outil ne nécessite aucune authentification.

        Returns:
            État global du système et détails par service
        """
        from ..config import get_settings
        settings = get_settings()
        results = {}

        # ── Test S3 ──────────────────────────────────────────
        try:
            from ..core.storage import get_storage
            storage = get_storage()
            results["s3"] = await storage.test_connection()
        except Exception as e:
            results["s3"] = {"status": "error", "message": str(e)}

        # ── Test LLMaaS ─────────────────────────────────────
        try:
            if settings.llmaas_api_url and settings.llmaas_api_key:
                from openai import AsyncOpenAI
                t0 = time.monotonic()
                client = AsyncOpenAI(
                    base_url=settings.llmaas_api_url,
                    api_key=settings.llmaas_api_key,
                    timeout=30,
                )
                await client.chat.completions.create(
                    model=settings.llmaas_model,
                    messages=[{"role": "user", "content": "Réponds OK"}],
                    max_tokens=5,
                )
                latency = round((time.monotonic() - t0) * 1000, 1)
                results["llmaas"] = {
                    "status": "ok",
                    "model": settings.llmaas_model,
                    "latency_ms": latency,
                }
            else:
                results["llmaas"] = {
                    "status": "warning",
                    "message": "LLMaaS non configuré",
                }
        except Exception as e:
            results["llmaas"] = {"status": "error", "message": str(e)}

        # ── Compteur d'espaces ───────────────────────────────
        spaces_count = -1
        try:
            from ..core.storage import get_storage
            storage = get_storage()
            prefixes = await storage.list_prefixes("")
            # Exclure les préfixes système (_system/, _backups/)
            spaces_count = len([p for p in prefixes if not p.startswith('_')])
        except Exception:
            pass

        # ── Statut global ────────────────────────────────────
        service_statuses = [
            r.get("status", "error")
            for r in results.values()
            if isinstance(r, dict)
        ]
        all_ok = all(s == "ok" for s in service_statuses)

        return {
            "status": "healthy" if all_ok else "degraded",
            "service_name": settings.mcp_server_name,
            "version": _read_version(),
            "uptime_seconds": round(time.monotonic() - _start_time, 1),
            "services": results,
            "spaces_count": spaces_count,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def system_about() -> dict:
        """
        Informations sur le service Live Memory MCP.

        Retourne la version, les outils disponibles, et les infos système.
        Cet outil ne nécessite aucune authentification.

        Returns:
            Métadonnées du service
        """
        from ..config import get_settings
        settings = get_settings()

        # Lister les outils MCP disponibles
        tools = []
        for tool in mcp._tool_manager.list_tools():
            tools.append({
                "name": tool.name,
                "description": (tool.description or "")[:100],
            })

        return {
            "status": "ok",
            "name": settings.mcp_server_name,
            "version": _read_version(),
            "description": "Mémoire de travail partagée pour agents IA collaboratifs",
            "author": "Cloud Temple",
            "documentation": "https://github.com/Cloud-Temple/live-memory",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "tools_count": len(tools),
            "tools": tools,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def system_whoami() -> dict:
        """
        Identité du token courant utilisé pour contacter le serveur.

        Retourne le nom de l'agent, le type d'authentification (bootstrap
        ou token S3), les permissions, les espaces autorisés, et les
        métadonnées du token (email, dates de création/expiration).

        Nécessite une authentification valide (read minimum).

        Returns:
            Identité complète du token courant
        """
        from ..auth.context import current_token_info

        token_info = current_token_info.get()
        if token_info is None:
            return {"status": "error", "message": "Authentification requise"}

        result = {
            "status": "ok",
            "client_name": token_info.get("client_name", "anonymous"),
            "auth_type": token_info.get("type", "unknown"),
            "permissions": token_info.get("permissions", []),
            "allowed_spaces": token_info.get("allowed_resources", []),
        }

        # Pour les tokens S3, enrichir avec les métadonnées du store
        token_hash = token_info.get("token_hash")
        if token_hash and token_info.get("type") == "token":
            try:
                from ..core.tokens import get_token_service
                store_data = await get_token_service().list_tokens()
                for t in store_data.get("tokens", []):
                    if t.get("hash") == token_hash:
                        result["email"] = t.get("email", "")
                        result["token_hash"] = token_hash
                        result["created_at"] = t.get("created_at", "")
                        result["expires_at"] = t.get("expires_at")
                        result["last_used_at"] = t.get("last_used_at", "")
                        result["space_ids"] = t.get("space_ids", [])
                        break
            except Exception:
                pass  # Enrichissement best-effort

        # Pour le bootstrap key, indiquer clairement
        if token_info.get("type") == "bootstrap":
            result["note"] = "Bootstrap key — accès admin total, pas de token S3"

        return result

    return 3  # Nombre d'outils enregistrés


# ─────────────────────────────────────────────────────────────
# Helpers internes au module
# ─────────────────────────────────────────────────────────────

# Temps de démarrage pour le calcul d'uptime
_start_time = time.monotonic()


def _read_version() -> str:
    """Lit la version depuis le fichier VERSION à la racine du projet."""
    version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "dev"
