# -*- coding: utf-8 -*-
"""
Service Consolidator — Pipeline LLM pour la consolidation notes → bank.

C'est le cœur intelligent de Live Memory. Le pipeline :
1. Collecte : rules + synthèse précédente + notes live + bank actuelle
2. Prompt : construit le prompt LLM (system + user)
3. Appel LLM : une seule requête au modèle configuré (LLMAAS_MODEL), réponse JSON
4. Application : éditions chirurgicales sur les fichiers bank existants
5. Écriture : bank files + synthesis + suppression notes + update meta

Principes :
    - Les agents n'écrivent JAMAIS dans la bank — seul le LLM le fait
    - Les notes sont supprimées UNIQUEMENT après succès complet (atomicité)
    - Un seul consolidate à la fois par espace (asyncio.Lock)
    - Le LLM produit des OPÉRATIONS D'ÉDITION (pas des réécritures complètes)
    - Ce qui n'est pas touché reste intact byte-for-byte (zéro perte)

Voir CONSOLIDATION_LLM.md pour les détails du pipeline et des prompts.
"""

import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import AsyncOpenAI

from ..config import get_settings
from .storage import get_storage, bank_relpath

logger = logging.getLogger("live_mem.consolidator")


# ─────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un assistant spécialisé dans la maintenance de Memory Banks pour des projets.

Ta mission : intégrer des notes de travail dans des fichiers Markdown structurés via des ÉDITIONS CHIRURGICALES.

## Ce que tu reçois :
1. Les RULES qui définissent la structure de la memory bank
2. La SYNTHÈSE PRÉCÉDENTE (contexte des consolidations antérieures)
3. Les NOTES LIVE nouvelles à intégrer
4. Les FICHIERS BANK actuels (le contenu existant)

## Ce que tu dois retourner :
Un JSON avec des OPÉRATIONS D'ÉDITION par fichier — PAS le contenu complet des fichiers.

## Principe fondamental : ÉDITER, NE PAS RÉÉCRIRE

⚠️ Tu ne dois JAMAIS renvoyer le contenu complet d'un fichier sauf si :
- C'est un nouveau fichier à créer (action "create")
- Le fichier nécessite une restructuration majeure (action "rewrite" — exceptionnel, justification obligatoire)

Pour les fichiers existants, tu produis des opérations d'édition par SECTION Markdown.
Tout ce que tu ne touches pas explicitement reste INTACT — c'est le but.

## Types d'opérations disponibles :

1. **replace_section** — Remplace le contenu d'une section (identifiée par son heading)
   Le contenu SOUS le heading jusqu'au prochain heading de même niveau ou supérieur est remplacé.
   
2. **append_to_section** — Ajoute du contenu à la FIN d'une section existante
   Préserve tout le contenu existant, ajoute après.

3. **prepend_to_section** — Ajoute du contenu au DÉBUT d'une section (après le heading)
   Préserve tout le contenu existant, ajoute avant.

4. **add_section** — Crée une nouvelle section (heading + contenu) à la fin du fichier
   Ou après une section spécifique si "after" est fourni.
   ⚠️ N'utilise JAMAIS add_section pour une section qui EXISTE DÉJÀ — utilise replace_section à la place.
   Si tu utilises add_section avec un heading déjà présent, il sera automatiquement converti en replace_section.

5. **delete_section** — Supprime une section entière (heading + contenu)

## Règles :
- Respecte STRICTEMENT la structure définie dans les rules
- Intègre les nouvelles informations des notes live
- Préfère append_to_section et replace_section — ce sont les opérations les plus courantes
- Pour les fichiers de CONTEXTE ACTUEL (focus, travail en cours) : replace_section le focus, append les éléments récents.
  ⚠️ NETTOIE ACTIVEMENT : déplace les éléments terminés vers le fichier de suivi/historique,
  supprime les détails de sessions anciennes (> 2 sessions), garde UNIQUEMENT
  le focus actuel, le travail récent, les prochaines étapes et les décisions actives.
  Ces fichiers doivent rester LÉGERS.
- Pour les fichiers d'HISTORIQUE/PROGRESSION : append les nouvelles entrées, NE JAMAIS supprimer l'historique.
  Résume les entrées anciennes (> 30 jours) en une ligne par jalon.
  ⚠️ ANTI-DOUBLON SÉMANTIQUE : avant de créer une NOUVELLE section dans un fichier d'historique,
  vérifie si un jalon couvrant le MÊME TRAVAIL (même date, même feature/phase) existe
  déjà dans le fichier, même avec un heading différent ou un format plus court.
  Exemples de doublons à éviter :
    - "### Phase B — Service créé (10/04)" ET "### Session du 10/04 — Phase B COMPLÈTE"
    - "### Phase 4.4x — Fix Mermaid (06/04)" ET "### Session du 06/04 — Fix complet diagrammes"
  Si un jalon similaire existe → ENRICHIS-LE avec replace_section (en gardant le heading
  existant et en ajoutant les détails manquants), au lieu de créer une section dupliquée.
  Ceci est particulièrement important après une compaction où les sections ont été résumées.
