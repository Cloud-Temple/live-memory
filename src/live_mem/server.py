# -*- coding: utf-8 -*-
"""
Serveur MCP Live Memory — Point d'entrée principal.

Ce fichier :
1. Crée l'instance FastMCP
2. Enregistre les outils MCP via tools/ (modulaire, par catégorie)
3. Assemble la chaîne de middlewares ASGI
4. Démarre le serveur Uvicorn

Architecture des outils (30 outils, 7 catégories) :
    tools/system.py → system_health, system_about (2)
    tools/space.py  → space_create, space_list, space_info, ... (7)
    tools/live.py   → live_note, live_read, live_search (3)
    tools/bank.py   → bank_read, bank_consolidate, ... (4)
    tools/graph.py  → graph_connect, graph_push, ... (4)
    tools/backup.py → backup_create, backup_restore, ... (5)
    tools/admin.py  → admin_create_token, admin_gc_notes, ... (5)

Usage :
    python -m live_mem.server
"""

import sys
import time
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import get_settings

# ─────────────────────────────────────────────────────────────
# Configuration du logging (stderr uniquement, JSON structuré)
# ─────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        import json as _json
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return _json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(_JsonFormatter())
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)

# Réduire le bruit des librairies tierces
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

logger = logging.getLogger("live_mem")

# =============================================================================
# Instance FastMCP
# =============================================================================

settings = get_settings()

mcp = FastMCP(
    name=settings.mcp_server_name,
    host=settings.mcp_server_host,
    port=settings.mcp_server_port,
)

# =============================================================================
# Enregistrement des outils — délégué aux modules tools/
# =============================================================================
# Chaque module tools/xxx.py expose une fonction register(mcp) -> int
# qui déclare ses outils via @mcp.tool() et retourne le nombre d'outils.

from .tools import register_all_tools

tools_count = register_all_tools(mcp)


# =============================================================================
# Assemblage ASGI — Chaîne de middlewares
# =============================================================================

def create_app():
    """
    Crée l'application ASGI complète avec les middlewares.

    Pile d'exécution (premier exécuté → dernier) :
        RequestId → Metrics → Auth → Audit → Logging
        → ResponseLimit → StaticFiles → MCP Streamable HTTP

    Le RequestIdMiddleware génère un ID unique par requête (contextvars).
    Le MetricsMiddleware expose /metrics et collecte les compteurs.
    L'AuthMiddleware extrait le Bearer token et l'injecte dans les contextvars.
    L'AuditMiddleware émet des entrées d'audit JSON structurées.
    Le LoggingMiddleware trace les requêtes HTTP en JSON sur stderr.
    Le ResponseLimitMiddleware tronque les réponses > 512 KB.
    Le StaticFilesMiddleware sert /live, /static/*, /api/* (interface web).
    """
    from .auth.middleware import (
        AuthMiddleware,
        LoggingMiddleware,
        StaticFilesMiddleware,
    )
    from .middleware import (
        RequestIdMiddleware,
        MetricsMiddleware,
        ResponseLimitMiddleware,
        AuditMiddleware,
    )

    # L'app de base est le Streamable HTTP handler du SDK MCP
    # Endpoint unique : POST/GET /mcp (remplace /sse + /messages)
    app = mcp.streamable_http_app()

    # Empiler les middlewares (dernier ajouté = premier exécuté)
    app = StaticFilesMiddleware(app)
    app = ResponseLimitMiddleware(app, max_bytes=settings.response_max_bytes)
    app = LoggingMiddleware(app)
    app = AuditMiddleware(app)
    app = AuthMiddleware(app)
    app = MetricsMiddleware(app)
    app = RequestIdMiddleware(app)

    return app


# =============================================================================
# Helpers internes
# =============================================================================

def _read_version() -> str:
    """Lit la version depuis le fichier VERSION à la racine du projet."""
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "dev"


# =============================================================================
# Point d'entrée
# =============================================================================

def main():
    """Démarre le serveur MCP Live Memory."""
    import uvicorn

    version = _read_version()

    # VULN-25 fix : refuser de démarrer avec le bootstrap key par défaut
    _weak_keys = {"change_me_in_production", "changeme", "admin", "password", ""}
    if settings.admin_bootstrap_key in _weak_keys:
        logger.critical(
            "⛔ ADMIN_BOOTSTRAP_KEY non configurée ou trop faible ('%s') ! "
            "Définissez une clé de ≥32 caractères aléatoires dans .env.",
            settings.admin_bootstrap_key[:10] + "..." if len(settings.admin_bootstrap_key) > 10 else settings.admin_bootstrap_key,
        )
        sys.exit(1)
    if len(settings.admin_bootstrap_key) < 32:
        logger.warning(
            "⚠️ ADMIN_BOOTSTRAP_KEY trop courte (%d chars). Minimum recommandé : 32 caractères.",
            len(settings.admin_bootstrap_key),
        )

    # Lister les outils disponibles et les grouper par catégorie
    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]

    categories = {
        "System": [n for n in tool_names if n.startswith("system_")],
        "Space":  [n for n in tool_names if n.startswith("space_")],
        "Live":   [n for n in tool_names if n.startswith("live_")],
        "Bank":   [n for n in tool_names if n.startswith("bank_")],
        "Graph":  [n for n in tool_names if n.startswith("graph_")],
        "Backup": [n for n in tool_names if n.startswith("backup_")],
        "Admin":  [n for n in tool_names if n.startswith("admin_")],
    }

    # Construire les lignes de contenu de la bannière
    content_lines = []
    content_lines.append(f"  Live Memory MCP Server v{version}")
    content_lines.append("")
    content_lines.append(f"  🔧 {len(tool_names)} outils MCP :")
    for cat, names in categories.items():
        if names:
            content_lines.append(f"     {cat:7s}: {', '.join(names)}")
    content_lines.append("")
    host = settings.mcp_server_host
    port = settings.mcp_server_port
    content_lines.append(f"  🌐 http://{host}:{port}")
    content_lines.append(f"  📡 http://{host}:{port}/mcp")
    content_lines.append(f"  🖥️  http://{host}:{port}/live")

    # Calculer la largeur du cadre (largeur max + marges)
    # Note : les emoji comptent pour 2 colonnes en affichage terminal
    def _display_len(s: str) -> int:
        """Longueur d'affichage (emoji/wide chars = 2 colonnes)."""
        import unicodedata
        length = 0
        for ch in s:
            eaw = unicodedata.east_asian_width(ch)
            if eaw in ("W", "F"):
                length += 2
            elif unicodedata.category(ch).startswith("So"):
                # Symboles (emoji non-CJK comme 🔧🌐📡)
                length += 2
            else:
                length += 1
        return length

    inner_width = max(_display_len(line) for line in content_lines) + 2
    inner_width = max(inner_width, 50)  # Minimum 50 colonnes

    # Construire la bannière avec cadre
    sep = "═" * inner_width
    banner = f"\n╔{sep}╗\n"
    for i, line in enumerate(content_lines):
        pad = inner_width - _display_len(line)
        banner += f"║{line}{' ' * pad}║\n"
        # Séparateur après le titre
        if i == 0:
            banner += f"╠{sep}╣\n"
    banner += f"╚{sep}╝\n"

    print(banner, file=sys.stderr)

    # Créer l'app ASGI avec middlewares et démarrer Uvicorn
    app = create_app()

    uvicorn.run(
        app,
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
        log_level="warning",  # Uvicorn en mode silencieux (on log via middleware)
    )


if __name__ == "__main__":
    main()
