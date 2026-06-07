# Production Deployment Guide — Live Memory

> **Version**: 2.4.0 | **Date**: 2026-05-22 | **Author**: Cloud Temple

---

## 1. Overview

Live Memory is deployed via Docker Compose with 2 services:

| Service         | Role                                     | Image          | Internal Port |
| --------------- | ---------------------------------------- | -------------- | ------------- |
| **WAF**         | Secure reverse proxy (Caddy + Coraza)    | Custom (build) | 8080          |
| **MCP Service** | Python MCP server (43 tools)             | Custom (build) | 8002          |

**Difference with graph-memory**: No Neo4j or Qdrant → much lighter deployment.

**Exposed features**:
- 43 MCP tools via Streamable HTTP (`/mcp`)
- Web visualization interface (`/live`)
- 5 REST API endpoints (`/api/*`)

---

## 2. Prerequisites

| Resource | Minimum   | Recommended |
| -------- | --------- | ----------- |
| CPU      | 1 vCPU    | 2 vCPU      |
| RAM      | 1 GB      | 2 GB        |
| Disk     | 10 GB SSD | 20 GB SSD   |

```bash
docker --version        # >= 24.0
docker compose version  # v2
```

---

## 3. Deployment

### 3.1 Development Mode (HTTP, port 8080)

```bash
git clone https://github.com/Cloud-Temple/live-memory.git
cd live-memory
cp .env.example .env
nano .env   # Fill in S3, LLMaaS, ADMIN_BOOTSTRAP_KEY

docker compose build
docker compose up -d
docker compose logs -f live-mem-service
```

### 3.2 Production Mode (HTTPS, Let's Encrypt)

```bash
# 1. DNS: live-mem.your-domain.com → server IP
# 2. .env: SITE_ADDRESS=live-mem.your-domain.com
# 3. docker-compose.yml: uncomment ports 80/443, comment out 8080
docker compose build && docker compose up -d
```

### 3.3 Post-deployment Verification

```bash
# Health check
curl -s http://localhost:8080/health

# Web interface
open http://localhost:8080/live

# WAF blocks SQL injection
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/api?id=1%20OR%201=1"
# Expected: 403

# Create the first admin token
export MCP_URL=http://localhost:8080
export MCP_TOKEN=<your_ADMIN_BOOTSTRAP_KEY>
python3 scripts/mcp_cli.py token create admin-ops admin
```

---

## 4. Docker Compose

```yaml
services:
  waf:
    build: ./waf
    ports:
      - "${WAF_PORT:-8080}:8080"
      # Production: uncomment these lines, comment out the one above
      # - "80:80"
      # - "443:443"
    environment:
      - SITE_ADDRESS=${SITE_ADDRESS:-:8080}
      - MCP_BACKEND=live-mem-service:8002
    depends_on:
      live-mem-service:
        condition: service_started
    restart: unless-stopped
    networks:
      - live-mem-network

  live-mem-service:
    build: .
    env_file: .env
    expose:
      - "8002"   # Internal only, not publicly exposed
    restart: unless-stopped
    networks:
      - live-mem-network

networks:
  live-mem-network:
    driver: bridge
```

**Key principle**: Only the WAF is exposed. The MCP service is isolated within the Docker network.

**Non-root container**: The Dockerfile uses a `mcp` user (UID 10001) — no root operations after `USER mcp`.

---

## 5. WAF Routes

| Route | WAF Coraza | Timeout | Usage |
|---|---|---|---|
| `/mcp*` | ❌ (bypass) | Unlimited | Single MCP Streamable HTTP endpoint (POST/GET/DELETE) |
| `/api/tool` | ⚠️ (headers/URI only, body not inspected) | 5min | Admin console tool proxy |
| `/api/*` (other) | ✅ | 5min | REST API (web interface) |
| `/live`, `/static/*` | ✅ | Standard | Web interface |
| Everything else | ✅ | Standard | Health (`/health`), etc. |

