# -*- coding: utf-8 -*-
"""
Service Space — Gestion des espaces mémoire et des notes live.

Ce service encapsule toutes les opérations sur les espaces :
    - CRUD espaces (create, list, info, rules, summary, export, delete)
    - Notes live (write, read, search)

Chaque méthode traduit l'opération en appels S3 via StorageService.
Les outils MCP (tools/space.py, tools/live.py) délèguent ici.

Voir S3_DATA_MODEL.md pour l'arborescence S3 des espaces.
Voir MCP_TOOLS_SPEC.md pour les signatures et retours attendus.
"""

import re
import base64
import tarfile
import io
import hmac
from datetime import datetime, timezone
from typing import Optional

from .storage import get_storage, bank_relpath
from .locks import get_lock_manager
from .models import SpaceMeta, mask_meta_secrets


# ─────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────

# Regex de validation du space_id (alphanumérique + tirets/underscores)
SPACE_ID_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# VULN-07 fix : limites de taille pour les contenus
MAX_RULES_SIZE = 50_000  # 50K caractères max pour les rules
MAX_DESCRIPTION_SIZE = 500  # 500 caractères max pour la description


class SpaceService:
    """
    Service de gestion des espaces mémoire et des notes live.

    Toutes les méthodes sont async et retournent un dict
    avec un champ "status" conforme à la convention MCP.
    """

    # ─────────────────────────────────────────────────────────
    # SPACES — CRUD
    # ─────────────────────────────────────────────────────────

    async def create(
        self,
        space_id: str,
        description: str,
        rules: str,
        owner: str = "",
        creator_token_hash: Optional[str] = None,
    ) -> dict:
        """
        Crée un nouvel espace mémoire avec ses rules.

        Opérations S3 : 4 PUTs (_rules.md, live/.keep, bank/.keep, _meta.json).
        Le meta est écrit en dernier : il matérialise l'existence complète.

        Args:
            space_id: Identifiant unique (alphanum + tirets, max 64 chars)
            description: Description courte de l'espace
            rules: Contenu Markdown des rules (structure de la bank)
            owner: Propriétaire (optionnel, informatif)
            creator_token_hash: preuve technique du créateur (optionnelle pour
                compatibilité bootstrap ; sans elle, la frappe de badge est
                refusée de manière sûre)

        Returns:
            {"status": "created", "space_id": ..., ...} ou erreur
        """
        # Valider le space_id
        if not SPACE_ID_REGEX.match(space_id):
            return {
                "status": "error",
                "message": (
                    f"space_id invalide : '{space_id}'. "
                    "Attendu : alphanumérique + tirets/underscores, 1-64 chars."
                ),
            }

        # VULN-07 fix : valider les tailles des champs
        if len(rules) > MAX_RULES_SIZE:
            return {
                "status": "error",
                "message": f"Rules trop longues ({len(rules)} chars, max {MAX_RULES_SIZE})",
            }
        if description and len(description) > MAX_DESCRIPTION_SIZE:
            return {
                "status": "error",
                "message": f"Description trop longue ({len(description)} chars, max {MAX_DESCRIPTION_SIZE})",
            }

        storage = get_storage()

        # Le même verrou mono-instance protège création, frappe et suppression
        # d'un space. Ainsi deux créations concurrentes ne peuvent pas écraser
        # la preuve du créateur, ni intercaler un badge avec une suppression.
        async with get_lock_manager().consolidation(space_id):
            # Vérifier que l'espace n'existe pas déjà
            if await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "already_exists",
                    "message": f"L'espace '{space_id}' existe déjà",
                }

            # Créer les métadonnées
            now = datetime.now(timezone.utc).isoformat()
            meta = SpaceMeta(
                space_id=space_id,
                description=description,
                owner=owner,
                creator_token_hash=creator_token_hash or None,
                created_at=now,
            )

            # Écrire les constituants avant le marqueur final. Une panne laisse
            # éventuellement des objets orphelins, mais jamais un space que les
            # outils puissent considérer comme créé.
            await storage.put(f"{space_id}/_rules.md", rules)
            await storage.put(f"{space_id}/live/.keep", "")
            await storage.put(f"{space_id}/bank/.keep", "")
            await storage.put_json(f"{space_id}/_meta.json", meta.model_dump())

        return {
            "status": "created",
            "space_id": space_id,
            "description": description,
            "rules_size": len(rules.encode("utf-8")),
            "created_at": now,
        }

    async def caller_is_creator(self, space_id: str, caller_token_hash: Optional[str]) -> bool:
        """Vérifie la seule preuve autorisant la frappe : le hash créateur.

        Les deux valeurs doivent être présentes ; notamment ``None == None``
        ne doit jamais donner au bootstrap un droit implicite sur un space.
        """
        if not caller_token_hash:
            return False

        storage = get_storage()
        async with get_lock_manager().consolidation(space_id):
            meta = await storage.get_json(f"{space_id}/_meta.json")
            stored_hash = meta.get("creator_token_hash") if isinstance(meta, dict) else None
            return bool(
                stored_hash
                and isinstance(stored_hash, str)
                and hmac.compare_digest(stored_hash, caller_token_hash)
            )

    async def ensure_creator_access(
        self, space_id: str, caller_token_hash: Optional[str]
    ) -> dict:
        """Vérifie le créateur et persiste son accès sans interstice.

        L'ordre est toujours space puis tokens : une suppression ou une
        recréation ne peut pas s'intercaler entre la preuve stockée dans le
        meta et l'auto-ajout dans le token du créateur.
        """
        if not caller_token_hash:
            return {"status": "forbidden", "message": "Preuve créateur absente"}

        storage = get_storage()
        async with get_lock_manager().consolidation(space_id):
            meta = await storage.get_json(f"{space_id}/_meta.json")
            stored_hash = meta.get("creator_token_hash") if isinstance(meta, dict) else None
            if not (
                stored_hash
                and isinstance(stored_hash, str)
                and hmac.compare_digest(stored_hash, caller_token_hash)
            ):
                return {
                    "status": "forbidden",
                    "message": "Seul le créateur technique du space peut réparer son accès",
                }

            from .tokens import get_token_service

            return await get_token_service().add_space_to_token(
                token_hash=caller_token_hash,
                space_id=space_id,
            )

    async def mint_badge(
        self, space_id: str, caller_token_hash: Optional[str], client_name: str
    ) -> dict:
        """Frappe un badge sous le verrou du space, après preuve créateur."""
        if not caller_token_hash:
            return {
                "status": "error",
                "message": "Preuve créateur absente : frappe de badge refusée",
            }

        storage = get_storage()
        async with get_lock_manager().consolidation(space_id):
            meta = await storage.get_json(f"{space_id}/_meta.json")
            stored_hash = meta.get("creator_token_hash") if isinstance(meta, dict) else None
            if not (
                stored_hash
                and isinstance(stored_hash, str)
                and hmac.compare_digest(stored_hash, caller_token_hash)
            ):
                return {
                    "status": "error",
                    "message": "Seul le créateur technique du space peut frapper un badge",
                }

            # Ordre de verrou unique : space puis tokens. Voir delete().
            from .tokens import get_token_service

            return await get_token_service().mint_space_badge(space_id, client_name)

    async def update(
        self,
        space_id: str,
        description: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> dict:
        """
        Met à jour les métadonnées d'un espace existant.

        Seuls les champs fournis (non-None) sont modifiés.
        Les rules restent immuables.

        Opérations S3 : GET _meta.json + PUT _meta.json

        Args:
            space_id: Identifiant de l'espace
            description: Nouvelle description (None = pas de changement)
            owner: Nouveau propriétaire (None = pas de changement)

        Returns:
            {"status": "ok", "space_id": ..., "updated_fields": [...]}
        """
        storage = get_storage()

        # Lire les métadonnées existantes
        meta = await storage.get_json(f"{space_id}/_meta.json")
        if meta is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Appliquer les modifications
        updated_fields = []
        if description is not None:
            meta["description"] = description
            updated_fields.append("description")
        if owner is not None:
            meta["owner"] = owner
            updated_fields.append("owner")

        if not updated_fields:
            return {
                "status": "ok",
                "space_id": space_id,
                "message": "Aucun champ à modifier",
                "updated_fields": [],
            }

        # Écrire les métadonnées mises à jour
        await storage.put_json(f"{space_id}/_meta.json", meta)

        return {
            "status": "ok",
            "space_id": space_id,
            "updated_fields": updated_fields,
            "description": meta.get("description", ""),
            "owner": meta.get("owner", ""),
        }

    async def update_rules(self, space_id: str, rules: str) -> dict:
        """
        Met à jour les rules d'un espace existant (admin only).

        ⚠️ Les rules sont normalement immuables. Cet outil permet de les
        mettre à jour sans devoir supprimer/recréer l'espace.

        Opérations S3 : GET _meta.json (vérif existence) + PUT _rules.md

        Args:
            space_id: Identifiant de l'espace
            rules: Nouveau contenu Markdown des rules

        Returns:
            {"status": "ok", "space_id": ..., "rules_size": N}
        """
        # Valider la taille
        if len(rules) > MAX_RULES_SIZE:
            return {
                "status": "error",
                "message": f"Rules trop longues ({len(rules)} chars, max {MAX_RULES_SIZE})",
            }

        if not rules.strip():
            return {
                "status": "error",
                "message": "Le contenu des rules ne peut pas être vide",
            }

        storage = get_storage()

        # Vérifier que l'espace existe
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Écrire les nouvelles rules
        await storage.put(f"{space_id}/_rules.md", rules)

        return {
            "status": "ok",
            "space_id": space_id,
            "rules_size": len(rules.encode("utf-8")),
            "message": f"Rules mises à jour ({len(rules.encode('utf-8'))} octets)",
        }

    async def list_spaces(self, allowed_space_ids: Optional[list[str]] = None) -> dict:
        """
        Liste tous les espaces accessibles.

        Opérations S3 : LIST préfixes racine + N GETs _meta.json

        Args:
            allowed_space_ids: Liste des space_ids autorisés (None = tous)

        Returns:
            {"status": "ok", "spaces": [...], "total": N}
        """
        storage = get_storage()

        # Lister les préfixes racine (chaque espace = un préfixe)
        prefixes = await storage.list_prefixes("")

        spaces = []
        for prefix in prefixes:
            # Exclure les préfixes système (_system/, _backups/)
            if prefix.startswith("_"):
                continue

            # Extraire le space_id (retirer le / final)
            sid = prefix.rstrip("/")

            # Filtrer par permissions du token
            if allowed_space_ids is not None and sid not in allowed_space_ids:
                continue

            # Lire les métadonnées
            meta = await storage.get_json(f"{sid}/_meta.json")
            if meta is None:
                continue  # Préfixe sans _meta.json → pas un espace valide

            # Compter les notes live et fichiers bank
            live_objects = await storage.list_objects(f"{sid}/live/")
            bank_objects = await storage.list_objects(f"{sid}/bank/")
            live_count = len(
                [o for o in live_objects if not o["Key"].endswith(".keep")]
            )
            bank_count = len(
                [o for o in bank_objects if not o["Key"].endswith(".keep")]
            )

            spaces.append(
                {
                    "space_id": sid,
                    "description": meta.get("description", ""),
                    "owner": meta.get("owner", ""),
                    "created_at": meta.get("created_at", ""),
                    "live_notes_count": live_count,
                    "bank_files_count": bank_count,
                }
            )

        return {"status": "ok", "spaces": spaces, "total": len(spaces)}

    async def get_info(self, space_id: str) -> dict:
        """
        Informations détaillées sur un espace.

        Opérations S3 : GET _meta.json + LIST live/* + LIST bank/*

        Args:
            space_id: Identifiant de l'espace

        Returns:
            {"status": "ok", "space_id": ..., "live": {...}, "bank": {...}}
        """
        storage = get_storage()

        # Lire les métadonnées
        meta = await storage.get_json(f"{space_id}/_meta.json")
        if meta is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Stats des notes live
        live_objects = await storage.list_objects(f"{space_id}/live/")
        live_files = [o for o in live_objects if not o["Key"].endswith(".keep")]

        # Stats des fichiers bank
        bank_objects = await storage.list_objects(f"{space_id}/bank/")
        bank_files = [o for o in bank_objects if not o["Key"].endswith(".keep")]

        # Vérifier l'existence de la synthèse
        synthesis_exists = await storage.exists(f"{space_id}/_synthesis.md")

        from .consolidation_queue import get_consolidation_queue

        consolidation_queue = await get_consolidation_queue().get_space_summary(
            space_id
        )

        return {
            "status": "ok",
            "space_id": space_id,
            "description": meta.get("description", ""),
            "owner": meta.get("owner", ""),
            "created_at": meta.get("created_at", ""),
            "live": {
                "notes_count": len(live_files),
                "total_size": sum(o["Size"] for o in live_files),
            },
            "bank": {
                "files_count": len(bank_files),
                "total_size": sum(o["Size"] for o in bank_files),
                "files": [bank_relpath(o["Key"], space_id) for o in bank_files],
            },
            "last_consolidation": meta.get("last_consolidation"),
            "consolidation_count": meta.get("consolidation_count", 0),
            "consolidation_queue": consolidation_queue,
            "synthesis_exists": synthesis_exists,
        }

    async def get_rules(self, space_id: str) -> dict:
        """
        Lit les rules immuables de l'espace.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            {"status": "ok", "rules": "..."} ou not_found
        """
        storage = get_storage()
        rules = await storage.get(f"{space_id}/_rules.md")
        if rules is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        return {"status": "ok", "space_id": space_id, "rules": rules}

    async def get_summary(self, space_id: str) -> dict:
        """
        Synthèse complète : info + rules + bank. L'outil de démarrage des agents.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Dict combinant info, rules et contenu bank complet
        """
        storage = get_storage()

        # Lire meta + rules
        meta = await storage.get_json(f"{space_id}/_meta.json")
        if meta is None:
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        rules = await storage.get(f"{space_id}/_rules.md") or ""

        # Lire tous les fichiers bank
        bank_data = await storage.list_and_get(f"{space_id}/bank/")
        bank_files = [
            {
                "filename": bank_relpath(item["key"], space_id),
                "content": item["content"],
                "size": item["size"],
            }
            for item in bank_data
        ]

        # Lire la synthèse si elle existe
        synthesis = await storage.get(f"{space_id}/_synthesis.md")

        return {
            "status": "ok",
            "space_id": space_id,
            "description": meta.get("description", ""),
            "rules": rules,
            "bank_files": bank_files,
            "bank_file_count": len(bank_files),
            "synthesis": synthesis,
        }

    async def export_space(self, space_id: str) -> dict:
        """
        Exporte un espace complet en archive tar.gz (base64).

        Le ``_meta.json`` inclus dans l'archive est masqué avant ajout au tar.
        S'il est illisible, l'archive contient un objet vide plutôt que ses
        octets bruts : elle n'expose alors ni token Graph ni hash créateur.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            {"status": "ok", "archive_base64": "...", "files_count": N}
        """
        import json as _json

        storage = get_storage()

        # Vérifier l'existence
        if not await storage.exists(f"{space_id}/_meta.json"):
            return {
                "status": "not_found",
                "message": f"Espace '{space_id}' introuvable",
            }

        # Lire tous les fichiers de l'espace
        all_objects = await storage.list_and_get(f"{space_id}/", exclude_keep=False)

        # Créer l'archive tar.gz en mémoire
        buf = io.BytesIO()
        meta_key = f"{space_id}/_meta.json"
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for obj in all_objects:
                # Nom relatif dans l'archive (sans le space_id/ prefix)
                arcname = obj["key"][len(space_id) + 1 :]
                content = obj["content"]

                # LM2-03 fix : masquer les secrets dans _meta.json avant export
                if obj["key"] == meta_key:
                    try:
                        meta_raw = _json.loads(content)
                        meta_masked = mask_meta_secrets(meta_raw)
                        content = _json.dumps(
                            meta_masked, indent=2, ensure_ascii=False
                        )
                    except (_json.JSONDecodeError, TypeError):
                        # Ne jamais exporter un meta brut non parsable : il
                        # peut contenir un secret que le masquage ne voit pas.
                        content = "{}"

                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=arcname)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        archive_bytes = buf.getvalue()

        return {
            "status": "ok",
            "space_id": space_id,
            "archive_base64": base64.b64encode(archive_bytes).decode("ascii"),
            "archive_size": len(archive_bytes),
            "files_count": len(all_objects),
        }

    async def delete(self, space_id: str) -> dict:
        """
        Supprime un espace et TOUTES ses données (irréversible).

        Args:
            space_id: Identifiant de l'espace

        Returns:
            {"status": "deleted", "files_deleted": N}
        """
        storage = get_storage()

        async with get_lock_manager().consolidation(space_id):
            # Vérifier l'existence
            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            # Fail closed : persister la révocation AVANT toute suppression
            # S3. Une suppression partielle peut laisser un space inerte mais
            # ne doit jamais laisser un badge vivant réutilisable après une
            # recréation du même identifiant.
            from .tokens import get_token_service

            badge_result = await get_token_service().revoke_space_badges(space_id)
            if badge_result.get("status") != "ok":
                return badge_result

            # Lister TOUS les fichiers de l'espace
            all_objects = await storage.list_objects(f"{space_id}/")
            all_keys = [o["Key"] for o in all_objects]

            # Supprimer en batch
            deleted = await storage.delete_many(all_keys)

        return {
            "status": "deleted",
            "space_id": space_id,
            "files_deleted": deleted,
            "badges_revoked": badge_result["revoked"],
        }


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_space_service: SpaceService | None = None


def get_space_service() -> SpaceService:
    """Retourne le singleton SpaceService."""
    global _space_service
    if _space_service is None:
        _space_service = SpaceService()
    return _space_service
