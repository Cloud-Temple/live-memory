# -*- coding: utf-8 -*-
"""
Outils MCP — Catégorie Bank (11 outils).

Memory Bank consolidée : lire, lister, consolider via LLM, compacter,
réparer, écrire et supprimer manuellement.

Permissions :
    - bank_read        🔑 (read)    — Lit un fichier bank spécifique
    - bank_read_all    🔑 (read)    — Lit toute la bank (démarrage agent)
    - bank_list        🔑 (read)    — Liste les fichiers bank (sans contenu)
    - bank_consolidate ✏️ (write)   — Déclenche la consolidation LLM
    - bank_consolidation_status 🔑 (read) — Consulte un job de consolidation
    - bank_consolidation_queues 🔑 (read) — Résume les lanes de consolidation
    - bank_stale_spaces 🔑 (read)   — Liste les spaces avec trop de notes non consolidées
    - bank_compact     🔧 (manage)  — Compacte les fichiers bank surdimensionnés via LLM
    - bank_repair      🔧 (manage)  — Répare les noms de fichiers corrompus par le LLM
    - bank_write       🔧 (manage)  — Écrit/remplace un fichier bank directement
    - bank_delete      🔧 (manage)  — Supprime un fichier bank

La consolidation est l'opération qui transforme les notes live en
fichiers bank structurés. `bank_consolidate` place un job dans une file
FIFO en mémoire par espace. Un seul job à la fois mute la bank d'un espace
(protégé par asyncio.Lock).

Voir CONSOLIDATION_LLM.md pour le pipeline détaillé.
"""

import re
from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


_LIVE_NOTE_TS_RE = re.compile(r"^(\d{8}T\d{6})_")


