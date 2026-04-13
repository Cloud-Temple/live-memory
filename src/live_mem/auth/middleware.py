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
import sys
import time
import hashlib
import logging
from typing import Optional
from .context import current_token_info, check_access
from ..config import get_settings
from ..middleware import current_request_id

logger = logging.getLogger("live_mem.auth")


class AuthMiddleware:
    """
    Middleware ASGI d'authentification par Bearer token.

    Supporte deux modes de validation :
    1. Bootstrap key (variable d'env) → admin total
    2. Tokens S3 (via TokenService) → permissions granulaires
    """

    # Routes qui ne nécessitent pas d'authentification
    PUBLIC_PATHS = {"/health", "/metrics", "/favicon.ico", "/live", "/live/"}

    # Préfixes de routes publiques (fichiers statiques)
    PUBLIC_PREFIXES = ("/static/",)

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

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
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # Injecter dans le contextvar
        tok = current_token_info.set(token_info)
        try:
            await self.app(scope, receive, send)
        finally:
            current_token_info.reset(tok)

    def _extract_token(self, scope) -> Optional[str]:
        """Extrait le token depuis le header Authorization ou query string."""
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer "):
            return auth[7:]

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
                client = scope.get("client")
                if client:
                    entry["client_ip"] = client[0]
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
            os.path.dirname(os.path.dirname(__file__)),
            "static"
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Health check — réponse directe (pas de MCP, pas d'auth)
        if path == "/health":
            await self._handle_health(send)
            return

        # Page de visualisation
        if path in ("/live", "/live/"):
            await self._serve_file(send, "live.html", "text/html; charset=utf-8")
            return

        # Fichiers statiques (CSS, JS, images)
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            if ".." not in rel_path and rel_path:
                ct = self._guess_content_type(rel_path)
                await self._serve_file(send, rel_path, ct)
                return

        # API REST — Liste des espaces
        if path == "/api/spaces" and method == "GET":
            await self._api_spaces(scope, send)
            return

        # API REST — Info d'un espace
        if path.startswith("/api/space/") and method == "GET":
            space_id = path[len("/api/space/"):]
            if space_id and "/" not in space_id:
                await self._api_space_info(send, space_id)
                return

        # API REST — Notes live
        if path.startswith("/api/live/") and method == "GET":
            space_id = path[len("/api/live/"):]
            if space_id and "/" not in space_id:
                qs = scope.get("query_string", b"").decode()
                await self._api_live_notes(send, space_id, qs)
                return

        # API REST — Bank (liste ou fichier)
        if path.startswith("/api/bank/") and method == "GET":
            remainder = path[len("/api/bank/"):]
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
        Endpoint /health — probes S3 connectivity.

        Returns 200 + {"status": "healthy"} when S3 is reachable,
        or 503 + {"status": "unhealthy", "reason": "..."} otherwise.
        Keeps the probe fast (2s timeout on S3 test).
        """
        import json
        from pathlib import Path

        version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
        version = version_file.read_text().strip() if version_file.exists() else "dev"

        status_code = 200
        result = {
            "status": "healthy",
            "service": "live-memory",
            "version": version,
            "transport": "streamable-http",
        }

        # Probe S3 connectivity (the critical dependency)
        try:
            from ..core.storage import get_storage
            storage = get_storage()
            s3_result = await storage.test_connection()
            if s3_result.get("status") != "ok":
                status_code = 503
                result["status"] = "unhealthy"
                result["reason"] = f"S3: {s3_result.get('message', 'not reachable')}"
        except Exception as e:
            status_code = 503
            result["status"] = "unhealthy"
            result["reason"] = f"S3: {e}"

        body = json.dumps(result).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    # ─────────────────── API Handlers ───────────────────

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
                        gm["token"] = gm["token"][:8] + "..." if len(gm["token"]) > 8 else "***"
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
                await self._send_json(send, {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable"
                })
                return

            # Lister les fichiers bank
            # VULN-11 fix : utiliser bank_relpath au lieu de split("/")[-1]
            from ..core.storage import bank_relpath
            objects = await storage.list_objects(f"{space_id}/bank/")
            files = []
            for obj in objects:
                key = obj["Key"]
                if key.endswith(".keep"):
                    continue
                filename = bank_relpath(key, space_id)
                files.append({
                    "filename": filename,
                    "size": obj.get("Size", 0),
                    "last_modified": obj.get("LastModified", ""),
                })

            await self._send_json(send, {
                "status": "ok",
                "space_id": space_id,
                "files": files,
                "total": len(files),
            })
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
                await self._send_json(send, {"status": "error", "message": "Nom de fichier invalide"}, 400)
                return

            key = f"{space_id}/bank/{filename}"
            content = await storage.get(key)
            if content is None:
                await self._send_json(send, {
                    "status": "not_found",
                    "message": f"Fichier '{filename}' introuvable"
                })
                return

            await self._send_json(send, {
                "status": "ok",
                "space_id": space_id,
                "filename": filename,
                "content": content,
                "size": len(content.encode("utf-8")),
            })
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)

    # ─────────────────── Utilitaires ───────────────────

    async def _send_json(self, send, data: dict, status: int = 200):
        """Envoie une réponse JSON."""
        import json
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                # VULN-17 fix : CORS supprimé — l'interface web est servie
                # par le même serveur (même origine), pas besoin de CORS.
                # Les agents MCP utilisent /mcp, pas /api/*.
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def _serve_file(self, send, filename: str, content_type: str):
        """Sert un fichier statique."""
        import os
        filepath = os.path.join(self._static_dir, filename)

        if not os.path.exists(filepath):
            body = f"<h1>404 Not Found</h1><p>{filename}</p>".encode()
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [
                    (b"content-type", b"text/html"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        with open(filepath, "rb") as f:
            body = f.read()

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-cache"),
            ],
        })
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
