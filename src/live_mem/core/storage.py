# -*- coding: utf-8 -*-
"""
Service S3 — Couche d'abstraction stockage pour Live Memory.

Gère la communication avec le S3 Cloud Temple (Dell ECS) en utilisant
une configuration HYBRIDE obligatoire :
  - SigV2 (signature legacy) pour PUT/GET/DELETE (données)
  - SigV4 (signature moderne) pour HEAD/LIST (métadonnées)

Voir CLOUD_TEMPLE_SERVICES.md pour les détails techniques.

Toutes les opérations sont wrappées dans run_in_executor car boto3
est synchrone — on ne veut pas bloquer l'event loop asyncio.

Usage :
    from .storage import get_storage
    storage = get_storage()

    await storage.put("spaces/my-space/_meta.json", '{"space_id": "my-space"}')
    content = await storage.get("spaces/my-space/_meta.json")
    objects = await storage.list_objects("spaces/my-space/live/")
    await storage.delete("spaces/my-space/live/old-note.md")
"""

import json
import asyncio
from typing import Optional
from functools import partial

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..config import get_settings

import logging

logger = logging.getLogger("live_mem.storage")


class StorageService:
    """
    Service S3 avec dual client SigV2/SigV4 pour Dell ECS Cloud Temple.

    Attributes:
        bucket: Nom du bucket S3
        _client_v2: Client boto3 en signature V2 (PUT/GET/DELETE)
        _client_v4: Client boto3 en signature V4 (HEAD/LIST)
    """

    def __init__(self):
        settings = get_settings()

        self.bucket = settings.s3_bucket_name
        self._endpoint = settings.s3_endpoint_url

        # ── Proxy HTTP sortant (optionnel) ────────────────────
        # Utilise PROXY_URL (variable custom) plutôt que HTTP_PROXY/HTTPS_PROXY
        # pour éviter d'affecter toutes les libs Python qui lisent les vars d'env OS.
        proxy_url = settings.proxy_url
        # Format botocore/requests : {"http": url, "https": url}
        _proxies: dict[str, str] | None = (
            {"http": proxy_url, "https": proxy_url} if proxy_url else None
        )

        # ── Client SigV2 — pour PUT/GET/DELETE (données) ──────
        # Dell ECS exige SigV2 pour les opérations de données,
        # sinon on obtient XAmzContentSHA256Mismatch.
        config_v2 = Config(
            region_name=settings.s3_region_name,
            signature_version="s3",  # SigV2 legacy
            s3={"addressing_style": "path"},  # Path-style obligatoire CT
            retries={"max_attempts": 3, "mode": "adaptive"},
            **({"proxies": _proxies} if _proxies else {}),
        )
        self._client_v2 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=config_v2,
        )

        # ── Client SigV4 — pour HEAD/LIST (métadonnées) ──────
        # Dell ECS exige SigV4 pour HEAD bucket et LIST objects,
        # sinon on obtient 403 Forbidden ou SignatureDoesNotMatch.
        config_v4 = Config(
            region_name=settings.s3_region_name,
            signature_version="s3v4",
            s3={
                "addressing_style": "path",  # Path-style obligatoire CT
                "payload_signing_enabled": False,  # Optimisation Dell ECS
            },
            retries={"max_attempts": 3, "mode": "adaptive"},
            **({"proxies": _proxies} if _proxies else {}),
        )
        self._client_v4 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=config_v4,
        )

        logger.info(
            "StorageService initialisé — bucket=%s endpoint=%s",
            self.bucket,
            self._endpoint,
        )
        if proxy_url:
            logger.info("StorageService: S3 requests via proxy %s", proxy_url)

    # ─────────────────────────────────────────────────────────────
    # Helpers async — wrappent les appels synchrones boto3
    # ─────────────────────────────────────────────────────────────

    async def _run(self, func, *args, **kwargs):
        """Exécute une fonction synchrone dans un thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    # ─────────────────────────────────────────────────────────────
    # PUT — Écriture (SigV2)
    # ─────────────────────────────────────────────────────────────

    async def put(
        self, key: str, content: str, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        """
        Écrit un objet sur S3.

        Args:
            key: Clé S3 (ex: "spaces/my-space/_meta.json")
            content: Contenu texte à écrire
            content_type: Type MIME (défaut: text/plain)
        """
        await self._run(
            self._client_v2.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )

    async def put_json(self, key: str, data: dict) -> None:
        """
        Écrit un objet JSON sur S3.

        Args:
            key: Clé S3
            data: Dictionnaire à sérialiser en JSON
        """
        content = json.dumps(data, indent=2, ensure_ascii=False)
        await self.put(key, content, content_type="application/json")

    # ─────────────────────────────────────────────────────────────
    # GET — Lecture (SigV2)
    # ─────────────────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[str]:
        """
        Lit un objet depuis S3.

        Args:
            key: Clé S3

        Returns:
            Contenu texte de l'objet, ou None si l'objet n'existe pas
        """
        try:
            response = await self._run(
                self._client_v2.get_object,
                Bucket=self.bucket,
                Key=key,
            )
            # response['Body'] est un StreamingBody, on le lit dans l'executor
            body = await self._run(response["Body"].read)
            return body.decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    async def get_json(self, key: str) -> Optional[dict]:
        """
        Lit un objet JSON depuis S3.

        Args:
            key: Clé S3

        Returns:
            Dictionnaire désérialisé, ou None si l'objet n'existe pas
        """
        content = await self.get(key)
        if content is None:
            return None
        return json.loads(content)

    # ─────────────────────────────────────────────────────────────
    # DELETE — Suppression (SigV2)
    # ─────────────────────────────────────────────────────────────

    async def delete(self, key: str) -> None:
        """
        Supprime un objet sur S3.

        Args:
            key: Clé S3
        """
        await self._run(
            self._client_v2.delete_object,
            Bucket=self.bucket,
            Key=key,
        )

    async def delete_many(self, keys: list[str]) -> int:
        """
        Supprime plusieurs objets un par un.

        Note : Dell ECS ne supporte pas delete_objects (batch) avec SigV2.
        On utilise des suppressions individuelles qui fonctionnent.

        Args:
            keys: Liste des clés S3 à supprimer

        Returns:
            Nombre d'objets supprimés
        """
        if not keys:
            return 0

        deleted = 0
        for key in keys:
            try:
                await self.delete(key)
                deleted += 1
            except Exception as e:
                # VULN-13 fix : logger les erreurs au lieu de les ignorer
                logger.warning("delete_many: échec suppression '%s': %s", key, e)

        return deleted

    # ─────────────────────────────────────────────────────────────
    # LIST — Listage (SigV4)
    # ─────────────────────────────────────────────────────────────

    async def list_objects(self, prefix: str, max_keys: int = 0) -> list[dict]:
        """
        Liste les objets sous un préfixe S3, avec pagination automatique.

        Args:
            prefix: Préfixe S3 (ex: "spaces/my-space/live/")
            max_keys: Nombre max d'objets à retourner (0 = tous)

        Returns:
            Liste de dicts avec 'Key', 'Size', 'LastModified' pour chaque objet
        """
        all_objects = []
        continuation_token = None

        while True:
            params = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = await self._run(
                self._client_v4.list_objects_v2,
                **params,
            )

            contents = response.get("Contents", [])
            for obj in contents:
                all_objects.append(
                    {
                        "Key": obj["Key"],
                        "Size": obj.get("Size", 0),
                        "LastModified": obj.get("LastModified", ""),
                    }
                )

                # Limite atteinte ?
                if max_keys > 0 and len(all_objects) >= max_keys:
                    return all_objects[:max_keys]

            # Pagination : continuer si tronqué
            if not response.get("IsTruncated", False):
                break
            continuation_token = response.get("NextContinuationToken")

        return all_objects

    async def list_prefixes(self, prefix: str, delimiter: str = "/") -> list[str]:
        """
        Liste les "dossiers" (préfixes communs) sous un préfixe S3.

        Utile pour lister les espaces (chaque espace = un préfixe top-level).

        Args:
            prefix: Préfixe S3 (ex: "" pour la racine)
            delimiter: Délimiteur (défaut: '/')

        Returns:
            Liste des préfixes communs (ex: ["space-alpha/", "space-beta/"])
        """
        all_prefixes = []
        continuation_token = None

        while True:
            params = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "Delimiter": delimiter,
                "MaxKeys": 1000,
            }
            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = await self._run(
                self._client_v4.list_objects_v2,
                **params,
            )

            common_prefixes = response.get("CommonPrefixes", [])
            for cp in common_prefixes:
                all_prefixes.append(cp["Prefix"])

            if not response.get("IsTruncated", False):
                break
            continuation_token = response.get("NextContinuationToken")

        return all_prefixes

    # ─────────────────────────────────────────────────────────────
    # HEAD — Existence (SigV4)
    # ─────────────────────────────────────────────────────────────

    async def exists(self, key: str) -> bool:
        """
        Vérifie si un objet existe sur S3.

        Args:
            key: Clé S3

        Returns:
            True si l'objet existe, False sinon
        """
        try:
            await self._run(
                self._client_v4.head_object,
                Bucket=self.bucket,
                Key=key,
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    # ─────────────────────────────────────────────────────────────
    # Opérations composées
    # ─────────────────────────────────────────────────────────────

    async def list_and_get(self, prefix: str, exclude_keep: bool = True) -> list[dict]:
        """
        Liste et lit tous les objets sous un préfixe.

        Utile pour charger toutes les notes live ou tous les fichiers bank.

        Args:
            prefix: Préfixe S3
            exclude_keep: Exclure les fichiers sentinelles .keep (défaut: True)

        Returns:
            Liste de dicts {'key': str, 'content': str, 'size': int, 'last_modified': str}
        """
        objects = await self.list_objects(prefix)
        results = []

        for obj in objects:
            key = obj["Key"]

            # Exclure les sentinelles
            if exclude_keep and key.endswith(".keep"):
                continue

            content = await self.get(key)
            if content is not None:
                results.append(
                    {
                        "key": key,
                        "content": content,
                        "size": obj["Size"],
                        "last_modified": str(obj.get("LastModified", "")),
                    }
                )

        return results

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        """
        Copie un objet S3 d'une clé à une autre (même bucket).

        Utile pour les backups.

        Args:
            source_key: Clé source
            dest_key: Clé destination
        """
        copy_source = {"Bucket": self.bucket, "Key": source_key}
        await self._run(
            self._client_v2.copy_object,
            CopySource=copy_source,
            Bucket=self.bucket,
            Key=dest_key,
        )

    # ─────────────────────────────────────────────────────────────
    # Test de connexion
    # ─────────────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """
        Teste la connexion au bucket S3.

        Utilise HEAD bucket (SigV4) pour vérifier l'accès.

        Returns:
            {"status": "ok", "bucket": "...", "latency_ms": ...} ou erreur
        """
        import time

        t0 = time.monotonic()
        try:
            await self._run(
                self._client_v4.head_bucket,
                Bucket=self.bucket,
            )
            latency = round((time.monotonic() - t0) * 1000, 1)
            return {
                "status": "ok",
                "bucket": self.bucket,
                "latency_ms": latency,
            }
        except ClientError as e:
            latency = round((time.monotonic() - t0) * 1000, 1)
            return {
                "status": "error",
                "bucket": self.bucket,
                "message": str(e),
                "latency_ms": latency,
            }
        except Exception as e:
            return {
                "status": "error",
                "bucket": self.bucket,
                "message": str(e),
            }


# =============================================================================
# Utilitaires pour les chemins bank
# =============================================================================


def bank_relpath(s3_key: str, space_id: str) -> str:
    """
    Extrait le chemin relatif d'un fichier bank depuis sa clé S3 complète.

    La bank supporte les sous-dossiers (v0.9.0). Le "filename" d'un fichier
    bank est son chemin relatif depuis {space_id}/bank/, pas juste le basename.

    Exemples :
        bank_relpath("presales/bank/acheteur.md", "presales")
            → "acheteur.md"
        bank_relpath("presales/bank/personaProfiles/acheteur.md", "presales")
            → "personaProfiles/acheteur.md"
        bank_relpath("presales/bank/1.MEMORY_BANK/foo.md", "presales")
            → "1.MEMORY_BANK/foo.md"

    Args:
        s3_key: Clé S3 complète du fichier
        space_id: Identifiant de l'espace

    Returns:
        Chemin relatif depuis le dossier bank/
    """
    prefix = f"{space_id}/bank/"
    if s3_key.startswith(prefix):
        relpath = s3_key[len(prefix) :]
        if relpath:
            return relpath
    # Fallback : juste le dernier segment (rétrocompat)
    return s3_key.split("/")[-1]


# =============================================================================
# Singleton
# =============================================================================

_storage: StorageService | None = None


def get_storage() -> StorageService:
    """Retourne le singleton StorageService."""
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