def _parse_live_note_timestamp(filename: str) -> datetime | None:
    """
    Extrait le timestamp UTC depuis le préfixe d'un nom de fichier de note live.

    Format attendu : `YYYYMMDDTHHMMSS_<agent>_<category>_<uuid8>.md`
    (généré par `LiveService.write_note()`).

    Retourne None si le format ne matche pas — la note sera ignorée.
    """
    m = _LIVE_NOTE_TS_RE.match(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


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
    Enregistre les 10 outils bank sur l'instance MCP.

    Args:
        mcp: Instance FastMCP

    Returns:
        Nombre d'outils enregistrés (10)
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
        Enfile une consolidation asynchrone : le LLM lira les notes live
        au moment de l'exécution du job et produira les fichiers bank mis
        à jour selon les rules.

        ⚠️ La file PR 1 est en mémoire et mono-processus :
        garantie `in_memory_best_effort`, non durable au redémarrage.

        Le pipeline :
        1. Lit les rules, synthèse, notes live, bank actuelle
        2. Envoie tout au LLM configuré (LLMAAS_MODEL)
        3. Écrit les fichiers bank mis à jour
        4. Supprime les notes live traitées
        5. Met à jour la synthèse résiduelle

        Args:
            space_id: Identifiant de l'espace à consolider
            agent: Nom de l'agent dont consolider les notes.
                   Vide + manage/admin = consolide TOUTES les notes.
                   Vide + write = auto-détecte le caller (ses propres notes).
                   Si l'agent correspond au token → write suffit.
                   Si l'agent est différent → manage requis.

        Returns:
            Accusé de réception async du job (running/queued + job_id),
            incluant le contrat machine-readable demandant de rendre la main
            sans attendre ni poller automatiquement. `bank_consolidation_status`
            est réservé aux demandes explicites de statut.
        """
        from ..auth.context import (
            check_access,
            check_write_permission,
            check_manage_permission,
            get_current_agent_name,
        )
        from ..core.consolidation_queue import get_consolidation_queue

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

            # Enfile le job. Le worker de fond utilise l'agent effectif
            # capturé ici, sans dépendre du contexte d'auth MCP.
            # agent="" → consolide TOUTES les notes (manage/admin uniquement)
            # agent="mon-agent" → consolide uniquement les notes de cet agent
            return await get_consolidation_queue().enqueue(
                space_id=space_id,
                agent=agent,
                requested_by=caller,
            )

        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_consolidation_status(
        job_id: Annotated[
            str, Field(description="Identifiant du job de consolidation")
        ],
    ) -> dict:
        """
        Consulte le statut d'un job de consolidation en mémoire.

        Args:
            job_id: Identifiant retourné par bank_consolidate

        Returns:
            Statut du job et résultat/erreur si terminé.
        """
        from ..auth.context import check_access
        from ..core.consolidation_queue import get_consolidation_queue

        try:
            result = await get_consolidation_queue().get_job(job_id)
            if result.get("status") == "not_found":
                return result

            access_err = check_access(result["space_id"])
            if access_err:
                return access_err

            return result
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_consolidation_queues(
        space_ids: Annotated[
            str,
            Field(
                default="",
                description=(
                    "CSV optionnel des spaces à inspecter. Vide = tous les "
                    "spaces accessibles au token courant."
                ),
            ),
        ] = "",
    ) -> dict:
        """
        Résume les lanes de consolidation par space.

        Modèle métier exposé :
        - une seule consolidation running par space ;
        - une queue FIFO indépendante par space ;
        - plusieurs spaces peuvent consolider en parallèle ;
        - scope `all_agents` pour manage/admin, scope `agent` pour un agent.

        Args:
            space_ids: CSV optionnel pour éviter un listing S3 si l'UI connaît
                déjà les spaces accessibles.

        Returns:
            Synthèse des lanes et totaux d'activité.
        """
        from ..auth.context import _get_effective_token_info, check_access
        from ..config import get_settings
        from ..core.consolidation_queue import get_consolidation_queue
        from ..core.space import get_space_service

        try:
            token_info = _get_effective_token_info()
            if token_info is None:
                return {"status": "error", "message": "Authentification requise"}

            requested_ids = [
                sid.strip() for sid in space_ids.split(",") if sid.strip()
            ]
            denied_spaces = []

            if requested_ids:
                visible_ids = []
                for sid in requested_ids:
                    access_err = check_access(sid)
                    if access_err:
                        denied_spaces.append(
                            {"space_id": sid, "message": access_err.get("message")}
                        )
                        continue
                    visible_ids.append(sid)
            else:
                permissions = token_info.get("permissions", [])
                allowed = token_info.get("allowed_resources", [])
                if "admin" in permissions:
                    allowed_ids = None
                elif not allowed:
                    allowed_ids = []
                else:
                    allowed_ids = allowed
                spaces_result = await get_space_service().list_spaces(
                    allowed_space_ids=allowed_ids
                )
                if spaces_result.get("status") != "ok":
                    return spaces_result
                visible_ids = [s["space_id"] for s in spaces_result.get("spaces", [])]

            queue = get_consolidation_queue()
            lanes = [await queue.get_space_summary(sid) for sid in visible_ids]
            running = sum(1 for lane in lanes if lane.get("running_job"))
            queued = sum(lane.get("queued_count", 0) for lane in lanes)
            failed_recent = sum(
                1
                for lane in lanes
                for job in lane.get("latest_jobs", [])
                if job.get("status") == "failed"
            )
            active = sum(
                1
                for lane in lanes
                if lane.get("running_job") or lane.get("queued_count", 0) > 0
            )

            return {
                "status": "ok",
                "lanes": lanes,
                "total_spaces": len(lanes),
                "active_spaces": active,
                "running_spaces": running,
                "queued_jobs": queued,
                "failed_recent": failed_recent,
                "parallelism_model": "one_worker_per_space",
                "service_config": {
                    "batch_size": get_settings().consolidation_batch_size,
                },
                "denied_spaces": denied_spaces,
            }
        except Exception as e:
            from ..auth.context import safe_error

            return safe_error(e, "bank")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def bank_stale_spaces(
        min_notes: Annotated[
            int,
            Field(
                default=5,
                ge=1,
                description=(
                    "Nombre minimum de notes live non consolidées pour qu'un "
                    "space soit considéré stale (défaut 5)."
                ),
            ),
        ] = 5,
        min_age_days: Annotated[
            int,
            Field(
                default=5,
                ge=0,
                description=(
                    "Âge minimum (en jours) de la note la plus ancienne pour "
                    "qu'un space soit considéré stale (défaut 5)."
                ),
            ),
        ] = 5,
        space_ids: Annotated[
            str,
            Field(
                default="",
                description=(
                    "CSV optionnel des spaces à inspecter. Vide = tous les "
                    "spaces accessibles au token courant."
                ),
            ),
        ] = "",
    ) -> dict:
        """
        Identifie les spaces dont la consolidation est en retard.

        Pour chaque space accessible, compte les notes live non consolidées
        et calcule l'âge de la plus ancienne (depuis le préfixe timestamp
        du nom de fichier `YYYYMMDDTHHMMSS_...`). Un space est marqué
        `stale` si :
        - `live_notes_count >= min_notes` ET
        - `oldest_note_age_days >= min_age_days`.

        Outil read-only utile pour la supervision multi-spaces : repère les
        banks qui accumulent du contexte non consolidé (agent inactif,
        oubli en fin de session, etc.). Les clients peuvent ensuite
        déclencher `bank_consolidate` par space ou en bulk.

        Args:
            min_notes: Seuil sur le nombre de notes (défaut 5).
            min_age_days: Seuil sur l'âge de la plus ancienne note (défaut 5).
            space_ids: CSV optionnel pour cibler une liste de spaces et
                éviter un listing.

        Returns:
            Liste des spaces stale + métriques globales et spaces refusés.
        """
        from ..auth.context import _get_effective_token_info, check_access
        from ..core.space import get_space_service
        from ..core.storage import get_storage

        try:
            token_info = _get_effective_token_info()
            if token_info is None:
                return {"status": "error", "message": "Authentification requise"}

            requested_ids = [
                sid.strip() for sid in space_ids.split(",") if sid.strip()
            ]
            denied_spaces = []

            if requested_ids:
                visible_ids = []
                for sid in requested_ids:
                    access_err = check_access(sid)
                    if access_err:
                        denied_spaces.append(
                            {"space_id": sid, "message": access_err.get("message")}
                        )
                        continue
                    visible_ids.append(sid)
            else:
                permissions = token_info.get("permissions", [])
                allowed = token_info.get("allowed_resources", [])
                if "admin" in permissions:
                    allowed_ids = None
                elif not allowed:
                    allowed_ids = []
                else:
                    allowed_ids = allowed
                spaces_result = await get_space_service().list_spaces(
                    allowed_space_ids=allowed_ids
                )
                if spaces_result.get("status") != "ok":
                    return spaces_result
                visible_ids = [s["space_id"] for s in spaces_result.get("spaces", [])]

            storage = get_storage()
            now = datetime.now(timezone.utc)
            scanned = []
            stale = []

            for sid in visible_ids:
                objects = await storage.list_objects(f"{sid}/live/")
                notes_count = 0
                oldest_ts: datetime | None = None
                oldest_filename = ""

                for obj in objects:
                    key = obj.get("Key", "")
                    filename = key.rsplit("/", 1)[-1]
                    ts = _parse_live_note_timestamp(filename)
                    if ts is None:
                        continue
                    notes_count += 1
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
                        oldest_filename = filename

                if notes_count == 0 or oldest_ts is None:
                    scanned.append(
                        {
                            "space_id": sid,
                            "live_notes_count": 0,
                            "oldest_note_age_days": 0.0,
                            "oldest_note_timestamp": "",
                            "oldest_note_filename": "",
                            "is_stale": False,
                        }
                    )
                    continue

                age_days = (now - oldest_ts).total_seconds() / 86400.0
                is_stale = (
                    notes_count >= min_notes and age_days >= float(min_age_days)
                )
                # Truncate (not round) to 2 decimals so the displayed age never
                # exceeds the real age. Otherwise "5.0 days, not stale" can
                # appear when the threshold is 5 — confusing the operator.
                displayed_age = int(age_days * 100) / 100.0
                entry = {
                    "space_id": sid,
                    "live_notes_count": notes_count,
                    "oldest_note_age_days": displayed_age,
                    "oldest_note_timestamp": oldest_ts.isoformat(),
                    "oldest_note_filename": oldest_filename,
                    "is_stale": is_stale,
                }
                scanned.append(entry)
                if is_stale:
                    stale.append(entry)

            stale.sort(
                key=lambda e: (
                    -e["live_notes_count"],
                    -e["oldest_note_age_days"],
                )
            )

            return {
                "status": "ok",
                "spaces": stale,
                "scanned": scanned,
                "total_spaces": len(scanned),
                "total_stale": len(stale),
                "min_notes": min_notes,
                "min_age_days": min_age_days,
                "denied_spaces": denied_spaces,
            }
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

    return 11  # Nombre d'outils enregistrés