- Identifie le RÔLE de chaque fichier bank à partir des RULES fournies (pas à partir du nom de fichier).
- Les headings doivent correspondre EXACTEMENT à ceux du fichier (avec les ## )
- Si un fichier n'a pas besoin de modification, NE L'INCLUS PAS
- La synthèse doit être concise mais couvrir les points clés des notes traitées
- ⚠️ RÈGLE ANTI-ACCUMULATION : chaque consolidation doit NETTOYER l'obsolète,
  pas seulement ajouter. Un fichier qui DÉPASSE SA LIMITE DE TAILLE et continue
  de grossir est un problème — compacte les sections anciennes pour faire de la place."""


class ConsolidatorService:
    """
    Service de consolidation LLM : transforme les notes live en bank.

    Utilise AsyncOpenAI pour communiquer avec le LLMaaS Cloud Temple.
    Mode "édition chirurgicale" : le LLM produit des opérations d'édition
    par section Markdown, pas des réécritures complètes.
    """

    def __init__(self):
        settings = get_settings()

        # ── Proxy HTTP sortant (optionnel) ────────────────────
        # Utilise PROXY_URL (variable custom) plutôt que HTTP_PROXY/HTTPS_PROXY
        # pour éviter d'affecter toutes les libs Python qui lisent les vars d'env OS.
        # AsyncOpenAI utilise httpx en interne — on passe un client httpx pré-configuré.
        _http_client: httpx.AsyncClient | None = None
        proxy_url = settings.proxy_url.strip() or None
        if proxy_url:
            _http_client = httpx.AsyncClient(
                proxy=httpx.Proxy(url=proxy_url),
                timeout=settings.consolidation_timeout,
            )
            logger.info("ConsolidatorService: LLM requests via proxy %s", proxy_url)

        self._client = AsyncOpenAI(
            base_url=settings.llmaas_api_url,
            api_key=settings.llmaas_api_key,
            timeout=settings.consolidation_timeout,
            **({"http_client": _http_client} if _http_client else {}),
        )
        self._model = settings.llmaas_model
        self._context_window = settings.llmaas_context_window
        self._max_tokens = settings.llmaas_max_tokens
        self._temperature = settings.llmaas_temperature
        self._max_notes = settings.consolidation_max_notes
        self._batch_size = settings.consolidation_batch_size
        # Bank compaction settings
        self._compact_threshold = settings.compact_threshold
        self._bank_file_max_size = settings.bank_file_max_size

    async def consolidate(self, space_id: str, agent: str = "") -> dict:
        """
        Pipeline complet de consolidation pour un espace, par lots.

        Les notes sont traitées par lots de `batch_size` (défaut 10) pour :
        - Garder les réponses JSON du LLM courtes (évite le drift Unicode)
        - Permettre une meilleure intégration incrémentale
        - Rendre le pipeline plus résilient (lots précédents déjà intégrés)

        Chaque lot relit la bank à jour depuis S3, ce qui permet au LLM
        de voir les modifications des lots précédents.

        IMPORTANT : Seules les notes de l'agent appelant sont consolidées.
        Les notes des autres agents restent dans live/ en attente.

        Args:
            space_id: Identifiant de l'espace à consolider
            agent: Nom de l'agent appelant (filtre les notes à consolider)

        Returns:
            Métriques de consolidation ou erreur
        """
        t0 = time.monotonic()
        storage = get_storage()
        agent_label = agent or "(all)"
        logger.info("Consolidation start — space=%s agent=%s", space_id, agent_label)

        # ── Étape 1 : Collecter les inputs ────────────────
        inputs = await self._collect_inputs(space_id, agent=agent)
        if inputs.get("status") == "error":
            return inputs

        all_notes = inputs["notes"]
        all_notes_keys = inputs["notes_keys"]

        # Pas de notes → rien à faire
        if not all_notes:
            return {
                "status": "ok",
                "notes_processed": 0,
                "message": "No new notes to consolidate",
            }

        # ── Étape 1b : Auto-compact de la bank si trop grosse ──
        compact_result = await self._compact_bank_if_needed(
            space_id, inputs["bank_files"], inputs["rules"]
        )
        if compact_result["compacted"]:
            # Relire la bank compactée depuis S3
            inputs["bank_files"] = await storage.list_and_get(f"{space_id}/bank/")
            logger.info(
                "Bank auto-compacted — %d files, %d→%d bytes",
                compact_result["files_compacted"],
                compact_result["size_before"],
                compact_result["size_after"],
            )

        # ── Étape 2 : Découper en lots ────────────────────
        batch_size = self._batch_size
        batches = []
        for i in range(0, len(all_notes), batch_size):
            batch_notes = all_notes[i : i + batch_size]
            batch_keys = all_notes_keys[i : i + batch_size]
            batches.append((batch_notes, batch_keys))

        batch_count = len(batches)
        rules = inputs["rules"]

        # Métriques accumulées
        total_notes = 0
        total_created = 0
        total_updated = 0
        total_ops_applied = 0
        total_ops_failed = 0
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        batches_completed = 0
        last_synthesis_size = 0

        # Bank et synthèse courantes (relues entre les lots)
        current_bank = inputs["bank_files"]
        current_synthesis = inputs["synthesis"]

        logger.info(
            "Consolidation plan — %d notes in %d batch(es) of %d",
            len(all_notes),
            batch_count,
            batch_size,
        )

        # ── Étape 3 : Traiter chaque lot ──────────────────
        for batch_idx, (batch_notes, batch_keys) in enumerate(batches, 1):
            logger.info(
                "Batch %d/%d — %d notes",
                batch_idx,
                batch_count,
                len(batch_notes),
            )

            # Relire la bank et la synthèse pour les lots suivants
            # (le lot précédent a pu modifier les fichiers bank)
            if batch_idx > 1:
                current_bank = await storage.list_and_get(f"{space_id}/bank/")
                current_synthesis = await storage.get(f"{space_id}/_synthesis.md")

            # Construire le prompt pour ce lot
            messages = self._build_prompt(
                space_id=space_id,
                rules=rules,
                synthesis=current_synthesis,
                notes=batch_notes,
                bank_files=current_bank,
            )

            # Appeler le LLM
            llm_result = await self._call_llm(messages)
            if llm_result.get("status") == "error":
                logger.error(
                    "Batch %d/%d LLM failed: %s — stopping (previous batches OK)",
                    batch_idx,
                    batch_count,
                    llm_result.get("message"),
                )
                break

            # Appliquer les éditions (bank + synthesis + delete notes)
            # skip_meta=True : on mettra à jour le meta une seule fois à la fin
            write_result = await self._write_results(
                space_id=space_id,
                llm_output=llm_result["data"],
                bank_files=current_bank,
                notes_keys=batch_keys,
                notes_count=len(batch_notes),
                usage=llm_result.get("usage", {}),
                skip_meta=True,
            )

            if write_result.get("status") != "ok":
                logger.error(
                    "Batch %d/%d write failed: %s — stopping",
                    batch_idx,
                    batch_count,
                    write_result.get("message"),
                )
                break

            # Accumuler les métriques
            batches_completed += 1
            total_notes += write_result.get("notes_processed", 0)
            total_created += write_result.get("bank_files_created", 0)
            total_updated += write_result.get("bank_files_updated", 0)
            total_ops_applied += write_result.get("operations_applied", 0)
            total_ops_failed += write_result.get("operations_failed", 0)
            total_tokens += write_result.get("llm_tokens_used", 0)
            total_prompt_tokens += write_result.get("llm_prompt_tokens", 0)
            total_completion_tokens += write_result.get("llm_completion_tokens", 0)
            last_synthesis_size = write_result.get("synthesis_size", 0)

            logger.info(
                "Batch %d/%d done — %d notes, %d created, %d updated, %d tokens",
                batch_idx,
                batch_count,
                len(batch_notes),
                write_result.get("bank_files_created", 0),
                write_result.get("bank_files_updated", 0),
                write_result.get("llm_tokens_used", 0),
            )

        # ── Étape 4 : Mettre à jour le meta (une seule fois) ─
        if total_notes > 0:
            now = datetime.now(timezone.utc).isoformat()
            meta = await storage.get_json(f"{space_id}/_meta.json") or {}
            meta["last_consolidation"] = now
            meta["consolidation_count"] = meta.get("consolidation_count", 0) + 1
            meta["total_notes_processed"] = (
                meta.get("total_notes_processed", 0) + total_notes
            )
            await storage.put_json(f"{space_id}/_meta.json", meta)

        # Compter les fichiers bank finaux
        bank_objects = await storage.list_objects(f"{space_id}/bank/")
        total_bank = len([o for o in bank_objects if not o["Key"].endswith(".keep")])

        duration = round(time.monotonic() - t0, 1)
        logger.info(
            "Consolidation done — space=%s agent=%s notes=%d batches=%d/%d "
            "created=%d updated=%d tokens=%d duration=%.1fs",
            space_id,
            agent_label,
            total_notes,
            batches_completed,
            batch_count,
            total_created,
            total_updated,
            total_tokens,
            duration,
        )

        return {
            "status": "ok",
            "space_id": space_id,
            "notes_processed": total_notes,
            "bank_files_updated": total_updated,
            "bank_files_created": total_created,
            "bank_files_unchanged": max(0, total_bank - total_created - total_updated),
            "operations_applied": total_ops_applied,
            "operations_failed": total_ops_failed,
            "synthesis_size": last_synthesis_size,
            "llm_tokens_used": total_tokens,
            "llm_prompt_tokens": total_prompt_tokens,
            "llm_completion_tokens": total_completion_tokens,
            "batches_total": batch_count,
            "batches_completed": batches_completed,
            "batch_size": batch_size,
            "duration_seconds": duration,
        }

    async def _collect_inputs(self, space_id: str, agent: str = "") -> dict:
        """
        Étape 1 : Lire les rules, synthèse, notes de l'agent et bank depuis S3.

        Si agent est fourni, seules les notes de cet agent sont collectées.
        Les notes des autres agents restent dans live/.

        Returns:
            Dict avec rules, synthesis, notes, notes_keys, bank_files
        """
        storage = get_storage()

        # Vérifier l'existence de l'espace
        meta = await storage.get_json(f"{space_id}/_meta.json")
        if meta is None:
            return {"status": "error", "message": f"Espace '{space_id}' introuvable"}

        # Lire les rules (immuables)
        rules = await storage.get(f"{space_id}/_rules.md") or ""

        # Lire la synthèse précédente (peut ne pas exister)
        synthesis = await storage.get(f"{space_id}/_synthesis.md")

        # Lire les notes live
        notes_raw = await storage.list_and_get(f"{space_id}/live/")
        # Trier par clé (= par timestamp, chronologique)
        notes_raw.sort(key=lambda n: n["key"])

        # Filtrer par agent : chaque agent ne consolide que SES notes
        # Le nom de l'agent est dans le nom de fichier : {ts}_{agent}_{cat}_{uuid}.md
        if agent:
            notes_raw = [
                n
                for n in notes_raw
                if f"_{agent}_" in n["key"].split("/")[-1]
                or n["key"].split("/")[-1].startswith(f"{agent}_")
            ]

        # Limiter au max_notes (les plus anciennes d'abord)
        notes_remaining = 0
        if len(notes_raw) > self._max_notes:
            notes_remaining = len(notes_raw) - self._max_notes
            notes_raw = notes_raw[: self._max_notes]

        # Garder les clés pour la suppression ultérieure
        notes_keys = [n["key"] for n in notes_raw]

        # Lire les fichiers bank actuels
        bank_raw = await storage.list_and_get(f"{space_id}/bank/")

        return {
            "rules": rules,
            "synthesis": synthesis,
            "notes": notes_raw,
            "notes_keys": notes_keys,
            "notes_remaining": notes_remaining,
            "bank_files": bank_raw,
            "meta": meta,
        }

    def _build_prompt(
        self,
        space_id: str,
        rules: str,
        synthesis: Optional[str],
        notes: list[dict],
        bank_files: list[dict],
    ) -> list[dict]:
        """
        Étape 2 : Construire les messages pour l'appel LLM.

        Le prompt demande des OPÉRATIONS D'ÉDITION, pas des réécritures.

        Returns:
            Liste de messages [{"role": "system", ...}, {"role": "user", ...}]
        """
        # Construire la section notes
        notes_section = ""
        for i, note in enumerate(notes, 1):
            content = note["content"]
            notes_section += f"\n--- Note {i}/{len(notes)} ---\n{content}\n"

        # Construire la section bank (fichiers existants avec leur contenu)
        # On sanitise les filenames pour que le LLM voie des noms propres
        # (pas contaminés par des caractères Unicode invisibles).
        if bank_files:
            bank_section = ""
            for bf in bank_files:
                # Extraire le chemin relatif complet (supporte les sous-dossiers)
                raw_relpath = bank_relpath(bf["key"], space_id)
                filename = _sanitize_filename(raw_relpath)
                bank_section += (
                    f"\n--- Fichier: {filename} ---\n"
                    f"{bf['content']}\n"
                    f"--- Fin fichier: {filename} ---\n"
                )
        else:
            bank_section = (
                "Aucun fichier bank — première consolidation. "
                "Utilise l'action 'create' pour créer les fichiers selon les rules."
            )

        # Construire le prompt utilisateur
        user_prompt = f"""=== RULES DE L'ESPACE "{space_id}" ===
{rules}

=== SYNTHÈSE PRÉCÉDENTE ===
{synthesis or "Aucune — première consolidation"}

=== NOTES LIVE À INTÉGRER ({len(notes)} notes) ===
{notes_section}

=== FICHIERS BANK ACTUELS ===
{bank_section}

=== FORMAT DE RÉPONSE ===
Retourne un JSON avec cette structure exacte :
{{
  "file_edits": [
    {{
      "filename": "activeContext.md",
      "action": "edit",
      "operations": [
        {{
          "type": "replace_section",
          "heading": "## Focus Actuel",
          "content": "Nouveau contenu de la section..."
        }},
        {{
          "type": "append_to_section",
          "heading": "## Travail Récent",
          "content": "- Nouvel élément ajouté\\n- Autre élément"
        }},
        {{
          "type": "add_section",
          "heading": "## Nouvelle Section",
          "content": "Contenu de la nouvelle section",
          "after": "## Section Existante"
        }},
        {{
          "type": "delete_section",
          "heading": "## Section Obsolète"
        }}
      ]
    }},
    {{
      "filename": "nouveau_fichier.md",
      "action": "create",
      "content": "# Titre\\n\\nContenu complet du nouveau fichier..."
    }},
    {{
      "filename": "fichier_restructure.md",
      "action": "rewrite",
      "content": "# Titre\\n\\nContenu complet réécrit...",
      "reason": "Restructuration majeure nécessaire car..."
    }}
  ],
  "synthesis": "Résumé concis des notes traitées..."
}}

=== CONSIGNES IMPORTANTES ===
1. Pour les fichiers EXISTANTS, utilise action "edit" avec des opérations chirurgicales
2. Pour les NOUVEAUX fichiers, utilise action "create" avec le contenu complet
3. Action "rewrite" = réécriture COMPLÈTE — UNIQUEMENT si restructuration majeure nécessaire
4. Les fichiers inchangés NE DOIVENT PAS apparaître dans file_edits
5. Les headings dans les opérations doivent correspondre EXACTEMENT à ceux du fichier (ex: "## Focus Actuel")
6. Préfère append_to_section pour AJOUTER de l'information sans rien perdre
7. Préfère replace_section pour METTRE À JOUR une section dont le contenu change
8. Pour les fichiers d'historique/progression : TOUJOURS append, JAMAIS supprimer l'historique
9. La synthèse résiduelle doit résumer les notes traitées"""

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    async def _call_llm(self, messages: list[dict]) -> dict:
        """
        Étape 3 : Appeler le LLM et parser la réponse JSON.

        Calcule dynamiquement max_tokens en sortie pour éviter de dépasser
        le context window du modèle (input + output ≤ context_window).

        Heuristique : 1 token ≈ 4 caractères. On réserve au minimum
        8192 tokens pour la sortie (éditions chirurgicales JSON).

        Inclut un retry si la réponse n'est pas du JSON valide.

        Returns:
            {"status": "ok", "data": {...}, "usage": {...}} ou erreur
        """
        # ── Calcul dynamique du budget de sortie ──────────────
        # Estimer les tokens d'input (heuristique 1 token ≈ 4 chars)
        input_chars = sum(len(m.get("content", "")) for m in messages)
        estimated_input_tokens = input_chars // 4

        # Budget de sortie :
        # - Ne doit pas dépasser max_tokens (config : max output demandé à l'API)
        # - Ne doit pas dépasser context_window - input (sinon le modèle rejette)
        # - Plancher : 8192 tokens (minimum pour du JSON chirurgical)
        _MIN_OUTPUT_TOKENS = 8192
        remaining_in_window = self._context_window - estimated_input_tokens
        output_budget = max(
            _MIN_OUTPUT_TOKENS, min(self._max_tokens, remaining_in_window)
        )

        if estimated_input_tokens > self._context_window * 0.8:
            logger.warning(
                "LLM input très large : ~%d tokens estimés "
                "(context_window=%d, max_tokens=%d). "
                "Budget sortie réduit à %d tokens. "
                "Considérez réduire la taille de la bank.",
                estimated_input_tokens,
                self._context_window,
                self._max_tokens,
                output_budget,
            )

        logger.info(
            "LLM call — input ~%d tokens, context_window=%d, "
            "output budget %d tokens (max_tokens=%d)",
            estimated_input_tokens,
            self._context_window,
            output_budget,
            self._max_tokens,
        )

        for attempt in range(2):  # 1 essai + 1 retry
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=output_budget,
                    temperature=self._temperature,
                )

                raw_content = response.choices[0].message.content or ""
                finish_reason = response.choices[0].finish_reason
                completion_tokens = (
                    response.usage.completion_tokens if response.usage else None
                )

                # Extraire le JSON de la réponse (peut être enveloppé dans ```json)
                json_str = _extract_json(raw_content)

                # Parser le JSON
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError as exc:
                    # Log la réponse brute (tronquée) pour diagnostic
                    raw_preview = raw_content[:500] if raw_content else "(empty)"
                    visible_tokens_est = len(raw_content) // 4
                    logger.warning(
                        "LLM: JSON invalide (attempt %d/%d) — "
                        "json_error=%s, finish_reason=%s, "
                        "completion_tokens=%s, visible_tokens_est=%d, "
                        "raw_len=%d, raw_preview=%s",
                        attempt + 1,
                        2,
                        str(exc)[:100],
                        finish_reason,
                        completion_tokens,
                        visible_tokens_est,
                        len(raw_content),
                        raw_preview,
                    )

                    # ── Tentative de réparation automatique ──
                    # Avant le retry coûteux (2ème appel LLM complet),
                    # essayer de réparer le JSON tronqué/malformé.
                    # Gère le cas "Unterminated string" (le plus fréquent
                    # avec qwen3.x : chaîne non fermée, finish_reason=stop).
                    repaired_data = _repair_json(json_str, exc)
                    repaired_files = (
                        len(repaired_data.get("file_edits", []))
                        if repaired_data
                        else 0
                    )
                    if repaired_data is not None and repaired_files > 0:
                        # Repair réussie avec du contenu utile
                        repaired_ops = sum(
                            len(fe.get("operations", []))
                            for fe in repaired_data.get("file_edits", [])
                            if fe.get("action") == "edit"
                        )
                        logger.warning(
                            "LLM: JSON réparé automatiquement — "
                            "%d file_edits, %d operations récupérées "
                            "(dernière opération tronquée supprimée)",
                            repaired_files,
                            repaired_ops,
                        )
                        data = repaired_data
                        # Fall through vers la validation ci-dessous
                    elif attempt == 0:
                        # Repair échouée OU repair vide (0 file_edits) → retry
                        if repaired_data is not None and repaired_files == 0:
                            logger.warning(
                                "LLM: JSON réparé mais 0 file_edits "
                                "récupérés — retry au lieu d'accepter"
                            )
                        # Retry avec un rappel plus explicite
                        messages.append({"role": "assistant", "content": raw_content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Ta réponse n'est pas du JSON valide. "
                                    "Retourne UNIQUEMENT un objet JSON valide "
                                    "avec file_edits et synthesis."
                                ),
                            }
                        )
                        continue
                    else:
                        return {
                            "status": "error",
                            "message": "LLM returned invalid JSON after retry",
                            "raw_preview": raw_preview,
                        }

                # Valider la structure minimale
                if "file_edits" not in data or "synthesis" not in data:
                    # Rétrocompat : accepter aussi l'ancien format "bank_files"
                    if "bank_files" in data and "synthesis" in data:
                        data = _convert_legacy_format(data)
                    elif attempt == 0:
                        logger.warning(
                            "LLM: structure invalide (attempt %d), retry...",
                            attempt + 1,
                        )
                        messages.append({"role": "assistant", "content": raw_content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Ta réponse doit contenir 'file_edits' et 'synthesis'. "
                                    "Retourne le JSON au format demandé."
                                ),
                            }
                        )
                        continue
                    else:
                        return {
                            "status": "error",
                            "message": "LLM response missing file_edits or synthesis",
                        }

                # Extraire les métriques d'usage
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                return {"status": "ok", "data": data, "usage": usage}

            except Exception as e:
                return {"status": "error", "message": f"LLM call failed: {str(e)}"}

        return {"status": "error", "message": "LLM failed after retries"}

    async def _write_results(
        self,
        space_id: str,
        llm_output: dict,
        bank_files: list[dict],
        notes_keys: list[str],
        notes_count: int,
        usage: dict,
        skip_meta: bool = False,
    ) -> dict:
        """
        Applique les éditions LLM et écrit les résultats sur S3.

        Pour chaque file_edit :
        - action "edit" : lire le fichier existant, appliquer les opérations, écrire
        - action "create" : écrire le contenu complet (nouveau fichier)
        - action "rewrite" : écrire le contenu complet (réécriture justifiée)

        Ordre : bank files → synthesis → [meta si non skip] → delete notes.
        Les notes sont supprimées EN DERNIER (atomicité logique).

        Args:
            skip_meta: Si True, ne met pas à jour _meta.json (mode batch,
                       le meta est mis à jour une seule fois à la fin)

        Returns:
            Métriques de consolidation
        """
        storage = get_storage()

        # Construire un index des fichiers bank existants par filename SANITISÉ.
        # On sanitise les clés pour matcher avec les filenames du LLM (qui sont
        # aussi sanitisés). On garde la correspondance raw_key → sanitized pour
        # pouvoir nettoyer les anciennes clés S3 contaminées par Unicode.
        bank_index = {}  # sanitized_filename → content
        bank_raw_keys = {}  # sanitized_filename → [liste des clés S3 brutes]
        for bf in bank_files:
            raw_key = bf["key"]
            # Extraire le chemin relatif complet (supporte les sous-dossiers)
            raw_relpath = bank_relpath(raw_key, space_id)
            sanitized = _sanitize_filename(raw_relpath)
            # Si plusieurs clés S3 sanitisent vers le même nom → doublons !
            # On garde la version la plus récente (dernière dans la liste triée)
            bank_index[sanitized] = bf["content"]
            if sanitized not in bank_raw_keys:
                bank_raw_keys[sanitized] = []
            bank_raw_keys[sanitized].append(raw_key)

        files_created = 0
        files_updated = 0
        files_cleaned = 0
        operations_applied = 0
        operations_failed = 0

        async def _cleanup_unicode_duplicates(sanitized_name: str) -> None:
            """Supprime les anciennes clés S3 contaminées par Unicode
            qui sanitisent vers le même nom de fichier."""
            nonlocal files_cleaned
            canonical_key = f"{space_id}/bank/{sanitized_name}"
            raw_keys = bank_raw_keys.get(sanitized_name, [])
            for rk in raw_keys:
                if rk != canonical_key:
                    logger.info(
                        "Cleaning Unicode duplicate: %r → canonical %s",
                        rk,
                        canonical_key,
                    )
                    await storage.delete(rk)
                    files_cleaned += 1

        # 4a. Appliquer chaque édition de fichier
        for file_edit in llm_output.get("file_edits", []):
            filename = _sanitize_filename(file_edit.get("filename", ""))
            action = file_edit.get("action", "edit")

            if not filename:
                logger.warning("file_edit sans filename, ignoré")
                continue

            if action == "create":
                # Nouveau fichier : écriture complète
                content = file_edit.get("content", "")
                if content:
                    await storage.put(f"{space_id}/bank/{filename}", content)
                    await _cleanup_unicode_duplicates(filename)
                    files_created += 1
                    logger.info("Created bank file: %s", filename)

            elif action == "rewrite":
                # Réécriture complète (fallback justifié)
                content = file_edit.get("content", "")
                reason = file_edit.get("reason", "non spécifiée")
                if content:
                    # Déduplication défensive via LLM : le LLM peut produire
                    # un rewrite avec des sections déjà dupliquées
                    content, dedup_count = await self._deduplicate_content(
                        content, filename
                    )
                    await storage.put(f"{space_id}/bank/{filename}", content)
                    await _cleanup_unicode_duplicates(filename)
                    files_updated += 1
                    logger.info("Rewrote bank file: %s (reason: %s)", filename, reason)

            elif action == "edit":
                # Édition chirurgicale : appliquer les opérations
                operations = file_edit.get("operations", [])
                if not operations:
                    continue

                # Lire le contenu existant
                existing_content = bank_index.get(filename)
                if existing_content is None:
                    # Le fichier n'existe pas → le LLM aurait dû utiliser "create"
                    # On tente quand même en partant de rien
                    logger.warning(
                        "edit sur fichier inexistant '%s', traité comme create",
                        filename,
                    )
                    existing_content = ""

                # Appliquer les opérations une par une
                updated_content = existing_content
                for op in operations:
                    try:
                        updated_content = _apply_operation(updated_content, op)
                        operations_applied += 1
                    except Exception as e:
                        logger.error(
                            "Échec opération %s sur %s: %s",
                            op.get("type", "?"),
                            filename,
                            str(e),
                        )
                        operations_failed += 1

                # Déduplication défensive post-opérations via LLM :
                # rattrape les doublons résiduels que les opérations
                # n'ont pas pu corriger (ex: doublons pré-existants)
                updated_content, dedup_count = await self._deduplicate_content(
                    updated_content, filename
                )

                # Écrire seulement si le contenu a changé
                if updated_content != existing_content:
                    await storage.put(f"{space_id}/bank/{filename}", updated_content)
                    await _cleanup_unicode_duplicates(filename)
                    files_updated += 1
                    logger.info(
                        "Updated bank file: %s (%d operations applied)",
                        filename,
                        len(operations),
                    )
            else:
                logger.warning(
                    "Action inconnue '%s' pour %s, ignorée", action, filename
                )

        # 4b. Écrire la synthèse résiduelle
        synthesis_content = llm_output.get("synthesis", "")
        now = datetime.now(timezone.utc).isoformat()
        synthesis_md = (
            f"---\n"
            f'consolidated_at: "{now}"\n'
            f"notes_processed: {notes_count}\n"
            f"mode: surgical_edit\n"
            f"operations_applied: {operations_applied}\n"
            f"operations_failed: {operations_failed}\n"
            f"---\n\n"
            f"{synthesis_content}"
        )
        await storage.put(f"{space_id}/_synthesis.md", synthesis_md)

        # 4c. Mettre à jour _meta.json (sauf en mode batch où le meta
        #     est mis à jour une seule fois à la fin par consolidate())
        if not skip_meta:
            meta = await storage.get_json(f"{space_id}/_meta.json") or {}
            meta["last_consolidation"] = now
            meta["consolidation_count"] = meta.get("consolidation_count", 0) + 1
            meta["total_notes_processed"] = (
                meta.get("total_notes_processed", 0) + notes_count
            )
            await storage.put_json(f"{space_id}/_meta.json", meta)

        # 4d. Supprimer les notes live traitées (EN DERNIER)
        await storage.delete_many(notes_keys)

        # Compter les fichiers bank inchangés
        bank_objects = await storage.list_objects(f"{space_id}/bank/")
        total_bank = len([o for o in bank_objects if not o["Key"].endswith(".keep")])
        files_unchanged = total_bank - files_created - files_updated

        return {
            "status": "ok",
            "space_id": space_id,
            "notes_processed": notes_count,
            "bank_files_updated": files_updated,
            "bank_files_created": files_created,
            "bank_files_unchanged": max(0, files_unchanged),
            "operations_applied": operations_applied,
            "operations_failed": operations_failed,
            "synthesis_size": len(synthesis_content),
            "llm_tokens_used": usage.get("total_tokens", 0),
            "llm_prompt_tokens": usage.get("prompt_tokens", 0),
            "llm_completion_tokens": usage.get("completion_tokens", 0),
        }

    async def _deduplicate_content(
        self, content: str, filename: str
    ) -> tuple[str, int]:
        """
        Détecte et fusionne les sections dupliquées via le LLM.

        Traite UN SEUL doublon par itération, puis re-détecte les doublons
        restants sur le contenu mis à jour. Cela évite le bug d'indices
        décalés (IndexError) qui survenait quand on utilisait les indices
        de la détection initiale après avoir modifié la liste de sections.

        Args:
            content: Contenu Markdown du fichier
            filename: Nom du fichier (pour les logs)

        Returns:
            Tuple (contenu dédupliqué, nombre de doublons fusionnés)
        """
        total_merged = 0
        max_iterations = 50  # Sécurité anti-boucle infinie

        for _ in range(max_iterations):
            # Re-détecter les doublons sur le contenu ACTUEL à chaque itération
            duplicates = _detect_duplicates(content)
            if not duplicates:
                break

            # Traiter le PREMIER doublon trouvé
            heading, indices = next(iter(duplicates.items()))
            sections = _parse_sections(content)

            # Vérifier que les indices sont valides (sécurité défensive)
            if any(i >= len(sections) for i in indices):
                logger.error(
                    "DEDUP %s: indices invalides pour '%s' (max=%d, indices=%s) — skip",
                    filename,
                    heading,
                    len(sections) - 1,
                    indices,
                )
                break

            # Extraire le contenu de chaque version dupliquée
            versions = [sections[i]["content"] for i in indices]

            logger.warning(
                "DEDUP %s: heading '%s' trouvé %d fois — fusion via LLM",
                filename,
                heading,
                len(indices),
            )

            # ── Optimisation : skip LLM si les versions sont identiques
            # ou si l'une est un sous-ensemble de l'autre ──
            stripped = [v.strip() for v in versions]
            unique = set(stripped)

            if len(unique) == 1:
                # Toutes les versions identiques → garder la dernière, pas d'appel LLM
                logger.info(
                    "DEDUP %s: '%s' — %d versions identiques, skip LLM",
                    filename, heading, len(indices),
                )
                merged = stripped[-1]
            elif len(unique) == 2:
                # Vérifier si l'une est un sous-ensemble de lignes de l'autre.
                # On compare au niveau des LIGNES (pas des sous-chaînes) pour
                # éviter les faux positifs comme "OK" in "Jalon OK terminé".
                short_v, long_v = sorted(unique, key=len)
                short_lines = {ln.strip() for ln in short_v.splitlines() if ln.strip()}
                long_lines = {ln.strip() for ln in long_v.splitlines() if ln.strip()}
                if short_lines and short_lines.issubset(long_lines):
                    merged = long_v  # Garder la version la plus complète
                    logger.info(
                        "DEDUP %s: '%s' — %d/%d lignes incluses dans la version longue, skip LLM",
                        filename, heading, len(short_lines), len(long_lines),
                    )
                else:
                    # Versions réellement différentes → appel LLM
                    logger.warning(
                        "DEDUP %s: heading '%s' trouvé %d fois — fusion via LLM",
                        filename, heading, len(indices),
                    )
                    merged = await self._merge_sections_via_llm(heading, versions)
            else:
                # 3+ versions différentes → appel LLM
                logger.warning(
                    "DEDUP %s: heading '%s' trouvé %d fois — fusion via LLM",
                    filename, heading, len(indices),
                )
                merged = await self._merge_sections_via_llm(heading, versions)

            if merged is not None:
                # Garder la DERNIÈRE occurrence, supprimer les précédentes
                last_idx = indices[-1]
                sections[last_idx]["content"] = (
                    "\n" + merged + "\n" if not merged.startswith("\n") else merged
                )

                # Supprimer les occurrences précédentes (en partant de la fin)
                for idx in reversed(indices[:-1]):
                    sections.pop(idx)
                    total_merged += 1
            else:
                # Fallback si le LLM échoue : garder la dernière occurrence
                logger.error(
                    "DEDUP %s: fusion LLM échouée pour '%s' — "
                    "fallback: conservation de la dernière occurrence",
                    filename,
                    heading,
                )
                for idx in reversed(indices[:-1]):
                    sections.pop(idx)
                    total_merged += 1

            # Reconstruire le contenu pour la prochaine itération
            content = _reconstruct_from_sections(sections)

        return content, total_merged

    async def _merge_sections_via_llm(
        self, heading: str, versions: list[str]
    ) -> str | None:
        """
        Appelle le LLM pour fusionner N versions d'une même section.

        Prompt court et ciblé : le LLM reçoit les versions et doit
        retourner une seule version fusionnée, sans perte d'information
        pertinente et sans duplication.

        Args:
            heading: Le heading Markdown de la section (ex: "### État technique V2")
            versions: Liste des contenus des différentes versions

        Returns:
            Contenu fusionné, ou None si l'appel LLM échoue
        """
        versions_text = ""
        for i, v in enumerate(versions, 1):
            versions_text += f"\n--- VERSION {i} ---\n{v.strip()}\n"

        prompt = f"""Tu reçois {len(versions)} versions d'une même section Markdown qui a été dupliquée par erreur.

SECTION : {heading}

{versions_text}

CONSIGNE : Fusionne ces versions en UNE SEULE version cohérente.
- Garde toutes les informations PERTINENTES et À JOUR des deux versions
- Si une version contient des données plus récentes (ex: "322 tests" vs "272 tests"), garde la plus récente
- Supprime les doublons d'information
- Conserve le format et le style Markdown
- Retourne UNIQUEMENT le contenu fusionné (SANS le heading, SANS balises, SANS explication)"""

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],  # type: ignore[list-item]
                max_tokens=4096,
                temperature=0.1,  # Basse température pour la fusion
            )

            merged = response.choices[0].message.content or ""

            # Nettoyer : retirer les blocs <think> et les backticks
            merged = re.sub(r"<think>.*?</think>", "", merged, flags=re.DOTALL)
            merged = re.sub(r"^```(?:markdown)?\s*", "", merged.strip())
            merged = re.sub(r"\s*```$", "", merged.strip())

            logger.info(
                "DEDUP merge OK: '%s' — %d versions → 1 (%d chars)",
                heading,
                len(versions),
                len(merged),
            )
            return merged

        except Exception as e:
            logger.error("DEDUP merge FAILED: '%s' — %s", heading, str(e))
            return None

    async def test_connection(self) -> dict:
        """Teste la connexion au LLMaaS avec un appel minimal."""
        try:
            t0 = time.monotonic()
            await self._client.models.list()
            latency = round((time.monotonic() - t0) * 1000, 1)
            return {
                "status": "ok",
                "model": self._model,
                "latency_ms": latency,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────
    # Bank Compaction
    # ─────────────────────────────────────────────────────────

    def _get_max_size_for_file(self, filename: str) -> int:
        """Retourne la taille max autorisée pour un fichier bank.

        Limite universelle unique — les noms de fichiers dépendent des
        rules de chaque espace et ne sont pas contrôlés par le serveur.
        """
        return self._bank_file_max_size

    async def _compact_bank_if_needed(
        self, space_id: str, bank_files: list[dict], rules: str
    ) -> dict:
        """
        Auto-compact de la bank avant consolidation.

        Vérifie si le prompt total (bank + notes estimées) risque de
        dépasser le seuil configuré. Si oui, compacte chaque fichier
        bank dépassant sa taille max via un appel LLM dédié.

        Inspiré de l'autoCompact de Claude Code — voir CONTEXT_COMPACTION.md.

        Args:
            space_id: Identifiant de l'espace
            bank_files: Liste des fichiers bank actuels
            rules: Rules de l'espace (pour le contexte du LLM)

        Returns:
            Dict avec compacted (bool), files_compacted, size_before, size_after
        """
        storage = get_storage()

        # Estimer la taille totale de la bank
        total_bank_size = sum(len(bf.get("content", "")) for bf in bank_files)
        estimated_bank_tokens = total_bank_size // 4

        # Vérifier si la compaction est nécessaire
        # Seuil : la bank seule consomme déjà > compact_threshold du budget
        if estimated_bank_tokens <= self._max_tokens * self._compact_threshold:
            logger.debug(
                "Bank size OK — %d bytes (~%d tokens), threshold %.0f%% of %d",
                total_bank_size,
                estimated_bank_tokens,
                self._compact_threshold * 100,
                self._max_tokens,
            )
            return {
                "compacted": False,
                "files_compacted": 0,
                "size_before": total_bank_size,
                "size_after": total_bank_size,
            }

        logger.warning(
            "COMPACT — Bank trop grosse : %d bytes (~%d tokens, "
            "seuil=%.0f%% de %d). Compaction en cours...",
            total_bank_size,
            estimated_bank_tokens,
            self._compact_threshold * 100,
            self._max_tokens,
        )

        # Identifier les fichiers à compacter (ceux qui dépassent leur limite)
        files_compacted = 0
        size_before = total_bank_size
        size_after = 0

        for bf in bank_files:
            raw_key = bf["key"]
            raw_relpath = bank_relpath(raw_key, space_id)
            filename = _sanitize_filename(raw_relpath)
            content = bf.get("content", "")
            file_size = len(content)
            max_size = self._get_max_size_for_file(filename)

            if file_size <= max_size:
                size_after += file_size
                continue

            # Ce fichier doit être compacté
            logger.info(
                "COMPACT %s — %d bytes (max %d), compaction via LLM...",
                filename,
                file_size,
                max_size,
            )

            compacted = await self._compact_single_file(
                filename, content, max_size, rules
            )

            if compacted is not None and len(compacted) < file_size:
                # Écrire le fichier compacté sur S3
                await storage.put(f"{space_id}/bank/{filename}", compacted)
                files_compacted += 1
                size_after += len(compacted)
                logger.info(
                    "COMPACT %s — %d → %d bytes (-%d%%)",
                    filename,
                    file_size,
                    len(compacted),
                    round((1 - len(compacted) / file_size) * 100),
                )
            else:
                # Compaction échouée ou pas de réduction → garder l'original
                size_after += file_size
                logger.warning(
                    "COMPACT %s — échec ou pas de réduction, fichier conservé",
                    filename,
                )

        return {
            "compacted": files_compacted > 0,
            "files_compacted": files_compacted,
            "size_before": size_before,
            "size_after": size_after,
        }

    async def _compact_single_file(
        self, filename: str, content: str, max_size: int, rules: str
    ) -> str | None:
        """
        Compacte un seul fichier bank via un appel LLM dédié.

        Le LLM reçoit le contenu actuel et doit le résumer/nettoyer
        pour le ramener sous la taille cible, tout en conservant
        les informations structurantes.

        Args:
            filename: Nom du fichier (pour adapter les instructions)
            content: Contenu Markdown actuel
            max_size: Taille cible en bytes
            rules: Rules de l'espace (contexte)

        Returns:
            Contenu compacté, ou None si l'appel LLM échoue
        """
        # Instructions de compaction génériques — les rules de l'espace
        # définissent la sémantique de chaque fichier, pas le serveur.
        specific = (
            "Synthétise le contenu en gardant la structure des sections.\n"
            "- Fusionne les informations redondantes\n"
            "- Supprime les détails obsolètes ou trop granulaires\n"
            "- Conserve les décisions architecturales et les informations structurantes\n"
            "- Résume les entrées anciennes en une ligne par jalon\n"
            "- Réfère-toi aux RULES DE RÉFÉRENCE ci-dessus pour comprendre le rôle de ce fichier"
        )

        prompt = f"""Tu reçois un fichier bank "{filename}" qui fait {len(content)} bytes
(limite : {max_size} bytes). Tu dois le COMPACTER pour le ramener sous cette limite.

=== RULES DE RÉFÉRENCE ===
{rules[:2000]}

=== INSTRUCTIONS SPÉCIFIQUES ===
{specific}

=== RÈGLES DE COMPACTION ===
- Garde le heading principal (# titre) et la structure des sections (##, ###)
- Résume les blocs redondants ou trop détaillés
- Supprime les éléments terminés/obsolètes
- Fusionne les entrées similaires
- Conserve les dates des jalons importants
- NE PERDS AUCUNE information structurante (décisions, architecture, stack)
- Objectif : ramener SOUS {max_size} bytes

=== CONTENU ACTUEL ===
{content}

Retourne UNIQUEMENT le contenu compacté (Markdown pur, pas de JSON, pas de balises, pas d'explication)."""

        try:
            # Estimer le budget de sortie : on veut ~max_size bytes en sortie
            # + marge pour le formatting. Le contenu max_size / 4 ≈ tokens cibles.
            output_tokens = max(4096, max_size // 3)

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=output_tokens,
                temperature=0.2,  # Basse température pour la compaction
            )

            compacted = response.choices[0].message.content or ""

            # Nettoyer : retirer les blocs <think> et les backticks
            compacted = re.sub(r"<think>.*?</think>", "", compacted, flags=re.DOTALL)
            compacted = re.sub(r"^```(?:markdown)?\s*", "", compacted.strip())
            compacted = re.sub(r"\s*```$", "", compacted.strip())

            return compacted

        except Exception as e:
            logger.error("COMPACT %s FAILED: %s", filename, str(e))
            return None

    async def compact_bank(self, space_id: str, dry_run: bool = True) -> dict:
        """
        Compaction manuelle de la bank d'un espace (outil MCP standalone).

        En mode dry_run, rapporte les fichiers à compacter et leurs tailles
        sans modifier quoi que ce soit.

        Args:
            space_id: Identifiant de l'espace
            dry_run: True = scan seul, False = compaction effective

        Returns:
            Rapport de compaction avec détails par fichier
        """
        storage = get_storage()

        # Vérifier l'existence de l'espace
        meta = await storage.get_json(f"{space_id}/_meta.json")
        if meta is None:
            return {"status": "error", "message": f"Espace '{space_id}' introuvable"}

        # Lire la bank et les rules
        bank_files = await storage.list_and_get(f"{space_id}/bank/")
        rules = await storage.get(f"{space_id}/_rules.md") or ""

        # Analyser chaque fichier
        file_reports = []
        total_before = 0
        total_after = 0
        files_over_limit = 0

        for bf in bank_files:
            raw_relpath = bank_relpath(bf["key"], space_id)
            filename = _sanitize_filename(raw_relpath)
            content = bf.get("content", "")
            file_size = len(content)
            max_size = self._get_max_size_for_file(filename)
            over = file_size > max_size

            total_before += file_size

            report = {
                "filename": filename,
                "size": file_size,
                "max_size": max_size,
                "over_limit": over,
                "ratio": round(file_size / max_size, 2) if max_size > 0 else 0,
            }

            if over:
                files_over_limit += 1
                if not dry_run:
                    # Compacter effectivement
                    compacted = await self._compact_single_file(
                        filename, content, max_size, rules
                    )
                    if compacted is not None and len(compacted) < file_size:
                        await storage.put(f"{space_id}/bank/{filename}", compacted)
                        report["compacted_size"] = len(compacted)
                        report["reduction_pct"] = round(
                            (1 - len(compacted) / file_size) * 100
                        )
                        total_after += len(compacted)
                    else:
                        report["compacted_size"] = file_size
                        report["error"] = "compaction failed or no reduction"
                        total_after += file_size
                else:
                    total_after += file_size
            else:
                total_after += file_size

            file_reports.append(report)

        return {
            "status": "ok",
            "space_id": space_id,
            "dry_run": dry_run,
            "files_total": len(bank_files),
            "files_over_limit": files_over_limit,
            "total_size_before": total_before,
            "total_size_after": total_after if not dry_run else total_before,
            "files": file_reports,
        }


# ─────────────────────────────────────────────────────────────
# Sanitisation des noms de fichiers LLM
# ─────────────────────────────────────────────────────────────

# Caractères Unicode invisibles que les LLMs insèrent parfois dans les
# noms de fichiers (surtout dans les réponses JSON longues — "drift").
# Leur présence crée des clés S3 visuellement identiques mais techniquement
# différentes, rendant les fichiers illisibles par bank_read.
_INVISIBLE_CHARS = frozenset(
    {
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\u202a",  # Left-to-Right Embedding
        "\u202b",  # Right-to-Left Embedding
        "\u202c",  # Pop Directional Formatting
        "\u202d",  # Left-to-Right Override
        "\u202e",  # Right-to-Left Override
        "\u2060",  # Word Joiner
        "\u2061",  # Function Application
        "\u2062",  # Invisible Times
        "\u2063",  # Invisible Separator
        "\u2064",  # Invisible Plus
        "\ufeff",  # Byte Order Mark (ZWNBS)
        "\u00ad",  # Soft Hyphen
        "\u034f",  # Combining Grapheme Joiner
        "\u061c",  # Arabic Letter Mark
        "\u180e",  # Mongolian Vowel Separator
    }
)

# Caractères Unicode ressemblant à des tirets mais qui ne sont pas
# le tiret ASCII standard (U+002D). Normalisés vers '-'.
_HYPHEN_LIKE = frozenset(
    {
        "\u2010",  # Hyphen
        "\u2011",  # Non-Breaking Hyphen
        "\u2012",  # Figure Dash
        "\u2013",  # En Dash
        "\u2014",  # Em Dash
        "\u2015",  # Horizontal Bar
        "\u2212",  # Minus Sign
        "\ufe58",  # Small Em Dash
        "\ufe63",  # Small Hyphen-Minus
        "\uff0d",  # Fullwidth Hyphen-Minus
    }
)


def _sanitize_filename(filename: str) -> str:
    """
    Nettoie un nom de fichier généré par le LLM.

    Supprime les caractères Unicode invisibles et normalise les tirets
    Unicode vers le tiret ASCII standard (U+002D).

    Bug découvert le 13/03/2026 : le LLM insère des
    caractères invisibles dans les noms de fichiers à partir du ~8ème
    fichier dans les réponses JSON longues. Ces caractères rendent
    les fichiers illisibles par bank_read (qui reconstruit la clé S3
    manuellement) alors que bank_read_all fonctionne (utilise les
    vraies clés S3 depuis list_objects).

    Args:
        filename: Nom de fichier brut issu du JSON LLM

    Returns:
        Nom de fichier nettoyé (ASCII + caractères courants uniquement)
    """
    chars = []
    removed = 0
    normalized = 0

    for ch in filename:
        if ch in _INVISIBLE_CHARS:
            removed += 1
            continue
        elif ch in _HYPHEN_LIKE:
            chars.append("-")
            normalized += 1
        else:
            chars.append(ch)

    sanitized = "".join(chars).strip()

    # Nettoyer les préfixes parasites que le LLM invente en lisant les rules.
    # Ex: les rules presales disent "ILS SONT DANS LE REPERTOIRE 1.MEMORY_BANK"
    # → le LLM retourne "1.MEMORY_BANK/personaProfiles/acheteur.md"
    # On retire ces préfixes connus mais on GARDE les sous-dossiers légitimes.
    _PARASITIC_PREFIXES = ("1.MEMORY_BANK/", "MEMORY_BANK/", "bank/")
    for prefix in _PARASITIC_PREFIXES:
        if sanitized.startswith(prefix):
            old = sanitized
            sanitized = sanitized[len(prefix) :]
            logger.warning(
                "Filename parasitic prefix removed: %r → %r",
                old,
                sanitized,
            )

    # Nettoyer les / en début/fin et les doubles //
    sanitized = sanitized.strip("/")
    while "//" in sanitized:
        sanitized = sanitized.replace("//", "/")

    if removed > 0 or normalized > 0:
        logger.warning(
            "Filename sanitized: %r → %r (removed %d invisible, normalized %d hyphens)",
            filename,
            sanitized,
            removed,
            normalized,
        )

    return sanitized


# ─────────────────────────────────────────────────────────────
# Moteur d'édition Markdown
# ─────────────────────────────────────────────────────────────


def _parse_sections(content: str) -> list[dict]:
    """
    Parse un fichier Markdown en sections.

    Chaque section est définie par un heading (# ## ### etc.) et contient
    tout le texte jusqu'au prochain heading de même niveau ou supérieur.

    Returns:
        Liste de dicts :
        {
            "heading": "## Section Title" (ou "" pour le préambule),
            "heading_text": "Section Title" (sans les #),
            "level": 2 (nombre de #, 0 pour le préambule),
            "content": "lignes de contenu après le heading\\n...",
            "start_line": 0  (index de ligne du heading)
        }
    """
    lines = content.split("\n")
    sections = []
    current_heading = ""
    current_heading_text = ""
    current_level = 0
    current_content_lines = []
    current_start = 0

    for i, line in enumerate(lines):
        # Détecter un heading Markdown (# à ######)
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)

        if heading_match:
            # Sauvegarder la section précédente
            sections.append(
                {
                    "heading": current_heading,
                    "heading_text": current_heading_text,
                    "level": current_level,
                    "content": "\n".join(current_content_lines),
                    "start_line": current_start,
                }
            )

            # Commencer une nouvelle section
            hashes = heading_match.group(1)
            current_heading = line
            current_heading_text = heading_match.group(2).strip()
            current_level = len(hashes)
            current_content_lines = []
            current_start = i
        else:
            current_content_lines.append(line)

    # Sauvegarder la dernière section
    sections.append(
        {
            "heading": current_heading,
            "heading_text": current_heading_text,
            "level": current_level,
            "content": "\n".join(current_content_lines),
            "start_line": current_start,
        }
    )

    return sections


def _find_section_index(sections: list[dict], heading: str) -> int:
    """
    Trouve l'index d'une section par son heading.

    Matching flexible :
    - Correspondance exacte : "## Focus Actuel"
    - Sans les # : "Focus Actuel"
    - Case-insensitive en dernier recours

    Returns:
        Index dans la liste sections, ou -1 si non trouvé
    """
    heading_stripped = heading.strip()

    # 1. Correspondance exacte
    for i, sec in enumerate(sections):
        if sec["heading"].strip() == heading_stripped:
            return i

    # 2. Sans les # (le LLM a peut-être omis les ##)
    heading_no_hash = re.sub(r"^#+\s*", "", heading_stripped)
    for i, sec in enumerate(sections):
        if sec["heading_text"] == heading_no_hash:
            return i

    # 3. Case-insensitive
    heading_lower = heading_no_hash.lower()
    for i, sec in enumerate(sections):
        if sec["heading_text"].lower() == heading_lower:
            return i

    return -1


def _reconstruct_from_sections(sections: list[dict]) -> str:
    """
    Reconstruit un fichier Markdown à partir de sections parsées.

    Returns:
        Contenu Markdown reconstruit
    """
    parts = []
    for sec in sections:
        if sec["heading"]:
            parts.append(sec["heading"])
        if sec["content"]:
            parts.append(sec["content"])
        elif sec["heading"]:
            # Section avec heading mais sans contenu : ajouter une ligne vide
            parts.append("")

    result = "\n".join(parts)

    # Nettoyer les lignes vides multiples (max 2 consécutives)
    result = re.sub(r"\n{4,}", "\n\n\n", result)

    return result


def _apply_operation(content: str, operation: dict) -> str:
    """
    Applique une seule opération d'édition sur un contenu Markdown.

    Args:
        content: Contenu Markdown du fichier
        operation: Dict avec "type", "heading", "content", etc.

    Returns:
        Contenu Markdown modifié

    Raises:
        ValueError: Si l'opération est invalide ou la section introuvable
    """
    op_type = operation.get("type", "")
    heading = operation.get("heading", "")
    new_content = operation.get("content", "")

    if op_type == "replace_section":
        return _op_replace_section(content, heading, new_content)
    elif op_type == "append_to_section":
        return _op_append_to_section(content, heading, new_content)
    elif op_type == "prepend_to_section":
        return _op_prepend_to_section(content, heading, new_content)
    elif op_type == "add_section":
        after = operation.get("after", "")
        return _op_add_section(content, heading, new_content, after)
    elif op_type == "delete_section":
        return _op_delete_section(content, heading)
    else:
        raise ValueError(f"Type d'opération inconnu: {op_type}")


def _op_replace_section(content: str, heading: str, new_content: str) -> str:
    """
    Remplace le contenu d'une section (entre le heading et le prochain
    heading de même niveau ou supérieur).

    Le heading lui-même est conservé.
    """
    sections = _parse_sections(content)
    idx = _find_section_index(sections, heading)

    if idx == -1:
        raise ValueError(f"Section non trouvée: {heading}")

    # Remplacer le contenu de la section
    # S'assurer que le nouveau contenu commence et finit proprement
    if new_content and not new_content.startswith("\n"):
        new_content = "\n" + new_content
    if new_content and not new_content.endswith("\n"):
        new_content = new_content + "\n"

    sections[idx]["content"] = new_content

    return _reconstruct_from_sections(sections)


def _op_append_to_section(content: str, heading: str, new_content: str) -> str:
    """
    Ajoute du contenu à la fin d'une section existante.
    Le contenu existant est intégralement préservé.
    """
    sections = _parse_sections(content)
    idx = _find_section_index(sections, heading)

    if idx == -1:
        raise ValueError(f"Section non trouvée: {heading}")

    existing = sections[idx]["content"]

    # Ajouter le nouveau contenu après l'existant
    if existing.rstrip():
        sections[idx]["content"] = existing.rstrip("\n") + "\n" + new_content + "\n"
    else:
        sections[idx]["content"] = "\n" + new_content + "\n"

    return _reconstruct_from_sections(sections)


def _op_prepend_to_section(content: str, heading: str, new_content: str) -> str:
    """
    Ajoute du contenu au début d'une section (après le heading).
    Le contenu existant est intégralement préservé.
    """
    sections = _parse_sections(content)
    idx = _find_section_index(sections, heading)

    if idx == -1:
        raise ValueError(f"Section non trouvée: {heading}")

    existing = sections[idx]["content"]

    # Ajouter le nouveau contenu avant l'existant
    if existing.lstrip():
        sections[idx]["content"] = "\n" + new_content + "\n" + existing.lstrip("\n")
    else:
        sections[idx]["content"] = "\n" + new_content + "\n"

    return _reconstruct_from_sections(sections)


def _op_add_section(
    content: str, heading: str, new_content: str, after: str = ""
) -> str:
    """
    Ajoute une nouvelle section au fichier.

    Si 'after' est spécifié, insère après cette section.
    Sinon, ajoute à la fin du fichier.

    GARDE-FOU ANTI-DOUBLON (v1.3.0) : si une section avec le même
    heading existe déjà, l'opération est automatiquement convertie
    en replace_section pour éviter les doublons récurrents.
    """
    sections = _parse_sections(content)

    # ── GARDE-FOU : vérifier si le heading existe déjà ────
    existing_idx = _find_section_index(sections, heading)
    if existing_idx != -1:
        logger.warning(
            "add_section '%s' AUTO-CONVERTI en replace_section "
            "(section déjà existante à l'index %d)",
            heading,
            existing_idx,
        )
        return _op_replace_section(content, heading, new_content)

    # Déterminer le niveau du heading
    heading_match = re.match(r"^(#{1,6})\s+(.+)$", heading.strip())
    if heading_match:
        level = len(heading_match.group(1))
        heading_text = heading_match.group(2).strip()
    else:
        # Pas de # → on assume ## (section de 2ème niveau)
        level = 2
        heading_text = heading.strip()
        heading = f"## {heading_text}"

    new_section = {
        "heading": heading,
        "heading_text": heading_text,
        "level": level,
        "content": "\n" + new_content + "\n",
        "start_line": -1,
    }

    if after:
        # Insérer après la section spécifiée
        idx = _find_section_index(sections, after)
        if idx != -1:
            sections.insert(idx + 1, new_section)
        else:
            # Section 'after' non trouvée → ajouter à la fin
            logger.warning(
                "Section 'after' non trouvée: %s — ajout en fin de fichier", after
            )
            sections.append(new_section)
    else:
        sections.append(new_section)

    return _reconstruct_from_sections(sections)


def _detect_duplicates(content: str) -> dict[str, list[int]]:
    """
    Détecte les sections dupliquées dans un fichier Markdown.

    Tient compte de la HIÉRARCHIE : deux headings identiques (ex: ### X)
    sous des parents différents (ex: ## A et ## B) sont des sections
    DISTINCTES, pas des doublons.

    L'identifiant complet d'une section est construit en préfixant
    le heading avec son parent hiérarchique le plus proche (heading
    de niveau strictement supérieur trouvé en remontant).

    Returns:
        Dict heading_key → [index1, index2, ...] pour les headings qui
        apparaissent plus d'une fois sous le même parent.
        Vide si pas de doublons.
    """
    sections = _parse_sections(content)

    # Compter les occurrences de chaque heading en tenant compte du chemin
    # hiérarchique COMPLET (tous les ancêtres, pas seulement le parent direct).
    # Ex: "## Parent A > ### Child > #### Grandchild"
    heading_indices: dict[str, list[int]] = {}
    for i, sec in enumerate(sections):
        h = sec["heading"].strip()
        if not h:  # Ignorer le préambule (heading vide)
            continue

        level = sec["level"]

        # Construire le chemin hiérarchique complet en remontant
        # vers tous les ancêtres (niveaux strictement décroissants)
        ancestors = []
        current_level = level
        if level > 1:
            for j in range(i - 1, -1, -1):
                jlevel = sections[j]["level"]
                if jlevel > 0 and jlevel < current_level:
                    ancestors.insert(0, sections[j]["heading"].strip())
                    current_level = jlevel
                    if current_level <= 1:
                        break

        # Identifiant hiérarchique complet :
        # "## Parent A > ### Child > #### Grandchild"
        if ancestors:
            full_key = " > ".join(ancestors) + " > " + h
        else:
            full_key = h

        if full_key not in heading_indices:
            heading_indices[full_key] = []
        heading_indices[full_key].append(i)

    # Ne garder que les headings dupliqués (même heading + même parent)
    return {h: indices for h, indices in heading_indices.items() if len(indices) > 1}


def _op_delete_section(content: str, heading: str) -> str:
    """
    Supprime une section entière (heading + contenu).
    """
    sections = _parse_sections(content)
    idx = _find_section_index(sections, heading)

    if idx == -1:
        raise ValueError(f"Section non trouvée pour suppression: {heading}")

    # Supprimer la section
    sections.pop(idx)

    return _reconstruct_from_sections(sections)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """
    Extrait le JSON d'une réponse LLM qui peut le contenir dans :
    - Un bloc ```json ... ```
    - Un bloc <think>...</think> suivi de JSON
    - Du texte brut avec un objet JSON {}

    Args:
        text: Réponse brute du LLM

    Returns:
        Chaîne JSON nettoyée prête pour json.loads()
    """
    # 1. Retirer les blocs <think>...</think> (Qwen thinking mode)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # 2. Chercher un bloc ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Chercher un bloc ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if candidate.startswith("{"):
            return candidate

    # 4. Chercher le premier { ... } (objet JSON brut)
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1]

    # 5. Retourner le texte tel quel (json.loads() échouera)
    return text.strip()


def _repair_json(json_str: str, exc: json.JSONDecodeError) -> dict | None:
    """
    Tente de réparer un JSON tronqué/malformé provenant du LLM.

    Gère le cas "Unterminated string" (le plus fréquent avec qwen3.x) :
    le modèle génère une chaîne JSON dont une valeur string n'est
    jamais fermée (ex: guillemet ou caractère spécial non échappé).
    finish_reason=stop mais le JSON est structurellement invalide.

    Stratégie :
    1. Tronquer au point de l'erreur (avant la chaîne non terminée)
    2. Ajouter une chaîne vide "" comme placeholder
    3. Fermer toutes les structures JSON ouvertes ({, [)
    4. Parser le JSON réparé
    5. Supprimer la dernière opération (celle avec le contenu tronqué)
    6. Ajouter un champ "synthesis" par défaut s'il est absent

    Avantages vs retry :
    - Récupère ~90% des opérations instantanément (0 latence)
    - Économise 1 appel LLM complet (~100s + ~50K tokens)
    - Si la réparation échoue, le retry existant prend le relais

    Args:
        json_str: Chaîne JSON extraite par _extract_json()
        exc: L'exception JSONDecodeError avec la position de l'erreur

    Returns:
        Dict parsé si la réparation réussit, None sinon
    """
    error_msg = str(exc)

    if "Unterminated string" not in error_msg:
        return None

    pos = exc.pos
    if not pos or pos <= 0 or pos >= len(json_str):
        return None

    # ── Étape 1 : Tronquer avant la chaîne non terminée ──
    # exc.pos pointe vers le `"` ouvrant de la chaîne qui n'a pas de `"` fermant.
    # Tout ce qui précède cette position est du JSON valide (parsé sans erreur).
    # On ajoute "" comme placeholder pour la valeur tronquée.
    prefix = json_str[:pos] + '""'

    # ── Étape 2 : Fermer toutes les structures ouvertes ──
    repaired_str = _close_json_structure(prefix)
    if repaired_str is None:
        return None

    # ── Étape 3 : Parser le JSON réparé ──
    try:
        data = json.loads(repaired_str)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or "file_edits" not in data:
        return None

    # ── Étape 4 : Nettoyer les opérations tronquées ──
    # La dernière opération du dernier file_edit a un content="" (notre placeholder).
    # Plutôt que d'appliquer une opération replace_section avec un contenu vide
    # (qui effacerait la section), on la supprime proprement.
    file_edits = data.get("file_edits", [])
    if file_edits:
        last_edit = file_edits[-1]
        if last_edit.get("action") == "edit":
            ops = last_edit.get("operations", [])
            if ops:
                last_op = ops[-1]
                # Supprimer l'opération si son contenu est vide (= tronquée)
                if not last_op.get("content", "").strip():
                    ops.pop()
                    logger.info(
                        "JSON repair: suppression de l'opération tronquée "
                        "(%s sur '%s')",
                        last_op.get("type", "?"),
                        last_op.get("heading", "?"),
                    )
                # Si plus aucune opération, supprimer le file_edit vide
                if not ops:
                    file_edits.pop()
        elif last_edit.get("action") in ("create", "rewrite"):
            # Pour create/rewrite, le content est le fichier entier.
            # S'il est vide, le file_edit est inutile.
            if not last_edit.get("content", "").strip():
                file_edits.pop()

    # ── Étape 5 : Ajouter synthesis par défaut si absent ──
    if "synthesis" not in data:
        data["synthesis"] = (
            "(consolidation partielle — JSON réparé automatiquement, "
            "dernière opération tronquée supprimée)"
        )

    return data


def _close_json_structure(partial_json: str) -> str | None:
    """
    Ferme toutes les structures JSON ouvertes à la fin d'un JSON partiel.

    Parcourt le JSON en suivant les guillemets (strings) et empile les
    ouvertures { et [. Puis ajoute les fermetures manquantes dans l'ordre.

    Robuste face aux strings contenant des accolades/crochets échappés.

    Args:
        partial_json: JSON partiel (potentiellement non terminé)

    Returns:
        JSON complété avec les fermetures manquantes, ou None si
        on est encore dans une string non fermée (irréparable)
    """
    stack = []
    in_string = False
    escape_next = False

    for ch in partial_json:
        if escape_next:
            escape_next = False
            continue

        if in_string:
            if ch == "\\":
                escape_next = True
            elif ch == '"':
                in_string = False
            continue

        # Hors d'une string
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()

    # Si on est encore dans une string, la réparation est impossible
    # (notre caller aurait dû fermer la string avant d'appeler)
    if in_string:
        return None

    if not stack:
        return partial_json

    # Fermer toutes les structures ouvertes dans l'ordre inverse
    closing = "".join(reversed(stack))
    return partial_json + closing


def _convert_legacy_format(data: dict) -> dict:
    """
    Convertit l'ancien format de réponse LLM (bank_files) vers le nouveau
    format (file_edits). Sert de filet de sécurité si le LLM retombe
    sur l'ancien format malgré le nouveau prompt.

    Ancien format:
        {"bank_files": [{"filename": "x.md", "content": "...", "action": "updated"}]}

    Nouveau format:
        {"file_edits": [{"filename": "x.md", "action": "rewrite", "content": "..."}]}
    """
    file_edits = []
    for bf in data.get("bank_files", []):
        old_action = bf.get("action", "updated")
        file_edits.append(
            {
                "filename": bf.get("filename", ""),
                "action": "create" if old_action == "created" else "rewrite",
                "content": bf.get("content", ""),
                "reason": "Legacy format conversion (LLM used old bank_files format)",
            }
        )

    return {
        "file_edits": file_edits,
        "synthesis": data.get("synthesis", ""),
    }


# ─────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────

_consolidator: ConsolidatorService | None = None


def get_consolidator() -> ConsolidatorService:
    """Retourne le singleton ConsolidatorService."""
    global _consolidator
    if _consolidator is None:
        _consolidator = ConsolidatorService()
    return _consolidator
