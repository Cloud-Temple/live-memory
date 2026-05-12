# -*- coding: utf-8 -*-
"""
Service Graph Bridge — Pont entre Live Memory et Graph Memory.

Ce service permet à un space de pousser ses fichiers bank consolidés
dans une instance Graph Memory (graphe de connaissances) pour la
mémoire long terme.

Flux de push :
    1. Connexion MCP Streamable HTTP à graph-memory
    2. Vérification/création de la mémoire cible
    3. Synchronisation : delete + re-ingest pour chaque fichier bank
    4. Nettoyage des fichiers obsolètes dans graph-memory
    5. Mise à jour des métadonnées du space

Communication : protocole MCP via Streamable HTTP (SDK officiel mcp>=1.8.0).
Graph Memory est un service externe, on utilise son API MCP telle quelle.

Migration SSE → Streamable HTTP (issue #1) :
    - Remplace httpx + httpx-sse par mcp.client.streamable_http
    - Endpoint : /sse → /mcp
    - Plus de handshake manuel (le SDK gère initialize automatiquement)
    - Chaque call_tool crée sa propre session (évite les conflits
      de cancel scope quand appelé depuis le serveur MCP)

Voir le README de graph-memory pour les outils disponibles :
    - memory_create, memory_list, memory_stats
    - memory_ingest, document_list, document_delete
"""

import json
import time
import base64
import asyncio
import logging
from datetime import datetime, timezone

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .storage import get_storage, bank_relpath
from .models import GraphMemoryConfig

logger = logging.getLogger("live_mem.graph_bridge")


# ─────────────────────────────────────────────────────────────
# Client MCP léger pour communiquer avec Graph Memory
# ─────────────────────────────────────────────────────────────


