# -*- coding: utf-8 -*-
"""
Tests — Issue #17 — Pass de validation `unattributed_claims_count` + markers [inféré].

Stratégie : tests purement code-only (déterministes, zéro appel LLM).
Chaque test décrit un scénario d'écriture bank et vérifie que le détecteur
de claims non sourcés donne le verdict attendu.

Convention : test_FIXNAME_blocks_ATTACK quand il s'agit de prouver qu'un
faux claim est correctement détecté (preuve par contrapposée).
"""

from __future__ import annotations

import pytest

from live_mem.core.consolidator import (
    SYSTEM_PROMPT,
    _validate_unattributed_claims,
    _extract_claim_tokens,
    _has_strong_status_claim,
    _normalize_for_match,
    _INFERRED_MARKER_RE,
)


# =============================================================================
# Helpers internes — `_extract_claim_tokens`, `_has_strong_status_claim`, etc.
# =============================================================================


class TestExtractClaimTokens:
    """`_extract_claim_tokens` doit extraire les signatures vérifiables."""

    def test_extracts_metric_with_tests(self):
        tokens = _extract_claim_tokens("171/171 tests PASS")
        # "171" devrait être normalisé via "171 tests" pattern
        assert any("171" in t for t in tokens), f"got {tokens}"

    def test_extracts_percentage(self):
        tokens = _extract_claim_tokens("Réduction de 80% sur les batches")
        assert any("80%" in t.replace(" ", "") for t in tokens), f"got {tokens}"

    def test_extracts_iso_date(self):
        tokens = _extract_claim_tokens("Mergé le 2026-05-15")
        assert "2026-05-15" in tokens

    def test_extracts_french_date(self):
        tokens = _extract_claim_tokens("Mergé le 15/05/2026")
        assert "15/05/2026" in tokens

    def test_extracts_short_date(self):
        tokens = _extract_claim_tokens("Phase démarrée le 12/03")
        assert "12/03" in tokens

    def test_extracts_version(self):
        tokens = _extract_claim_tokens("Release v2.0.0 publiée")
        assert "v2.0.0" in tokens

    def test_extracts_pr_ref(self):
        tokens = _extract_claim_tokens("PR #14 fermée")
        assert "#14" in tokens

    def test_returns_empty_on_pure_structural_line(self):
        # Pas de chiffre, pas de date, pas de version, pas de #ref
        assert _extract_claim_tokens("## Section title") == set()
        assert _extract_claim_tokens("- Bullet sans chiffre") == set()
        assert _extract_claim_tokens("") == set()


class TestHasStrongStatusClaim:
    """`_has_strong_status_claim` détecte les changements d'état revendiqués."""

    @pytest.mark.parametrize(
        "line",
        [
            "Bug résolu hier",
            "Bug resolu hier",
            "PR mergé",
            "Branch merged",
            "v2.0.0 publié",
            "Issue fermée",
            "Tests passed",
            "Tests failed",
            "Build OK",
        ],
    )
    def test_detects_status_keywords(self, line):
        assert _has_strong_status_claim(line), f"missed status in: {line}"

    @pytest.mark.parametrize(
        "line",
        [
            "Réflexion sur l'architecture",
            "## Focus actuel",
            "- Tâche en cours",
        ],
    )
    def test_no_status_on_neutral_lines(self, line):
        assert not _has_strong_status_claim(line)


class TestNormalizeForMatch:
    """`_normalize_for_match` doit garder les tokens-clés intacts."""

    def test_keeps_version_intact(self):
        assert "v2.0.0" in _normalize_for_match("Version v2.0.0 publiée")

    def test_keeps_pr_ref_intact(self):
        assert "#14" in _normalize_for_match("PR #14 mergée")

    def test_keeps_percentage(self):
        # On garde le chiffre et le % collé
        normalized = _normalize_for_match("Réduction 80% obtenue")
        assert "80%" in normalized

    def test_strips_punctuation_around_numbers(self):
        # "171" doit apparaître dans la forme normalisée
        normalized = _normalize_for_match("Total: 171/171 tests, OK.")
        assert "171/171" in normalized

    def test_case_insensitive(self):
        assert _normalize_for_match("ABC") == _normalize_for_match("abc")


