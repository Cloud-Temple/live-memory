# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Bank (8 outils).

Memory Bank consolidée : lire, lister, consolider via LLM, compacter,
réparer, écrire et supprimer manuellement.

Permissions :
    - bank_read        🔑 (read)    — Lit un fichier bank spécifique
    - bank_read_all    🔑 (read)    — Lit toute la bank (démarrage agent)
    - bank_list        🔑 (read)    — Liste les fichiers bank (sans contenu)
    - bank_consolidate ✏️ (write)   — Déclenche la consolidation LLM
    - bank_compact     🔧 (manage)  — Compacte les fichiers bank surdimensionnés via LLM
    - bank_repair      🔧 (manage)  — Répare les noms de fichiers corrompus par le LLM
    - bank_write       🔧 (manage)  — Écrit/remplace un fichier bank directement
    - bank_delete      🔧 (manage)  — Supprime un fichier bank

La consolidation est l'opération qui transforme les notes live en
fichiers bank structurés. Un seul consolidate à la fois par espace
(protégé par asyncio.Lock).

Voir CONSOLIDATION_LLM.md pour le pipeline détaillé.
"""

import re
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


# LM2-12 fix : caractères interdits dans les noms de fichiers bank.
# Le sanitize Unicode existant ne couvrait que les chars invisibles.
# Ces caractères-ci permettent un XSS persistant côté web (LM2-01) si
# un opérateur compromis écrit un fichier nommé `<img src=x onerror=...>`.
# La règle s'applique au filename ENTIER (y compris les sous-dossiers).
# Les `/` restent autorisés comme séparateurs de sous-dossiers (Option B v0.9.0).
_BANK_FILENAME_DANGEROUS = re.compile(r"[<>\"'\\\x00-\x1f\x7f]")


def _validate_bank_filename(filename: str) -> dict | None:
    """
    LM2-12 fix : refuse les filenames bank contenant des caractères dangereux.

    Retourne None si OK, sinon un dict d'erreur prêt à être renvoyé.
    """
    if not filename or not filename.strip():
        return {"status": "error", "message": "Nom de fichier requis"}
    if ".." in filename:
        return {
            "status": "error",
            "message": "Nom de fichier invalide : '..' interdit",
        }
    if filename.startswith("/"):
        return {
            "status": "error",
            "message": "Nom de fichier invalide : ne peut pas commencer par '/'",
        }
    if _BANK_FILENAME_DANGEROUS.search(filename):
        return {
            "status": "error",
            "message": (
                "Caractères dangereux dans le nom de fichier "
                "(< > \" ' \\ ou caractères de contrôle interdits)"
            ),
        }
    return None


def register(mcp: FastMCP) -> int:
    """
    Enregistre les 8 outils bank sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (8)
    """

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_read(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
        filename: Annotated[
            str,
            Field(
                description="Nom du fichier bank (ex: 'activeContext.md', 'progress.md')"
            ),
        ],
    ) -> dict:
        """
        Lit un fichier spécifique de la Memory Bank.

        Les fichiers bank sont du Markdown pur, créés et maintenus
        par le LLM lors de la consolidation.

        Inclut un fallback Unicode : si la clé directe n'existe pas,
        scanne les vraies clés S3 et cherche par correspondance sanitisée.
        Cela résout le problème des fichiers avec des caractères Unicode
        invisibles dans le nom.

        Args:
            space_id: Identifiant de l'espace
            filename: Nom du fichier (ex: "activeContext.md")

        Returns:
            Contenu du fichier, taille, date de modification
        """
        from ..auth.context import check_access
        from ..core.storage import get_storage
        from ..core.consolidator import _sanitize_filename

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            storage = get_storage()
            key = f"{space_id}/bank/{filename}"
            content = await storage.get(key)

            if content is None:
                # Fallback : la clé S3 réelle peut contenir des caractères
                # Unicode invisibles (bug LLM drift). On scanne les vraies
                # clés et on cherche par correspondance sanitisée.
                objects = await storage.list_objects(f"{space_id}/bank/")
                sanitized_target = _sanitize_filename(filename)
                matched_key = None

                for obj in objects:
                    raw_filename = obj["Key"].split("/")[-1]
                    if _sanitize_filename(raw_filename) == sanitized_target:
                        matched_key = obj["Key"]
                        break

                if matched_key:
                    content = await storage.get(matched_key)
                    if content is not None:
                        return {
                            "status": "ok",
                            "space_id": space_id,
                            "filename": filename,
                            "content": content,
                            "size": len(content.encode("utf-8")),
                            "note": (
                                f"Fichier trouvé via fallback Unicode "
                                f"(clé S3 réelle: {matched_key.split('/')[-1]!r}). "
                                f"Utilisez bank_repair pour corriger."
                            ),
                        }

                return {
                    "status": "not_found",
                    "message": f"Fichier '{filename}' introuvable dans '{space_id}'",
                }

            return {
                "status": "ok",
                "space_id": space_id,
                "filename": filename,
                "content": content,
                "size": len(content.encode("utf-8")),
            }
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_read_all(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
    ) -> dict:
        """
        Lit l'ensemble de la Memory Bank en une seule requête.

        C'est l'outil qu'un agent appelle au démarrage pour charger
        tout son contexte mémoire d'un coup.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Tous les fichiers bank avec leur contenu
        """
        from ..auth.context import check_access
        from ..core.storage import get_storage

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            storage = get_storage()

            # Vérifier l'existence de l'espace
            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            # Lire tous les fichiers bank
            from ..core.storage import bank_relpath

            bank_data = await storage.list_and_get(f"{space_id}/bank/")
            files = [
                {
                    "filename": bank_relpath(item["key"], space_id),
                    "content": item["content"],
                    "size": item["size"],
                }
                for item in bank_data
            ]

            total_size = sum(f["size"] for f in files)

            return {
                "status": "ok",
                "space_id": space_id,
                "files": files,
                "total_size": total_size,
                "file_count": len(files),
            }
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_list(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
    ) -> dict:
        """
        Liste les fichiers de la Memory Bank (sans leur contenu).

        Utile pour connaître la structure de la bank avant de lire
        des fichiers spécifiques.

        Args:
            space_id: Identifiant de l'espace

        Returns:
            Liste des fichiers avec taille et date de modification
        """
        from ..auth.context import check_access
        from ..core.storage import get_storage

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            storage = get_storage()

            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            # Lister les objets bank (sans les .keep)
            from ..core.storage import bank_relpath

            objects = await storage.list_objects(f"{space_id}/bank/")
            files = [
                {
                    "filename": bank_relpath(o["Key"], space_id),
                    "size": o["Size"],
                    "last_modified": str(o.get("LastModified", "")),
                }
                for o in objects
                if not o["Key"].endswith(".keep")
            ]

            return {
                "status": "ok",
                "space_id": space_id,
                "files": files,
                "file_count": len(files),
            }
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
    async def bank_consolidate(
        space_id: Annotated[
            str, Field(description="Identifiant de l'espace à consolider")
        ],
        agent: Annotated[
            str,
            Field(
                default="",
                description="Nom de l'agent dont consolider les notes (vide = toutes, admin requis)",
            ),
        ] = "",
    ) -> dict:
        """
        Déclenche la consolidation : le LLM lit les notes live et produit
        les fichiers bank mis à jour selon les rules.

        ⚠️ Un seul consolidate peut s'exécuter à la fois par espace.
        Si une consolidation est déjà en cours, retourne "conflict".

        Le pipeline :
        1. Lit les rules, synthèse, notes live, bank actuelle
        2. Envoie tout au LLM configuré (LLMAAS_MODEL)
        3. Écrit les fichiers bank mis à jour
        4. Supprime les notes live traitées
        5. Met à jour la synthèse résiduelle

        Args:
            space_id: Identifiant de l'espace à consolider
            agent: Nom de l'agent dont consolider les notes.
                   Vide + admin = consolide TOUTES les notes.
                   Vide + write = auto-détecte le caller (ses propres notes).
                   Si l'agent correspond au token → write suffit.
                   Si l'agent est différent → admin requis.

        Returns:
            Métriques de consolidation (notes traitées, fichiers MAJ, tokens)
        """
        from ..auth.context import (
            check_access,
            check_write_permission,
            check_manage_permission,
            check_admin_permission,
            get_current_agent_name,
        )
        from ..core.locks import get_lock_manager
        from ..core.consolidator import get_consolidator

        try:
            # Vérifier accès à l'espace
            access_err = check_access(space_id)
            if access_err:
                return access_err

            # Identifier le caller (client_name du token)
            caller = get_current_agent_name()

            # Règles de permissions pour bank_consolidate :
            #
            # 1. manage+ (manage ou admin) → peut consolider tout
            #    (agent="" = toutes les notes) ou les notes d'un agent
            #    spécifique (agent="xxx")
            #
            # 2. write (pas manage) → ne peut consolider QUE ses propres notes
            #    - agent="" → auto-set à caller (on consolide ses propres notes)
            #    - agent=caller → OK
            #    - agent=autre → REFUSÉ (manage requis)
            #
            # 3. read → REFUSÉ (write minimum requis)

            manage_err = check_manage_permission()
            is_manager = manage_err is None

            if is_manager:
                # Manage+ : peut tout consolider, pas de restriction
                pass
            else:
                # Vérifier au minimum la permission write
                write_err = check_write_permission()
                if write_err:
                    return write_err

                # Write sans manage : on ne peut consolider que ses notes
                if agent and agent != caller:
                    return {
                        "status": "error",
                        "message": (
                            f"Permission 'manage' requise pour consolider "
                            f"les notes de l'agent '{agent}'. "
                            f"Vous pouvez consolider vos propres notes "
                            f"avec agent='{caller}' ou agent='' (auto-détection)."
                        ),
                    }
                # Auto-détection : agent vide → consolider ses propres notes
                if not agent:
                    agent = caller

            # Vérifier le lock de consolidation
            lock = get_lock_manager().consolidation(space_id)
            if lock.locked():
                return {
                    "status": "conflict",
                    "message": (
                        f"Consolidation déjà en cours pour '{space_id}'. "
                        "Réessayez dans quelques minutes."
                    ),
                }

            # Exécuter la consolidation sous lock
            # agent="" → consolide TOUTES les notes (pas de filtre)
            # agent="mon-agent" → consolide uniquement les notes de cet agent
            async with lock:
                return await get_consolidator().consolidate(space_id, agent=agent)

        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def bank_repair(
        space_id: Annotated[
            str, Field(description="Identifiant de l'espace à réparer")
        ],
        dry_run: Annotated[
            bool,
            Field(
                default=True,
                description="True = scan seul (liste les fichiers à réparer), False = applique les corrections",
            ),
        ] = True,
    ) -> dict:
        """
        Répare les fichiers bank : caractères Unicode invisibles,
        préfixes parasites (1.MEMORY_BANK/) et doublons multi-chemins.

        Détecte 3 types de problèmes :
        1. Caractères Unicode invisibles dans les noms de fichiers
        2. Préfixes parasites (1.MEMORY_BANK/, MEMORY_BANK/, bank/)
        3. Doublons : même fichier sanitisé à des chemins S3 différents

        Pour chaque fichier, extrait le chemin relatif complet,
        le sanitise, et si le chemin canonique diffère :
        - Écrit le contenu sous le chemin canonique
        - Supprime l'ancien fichier

        Si un doublon existe (même nom sanitisé, plusieurs clés S3),
        garde la version la plus récente et supprime les autres.

        ⚠️ Par défaut dry_run=True : scanne et rapporte sans modifier.
        Passez dry_run=False pour appliquer les corrections.

        Args:
            space_id: Espace à réparer
            dry_run: True = scan seul, False = correction effective

        Returns:
            Liste des fichiers réparés + doublons détectés
        """
        from ..auth.context import check_access, check_manage_permission
        from ..core.storage import get_storage, bank_relpath
        from ..core.consolidator import _sanitize_filename

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            manage_err = check_manage_permission()
            if manage_err:
                return manage_err

            storage = get_storage()

            # Vérifier l'existence de l'espace
            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            # Lister les vrais fichiers bank sur S3
            objects = await storage.list_objects(f"{space_id}/bank/")

            # Phase 1 : Scanner et grouper par nom sanitisé
            # sanitized_name → [(s3_key, relpath, size, last_modified), ...]
            groups: dict[str, list] = {}
            for obj in objects:
                key = obj["Key"]
                if key.endswith(".keep"):
                    continue

                relpath = bank_relpath(key, space_id)
                sanitized = _sanitize_filename(relpath)

                if sanitized not in groups:
                    groups[sanitized] = []
                groups[sanitized].append(
                    {
                        "key": key,
                        "relpath": relpath,
                        "size": obj["Size"],
                        "last_modified": str(obj.get("LastModified", "")),
                    }
                )

            # Phase 2 : Identifier les réparations et doublons
            repairs = []
            duplicates = []
            files_ok = 0

            for sanitized, entries in groups.items():
                canonical_key = f"{space_id}/bank/{sanitized}"

                # Trier par date (plus récent d'abord) pour garder la meilleure version
                entries.sort(key=lambda e: e["last_modified"], reverse=True)

                if len(entries) == 1 and entries[0]["key"] == canonical_key:
                    # Fichier OK : un seul exemplaire au bon chemin
                    files_ok += 1
                    continue

                # Premier = version à garder (la plus récente)
                best = entries[0]

                if best["key"] != canonical_key:
                    # Le fichier principal n'est pas au bon chemin → réparer
                    repairs.append(
                        {
                            "original_relpath": best["relpath"],
                            "sanitized": sanitized,
                            "original_key": best["key"],
                            "canonical_key": canonical_key,
                            "size": best["size"],
                            "action": "move",
                        }
                    )

                # Les autres entrées sont des doublons à supprimer
                for dup in entries[1:] if len(entries) > 1 else []:
                    duplicates.append(
                        {
                            "relpath": dup["relpath"],
                            "key": dup["key"],
                            "size": dup["size"],
                            "canonical": sanitized,
                            "action": "delete_duplicate",
                        }
                    )

            # Phase 3 : Appliquer si dry_run=False
            if not dry_run:
                for r in repairs:
                    content = await storage.get(r["original_key"])
                    if content is not None:
                        await storage.put(r["canonical_key"], content)
                        if r["original_key"] != r["canonical_key"]:
                            await storage.delete(r["original_key"])
                        r["status"] = "repaired"
                    else:
                        r["status"] = "error_read"

                for d in duplicates:
                    await storage.delete(d["key"])
                    d["status"] = "deleted"
            else:
                for r in repairs:
                    r["status"] = "would_repair"
                for d in duplicates:
                    d["status"] = "would_delete"

            mode = "dry-run" if dry_run else "applied"
            total_issues = len(repairs) + len(duplicates)

            return {
                "status": "ok",
                "space_id": space_id,
                "mode": mode,
                "files_scanned": len(groups),
                "files_ok": files_ok,
                "files_to_repair": len(repairs),
                "duplicates_found": len(duplicates),
                "repairs": repairs,
                "duplicates": duplicates,
                "message": (
                    f"{len(repairs)} fichier(s) à déplacer, "
                    f"{len(duplicates)} doublon(s) à supprimer "
                    f"sur {len(groups)} fichiers uniques. "
                    + (
                        "Passez dry_run=False pour appliquer."
                        if dry_run and total_issues > 0
                        else ""
                    )
                    + (
                        "Corrections appliquées."
                        if not dry_run and total_issues > 0
                        else ""
                    )
                    + ("Tous les fichiers sont OK." if total_issues == 0 else "")
                ),
            }
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def bank_write(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
        filename: Annotated[
            str, Field(description="Nom du fichier bank (ex: 'activeContext.md')")
        ],
        content: Annotated[
            str, Field(description="Contenu Markdown complet du fichier")
        ],
    ) -> dict:
        """
        Écrit ou remplace un fichier dans la Memory Bank (manage).

        ⚠️ Cet outil contourne la consolidation LLM — il écrit directement
        dans la bank. À utiliser pour les corrections manuelles quand la
        consolidation échoue (doublons, contenu tronqué, migration).

        Si un fichier avec le même nom existe déjà, il est remplacé.
        Les éventuels doublons Unicode sont automatiquement nettoyés.

        Args:
            space_id: Identifiant de l'espace
            filename: Nom du fichier à écrire
            content: Contenu Markdown complet

        Returns:
            Statut de l'écriture avec taille du fichier
        """
        from ..auth.context import check_access, check_manage_permission
        from ..core.storage import get_storage
        from ..core.consolidator import _sanitize_filename

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            manage_err = check_manage_permission()
            if manage_err:
                return manage_err

            # LM2-12 fix : refuser les caractères dangereux (XSS persistant
            # côté web — voir LM2-01). Cette validation s'ajoute au
            # _sanitize_filename existant qui ne traitait que l'Unicode.
            name_err = _validate_bank_filename(filename)
            if name_err:
                return name_err

            storage = get_storage()

            # Vérifier l'existence de l'espace
            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            # Sanitiser le filename
            sanitized = _sanitize_filename(filename)
            if not sanitized:
                return {
                    "status": "error",
                    "message": f"Nom de fichier invalide : '{filename}'",
                }

            # Re-valider après sanitisation Unicode (défense en profondeur :
            # _sanitize_filename pourrait ne pas être idempotent face à
            # certaines combinaisons de caractères).
            post_sanitize_err = _validate_bank_filename(sanitized)
            if post_sanitize_err:
                return post_sanitize_err

            # Écrire le fichier avec le nom canonique
            canonical_key = f"{space_id}/bank/{sanitized}"
            existed = await storage.exists(canonical_key)
            await storage.put(canonical_key, content)

            # Nettoyer les doublons Unicode (clés S3 qui sanitisent vers
            # le même nom mais avec des caractères invisibles)
            cleaned = 0
            objects = await storage.list_objects(f"{space_id}/bank/")
            for obj in objects:
                raw_key = obj["Key"]
                if raw_key == canonical_key or raw_key.endswith(".keep"):
                    continue
                raw_filename = raw_key.split("/")[-1]
                if _sanitize_filename(raw_filename) == sanitized:
                    await storage.delete(raw_key)
                    cleaned += 1

            action = "replaced" if existed else "created"
            result = {
                "status": "ok",
                "space_id": space_id,
                "filename": sanitized,
                "action": action,
                "size": len(content.encode("utf-8")),
            }
            if cleaned > 0:
                result["unicode_duplicates_cleaned"] = cleaned
            return result

        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def bank_delete(
        space_id: Annotated[str, Field(description="Identifiant de l'espace")],
        filename: Annotated[str, Field(description="Nom du fichier bank à supprimer")],
        confirm: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "LM2-31 : doit être True pour confirmer la suppression "
                    "(harmonisation avec space_delete, backup_restore, backup_delete)."
                ),
            ),
        ] = False,
    ) -> dict:
        """
        Supprime un fichier de la Memory Bank (manage).

        Supprime aussi tous les doublons (fichiers avec le même
        nom sanitisé à des chemins S3 différents).

        ⚠️ Irréversible. Utilisez bank_read pour sauvegarder le contenu
        avant de supprimer si nécessaire. Depuis v2.0.0 (LM2-31 fix), un
        ``confirm=True`` explicite est requis pour éviter les suppressions
        accidentelles par un opérateur ``manage``.

        Args:
            space_id: Identifiant de l'espace
            filename: Nom du fichier à supprimer (peut inclure un sous-dossier)
            confirm: Doit être True pour confirmer (sécurité)

        Returns:
            Nombre de fichiers supprimés (incluant les doublons)
        """
        from ..auth.context import check_access, check_manage_permission
        from ..core.storage import get_storage, bank_relpath
        from ..core.consolidator import _sanitize_filename

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            manage_err = check_manage_permission()
            if manage_err:
                return manage_err

            # LM2-31 fix : exiger confirm=True (harmonisation avec les autres
            # outils destructifs : space_delete, backup_restore, backup_delete,
            # admin_gc_notes).
            if not confirm:
                return {
                    "status": "error",
                    "message": (
                        "Suppression refusée : confirm=True requis pour "
                        "supprimer un fichier bank (sécurité, irréversible)."
                    ),
                }

            storage = get_storage()

            # Vérifier l'existence de l'espace
            if not await storage.exists(f"{space_id}/_meta.json"):
                return {
                    "status": "not_found",
                    "message": f"Espace '{space_id}' introuvable",
                }

            sanitized = _sanitize_filename(filename)

            # Trouver toutes les clés S3 qui sanitisent vers ce nom
            # (= le fichier canonique + tous ses doublons)
            objects = await storage.list_objects(f"{space_id}/bank/")
            keys_to_delete = []
            for obj in objects:
                raw_key = obj["Key"]
                if raw_key.endswith(".keep"):
                    continue
                raw_relpath = bank_relpath(raw_key, space_id)
                if _sanitize_filename(raw_relpath) == sanitized:
                    keys_to_delete.append(raw_key)

            if not keys_to_delete:
                return {
                    "status": "not_found",
                    "message": f"Fichier '{filename}' introuvable dans '{space_id}'",
                }

            # Supprimer toutes les variantes
            deleted = await storage.delete_many(keys_to_delete)

            return {
                "status": "deleted",
                "space_id": space_id,
                "filename": sanitized,
                "files_deleted": deleted,
                "keys_deleted": [k.split("/")[-1] for k in keys_to_delete],
            }

        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    async def bank_compact(
        space_id: Annotated[
            str, Field(description="Identifiant de l'espace à compacter")
        ],
        dry_run: Annotated[
            bool,
            Field(
                default=True,
                description="True = scan seul (rapport sans modification), False = compaction effective via LLM",
            ),
        ] = True,
    ) -> dict:
        """
        Compacte les fichiers bank surdimensionnés via LLM (manage).

        Analyse chaque fichier bank et compare sa taille à la limite
        universelle configurée (BANK_FILE_MAX_SIZE, par défaut 15 KB).
        Les fichiers dépassant cette limite sont résumés/nettoyés par le LLM.

        Le LLM utilise les rules de l'espace pour comprendre le rôle de
        chaque fichier et applique des règles de compaction adaptées :
        fusionne les redondances, supprime les détails obsolètes,
        résume les entrées anciennes en une ligne par jalon.

        ⚠️ Par défaut dry_run=True : scanne et rapporte sans modifier.
        Passez dry_run=False pour compacter effectivement.

        ⚠️ La compaction est protégée par le lock de consolidation.
        Si une consolidation est en cours, retourne "conflict".

        Args:
            space_id: Espace à compacter
            dry_run: True = scan seul, False = compaction effective

        Returns:
            Rapport de compaction avec détails par fichier (taille, ratio, réduction)
        """
        from ..auth.context import check_access, check_manage_permission
        from ..core.locks import get_lock_manager
        from ..core.consolidator import get_consolidator

        try:
            access_err = check_access(space_id)
            if access_err:
                return access_err

            manage_err = check_manage_permission()
            if manage_err:
                return manage_err

            # Protéger par le lock de consolidation (la compaction
            # modifie les fichiers bank — incompatible avec une
            # consolidation simultanée)
            if not dry_run:
                lock = get_lock_manager().consolidation(space_id)
                if lock.locked():
                    return {
                        "status": "conflict",
                        "message": (
                            f"Consolidation en cours pour '{space_id}'. "
                            "Réessayez dans quelques minutes."
                        ),
                    }
                async with lock:
                    return await get_consolidator().compact_bank(
                        space_id, dry_run=False
                    )
            else:
                # Dry-run : pas besoin de lock (lecture seule)
                return await get_consolidator().compact_bank(space_id, dry_run=True)

        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    return 8  # Nombre d'outils enregistrés