> **Note v0.5.0**: The former `/sse*` and `/messages/*` routes (SSE transport) have been removed and unified into `/mcp*` (Streamable HTTP).

> **Note v2.5.2 — `/api/tool` request body excluded from CRS inspection.**
> The admin console proxies tool calls through `POST /api/tool`, whose body
> carries free-form Markdown (e.g. Memory Bank rules: `<` comparisons,
> the word `delete`, `**`, backticks). The OWASP CRS flagged these as
> XSS/SQLi, pushed the anomaly score past the threshold, and Coraza
> returned an empty-body 403 — surfacing in the UI as `space_create`
> failing with *"Empty response"*. The endpoint is already gated by an
> HttpOnly cookie **and** the `write` permission, and only proxies
> structured `{tool, arguments}` calls, so its **request body** is
> excluded from CRS inspection (`ctl:requestBodyAccess=Off` scoped to
> `REQUEST_URI @beginsWith /api/tool`). Rate-limiting, body-size limits,
> and URI/header inspection (path traversal, scanners) stay active — same
> trust rationale already applied to `/mcp*`.

---

## 6. Backup & Restore

```bash
# Create a backup
python3 scripts/mcp_cli.py backup create project-alpha -d "Weekly backup"

# List backups
python3 scripts/mcp_cli.py backup list

# Restore (the space MUST NOT exist)
python3 scripts/mcp_cli.py space delete project-alpha --confirm
python3 scripts/mcp_cli.py backup restore "project-alpha/2026-02-20T18-00-00"
```

Backups are stored on S3: `_backups/{space_id}/{timestamp}/`

---

## 7. Monitoring

```bash
# MCP service logs
docker compose logs -f live-mem-service

# WAF logs (blocked requests)
docker compose logs -f waf

# Health check via CLI
python3 scripts/mcp_cli.py health

# Space stats
python3 scripts/mcp_cli.py space info project-alpha

# Web interface
open http://localhost:8080/live
```

---

## 8. Maintenance

### Orphaned Note GC

```bash
# Dry-run: scan notes older than 7 days
python3 scripts/mcp_cli.py admin gc-notes --max-age 7

# Consolidate orphaned notes via LLM
python3 scripts/mcp_cli.py admin gc-notes --max-age 7 --confirm

# Delete without consolidating
python3 scripts/mcp_cli.py admin gc-notes --max-age 7 --confirm --delete-only
```

### Update

```bash
git pull origin main
docker compose build
docker compose up -d
docker compose logs -f live-mem-service --tail=50
```

> **⚠️** Data is on S3, not in the containers. A `docker compose down` is safe.

---

## 9. Graph Bridge (optional)

To connect a space to Graph Memory (long-term memory):

```bash
# Connect
python3 scripts/mcp_cli.py graph connect project-alpha \
  https://graph-mem.mcp.cloud-temple.app \
  $GRAPH_TOKEN \
  project-alpha-mem \
  -o general

# Push the bank into the graph
python3 scripts/mcp_cli.py graph push project-alpha

# Check status
python3 scripts/mcp_cli.py graph status project-alpha
```

---

## 10. Remote CLI

```bash
# From any workstation
export MCP_URL=https://live-mem.your-domain.com
export MCP_TOKEN=your_admin_token
python3 scripts/mcp_cli.py health
python3 scripts/mcp_cli.py space list
```

---

## 11. Essential Commands

```bash
# Deployment
cp .env.example .env && nano .env
docker compose build && docker compose up -d

# First token
python3 scripts/mcp_cli.py token create admin-ops admin

# Create a space
python3 scripts/mcp_cli.py space create my-project --rules-file ./rules/standard.md

# Verify
python3 scripts/mcp_cli.py health
python3 scripts/mcp_cli.py space list

# Web interface
open http://localhost:8080/live
```

---

*Document updated April 25, 2026 — Live Memory v1.6.0*