class TestInferredMarkerRegex:
    """Le regex `[inféré]` doit reconnaître les variantes du LLM."""

    @pytest.mark.parametrize(
        "line",
        [
            "Phase 2 terminée [inféré]",
            "Phase 2 terminée [inféré, suite progress Phase 3]",
            "Phase 2 terminée [INFÉRÉ]",
            "Phase 2 terminée [Inféré, raison]",
        ],
    )
    def test_matches_variants(self, line):
        assert _INFERRED_MARKER_RE.search(line) is not None, f"missed in: {line}"

    @pytest.mark.parametrize(
        "line",
        [
            "Phase 2 terminée",  # pas de marker
            "Phase 2 inféré sans crochets",  # sans crochets
            "[infered] mauvais accent",  # accent absent
        ],
    )
    def test_rejects_non_marker(self, line):
        assert _INFERRED_MARKER_RE.search(line) is None


# =============================================================================
# `_validate_unattributed_claims` — preuves par contrapposée
# =============================================================================


def _note(content: str) -> dict:
    """Helper : fabriquer une note minimale (juste son `content`)."""
    return {"content": content}


class TestValidateUnattributedClaims_HappyPaths:
    """Cas où la consolidation est sourcée correctement → 0 claim non sourcé."""

    def test_no_changes_returns_zero(self):
        """Si la bank n'a pas bougé, aucun claim ajouté."""
        before = {"activeContext.md": "## Focus\nRien"}
        after = before.copy()
        result = _validate_unattributed_claims(before, after, [_note("note 1")], 20)
        assert result["unattributed_claims_count"] == 0
        assert result["lines_added"] == 0

    def test_sourced_metric_is_attributed(self):
        """Métrique 171/171 présente dans une note → claim attribué."""
        before = {"progress.md": "# Progress\n"}
        after = {"progress.md": "# Progress\n- 171/171 tests PASS"}
        notes = [_note("Suite complète : 171/171 tests PASS, aucune régression.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0
        assert result["lines_scanned"] >= 1, "the metric line must be scanned"

    def test_sourced_date_is_attributed(self):
        before = {"progress.md": ""}
        after = {"progress.md": "- v2.0.0 publiée le 15/05/2026"}
        notes = [_note("Release v2.0.0 mergée sur main le 15/05/2026.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0

    def test_sourced_pr_ref_is_attributed(self):
        before = {"progress.md": ""}
        after = {"progress.md": "- PR #14 mergée"}
        notes = [_note("PR #14 review terminée, prête à merge.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0

    def test_inferred_marker_excludes_line(self):
        """Une ligne marquée `[inféré]` ne compte pas comme non sourcé,
        même si les tokens ne sont pas dans les notes."""
        before = {"progress.md": ""}
        # 999 jours n'est PAS dans la note → mais le marker est explicite
        after = {"progress.md": "- 999 jours écoulés [inféré, suite migration]"}
        notes = [_note("Migration en cours.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0
        assert result["inferred_claims_count"] == 1


class TestValidateUnattributedClaims_DetectsHallucinations:
    """Preuves par contrapposée — sans le pass, les hallucinations passent."""

    def test_blocks_invented_metric(self):
        """Le LLM invente 999/999 tests, la note n'en parle pas."""
        before = {"progress.md": "# Progress\n"}
        after = {"progress.md": "# Progress\n- 999/999 tests PASS"}
        notes = [_note("Travail en cours sur l'authentification.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1
        assert any(
            "999/999" in ex["line"] or "999" in " ".join(ex["tokens"])
            for ex in result["examples"]
        ), f"examples: {result['examples']}"

    def test_blocks_invented_date(self):
        before = {"progress.md": ""}
        after = {"progress.md": "- Migration lancée le 2024-01-01"}
        notes = [_note("Migration en cours, pas de date précise.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1

    def test_blocks_invented_pr_ref(self):
        before = {"progress.md": ""}
        after = {"progress.md": "- PR #9999 reviewée"}
        notes = [_note("Quelques notes sans référence à des PRs précises.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1

    def test_blocks_invented_version(self):
        before = {"progress.md": ""}
        after = {"progress.md": "- Release v99.99.99 publiée"}
        notes = [_note("Préparation d'une release prochaine.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1

    def test_blocks_invented_status_without_source(self):
        """Statut fort 'résolu' sans aucune source dans les notes."""
        before = {"progress.md": "## Bugs\n- bug X ouvert"}
        after = {"progress.md": "## Bugs\n- bug X ouvert\n- bug Y résolu"}
        # La note ne parle ni de bug Y ni de résolution
        notes = [_note("Sprint planning en cours.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1

    def test_accepts_status_when_mentioned_in_notes(self):
        """Inverse du précédent : la note dit 'résolu' → la ligne est OK."""
        before = {"progress.md": ""}
        after = {"progress.md": "- bug Y résolu"}
        notes = [_note("Le bug Y a été résolu lors de la session de hier.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0


class TestValidateUnattributedClaims_BorneExamples:
    """Le compteur d'exemples est borné par `max_examples`."""

    def test_examples_capped(self):
        before = {"f.md": ""}
        # 10 claims non sourcés dans 1 fichier
        after_lines = [f"- {i}/{i} tests PASS" for i in range(100, 110)]
        after = {"f.md": "\n".join(after_lines)}
        notes = [_note("Rien à voir.")]
        result = _validate_unattributed_claims(before, after, notes, max_examples=3)
        assert result["unattributed_claims_count"] == 10
        assert len(result["examples"]) == 3, "examples doivent être bornés à 3"

    def test_zero_examples_when_max_is_zero(self):
        before = {"f.md": ""}
        after = {"f.md": "- 99/99 tests"}
        notes = [_note("rien")]
        result = _validate_unattributed_claims(before, after, notes, max_examples=0)
        assert result["unattributed_claims_count"] == 1
        assert result["examples"] == []


class TestValidateUnattributedClaims_DiffOnly:
    """Le pass ne doit regarder QUE les lignes ajoutées (diff)."""

    def test_existing_unsourced_lines_are_not_flagged(self):
        """Les lignes pré-existantes (potentiellement non sourcées par
        de vieilles consolidations) ne sont JAMAIS scannées : on ne
        regarde que ce que le batch courant a ajouté."""
        old_line = "- 42 tests PASS (vieille entrée jamais sourcée)"
        before = {"progress.md": old_line}
        # Pas de changement → 0 même si la ligne porte un claim non sourcé
        after = {"progress.md": old_line}
        notes = [_note("Travail en cours.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 0

    def test_new_file_with_unsourced_metric_is_flagged(self):
        before = {}
        after = {"new.md": "- 555 tests PASS"}
        notes = [_note("Démarrage projet.")]
        result = _validate_unattributed_claims(before, after, notes, 20)
        assert result["unattributed_claims_count"] == 1


# =============================================================================
# SYSTEM_PROMPT — règle #8 [inféré]
# =============================================================================


class TestSystemPromptRule8:
    """Le SYSTEM_PROMPT doit contenir la règle [inféré]."""

    def test_rule_8_present_in_system_prompt(self):
        assert "[inféré]" in SYSTEM_PROMPT, (
            "Sans la règle #8 : le LLM ne signalera pas ses inférences, "
            "et le pass de validation rapportera des faux positifs"
        )

    def test_rule_8_mentions_inference_transitive(self):
        # La règle #8 doit faire référence à l'inférence transitive ou
        # à la déduction logique, pour que le LLM sache quand l'appliquer.
        assert (
            "INFÉRENCE TRANSITIVE" in SYSTEM_PROMPT
            or "déduction logique" in SYSTEM_PROMPT
        )

    def test_rule_8_provides_examples(self):
        # On vérifie la présence d'au moins un exemple littéral de la règle.
        # Cela protège contre les régressions de prompt qui retireraient
        # les exemples (qui sont cruciaux pour les modèles plus petits).
        assert "Migration terminée [inféré]" in SYSTEM_PROMPT


# =============================================================================
# Config — opt-in default OFF
# =============================================================================


class TestValidationConfig:
    """Les ENV vars Issue #17 doivent être opt-in (default OFF)."""

    def test_validation_disabled_by_default(self):
        # Import depuis l'objet Settings sans le singleton pour tester
        # la valeur par défaut en isolation.
        from live_mem.config import Settings

        s = Settings()
        assert s.consolidation_validation_enabled is False, (
            "Issue #17 doit être opt-in (zéro impact pour les déploiements "
            "existants tant qu'on n'active pas explicitement la feature)"
        )

    def test_validation_max_examples_default_is_bounded(self):
        from live_mem.config import Settings

        s = Settings()
        # Borne raisonnable : pas trop élevée pour éviter un payload énorme,
        # pas trop basse pour rester informatif.
        assert 1 <= s.consolidation_validation_max_examples <= 100

    def test_validation_can_be_enabled_via_env(self, monkeypatch):
        from live_mem.config import Settings

        monkeypatch.setenv("CONSOLIDATION_VALIDATION_ENABLED", "true")
        s = Settings()
        assert s.consolidation_validation_enabled is True
