# =============================================================================
# Dockerfile — Live Memory MCP Server (multi-stage, rootless)
# =============================================================================
# Two-stage build:
#   1. Builder — installs dependencies into a virtual environment
#   2. Runtime — copies only the venv + source code (no pip, no build tools)
#
# Result: smaller image, no build tools in prod, reduced attack surface.
#
# Usage :
#   docker compose build
#   docker compose up -d
# =============================================================================

ARG PYTHON_VER=3.11

# ─────────────────────────────────────────────────────────────
# Stage 1: Builder — install dependencies
# ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VER}-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

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

# Use the venv Python and add src/ to module path
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Basculer sur l'utilisateur non-root (rootless)
USER mcp

EXPOSE 8002

# Healthcheck : vérifier que le serveur répond sur /health
# (pas de curl dans slim → utiliser python)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health', timeout=2)" || exit 1

# Point d'entrée : le serveur MCP
CMD ["python", "-m", "live_mem"]
