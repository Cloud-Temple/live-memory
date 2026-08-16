# -*- coding: utf-8 -*-
"""
Middlewares ASGI : authentification, logging, fichiers statiques.

Pile d'exécution (ordre) :
    AuthMiddleware → LoggingMiddleware → StaticFilesMiddleware → mcp.streamable_http_app()

L'AuthMiddleware :
    1. Extrait le Bearer token du header Authorization (ou query string)
    2. Vérifie d'abord le bootstrap key (accès admin direct)
    3. Sinon, valide le token via TokenService (lookup SHA-256 dans S3)
    4. Injecte les infos du token dans les contextvars
"""

import hmac
import json
import time
import logging
from typing import Optional
from .context import current_token_info, check_access, is_space_badge, update_fresh_token
from ..config import get_settings
from ..middleware import current_request_id

logger = logging.getLogger("live_mem.auth")
audit_logger = logging.getLogger("live_mem.audit")


# LM2-04 fix : nom du cookie d'authentification du front web.
# Émis par /api/login (HttpOnly, SameSite=Strict), supprimé par /api/logout.
# Les agents MCP continuent d'utiliser le header Authorization Bearer.
AUTH_COOKIE_NAME = "livemem_auth"


def _client_ip_from_scope(scope: dict) -> str:
    """
    LM2-17 fix : extrait l'IP cliente réelle en privilégiant les headers
    de proxy upstream.

    Quand live-mem est derrière le WAF Caddy (ou tout reverse proxy),
    ``scope["client"]`` contient l'IP du proxy, pas du client réel.
    On lit ``X-Forwarded-For`` (premier IP = client originel) ou
    ``X-Real-IP`` en fallback, puis ``scope["client"]`` en dernier
    recours.

    ⚠️ La confiance dans ces headers suppose que le serveur n'est PAS
    exposé directement à Internet (sinon n'importe qui peut les
    forger). En production, Caddy nettoie/réécrit ces headers — voir
    waf/Caddyfile et DESIGN/live-mem/DEPLOIEMENT_PRODUCTION.md.
    """
    headers = dict(scope.get("headers", []))

    xff = headers.get(b"x-forwarded-for", b"").decode().strip()
    if xff:
        # Format : "client-ip, proxy1, proxy2" → on prend le premier
        first = xff.split(",")[0].strip()
        if first:
            return first

    xri = headers.get(b"x-real-ip", b"").decode().strip()
    if xri:
        return xri

    # Fallback : socket TCP du peer (IP du proxy si reverse proxy)
    client = scope.get("client")
    if client and len(client) > 0:
        return client[0]

    return "unknown"


