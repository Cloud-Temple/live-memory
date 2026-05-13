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

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_logger = logging.getLogger("live_mem.config")


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

    # ─── Auth ──────────────────────────────────────────────────
    # Clé bootstrap pour le premier accès admin.
    # ⚠️ Changer impérativement en production !
    admin_bootstrap_key: str = "change_me_in_production"

    # ─── S3 Cloud Temple (Dell ECS) ────────────────────────────
    # Configuration HYBRIDE obligatoire : SigV2 pour PUT/GET/DELETE,
    # SigV4 pour HEAD/LIST. Voir CLOUD_TEMPLE_SERVICES.md.
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = "live-mem"
    s3_region_name: str = "fr1"

    # ─── LLMaaS Cloud Temple ──────────────────────────────────
    # API OpenAI-compatible. L'URL INCLUT déjà /v1 — ne pas l'ajouter.
    llmaas_api_url: str = ""
    llmaas_api_key: str = ""
    llmaas_model: str = "qwen3.5:27b"
    llmaas_context_window: int = (
        131072  # Taille totale du context window du modèle (input + output)
    )
    llmaas_max_tokens: int = 16384  # Max tokens de SORTIE demandés à l'API
    llmaas_temperature: float = 0.3

    # ─── Proxy HTTP sortant ───────────────────────────────────
    # Variable custom (pas HTTP_PROXY/HTTPS_PROXY) pour ne pas affecter
    # toutes les libs Python qui lisent automatiquement les vars d'env OS.
    # Injecté manuellement dans boto3 (S3) et httpx (LLM).
    # Non supporté pour les connexions Graph Memory (streamablehttp_client).
    proxy_url: str | None = None

    @field_validator("proxy_url", mode="before")
    @classmethod
    def _normalize_proxy_url(cls, v: str | None) -> str | None:
        """Normalise proxy_url : strip whitespace, retourne None si vide."""
        if v is None:
            return None
        stripped = str(v).strip()
        return stripped if stripped else None

    # ─── Rules par défaut ─────────────────────────────────────
    # Chemin vers le fichier Markdown utilisé comme rules par défaut
    # quand space_create est appelé sans paramètre rules.
    # Ex: RULES/live-mem.standard.memory.bank.md (relatif au CWD)
    # ou /app/RULES/live-mem.standard.memory.bank.md (absolu dans Docker)
    default_rules_file: str = ""

    # ─── Consolidation ────────────────────────────────────────
    consolidation_timeout: int = 600  # Timeout par appel LLM (secondes)
    consolidation_max_notes: int = 500  # Max notes traitées par consolidation
    consolidation_batch_size: int = (
        5  # Notes par lot LLM (réponses courtes = moins de drift)
    )

    # ─── Bank Compaction ──────────────────────────────────────
    # Compaction automatique des fichiers bank avant consolidation
    # quand le contexte total est trop gros pour le LLM.
    # Voir DESIGN/live-mem/CONTEXT_COMPACTION.md pour les détails.
    compact_threshold: float = (
        0.6  # Ratio input/max_tokens au-delà duquel on compacte (0.6 = 60%)
    )
    bank_file_max_size: int = (
        15360  # Taille max universelle pour tout fichier bank (bytes)
    )

    # ─── Response limits ──────────────────────────────────────
    response_max_bytes: int = 512 * 1024  # Max response body size (512 KB)

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

        # LLM: API key without URL or vice versa
        if bool(self.llmaas_api_url) != bool(self.llmaas_api_key):
            errors.append(
                "LLMaaS partially configured — set both LLMAAS_API_URL "
                "and LLMAAS_API_KEY or neither"
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
