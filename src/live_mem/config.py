# -*- coding: utf-8 -*-
"""
Configuration du service MCP Live Memory via pydantic-settings.

Toutes les variables sont chargées depuis :
1. Variables d'environnement (priorité haute)
2. Fichier .env (priorité basse)

Usage :
    from .config import get_settings
    settings = get_settings()
    print(settings.s3_bucket_name)
"""

import logging
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_logger = logging.getLogger("live_mem.config")


def _parse_csv_allowlist(value: str, setting_name: str) -> list[str]:
    """Parse a strict comma-separated HTTP security allowlist."""
    values = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not values:
        raise ValueError(f"{setting_name} must contain at least one value")
    return values


def _validate_host_allowlist(value: str) -> str:
    values = _parse_csv_allowlist(value, "MCP_ALLOWED_HOSTS")
    for host in values:
        base_host = host[:-2] if host.endswith(":*") else host
        if host == "*" or "/" in host or "@" in host or not base_host:
            raise ValueError("MCP_ALLOWED_HOSTS only accepts exact hosts or a ':*' port suffix")
        if "*" in base_host:
            raise ValueError("MCP_ALLOWED_HOSTS only permits the ':*' port suffix")
    return ",".join(values)


def _validate_origin_allowlist(value: str) -> str:
    values = _parse_csv_allowlist(value, "MCP_ALLOWED_ORIGINS")
    for origin in values:
        if origin == "*" or "*" in origin[:-2] or ("*" in origin and not origin.endswith(":*")):
            raise ValueError("MCP_ALLOWED_ORIGINS only permits the ':*' port suffix")
        parsed = urlsplit(origin[:-2] if origin.endswith(":*") else origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MCP_ALLOWED_ORIGINS must contain absolute http(s) origins")
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("MCP_ALLOWED_ORIGINS must not contain a path, query, or credentials")
    return ",".join(values)


class Settings(BaseSettings):
    """
    Configuration chargée depuis les variables d'env / .env.

    Includes startup validation that fails fast on misconfiguration.
    """

    # ─── Serveur MCP ───────────────────────────────────────────
    mcp_server_name: str = "Live Memory"
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8002
    mcp_server_debug: bool = False
    # MCP v2 validates Host and, when present, Origin to prevent DNS rebinding.
    # Port wildcards are intentionally limited to the SDK's documented ':*' form.
    mcp_allowed_hosts: str = "localhost,localhost:*,127.0.0.1,127.0.0.1:*,[::1],[::1]:*"
    mcp_allowed_origins: str = "http://localhost,http://localhost:*,http://127.0.0.1,http://127.0.0.1:*,http://[::1],http://[::1]:*"

    # ─── Auth ──────────────────────────────────────────────────
    # Clé bootstrap pour le premier accès admin.
    # ⚠️ Changer impérativement en production !
    admin_bootstrap_key: str = "change_me_in_production"

    # ─── S3 — Stockage objets ─────────────────────────────────
    # Live Memory supporte deux modes de signature S3 :
    #   - "dual" (défaut) : SigV2 pour PUT/GET/DELETE/COPY, SigV4 pour
    #     HEAD/LIST. Requis pour Dell ECS Cloud Temple — voir
    #     CLOUD_TEMPLE_SERVICES.md.
    #   - "sigv4" : SigV4 pour toutes les opérations. Recommandé pour
    #     MinIO, AWS S3, et tout provider S3-compatible moderne (SigV2
    #     est déprécié AWS depuis 2018 et non supporté par MinIO).
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = "live-mem"
    s3_region_name: str = "fr1"
    s3_signature_mode: str = "dual"

    # ─── LLMaaS Cloud Temple ──────────────────────────────────
    # API OpenAI-compatible. L'URL INCLUT déjà /v1 — ne pas l'ajouter.
    llmaas_api_url: str = ""
    llmaas_api_key: str = ""
    llmaas_model: str = "qwen3.5:27b"
    # Optional dedicated model for hierarchical Bank compaction. Empty keeps
    # backward compatibility by reusing LLMAAS_MODEL.
    llmaas_compaction_model: str = ""
    llmaas_context_window: int = (
        131072  # Taille totale du context window du modèle (input + output)
    )
    llmaas_max_tokens: int = 16384  # Max tokens de SORTIE demandés à l'API
    llmaas_temperature: float = 0.3

    # ─── Proxy HTTP sortant ───────────────────────────────────
    # Variable custom (pas HTTP_PROXY/HTTPS_PROXY) pour ne pas affecter
    # toutes les libs Python qui lisent automatiquement les vars d'env OS.
    # Injecté manuellement dans boto3 (S3) et httpx (LLM).
    # Non supporté pour les connexions Graph Memory (streamable_http_client).
    proxy_url: str | None = None

    @field_validator("proxy_url", mode="before")
    @classmethod
    def _normalize_proxy_url(cls, v: str | None) -> str | None:
        """Normalise proxy_url : strip whitespace, retourne None si vide."""
        if v is None:
            return None
        stripped = str(v).strip()
        return stripped if stripped else None

    @field_validator("mcp_allowed_hosts", mode="before")
    @classmethod
    def _normalize_mcp_allowed_hosts(cls, value: str) -> str:
        return _validate_host_allowlist(str(value))

    @field_validator("mcp_allowed_origins", mode="before")
    @classmethod
    def _normalize_mcp_allowed_origins(cls, value: str) -> str:
        return _validate_origin_allowlist(str(value))

    @property
    def mcp_transport_allowed_hosts(self) -> list[str]:
        return self.mcp_allowed_hosts.split(",")

    @property
    def mcp_transport_allowed_origins(self) -> list[str]:
        return self.mcp_allowed_origins.split(",")

    # ─── Rules par défaut ─────────────────────────────────────
    # Chemin vers le fichier Markdown utilisé comme rules par défaut
    # quand space_create est appelé sans paramètre rules.
    # Ex: RULES/live-mem.standard.memory.bank.md (relatif au CWD)
    # ou /app/RULES/live-mem.standard.memory.bank.md (absolu dans Docker)
    default_rules_file: str = ""

    # ─── Consolidation ────────────────────────────────────────
    consolidation_timeout: int = 1800  # Timeout par appel LLM (secondes)
    # LM2-14 fix : limite revue à la baisse pour brider la conso budget LLM.
    # 200 = ~1 MB d'input LLM si chaque note fait 5 KB ; ~10 MB si 50 KB.
    # Au-delà, l'auto-compact bank prend le relais. Une note massive reste
    # bornée par MAX_NOTE_CONTENT_SIZE (100 KB) côté live.py.
    consolidation_max_notes: int = 200  # Max notes traitées par consolidation
    consolidation_batch_size: int = (
        5  # Notes par lot LLM (réponses courtes = moins de drift)
    )
    # LM2-18 fix : cooldown entre deux consolidations du même space.
    # Empêche un agent write de boucler sur bank_consolidate et de
    # saturer le budget LLM ou de monopoliser le lock du space.
    # 60s = ~1 consolidation/min/space max, largement suffisant pour
    # un flux de travail humain. Mettre à 0 pour désactiver (déconseillé).
    consolidation_cooldown_seconds: int = 60

    # Issue #17 — Post-consolidation validation pass (opt-in).
    # When enabled, after each consolidated batch the server counts the
    # "claims" (numeric facts, metrics, dates, refs) in the modified bank
    # that do NOT appear in any note of the batch. The counter
    # `unattributed_claims_count` is surfaced in the bank_consolidate
    # response for observability.
    # Code-only approach (regex + pattern matching): no LLM tokens spent,
    # deterministic, easy to reason about. Some false positives are
    # possible on structurally unchanged content — see
    # _validate_unattributed_claims() for the heuristic details.
    # Disabled by default to keep existing consolidations unaffected;
    # enable for observability/CI deployments.
    consolidation_validation_enabled: bool = False
    # Cap on reported claims (only the first few are returned, to bound
    # the payload size sent back to the MCP caller).
    consolidation_validation_max_examples: int = 20

    # ─── Bank Compaction ──────────────────────────────────────
    # Conservé pour compatibilité ; la limite logique par fichier est le
    # déclencheur déterministe de la compaction.
    compact_threshold: float = 0.6
    bank_file_max_size: int = (
        15360  # Taille max universelle pour tout fichier bank (bytes)
    )

    # ─── S3 chiffrement at-rest (LM2-15 fix) ─────────────────
    # Si configuré, applique le header `ServerSideEncryption` sur
    # tous les `put_object`. Valeurs typiques :
    #   - "" / None : aucune (compatible Dell ECS sans SSE)
    #   - "AES256"  : SSE-S3 (chiffrement géré par S3)
    #   - "aws:kms" : SSE-KMS (clé KMS, nécessite S3_SSE_KMS_KEY_ID)
    # Sur Dell ECS Cloud Temple, le chiffrement at-rest est déjà géré
    # au niveau cluster. Cette option ajoute une couche applicative
    # explicite pour les déploiements multi-cibles (S3 AWS, MinIO).
    s3_sse: str | None = None
    s3_sse_kms_key_id: str | None = None  # Optionnel, requis si s3_sse=aws:kms

    # ─── Response limits ──────────────────────────────────────
    response_max_bytes: int = 512 * 1024  # Max response body size (512 KB)

    # ─── Graph push guardrails ────────────────────────────────
    # CSV of Memory Bank filenames excluded from graph_push by default.
    # Operators can override with GRAPH_PUSH_VOLATILE_FILES, or opt in per
    # call with include_volatile=True (manage/admin only).
    graph_push_volatile_files: str = "activeContext.md,progress.md"

    # ─── Admin console /api/tool (ADM-05 fix) ─────────────
    api_tool_max_body_bytes: int = 1_048_576  # Max request body for /api/tool (1 MB)

    # extra="ignore" permet d'avoir des variables dans .env (SITE_ADDRESS, WAF_PORT)
    # qui ne sont pas déclarées dans Settings (utilisées par Docker/Caddy uniquement)
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def _validate_config(self) -> "Settings":
        """Semantic validation — fail fast at startup on misconfiguration."""
        errors: list[str] = []

        # Port range
        if not (1 <= self.mcp_server_port <= 65535):
            errors.append(
                f"MCP_SERVER_PORT={self.mcp_server_port} out of range [1, 65535]"
            )

        # S3: all-or-nothing (all three must be set, or none)
        s3_fields = [
            self.s3_endpoint_url,
            self.s3_access_key_id,
            self.s3_secret_access_key,
        ]
        s3_set = [bool(f) for f in s3_fields]
        if any(s3_set) and not all(s3_set):
            errors.append(
                "S3 partially configured — set all of S3_ENDPOINT_URL, "
                "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY or none"
            )

        # S3 endpoint URL format
        if self.s3_endpoint_url and not self.s3_endpoint_url.startswith(
            ("http://", "https://")
        ):
            errors.append(
                f"S3_ENDPOINT_URL must start with http:// or https://, "
                f"got '{self.s3_endpoint_url[:50]}'"
            )

        # Bucket name: S3 naming rules (3-63 chars, lowercase, no underscore)
        if self.s3_bucket_name:
            import re

            if not re.match(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", self.s3_bucket_name):
                _logger.warning(
                    "S3_BUCKET_NAME='%s' may not be a valid S3 bucket name",
                    self.s3_bucket_name,
                )

        # S3 signature mode
        if self.s3_signature_mode not in ("dual", "sigv4"):
            errors.append(
                f"S3_SIGNATURE_MODE='{self.s3_signature_mode}' invalid — "
                "must be 'dual' (Dell ECS Cloud Temple) or 'sigv4' "
                "(MinIO / AWS S3 / other S3-compatible providers)"
            )

        # LLM: API key without URL or vice versa
        if bool(self.llmaas_api_url) != bool(self.llmaas_api_key):
            errors.append(
                "LLMaaS partially configured — set both LLMAAS_API_URL "
                "and LLMAAS_API_KEY or neither"
            )

        # LLM budget coherence (issue #32) : an output budget that consumes
        # the whole context window can never produce a valid call — the
        # backend rejects input + max_tokens > window before inference.
        if self.llmaas_max_tokens >= self.llmaas_context_window:
            errors.append(
                f"LLMAAS_MAX_TOKENS={self.llmaas_max_tokens} must be strictly "
                f"less than LLMAAS_CONTEXT_WINDOW={self.llmaas_context_window} "
                "(output budget cannot consume the whole model context window)"
            )

        # Consolidation ranges
        if self.consolidation_timeout < 10:
            errors.append(
                f"CONSOLIDATION_TIMEOUT={self.consolidation_timeout} too low (min 10s)"
            )
        if self.consolidation_max_notes < 1:
            errors.append(
                f"CONSOLIDATION_MAX_NOTES={self.consolidation_max_notes} must be ≥1"
            )
        if self.consolidation_batch_size < 1:
            errors.append(
                f"CONSOLIDATION_BATCH_SIZE={self.consolidation_batch_size} must be ≥1"
            )

        # Temperature range
        if not (0.0 <= self.llmaas_temperature <= 2.0):
            errors.append(
                f"LLMAAS_TEMPERATURE={self.llmaas_temperature} out of range [0.0, 2.0]"
            )

        # Proxy URL format (optionnel — si renseigné doit être une URL valide)
        if self.proxy_url and not self.proxy_url.startswith(("http://", "https://")):
            errors.append(
                f"PROXY_URL must start with http:// or https://, "
                f"got '{self.proxy_url[:50]}'"
            )

        # Response limit
        if self.response_max_bytes < 1024:
            errors.append(
                f"RESPONSE_MAX_BYTES={self.response_max_bytes} too low (min 1024)"
            )

        if errors:
            msg = "Configuration errors at startup:\n  - " + "\n  - ".join(errors)
            raise ValueError(msg)

        return self


@lru_cache()
def get_settings() -> Settings:
    """Singleton Settings (cached)."""
    return Settings()