class AuthMiddleware:
    """
    Middleware ASGI d'authentification par Bearer token.

    Supporte trois modes de validation :
    1. Bootstrap key (variable d'env) → admin total
    2. Tokens S3 (via TokenService) → permissions granulaires
    3. Cookie HttpOnly (LM2-04 fix, web UI uniquement) — émis par /api/login

    Sources du token (prioritaire → fallback) :
    1. Header ``Authorization: Bearer <token>`` (agents MCP, API REST)
    2. Cookie ``livemem_auth=<token>`` (web UI, jamais en JS via HttpOnly)
    3. Query string ``?token=<token>`` (legacy, déconseillé)
    """

    # Routes qui ne nécessitent pas d'authentification
    # /api/login est public (sinon on ne peut jamais se connecter)
    PUBLIC_PATHS = {
        "/health",
        "/metrics",
        "/favicon.ico",
        "/live",
        "/live/",
        "/admin",
        "/admin/",
        "/api/login",
        "/api/logout",
    }

    # Préfixes de routes publiques (fichiers statiques)
    PUBLIC_PREFIXES = ("/static/",)

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        # Les routes publiques web restent anonymes, mais un badge présenté
        # explicitement ne doit jamais être accepté par une surface `/api/*`.
        # Sans ce contrôle, `/api/login` et `/api/logout` court-circuiteraient
        # l'injection du contexte avant StaticFilesMiddleware.
        if path in self.PUBLIC_PATHS and path.startswith("/api/"):
            token = self._extract_token(scope)
            if token:
                token_info = await self._validate_token(token)
                if is_space_badge(token_info):
                    body = json.dumps(
                        {
                            "status": "error",
                            "message": "Les badges de mission ne sont pas utilisables via l'API web",
                        }
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return

        # Routes publiques → pas d'auth
        if path in self.PUBLIC_PATHS:
            return await self.app(scope, receive, send)
        if any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        # Extraire le Bearer token
        token = self._extract_token(scope)
        token_info = None

        if token:
            # Valider le token (bootstrap key puis TokenService S3)
            token_info = await self._validate_token(token)

        # Bloquer si pas de token valide sur route non-publique
        if token_info is None:
            body = json.dumps({"error": "Authorization header required"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

            # Audit log pour les rejets d'auth (AuditMiddleware ne voit pas
            # les 401 car Auth court-circuite avant de l'atteindre)
            method = scope.get("method", "?")
            audit_entry = {
                "event": "auth_rejected",
                "request_id": current_request_id.get(),
                "method": method,
                "path": path,
                "status": 401,
                "client": "unauthenticated",
                "auth_type": "none",
                "reason": "missing_or_invalid_token",
                # LM2-17 fix : utiliser X-Forwarded-For si présent
                "client_ip": _client_ip_from_scope(scope),
            }
            audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))
            return

        # Mettre à jour le store global (visible par les session tasks MCP)
        update_fresh_token(token_info)

        # Injecter dans le contextvar
        tok = current_token_info.set(token_info)
        try:
            await self.app(scope, receive, send)
        finally:
            current_token_info.reset(tok)

    def _extract_token(self, scope) -> Optional[str]:
        """
        Extrait le token depuis Authorization, cookie HttpOnly ou query string.

        Priorité (LM2-04 fix) :
        1. Header ``Authorization: Bearer <token>`` (agents MCP, CLI)
        2. Cookie ``livemem_auth`` HttpOnly (web UI, jamais lisible par JS)
        3. Query string ``?token=<token>`` (legacy, navigateurs sans cookie)
        """
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer "):
            return auth[7:]

        # LM2-04 fix : extraire le cookie d'authentification.
        # HttpOnly côté serveur ⇒ inaccessible à un XSS, contrairement à
        # localStorage qui était exfiltrable trivialement (api.js historique).
        cookie_header = headers.get(b"cookie", b"").decode()
        if cookie_header:
            for raw in cookie_header.split(";"):
                pair = raw.strip().split("=", 1)
                if len(pair) == 2 and pair[0].strip() == AUTH_COOKIE_NAME:
                    val = pair[1].strip()
                    if val:
                        return val

        # Fallback: query string ?token=xxx (pour les navigateurs)
        qs = scope.get("query_string", b"").decode()
        for param in qs.split("&"):
            if param.startswith("token="):
                return param[6:]
        return None

    async def _validate_token(self, token: str) -> Optional[dict]:
        """
        Valide un token et retourne ses infos.

        Deux modes de validation :
        1. Bootstrap key → admin total (pour le premier démarrage)
        2. TokenService → lookup SHA-256 dans _system/tokens.json sur S3

        Args:
            token: Token brut (ex: "lm_a1B2c3..." ou bootstrap key)

        Returns:
            Dict {client_name, permissions, allowed_resources} ou None
        """
        settings = get_settings()

        # Mode 1 : Bootstrap key → admin total
        # VULN-04 fix : comparaison constant-time pour éviter les timing attacks
        if hmac.compare_digest(token, settings.admin_bootstrap_key):
            return {
                "type": "bootstrap",
                "token_kind": "bootstrap",
                "client_name": "admin",
                "permissions": ["admin", "read", "write"],
                "allowed_resources": [],  # vide = accès total
                "token_hash": None,  # bootstrap n'a pas de hash S3
            }

        # Mode 2 : Validation via TokenService (tokens stockés sur S3)
        try:
            from ..core.tokens import get_token_service

            token_info = await get_token_service().validate_token(token)
            if token_info:
                return token_info
        except Exception as e:
            # Si S3 n'est pas configuré ou tokens.json n'existe pas,
            # on continue silencieusement (le token sera invalide)
            logger.warning("TokenService error: %s", e)

        return None  # Token invalide


class LoggingMiddleware:
    """
    Middleware ASGI de logging des requêtes HTTP.

    Emits structured JSON log lines to stderr with:
    request_id, method, path, status, latency_ms, client identity.
    """

    # Paths not worth logging (high-frequency probes)
    _QUIET_PATHS = {"/health", "/metrics"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "?")
        t0 = time.monotonic()
        status_code = 0

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            # Skip health/metrics probes to reduce noise
            if path not in self._QUIET_PATHS:
                token_info = current_token_info.get()
                entry = {
                    "request_id": current_request_id.get(),
                    "method": method,
                    "path": path,
                    "status": status_code,
                    "latency_ms": elapsed,
                }
                if token_info:
                    entry["client"] = token_info.get("client_name", "anonymous")
                # LM2-17 fix : utiliser X-Forwarded-For pour avoir l'IP réelle
                # du client derrière le WAF (au lieu de l'IP du WAF lui-même)
                entry["client_ip"] = _client_ip_from_scope(scope)
                logger.info(json.dumps(entry, ensure_ascii=False))


class StaticFilesMiddleware:
    """
    Middleware ASGI pour servir l'interface web et l'API REST.

    Routes interceptées :
    - GET /live           → Page de visualisation (live.html)
    - GET /static/*       → Fichiers statiques (CSS, JS, images)
    - GET /api/spaces     → Liste des espaces (JSON)
    - GET /api/space/{id} → Info complète d'un espace (JSON)
    - GET /api/live/{id}  → Notes live d'un espace (JSON)
    - GET /api/bank/{id}  → Liste des fichiers bank (JSON)
    - GET /api/bank/{id}/{filename} → Contenu d'un fichier bank (JSON)

    Toutes les autres routes passent au handler suivant (MCP Streamable HTTP).
    """

    def __init__(self, app):
        import os

        self.app = app
        self._static_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "static"
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Un badge est exclusivement un credential MCP live. Les routes API
        # doivent rester inaccessibles, y compris via le proxy d'outils admin.
        if path.startswith("/api/") and is_space_badge(current_token_info.get()):
            await self._send_json(
                send,
                {
                    "status": "error",
                    "message": "Les badges de mission ne sont pas utilisables via l'API web",
                },
                403,
            )
            return

        # Health check — réponse directe (pas de MCP, pas d'auth)
        if path == "/health":
            await self._handle_health(send)
            return

        # Page de visualisation
        if path in ("/live", "/live/"):
            await self._serve_file(send, "live.html", "text/html; charset=utf-8")
            return

        # Admin console
        if path in ("/admin", "/admin/"):
            await self._serve_file(send, "admin.html", "text/html; charset=utf-8")
            return

        # Fichiers statiques (CSS, JS, images)
        if path.startswith("/static/"):
            rel_path = path[len("/static/") :]
            if ".." not in rel_path and rel_path:
                ct = self._guess_content_type(rel_path)
                await self._serve_file(send, rel_path, ct)
                return

        # API REST — Tool proxy (admin console)
        if path == "/api/tool" and method == "POST":
            await self._api_tool_call(receive, send)
            return

        # API REST — Login (LM2-04 fix : émet un cookie HttpOnly)
        if path == "/api/login" and method == "POST":
            await self._api_login(scope, receive, send)
            return

        # API REST — Logout (efface le cookie HttpOnly)
        if path == "/api/logout" and method == "POST":
            await self._api_logout(send)
            return

        # API REST — Liste des espaces
        if path == "/api/spaces" and method == "GET":
            await self._api_spaces(scope, send)
            return

        # API REST — Info d'un espace
        if path.startswith("/api/space/") and method == "GET":
            space_id = path[len("/api/space/") :]
            if space_id and "/" not in space_id:
                await self._api_space_info(send, space_id)
                return

        # API REST — Notes live
        if path.startswith("/api/live/") and method == "GET":
            space_id = path[len("/api/live/") :]
            if space_id and "/" not in space_id:
                qs = scope.get("query_string", b"").decode()
                await self._api_live_notes(send, space_id, qs)
                return

        # API REST — Bank (liste ou fichier)
        if path.startswith("/api/bank/") and method == "GET":
            remainder = path[len("/api/bank/") :]
            parts = remainder.split("/", 1)
            if len(parts) == 1 and parts[0]:
                await self._api_bank_list(send, parts[0])
                return
            elif len(parts) == 2 and parts[0] and parts[1]:
                await self._api_bank_file(send, parts[0], parts[1])
                return

        # Passer au handler suivant (MCP Streamable HTTP)
        await self.app(scope, receive, send)

    # ─────────────────── Health Check ───────────────────

    async def _handle_health(self, send):
        """
        Endpoint /health — probes S3 and LLMaaS connectivity.

        Returns 200 + {"status": "healthy"} when all dependencies are reachable,
        200 + {"status": "degraded"} when some are down,
        or 503 + {"status": "unhealthy"} when critical deps fail.
        """
        import json
        import time
        from pathlib import Path

        version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
        version = version_file.read_text().strip() if version_file.exists() else "dev"

        services = {}

        # ── Probe S3 (critical) ──────────────────────────────
        # LM2-24 fix : `/health` est PUBLIC (sans auth). Une exception
        # botocore exposait sinon l'endpoint S3 complet, le bucket, et
        # potentiellement la clé d'accès dans la trace. On loggue côté
        # serveur le détail, et on renvoie un message générique au client.
        try:
            from ..core.storage import get_storage

            storage = get_storage()
            services["s3"] = await storage.test_connection()
        except Exception as e:
            logger.warning("/health: S3 probe failed: %s", e)
            services["s3"] = {"status": "error", "message": "S3 unreachable"}

        # ── Probe LLMaaS ─────────────────────────────────────
        try:
            from ..config import get_settings

            settings = get_settings()
            if settings.llmaas_api_url and settings.llmaas_api_key:
                import httpx
                from openai import AsyncOpenAI

                t0 = time.monotonic()
                # Même pattern que ConsolidatorService : PROXY_URL reste opt-in
                # et n'affecte que le client HTTP explicitement configuré.
                proxy_url = settings.proxy_url
                http_client = (
                    httpx.AsyncClient(
                        proxy=httpx.Proxy(url=proxy_url),
                        timeout=5,
                    )
                    if proxy_url
                    else None
                )
                client = AsyncOpenAI(
                    base_url=settings.llmaas_api_url,
                    api_key=settings.llmaas_api_key,
                    timeout=5,
                    http_client=http_client,
                )
                try:
                    models = await client.models.list()
                finally:
                    if http_client is not None:
                        await http_client.aclose()
                latency = round((time.monotonic() - t0) * 1000, 1)
                model_ids = [m.id for m in models.data]
                services["llmaas"] = {
                    "status": "ok",
                    "model": settings.llmaas_model,
                    "model_available": settings.llmaas_model in model_ids,
                    "latency_ms": latency,
                }
            else:
                services["llmaas"] = {
                    "status": "warning",
                    "message": "LLMaaS non configuré",
                }
        except Exception as e:
            # LM2-24 fix : pareil que S3 — ne pas exposer la stack openai
            # ou l'URL LLMaaS sur un endpoint public.
            logger.warning("/health: LLMaaS probe failed: %s", e)
            services["llmaas"] = {"status": "error", "message": "LLMaaS unreachable"}

        # ── Global status ─────────────────────────────────────
        statuses = [s.get("status", "error") for s in services.values()]
        if all(s == "ok" for s in statuses):
            overall = "healthy"
            status_code = 200
        elif services["s3"].get("status") != "ok":
            overall = "unhealthy"
            status_code = 503
        else:
            overall = "degraded"
            status_code = 200

        result = {
            "status": overall,
            "service": "live-memory",
            "version": version,
            "transport": "streamable-http",
            "services": services,
        }

        body = json.dumps(result).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    # ─────────────────── API Handlers ───────────────────

    async def _api_tool_call(self, receive, send):
        """
        POST /api/tool — proxies tool calls from the admin web UI.

        Accepts ``{"tool": "tool_name", "arguments": {...}}`` and calls
        the MCP tool directly via the tool registry. Auth context is
        already set by AuthMiddleware (cookie HttpOnly).

        Each tool enforces its own permissions internally.

        Security (ADM-* fixes from audit 2026-05-16):
        - ADM-06: Requires write permission minimum
        - ADM-05: Request body limited to api_tool_max_body_bytes
        - ADM-08: Audit log includes tool name and argument keys
        - ADM-02: Exception messages use safe_error() (no leakage)
        """
        try:
            # ADM-06 fix: require write permission minimum for admin console.
            # Read-only tokens can use /live for viewing. The admin console
            # is for management — individual tools enforce stricter permissions.
            from ..auth.context import check_write_permission

            perm_err = check_write_permission()
            if perm_err:
                await self._send_json(send, perm_err, 403)
                return

            # ADM-05 fix: limit request body size to prevent memory exhaustion.
            from ..config import get_settings as _adm_gs

            max_body = _adm_gs().api_tool_max_body_bytes

            body_chunks: list[bytes] = []
            total_len = 0
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.request":
                    chunk = message.get("body", b"")
                    total_len += len(chunk)
                    if total_len > max_body:
                        await self._send_json(
                            send,
                            {"status": "error", "message": "Request body too large"},
                            413,
                        )
                        return
                    body_chunks.append(chunk)
                    more_body = message.get("more_body", False)
                else:
                    break
            raw_body = b"".join(body_chunks)

            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                await self._send_json(
                    send, {"status": "error", "message": "Invalid JSON body"}, 400
                )
                return

            tool_name = (payload.get("tool") or "").strip()
            arguments = payload.get("arguments", {})

            if not tool_name:
                await self._send_json(
                    send, {"status": "error", "message": "Missing 'tool' field"}, 400
                )
                return

            # ADM-08 fix: audit log with tool name before execution.
            # Only argument keys are logged (not values, which may be sensitive).
            token_info = current_token_info.get()
            audit_logger.info(
                json.dumps(
                    {
                        "event": "admin_tool_call",
                        "request_id": current_request_id.get(),
                        "tool": tool_name,
                        "arguments_keys": list(arguments.keys()),
                        "client": token_info.get("client_name", "?")
                        if token_info
                        else "?",
                    },
                    ensure_ascii=False,
                )
            )

            from ..tools import call_tool_direct

            result = await call_tool_direct(tool_name, arguments)
            await self._send_json(send, result)
        except Exception as e:
            # ADM-02 fix: use safe_error() to prevent exception message leakage.
            # The full exception is logged server-side, but the client only
            # sees a generic message (unless MCP_SERVER_DEBUG=true).
            logger.exception("/api/tool error")
            from ..auth.context import safe_error

            await self._send_json(send, safe_error(e, "/api/tool"), 500)

    async def _api_login(self, scope, receive, send):
        """
        LM2-04 fix : authentification web via cookie HttpOnly.

        Reçoit ``POST /api/login`` avec ``{"token": "lm_..."}`` ou
        ``{"token": "<bootstrap_key>"}``. Valide via le pipeline standard
        (TokenService + bootstrap), puis émet un cookie ``livemem_auth``
        avec les flags ``HttpOnly`` (anti-XSS), ``SameSite=Strict`` (anti-CSRF)
        et ``Secure`` (HTTPS-only, sauf en HTTP local pour le développement).

        Le cookie est inaccessible au JavaScript (différence majeure avec
        l'ancien stockage ``localStorage`` qui était trivialement exfiltrable
        par un XSS comme LM2-01).

        Returns:
            ``{"status": "ok", "client_name": ..., "permissions": ...}``
            avec ``Set-Cookie`` header. ``401`` si token invalide.
        """
        try:
            # Lire le body (1 chunk suffit pour un payload {"token": "..."})
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.request":
                    body_chunks.append(message.get("body", b""))
                    more_body = message.get("more_body", False)
                else:
                    break
            raw_body = b"".join(body_chunks)

            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                await self._send_json(
                    send,
                    {"status": "error", "message": "Body JSON invalide"},
                    400,
                )
                return

            token = (payload.get("token") or "").strip()
            if not token:
                await self._send_json(
                    send,
                    {"status": "error", "message": "Champ 'token' requis"},
                    400,
                )
                return

            # Réutilise la pile d'auth standard (bootstrap + TokenService).
            # On instancie un AuthMiddleware just-in-time pour ne pas dupliquer
            # la logique de validation (single source of truth).
            auth = AuthMiddleware(None)
            token_info = await auth._validate_token(token)

            if token_info is None:
                # Audit log explicite (cohérent avec le rejet middleware)
                audit_logger.info(
                    json.dumps(
                        {
                            "event": "login_failed",
                            "request_id": current_request_id.get(),
                            "path": "/api/login",
                            "status": 401,
                            "reason": "invalid_token",
                        },
                        ensure_ascii=False,
                    )
                )
                await self._send_json(
                    send,
                    {"status": "error", "message": "Token invalide"},
                    401,
                )
                return

            if is_space_badge(token_info):
                audit_logger.info(
                    json.dumps(
                        {
                            "event": "login_failed",
                            "request_id": current_request_id.get(),
                            "path": "/api/login",
                            "status": 403,
                            "reason": "space_badge_not_web",
                        },
                        ensure_ascii=False,
                    )
                )
                await self._send_json(
                    send,
                    {
                        "status": "error",
                        "message": "Les badges de mission ne sont pas utilisables via l'API web",
                    },
                    403,
                )
                return

            # Construire les flags du cookie. ``Secure`` n'est ajouté qu'en HTTPS
            # détecté via l'en-tête X-Forwarded-Proto (cas WAF Caddy en prod)
            # ou via le scheme ASGI direct. En dev HTTP pur on l'omet sinon
            # le navigateur ignore le cookie.
            headers = dict(scope.get("headers", []))
            forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode().lower()
            scheme = scope.get("scheme", "http").lower()
            is_https = scheme == "https" or forwarded_proto == "https"

            cookie_parts = [
                f"{AUTH_COOKIE_NAME}={token}",
                "Path=/",
                "HttpOnly",
                "SameSite=Strict",
            ]
            if is_https:
                cookie_parts.append("Secure")
            # Pas de Max-Age : cookie de session (s'efface à la fermeture du navigateur).
            # L'expiration applicative est gérée par le TokenService (expires_at).
            cookie_value = "; ".join(cookie_parts)

            audit_logger.info(
                json.dumps(
                    {
                        "event": "login_success",
                        "request_id": current_request_id.get(),
                        "client": token_info.get("client_name", "?"),
                        "auth_type": token_info.get("type", "?"),
                    },
                    ensure_ascii=False,
                )
            )

            body = json.dumps(
                {
                    "status": "ok",
                    "client_name": token_info.get("client_name", "?"),
                    "permissions": token_info.get("permissions", []),
                    "allowed_resources": token_info.get("allowed_resources", []),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                        (b"set-cookie", cookie_value.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    async def _api_logout(self, send):
        """
        Efface le cookie d'authentification HttpOnly (LM2-04 fix).

        Envoie un cookie ``Max-Age=0`` qui force le navigateur à
        l'oublier immédiatement. Note : ce ne révoque PAS le token
        côté serveur (le token reste valide pour les agents MCP qui
        l'utilisent en Bearer header) — pour une révocation effective
        utiliser ``admin_revoke_token``.
        """
        expired_cookie = (
            f"{AUTH_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        )
        body = json.dumps({"status": "ok"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"set-cookie", expired_cookie.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _api_spaces(self, scope, send):
        """Liste des espaces."""
        try:
            from ..core.space import get_space_service

            # Récupérer les permissions du token si disponibles
            allowed = None
            token_info = current_token_info.get()
            if token_info and token_info.get("allowed_resources"):
                allowed = token_info["allowed_resources"]
            elif token_info and token_info.get("space_ids"):
                allowed = token_info["space_ids"]

            result = await get_space_service().list_spaces(
                allowed_space_ids=allowed if allowed else None
            )
            await self._send_json(send, result)
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    async def _api_space_info(self, send, space_id: str):
        """Info complète d'un espace (meta + rules + stats)."""
        try:
            # VULN-02 fix : vérifier l'accès à l'espace
            access_err = check_access(space_id)
            if access_err:
                await self._send_json(send, access_err, 403)
                return

            from ..core.space import get_space_service
            from ..core.storage import get_storage

            svc = get_space_service()
            info = await svc.get_info(space_id)
            if info.get("status") != "ok":
                await self._send_json(send, info)
                return

            # Ajouter les rules
            rules_result = await svc.get_rules(space_id)
            info["rules"] = rules_result.get("rules", "")

            # Ajouter les métadonnées complètes (pour graph_memory, etc.)
            storage = get_storage()
            meta = await storage.get_json(f"{space_id}/_meta.json")
            if meta:
                info["total_notes_processed"] = meta.get("total_notes_processed", 0)
                if meta.get("graph_memory"):
                    # VULN-12 fix : masquer le token Graph Memory dans la réponse
                    gm = dict(meta["graph_memory"])
                    if gm.get("token"):
                        gm["token"] = (
                            gm["token"][:8] + "..." if len(gm["token"]) > 8 else "***"
                        )
                    info["graph_memory"] = gm

            await self._send_json(send, info)
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    async def _api_live_notes(self, send, space_id: str, query_string: str):
        """Notes live avec filtres optionnels."""
        try:
            # VULN-02 fix : vérifier l'accès à l'espace
            access_err = check_access(space_id)
            if access_err:
                await self._send_json(send, access_err, 403)
                return

            from ..core.live import get_live_service
            from urllib.parse import parse_qs

            params = parse_qs(query_string)
            result = await get_live_service().read_notes(
                space_id=space_id,
                limit=int(params.get("limit", ["500"])[0]),
                category=params.get("category", [""])[0],
                agent=params.get("agent", [""])[0],
                since=params.get("since", [""])[0],
            )
            await self._send_json(send, result)
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    async def _api_bank_list(self, send, space_id: str):
        """Liste des fichiers bank."""
        try:
            # VULN-02 fix : vérifier l'accès à l'espace
            access_err = check_access(space_id)
            if access_err:
                await self._send_json(send, access_err, 403)
                return

            from ..core.storage import get_storage

            storage = get_storage()

            # Vérifier l'existence de l'espace
            if not await storage.exists(f"{space_id}/_meta.json"):
                await self._send_json(
                    send,
                    {
                        "status": "not_found",
                        "message": f"Espace '{space_id}' introuvable",
                    },
                )
                return

            # Exposer uniquement les documents logiques. Les objets multipart
            # v2.7.x restent lisibles le temps de leur migration canonique.
            from ..core.consolidator import _build_compaction_units

            bank_data = await storage.list_and_get(f"{space_id}/bank/")
            units = _build_compaction_units(space_id, bank_data)
            invalid_units = [unit for unit in units if unit.get("error")]
            if invalid_units:
                await self._send_json(
                    send,
                    {
                        "status": "error",
                        "space_id": space_id,
                        "message": "Invalid legacy multipart bank family",
                        "invalid_files": len(invalid_units),
                    },
                    409,
                )
                return
            files = [
                {
                    "filename": unit["source"],
                    "size": len(unit["content"].encode("utf-8")),
                    "last_modified": max(
                        (member.get("last_modified", "") for member in unit["members"]),
                        default="",
                    ),
                    "legacy_parts": max(0, len(unit["members"]) - 1),
                    "legacy_split": unit["legacy_split"],
                    **({"error": unit["error"]} if unit.get("error") else {}),
                }
                for unit in units
            ]

            await self._send_json(
                send,
                {
                    "status": "ok",
                    "space_id": space_id,
                    "files": files,
                    "total": len(files),
                },
            )
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    async def _api_bank_file(self, send, space_id: str, filename: str):
        """Contenu d'un fichier bank."""
        try:
            # VULN-02 fix : vérifier l'accès à l'espace
            access_err = check_access(space_id)
            if access_err:
                await self._send_json(send, access_err, 403)
                return

            from ..core.storage import get_storage
            from urllib.parse import unquote

            storage = get_storage()
            filename = unquote(filename)

            # VULN-09 fix : valider le filename contre path traversal
            if ".." in filename or filename.startswith("/"):
                await self._send_json(
                    send, {"status": "error", "message": "Nom de fichier invalide"}, 400
                )
                return

            from ..core.consolidator import _build_compaction_units, _sanitize_filename

            sanitized_target = _sanitize_filename(filename)
            bank_data = await storage.list_and_get(f"{space_id}/bank/")
            unit = next(
                (
                    item
                    for item in _build_compaction_units(space_id, bank_data)
                    if item["source"] == sanitized_target
                ),
                None,
            )
            if unit is None:
                await self._send_json(
                    send,
                    {
                        "status": "not_found",
                        "message": f"Fichier '{filename}' introuvable",
                    },
                )
                return
            if unit.get("error"):
                await self._send_json(
                    send,
                    {
                        "status": "error",
                        "space_id": space_id,
                        "filename": unit["source"],
                        "message": unit["error"],
                    },
                    409,
                )
                return

            content = unit["content"]

            await self._send_json(
                send,
                {
                    "status": "ok",
                    "space_id": space_id,
                    "filename": unit["source"],
                    "content": content,
                    "size": len(content.encode("utf-8")),
                },
            )
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    # ─────────────────── Utilitaires ───────────────────

    async def _send_json(self, send, data: dict, status: int = 200):
        """Envoie une réponse JSON."""
        import json

        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    # VULN-17 fix : CORS supprimé — l'interface web est servie
                    # par le même serveur (même origine), pas besoin de CORS.
                    # Les agents MCP utilisent /mcp, pas /api/*.
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _serve_file(self, send, filename: str, content_type: str):
        """Sert un fichier statique."""
        import os

        filepath = os.path.join(self._static_dir, filename)

        if not os.path.exists(filepath):
            body = f"<h1>404 Not Found</h1><p>{filename}</p>".encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [
                        (b"content-type", b"text/html"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        with open(filepath, "rb") as f:
            body = f.read()

        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-cache"),
        ]

        # ADM-03 fix: defense-in-depth security headers on HTML pages.
        # These duplicate what the WAF Caddy sets, but protect against
        # direct access on port 8002 (dev, debug, misconfigured deploy).
        if "text/html" in content_type:
            headers.extend(
                [
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; "
                        b"style-src 'self' 'unsafe-inline'; "
                        b"img-src 'self' data:; connect-src 'self'; "
                        b"frame-ancestors 'none'; object-src 'none'; "
                        b"base-uri 'self'",
                    ),
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (
                        b"permissions-policy",
                        b"camera=(), microphone=(), geolocation=(), payment=()",
                    ),
                ]
            )

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """Devine le content-type à partir de l'extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return {
            "html": "text/html; charset=utf-8",
            "css": "text/css; charset=utf-8",
            "js": "application/javascript; charset=utf-8",
            "json": "application/json",
            "png": "image/png",
            "svg": "image/svg+xml",
            "ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
