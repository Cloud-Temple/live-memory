# -*- coding: utf-8 -*-
"""
Service Backup — Sauvegarde et restauration d'espaces.

Les backups sont des snapshots complets stockés dans _backups/ sur S3.
Chaque backup copie tous les fichiers d'un espace dans un sous-dossier
horodaté.

Architecture :
    tools/backup.py → BackupService (ce fichier) → StorageService (S3)

Arborescence S3 :
    _backups/{space_id}/{timestamp}/
        ├── _meta.json
        ├── _rules.md
        ├── _synthesis.md
        ├── bank/...
        └── live/...

Voir S3_DATA_MODEL.md pour les détails.
"""

import base64
import io
import json as _json
import tarfile
from datetime import datetime, timezone

from .storage import get_storage
from .models import mask_meta_secrets


class BackupService:
    """
    Service de sauvegarde et restauration d'espaces mémoire.
    """

    async def create(self, space_id: str, description: str = "") -> dict:
        """
        Crée un snapshot complet de l'espace sur S3.

        Copie tous les fichiers de {space_id}/ vers _backups/{space_id}/{timestamp}/.

        Args:
            space_id: Espace à sauvegarder
            description: Description du backup (optionnel)

        Returns:
            {"status": "created", "backup_id": "...", ...}
        """
        storage = get_storage()

        # Vérifier l'existence de l'espace
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Générer le timestamp pour le backup
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H-%M-%S")
        backup_prefix = f"_backups/{space_id}/{ts}/"
        backup_id = f"{space_id}/{ts}"

        # Lister et copier tous les fichiers
        objects = await storage.list_objects(f"{space_id}/")
        total_size = 0

        for obj in objects:
            source_key = obj["Key"]
            # Chemin relatif dans l'espace
            relative = source_key[len(space_id) + 1 :]
            dest_key = backup_prefix + relative

            await storage.copy_object(source_key, dest_key)
            total_size += obj["Size"]

        return {
            "status": "created",
            "backup_id": backup_id,
            "space_id": space_id,
            "timestamp": now.isoformat(),
            "description": description,
            "files_backed_up": len(objects),
            "total_size": total_size,
        }

    async def create_all(self, description: str = "") -> dict:
        """
        Crée un snapshot de TOUS les espaces (admin only).

        Liste tous les espaces existants et crée un backup pour chacun.
        Les erreurs sur un espace n'empêchent pas le backup des suivants.

        Args:
            description: Description commune pour tous les backups

        Returns:
            {"status": "ok", "spaces_backed_up": N, "spaces_failed": N, "details": [...]}
        """
        storage = get_storage()

        # Lister tous les espaces (préfixes de premier niveau avec _meta.json)
        # On utilise list_prefixes pour trouver les espaces
        all_prefixes = await storage.list_prefixes("", delimiter="/")

        # Filtrer : garder seulement les espaces réels (pas _backups, _system)
        space_ids = []
        for prefix in all_prefixes:
            sid = prefix.rstrip("/")
            if sid.startswith("_"):
                continue
            # Vérifier que c'est un vrai espace (a un _meta.json)
            if await storage.exists(f"{sid}/_meta.json"):
                space_ids.append(sid)

        if not space_ids:
            return {
                "status": "ok",
                "message": "Aucun espace trouvé",
                "spaces_backed_up": 0,
                "spaces_failed": 0,
                "details": [],
            }

        # Backup chaque espace
        details = []
        spaces_ok = 0
        spaces_failed = 0

        for sid in sorted(space_ids):
            try:
                result = await self.create(sid, description)
                if result.get("status") == "created":
                    spaces_ok += 1
                    details.append(
                        {
                            "space_id": sid,
                            "status": "created",
                            "backup_id": result.get("backup_id", ""),
                            "files": result.get("files_backed_up", 0),
                            "size": result.get("total_size", 0),
                        }
                    )
                else:
                    spaces_failed += 1
                    details.append(
                        {
                            "space_id": sid,
                            "status": "error",
                            "message": result.get("message", "?"),
                        }
                    )
            except Exception as e:
                spaces_failed += 1
                details.append(
                    {
                        "space_id": sid,
                        "status": "error",
                        "message": str(e),
                    }
                )

        return {
            "status": "ok",
            "spaces_total": len(space_ids),
            "spaces_backed_up": spaces_ok,
            "spaces_failed": spaces_failed,
            "details": details,
        }

    async def list_backups(self, space_id: str = "") -> dict:
        """
        Liste les backups disponibles.

        Args:
            space_id: Filtrer par espace (vide = tous)

        Returns:
            {"status": "ok", "backups": [...], "total": N}
        """
        storage = get_storage()

        prefix = f"_backups/{space_id}/" if space_id else "_backups/"
        prefixes = await storage.list_prefixes(prefix, delimiter="/")

        backups = []
        if space_id:
            # Lister les timestamps pour cet espace
            for p in prefixes:
                parts = p.rstrip("/").split("/")
                ts = parts[-1] if len(parts) >= 3 else "?"
                backups.append(
                    {
                        "backup_id": f"{space_id}/{ts}",
                        "space_id": space_id,
                        "timestamp": ts,
                    }
                )
        else:
            # Lister les espaces qui ont des backups
            space_prefixes = await storage.list_prefixes("_backups/", delimiter="/")
            for sp in space_prefixes:
                sid = sp.rstrip("/").split("/")[-1]
                ts_prefixes = await storage.list_prefixes(sp, delimiter="/")
                for tp in ts_prefixes:
                    ts = tp.rstrip("/").split("/")[-1]
                    backups.append(
                        {
                            "backup_id": f"{sid}/{ts}",
                            "space_id": sid,
                            "timestamp": ts,
                        }
                    )

        return {"status": "ok", "backups": backups, "total": len(backups)}

    async def restore(self, backup_id: str) -> dict:
        """
        Restaure un espace depuis un backup.

        L'espace NE DOIT PAS exister (supprimer d'abord).

        Args:
            backup_id: Format "space_id/timestamp"

        Returns:
            {"status": "ok", "files_restored": N}
        """
        storage = get_storage()

        # Parser le backup_id
        parts = backup_id.split("/", 1)
        if len(parts) != 2:
            return {
                "status": "error",
                "message": "backup_id invalide (format: space_id/timestamp)",
            }

        space_id, timestamp = parts
        backup_prefix = f"_backups/{space_id}/{timestamp}/"

        # Vérifier que le backup existe
        backup_objects = await storage.list_objects(backup_prefix)
        if not backup_objects:
            return {
                "status": "not_found",
                "message": f"Backup '{backup_id}' introuvable",
            }

        # Vérifier que l'espace N'existe PAS
        if await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "error",
                "message": f"L'espace '{space_id}' existe déjà. Supprimez-le d'abord.",
            }

        # Copier tous les fichiers du backup vers l'espace
        for obj in backup_objects:
            source_key = obj["Key"]
            relative = source_key[len(backup_prefix) :]
            dest_key = f"{space_id}/{relative}"
            await storage.copy_object(source_key, dest_key)

        return {
            "status": "ok",
            "backup_id": backup_id,
            "space_id": space_id,
            "files_restored": len(backup_objects),
        }

    async def download(self, backup_id: str) -> dict:
        """
        Télécharge un backup en archive tar.gz (base64).

        LM2-03 fix : si l'archive contient un ``_meta.json``, le token
        Graph Memory est masqué avant ajout au tar (mêmes garanties
        que ``space_export``). L'archive téléchargée n'expose donc plus
        le secret stocké en clair sur S3.

        Args:
            backup_id: Format "space_id/timestamp"

        Returns:
            {"status": "ok", "archive_base64": "...", ...}
        """
        storage = get_storage()

        parts = backup_id.split("/", 1)
        if len(parts) != 2:
            return {"status": "error", "message": "backup_id invalide"}

        space_id, timestamp = parts
        backup_prefix = f"_backups/{space_id}/{timestamp}/"

        all_objects = await storage.list_and_get(backup_prefix, exclude_keep=False)
        if not all_objects:
            return {
                "status": "not_found",
                "message": f"Backup '{backup_id}' introuvable",
            }

        # Créer l'archive tar.gz
        buf = io.BytesIO()
        meta_key = f"{backup_prefix}_meta.json"
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for obj in all_objects:
                arcname = obj["key"][len(backup_prefix) :]
                content = obj["content"]

                # LM2-03 fix : masquer le token GM dans _meta.json avant export
                if obj["key"] == meta_key:
                    try:
                        meta_raw = _json.loads(content)
                        meta_masked = mask_meta_secrets(meta_raw)
                        content = _json.dumps(
                            meta_masked, indent=2, ensure_ascii=False
                        )
                    except (_json.JSONDecodeError, TypeError):
                        # Best-effort : on n'écrit pas en clair si parse échoue
                        # → on remplace par un meta vide protecteur.
                        content = "{}"

                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=arcname)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        archive_bytes = buf.getvalue()

        return {
            "status": "ok",
            "backup_id": backup_id,
            "archive_base64": base64.b64encode(archive_bytes).decode("ascii"),
            "archive_size": len(archive_bytes),
            "files_count": len(all_objects),
        }

    async def delete(self, backup_id: str) -> dict:
        """
        Supprime un backup.

        Args:
            backup_id: Format "space_id/timestamp"

        Returns:
            {"status": "deleted", "files_deleted": N}
        """
        storage = get_storage()

        parts = backup_id.split("/", 1)
        if len(parts) != 2:
            return {"status": "error", "message": "backup_id invalide"}

        space_id, timestamp = parts
        backup_prefix = f"_backups/{space_id}/{timestamp}/"

        objects = await storage.list_objects(backup_prefix)
        if not objects:
            return {
                "status": "not_found",
                "message": f"Backup '{backup_id}' introuvable",
            }

        keys = [o["Key"] for o in objects]
        deleted = await storage.delete_many(keys)

        return {
            "status": "deleted",
            "backup_id": backup_id,
            "files_deleted": deleted,
        }


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_backup_service: BackupService | None = None


def get_backup_service() -> BackupService:
    """Retourne le singleton BackupService."""
    global _backup_service
    if _backup_service is None:
        _backup_service = BackupService()
    return _backup_service