class GraphMemoryClient:
    """
    Client MCP Streamable HTTP pour appeler les outils de Graph Memory.

    Chaque appel call_tool() crée sa propre connexion MCP complète
    (transport + session + initialize + appel + fermeture).

    C'est volontaire : le SDK MCP utilise des anyio TaskGroups qui ne
    supportent pas d'être ouvertes dans une task et fermées dans une
    autre (erreur "cancel scope in different task"). Comme le serveur
    MCP exécute les outils dans ses propres tasks, un context manager
    persistant casse. Chaque appel auto-contenu résout le problème.

    Pour les opérations multi-appels (push), on utilise call_tools_batch()
    qui exécute tout dans un seul scope asyncio.

    Usage :
        gm = GraphMemoryClient("http://localhost:8080", "token")
        result = await gm.call_tool("memory_list", {})
    """

    def __init__(self, base_url: str, token: str, timeout: float = 120.0):
        """
        Args:
            base_url: URL de base de graph-memory (ex: "http://localhost:8080")
            token: Bearer token pour l'authentification
            timeout: Timeout par appel d'outil en secondes

        Note proxy :
            PROXY_URL n'est pas encore supporté pour cette connexion.
            streamablehttp_client (SDK MCP officiel) ne prend pas de
            paramètre proxy ni d'httpx_client dans son API actuelle.
            Les appels vers graph-memory passent donc toujours en direct.
        """
        # Normaliser l'URL : retirer /sse ou /mcp si présent en fin
        self._base_url = base_url.rstrip("/")
        for suffix in ("/sse", "/mcp"):
            if self._base_url.endswith(suffix):
                self._base_url = self._base_url[: -len(suffix)]
        self._token = token
        self._timeout = timeout

    @property
    def _headers(self) -> dict:
        """Headers HTTP avec authentification Bearer."""
        h = {}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    @property
    def _mcp_url(self) -> str:
        return f"{self._base_url}/mcp"

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Appelle un outil MCP sur Graph Memory (session auto-contenue).

        Crée une connexion complète pour chaque appel :
        transport → session → initialize → call_tool → fermeture.

        Args:
            tool_name: Nom de l'outil (ex: "memory_create")
            arguments: Paramètres de l'outil

        Returns:
            Résultat de l'outil (dict)
        """
        try:
            async with streamablehttp_client(
                self._mcp_url,
                headers=self._headers,
                timeout=self._timeout,
                sse_read_timeout=self._timeout,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments),
                        timeout=self._timeout,
                    )

                    # Extraire le résultat (SDK MCP encapsule dans content[0].text)
                    if result.content and len(result.content) > 0:
                        text = result.content[0].text
                        try:
                            return json.loads(text)
                        except (json.JSONDecodeError, TypeError):
                            return {"status": "ok", "raw": text}

                    return {"status": "ok", "raw": ""}

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Timeout après {self._timeout}s pour '{tool_name}' sur Graph Memory"
            )
        except Exception as e:
            raise ConnectionError(f"Erreur MCP '{tool_name}' sur Graph Memory : {e}")

    async def call_tools_batch(self, calls: list[tuple[str, dict]]) -> list[dict]:
        """
        Exécute plusieurs appels d'outils dans une seule session MCP.

        Utile pour les opérations multi-appels (push) : une seule
        connexion pour N appels, tout dans le même scope asyncio.

        Args:
            calls: Liste de (tool_name, arguments) tuples

        Returns:
            Liste de résultats (même ordre que les appels)
        """
        results = []
        try:
            async with streamablehttp_client(
                self._mcp_url,
                headers=self._headers,
                timeout=self._timeout,
                sse_read_timeout=self._timeout,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    for tool_name, arguments in calls:
                        try:
                            result = await asyncio.wait_for(
                                session.call_tool(tool_name, arguments),
                                timeout=self._timeout,
                            )
                            if result.content and len(result.content) > 0:
                                text = result.content[0].text
                                try:
                                    results.append(json.loads(text))
                                except (json.JSONDecodeError, TypeError):
                                    results.append({"status": "ok", "raw": text})
                            else:
                                results.append({"status": "ok", "raw": ""})
                        except asyncio.TimeoutError:
                            results.append(
                                {
                                    "status": "error",
                                    "message": f"Timeout {self._timeout}s pour '{tool_name}'",
                                }
                            )
                        except Exception as e:
                            results.append(
                                {
                                    "status": "error",
                                    "message": f"Erreur '{tool_name}': {e}",
                                }
                            )

        except Exception as e:
            # Si la connexion elle-même échoue, remplir tous les résultats manquants
            while len(results) < len(calls):
                results.append(
                    {
                        "status": "error",
                        "message": f"Connexion Graph Memory échouée : {e}",
                    }
                )

        return results

    # Context manager pour compatibilité (délègue à call_tool par appel)
    async def __aenter__(self):
        logger.info(
            "GraphMemoryClient connecté (mode appels auto-contenus) : %s",
            self._base_url,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # Rien à fermer — chaque call_tool gère sa propre session


# ─────────────────────────────────────────────────────────────
# Service Graph Bridge
# ─────────────────────────────────────────────────────────────


class GraphBridgeService:
    """
    Service orchestrateur pour le pont live-memory → graph-memory.

    Gère la configuration de connexion, la synchronisation des fichiers
    bank, et les métriques de push.
    """

    # ─────────────────────────────────────────────────────────
    # CONNECT — Configurer la connexion graph-memory
    # ─────────────────────────────────────────────────────────

    async def connect(
        self,
        space_id: str,
        url: str,
        token: str,
        memory_id: str,
        ontology: str = "general",
    ) -> dict:
        """
        Connecte un space à une instance Graph Memory.

        Opérations :
        1. Vérifie que le space existe
        2. Teste la connexion à graph-memory (health check)
        3. Vérifie/crée la mémoire cible dans graph-memory
        4. Sauvegarde la config dans _meta.json

        Args:
            space_id: Identifiant du space live-memory
            url: URL de graph-memory (ex: "http://localhost:8080" ou "/mcp")
            token: Bearer token pour graph-memory
            memory_id: Memory cible dans graph-memory
            ontology: Ontologie à utiliser (défaut: "general")

        Returns:
            {"status": "connected", ...} ou erreur
        """
        storage = get_storage()

        # Vérifier que le space existe
        meta_data = await storage.get_json(f"{space_id}/_meta.json")
        if meta_data is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Tester la connexion à graph-memory
        try:
            gm = GraphMemoryClient(url, token)

            # Vérifier la santé
            health = await gm.call_tool("system_health", {})
            if health.get("status") == "error":
                return {
                    "status": "error",
                    "message": (
                        f"Graph Memory non disponible : "
                        f"{health.get('message', 'erreur inconnue')}"
                    ),
                }

            # Vérifier si la mémoire existe déjà
            memories = await gm.call_tool("memory_list", {})
            existing_ids = []
            if memories.get("status") == "ok":
                existing_ids = [
                    m.get("memory_id", m.get("id", ""))
                    for m in memories.get("memories", [])
                ]

            memory_created = False
            if memory_id not in existing_ids:
                # Créer la mémoire dans graph-memory
                create_result = await gm.call_tool(
                    "memory_create",
                    {
                        "memory_id": memory_id,
                        "name": f"Live Memory — {space_id}",
                        "description": (
                            f"Memory Bank synchronisée depuis live-memory "
                            f"space '{space_id}'"
                        ),
                        "ontology": ontology,
                    },
                )

                if create_result.get("status") == "error":
                    return {
                        "status": "error",
                        "message": (
                            f"Impossible de créer la mémoire '{memory_id}' "
                            f"dans Graph Memory : "
                            f"{create_result.get('message', '')}"
                        ),
                    }
                memory_created = True
                logger.info(
                    "Mémoire '%s' créée dans Graph Memory (ontologie: %s)",
                    memory_id,
                    ontology,
                )

        except ConnectionError as e:
            return {
                "status": "error",
                "message": f"Connexion impossible à Graph Memory : {e}",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors du test de connexion : {e}",
            }

        # Sauvegarder la config dans _meta.json
        graph_config = GraphMemoryConfig(
            url=url,
            token=token,
            memory_id=memory_id,
            ontology=ontology,
        )
        meta_data["graph_memory"] = graph_config.model_dump()
        await storage.put_json(f"{space_id}/_meta.json", meta_data)

        logger.info(
            "Space '%s' connecté à Graph Memory '%s' (%s)",
            space_id,
            memory_id,
            url,
        )

        return {
            "status": "connected",
            "space_id": space_id,
            "graph_memory": {
                "url": url,
                "memory_id": memory_id,
                "ontology": ontology,
                "memory_created": memory_created,
            },
        }

    # ─────────────────────────────────────────────────────────
    # PUSH — Pousser la bank dans graph-memory
    # ─────────────────────────────────────────────────────────

    async def push(self, space_id: str) -> dict:
        """
        Pousse les fichiers bank du space dans graph-memory.

        Synchronisation intelligente (delete + re-ingest) :
        1. Liste les documents existants dans graph-memory
        2. Pour chaque fichier bank :
           - Si existe dans graph-memory → delete puis re-ingest
           - Sinon → ingest
        3. Supprime les documents dans graph-memory qui ne sont
           plus dans la bank (nettoyage)
        4. Met à jour _meta.json avec les métriques de push

        Utilise call_tools_batch() pour exécuter tous les appels
        dans une seule session MCP (performance).

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            {"status": "ok", "pushed": N, "deleted": N, "errors": N, ...}
        """
        storage = get_storage()
        t0 = time.monotonic()

        # Lire la config
        meta_data = await storage.get_json(f"{space_id}/_meta.json")
        if meta_data is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        gm_config = meta_data.get("graph_memory")
        if not gm_config:
            return {
                "status": "error",
                "message": (
                    f"Espace '{space_id}' non connecté à Graph Memory. "
                    f"Utilisez graph_connect d'abord."
                ),
            }

        config = GraphMemoryConfig(**gm_config)
        memory_id = config.memory_id

        # Lire tous les fichiers bank depuis S3
        bank_data = await storage.list_and_get(f"{space_id}/bank/")
        bank_files = {
            bank_relpath(item["key"], space_id): item["content"] for item in bank_data
        }

        if not bank_files:
            return {
                "status": "ok",
                "space_id": space_id,
                "message": "Aucun fichier bank à pousser",
                "pushed": 0,
                "deleted": 0,
                "errors": 0,
            }

        # Connexion à graph-memory
        gm = GraphMemoryClient(config.url, config.token, timeout=180.0)

        try:
            # 1. Lister les documents existants dans graph-memory
            doc_list = await gm.call_tool(
                "document_list",
                {
                    "memory_id": memory_id,
                },
            )
            existing_docs = set()
            if doc_list.get("status") == "ok":
                for doc in doc_list.get("documents", []):
                    existing_docs.add(doc.get("filename", ""))

            logger.info(
                "Push '%s' → '%s' : %d fichiers bank, %d docs existants",
                space_id,
                memory_id,
                len(bank_files),
                len(existing_docs),
            )

            # 2. Construire le batch d'appels (delete + ingest pour chaque fichier)
            calls = []
            call_metadata = []  # Pour tracker quel appel fait quoi

            for filename, content in bank_files.items():
                # Si le document existe → supprimer d'abord
                if filename in existing_docs:
                    calls.append(
                        (
                            "document_delete",
                            {
                                "memory_id": memory_id,
                                "filename": filename,
                            },
                        )
                    )
                    call_metadata.append(("delete", filename))

                # Encoder en base64 et ingérer
                content_bytes = content.encode("utf-8")
                content_b64 = base64.b64encode(content_bytes).decode("ascii")
                calls.append(
                    (
                        "memory_ingest",
                        {
                            "memory_id": memory_id,
                            "content_base64": content_b64,
                            "filename": filename,
                        },
                    )
                )
                call_metadata.append(("ingest", filename))

            # 3. Nettoyage des orphelins
            orphan_docs = existing_docs - set(bank_files.keys())
            for orphan in orphan_docs:
                calls.append(
                    (
                        "document_delete",
                        {
                            "memory_id": memory_id,
                            "filename": orphan,
                        },
                    )
                )
                call_metadata.append(("clean", orphan))

            # 4. Exécuter tout le batch dans une seule session
            results = await gm.call_tools_batch(calls)

            # 5. Analyser les résultats
            pushed = 0
            deleted_before_reingest = 0
            cleaned = 0
            errors = 0
            error_details = []

            for (action, filename), result in zip(call_metadata, results):
                if result.get("status") == "error":
                    if action == "ingest":
                        errors += 1
                        error_details.append(
                            {
                                "filename": filename,
                                "error": result.get("message", ""),
                            }
                        )
                        logger.error(
                            "Échec %s '%s' : %s",
                            action,
                            filename,
                            result.get("message", ""),
                        )
                    else:
                        logger.warning(
                            "Échec %s '%s' : %s",
                            action,
                            filename,
                            result.get("message", ""),
                        )
                else:
                    if action == "ingest":
                        pushed += 1
                        logger.info("Ingéré '%s'", filename)
                    elif action == "delete":
                        deleted_before_reingest += 1
                    elif action == "clean":
                        cleaned += 1
                        logger.info("Nettoyé orphelin '%s'", filename)

        except ConnectionError as e:
            return {
                "status": "error",
                "message": f"Connexion impossible à Graph Memory : {e}",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors du push : {e}",
            }

        duration = round(time.monotonic() - t0, 1)

        # 6. Mettre à jour _meta.json avec les métriques
        now = datetime.now(timezone.utc).isoformat()
        gm_config["last_push"] = now
        gm_config["push_count"] = gm_config.get("push_count", 0) + 1
        gm_config["files_pushed"] = pushed
        meta_data["graph_memory"] = gm_config
        await storage.put_json(f"{space_id}/_meta.json", meta_data)

        result = {
            "status": "ok",
            "space_id": space_id,
            "memory_id": memory_id,
            "pushed": pushed,
            "deleted_before_reingest": deleted_before_reingest,
            "cleaned_orphans": cleaned,
            "errors": errors,
            "duration_seconds": duration,
        }

        if error_details:
            result["error_details"] = error_details

        logger.info(
            "Push terminé '%s' → '%s' : %d poussés, %d nettoyés, %d erreurs (%.1fs)",
            space_id,
            memory_id,
            pushed,
            cleaned,
            errors,
            duration,
        )

        return result

    # ─────────────────────────────────────────────────────────
    # STATUS — Vérifier la connexion et les stats
    # ─────────────────────────────────────────────────────────

    async def status(self, space_id: str) -> dict:
        """
        Vérifie le statut de la connexion graph-memory d'un space.

        Récupère :
        - Statistiques de la mémoire (documents, entités, relations)
        - Liste des documents ingérés avec leurs métadonnées
        - Top entités du graphe de connaissances
        - Historique des pushs

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            {"status": "ok", "connected": bool, "graph_stats": {...},
             "graph_documents": [...], "top_entities": [...], ...}
        """
        storage = get_storage()

        meta_data = await storage.get_json(f"{space_id}/_meta.json")
        if meta_data is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        gm_config = meta_data.get("graph_memory")
        if not gm_config:
            return {
                "status": "ok",
                "space_id": space_id,
                "connected": False,
                "message": "Aucune connexion Graph Memory configurée",
            }

        config = GraphMemoryConfig(**gm_config)

        # Tester la connexion et récupérer les stats + documents
        try:
            gm = GraphMemoryClient(config.url, config.token)

            # Batch : stats + document_list
            results = await gm.call_tools_batch(
                [
                    ("memory_stats", {"memory_id": config.memory_id}),
                    ("document_list", {"memory_id": config.memory_id}),
                ]
            )

            stats = results[0]
            doc_list = results[1]

            graph_stats = None
            top_entities = []
            if stats.get("status") == "ok":
                graph_stats = {
                    "document_count": stats.get("document_count", 0),
                    "entity_count": stats.get("entity_count", 0),
                    "relation_count": stats.get("relation_count", 0),
                }
                top_entities = stats.get("top_entities", [])

            graph_documents = []
            if doc_list.get("status") == "ok":
                for doc in doc_list.get("documents", []):
                    graph_documents.append(
                        {
                            "filename": doc.get("filename", "?"),
                            "entity_count": doc.get("entity_count", 0),
                            "ingested_at": doc.get("ingested_at", ""),
                            "size": doc.get("size_bytes", doc.get("size", 0)),
                        }
                    )

        except ConnectionError as e:
            return {
                "status": "ok",
                "space_id": space_id,
                "connected": True,
                "reachable": False,
                "config": {
                    "url": config.url,
                    "memory_id": config.memory_id,
                    "ontology": config.ontology,
                },
                "last_push": config.last_push,
                "push_count": config.push_count,
                "files_pushed": config.files_pushed,
                "error": str(e),
            }
        except Exception as e:
            return {
                "status": "ok",
                "space_id": space_id,
                "connected": True,
                "reachable": False,
                "config": {
                    "url": config.url,
                    "memory_id": config.memory_id,
                    "ontology": config.ontology,
                },
                "error": str(e),
            }

        return {
            "status": "ok",
            "space_id": space_id,
            "connected": True,
            "reachable": True,
            "config": {
                "url": config.url,
                "memory_id": config.memory_id,
                "ontology": config.ontology,
            },
            "last_push": config.last_push,
            "push_count": config.push_count,
            "files_pushed": config.files_pushed,
            "graph_stats": graph_stats,
            "graph_documents": graph_documents,
            "top_entities": top_entities,
        }

    # ─────────────────────────────────────────────────────────
    # DISCONNECT — Retirer la connexion graph-memory
    # ─────────────────────────────────────────────────────────

    async def disconnect(self, space_id: str) -> dict:
        """
        Déconnecte un space de Graph Memory.

        Retire la configuration graph_memory de _meta.json.
        Ne supprime PAS les données dans graph-memory.

        Args:
            space_id: Identifiant du space live-memory

        Returns:
            {"status": "disconnected", ...}
        """
        storage = get_storage()

        meta_data = await storage.get_json(f"{space_id}/_meta.json")
        if meta_data is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        if "graph_memory" not in meta_data or meta_data["graph_memory"] is None:
            return {
                "status": "ok",
                "message": (f"Espace '{space_id}' n'est pas connecté à Graph Memory"),
            }

        old_config = meta_data["graph_memory"]
        meta_data["graph_memory"] = None
        await storage.put_json(f"{space_id}/_meta.json", meta_data)

        logger.info(
            "Space '%s' déconnecté de Graph Memory '%s'",
            space_id,
            old_config.get("memory_id", ""),
        )

        return {
            "status": "disconnected",
            "space_id": space_id,
            "was_connected_to": {
                "url": old_config.get("url", ""),
                "memory_id": old_config.get("memory_id", ""),
                "push_count": old_config.get("push_count", 0),
            },
        }


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_graph_bridge: GraphBridgeService | None = None


def get_graph_bridge() -> GraphBridgeService:
    """Retourne le singleton GraphBridgeService."""
    global _graph_bridge
    if _graph_bridge is None:
        _graph_bridge = GraphBridgeService()
    return _graph_bridge
