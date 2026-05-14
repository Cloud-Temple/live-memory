# =============================================================================
# Dockerfile — Live Memory MCP Server (multi-stage, rootless)
# =============================================================================
# Two-stage build:
#   1. Builder — installs dependencies via uv (frozen lockfile)
#   2. Runtime — copies only the venv + source code (no build tools)
#
# Usage :
#   docker compose build
#   docker compose up -d
# =============================================================================

ARG PYTHON_VER=3.11

# ─────────────────────────────────────────────────────────────
# Stage 1: Builder — install dependencies via uv
# ─────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.7-python${PYTHON_VER}-bookworm-slim AS builder

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/opt/venv"

# 1) Install deps only (cached layer — only invalidated when lockfile changes)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-install-workspace

# 2) Install the project itself
COPY VERSION .
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ─────────────────────────────────────────────────────────────
# Stage 2: Runtime — lean production image
# ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VER}-slim

WORKDIR /app

# Créer l'utilisateur non-root AVANT tout COPY
RUN useradd -r -u 10001 -s /bin/false mcp

# Copy virtual environment from builder (no pip/setuptools in runtime)
COPY --from=builder --chown=mcp:mcp /opt/venv /opt/venv

# Code source — copié directement avec les bons droits
COPY --chown=mcp:mcp src/ src/
COPY --chown=mcp:mcp scripts/ scripts/
COPY --chown=mcp:mcp RULES/ RULES/
COPY --chown=mcp:mcp VERSION .

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Basculer sur l'utilisateur non-root (rootless)
USER mcp

EXPOSE 8002

# Healthcheck : vérifier que le serveur répond sur /health
# MCP_SERVER_PORT est expansé par le shell (valeur par défaut: 8002)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${MCP_SERVER_PORT:-8002}/health', timeout=2)" || exit 1

# Point d'entrée : le serveur MCP
CMD ["python", "-m", "live_mem"]
