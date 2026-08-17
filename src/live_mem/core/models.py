# -*- coding: utf-8 -*-
"""
Modèles Pydantic — Structures de données de Live Memory.

Ces modèles définissent les objets échangés entre les services (storage,
space, consolidator, tokens, backup) et sérialisés en JSON/Markdown sur S3.

Voir S3_DATA_MODEL.md pour l'arborescence S3 complète.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Space — Métadonnées d'un espace mémoire
# =============================================================================


class GraphMemoryConfig(BaseModel):
    """
    Configuration de connexion vers une instance Graph Memory.

    Permet à un space de pousser ses fichiers bank dans un graphe
    de connaissances pour la mémoire long terme.

    Stocké dans _meta.json, champ "graph_memory".
    """

    url: str = ""  # URL de graph-memory (ex: "http://localhost:8080/mcp")
    token: str = ""  # Bearer token pour graph-memory
    memory_id: str = ""  # Memory cible dans graph-memory
    ontology: str = "general"  # Ontologie graph-memory à utiliser
    last_push: Optional[str] = None  # ISO 8601 du dernier push
    push_count: int = 0  # Nombre total de pushs effectués
    files_pushed: int = 0  # Nombre de fichiers poussés au dernier push


def mask_meta_secrets(meta: Optional[dict]) -> Optional[dict]:
    """
    LM2-03 fix : masque les secrets dans une copie d'un _meta.json.

    Doit être appliqué AVANT toute exposition vers l'extérieur :

    - réponses API REST (``/api/space/{id}`` — déjà fixé en VULN-12)
    - retour de outils MCP exposant le meta (``space_summary``, ``space_export``)
    - dump de backups (``backup_download``)

    Le token Graph Memory était auparavant masqué uniquement dans
    ``/api/space/{id}`` (VULN-12 partiel). Cette fonction généralise
    le masquage à tous les chemins, transformant le token en
    ``"<prefix>..."`` (8 premiers chars du token + ellipse).

    Args:
        meta: dict _meta.json brut (ou None si l'espace n'existe pas)

    Le hash du créateur technique est également sensible : il ne permet pas
    d'authentifier seul, mais il ne doit pas être exporté ni inclus dans un
    backup téléchargeable.

    Returns:
        Une COPIE du dict avec les secrets masqués, ou ``None`` si l'entrée
        était None. Ne modifie pas l'entrée.
    """
    if not meta:
        return meta

    # Copie défensive (jamais muter le dict en place — pourrait corrompre
    # un singleton de cache ou une réponse parallèle).
    masked = dict(meta)
    changed = False

    creator_token_hash = meta.get("creator_token_hash")
    if creator_token_hash:
        masked["creator_token_hash"] = "***"
        changed = True

    gm = meta.get("graph_memory")
    token = gm.get("token") if isinstance(gm, dict) else None
    if token:
        masked_token = token[:8] + "..." if len(token) > 8 else "***"
        masked["graph_memory"] = {**gm, "token": masked_token}
        changed = True

    return masked if changed else meta


class SpaceMeta(BaseModel):
    """
    Métadonnées d'un espace (_meta.json sur S3).

    Créé par space_create, mis à jour par bank_consolidate.
    """

    space_id: str
    description: str = ""
    owner: str = ""
    # Preuve technique du créateur. Jamais exposée dans les exports ou backups.
    # Les spaces historiques/bootstrap sans hash restent volontairement non
    # mintables pour les badges de mission (fail closed).
    creator_token_hash: Optional[str] = None
    created_at: str = ""  # ISO 8601
    last_consolidation: Optional[str] = None  # ISO 8601 ou None
    consolidation_count: int = 0
    total_notes_processed: int = 0
    graph_memory: Optional[GraphMemoryConfig] = None  # Connexion graph-memory
    version: int = 1


# =============================================================================
# Live — Notes en temps réel
# =============================================================================


class LiveNote(BaseModel):
    """
    Une note live (front-matter YAML + contenu Markdown).

    Chaque note = 1 fichier S3 unique dans {space_id}/live/.
    Naming convention : {YYYYMMDD}T{HHMMSS}_{agent}_{category}_{uuid8}.md
    """

    filename: str = ""  # Nom du fichier S3 (sans le préfixe)
    timestamp: str = ""  # ISO 8601
    agent: str = ""  # Identifiant de l'agent auteur
    category: str = (
        ""  # observation, decision, todo, insight, question, progress, issue
    )
    tags: list[str] = Field(default_factory=list)
    space_id: str = ""
    content: str = ""  # Corps de la note (sans le front-matter)
    size: int = 0  # Taille en octets du fichier complet

    # Catégories autorisées
    VALID_CATEGORIES: list[str] = [
        "observation",
        "decision",
        "todo",
        "insight",
        "question",
        "progress",
        "issue",
    ]


# =============================================================================
# Bank — Fichiers consolidés
# =============================================================================


class BankFile(BaseModel):
    """
    Un fichier de la memory bank (Markdown pur, sans front-matter).

    Les fichiers bank sont créés et maintenus exclusivement par le LLM
    lors de la consolidation. Les noms sont décidés par le LLM selon les rules.
    """

    filename: str = ""  # Ex: "activeContext.md"
    content: str = ""  # Contenu Markdown complet
    size: int = 0  # Taille en octets
    last_modified: Optional[str] = None  # ISO 8601
    action: str = ""  # "created", "updated", "unchanged" (post-consolidation)


# =============================================================================
# Tokens — Authentification
# =============================================================================


class TokenInfo(BaseModel):
    """
    Infos d'un token d'authentification (stocké dans _system/tokens.json).

    Le token en clair n'est JAMAIS stocké — seul le hash SHA-256 est conservé.
    """

    hash: str = ""  # "sha256:{hex}" — identifiant unique
    kind: Literal["standard", "space_badge"] = "standard"
    name: str = ""  # Nom descriptif (ex: "agent-cline")
    email: str = ""  # Email du propriétaire (optionnel, traçabilité)
    permissions: list[str] = Field(
        default_factory=list
    )  # ["read"], ["read", "write"], etc.
    space_ids: list[str] = Field(default_factory=list)  # [] = aucun espace non-admin
    created_at: str = ""  # ISO 8601
    expires_at: Optional[str] = None  # ISO 8601 ou None (jamais)
    last_used_at: Optional[str] = None
    revoked: bool = False


class TokensStore(BaseModel):
    """
    Registre complet des tokens (_system/tokens.json).

    Protégé par un asyncio.Lock pour éviter les conflits
    lors de modifications concurrentes par plusieurs admins.
    """

    version: int = 1
    tokens: list[TokenInfo] = Field(default_factory=list)


# =============================================================================
# Backup — Sauvegarde & restauration
# =============================================================================


class BackupMeta(BaseModel):
    """
    Métadonnées d'un backup (snapshot d'un espace).

    Stocké dans _backups/{space_id}/{timestamp}/.
    """

    backup_id: str = ""  # "space_id/timestamp"
    space_id: str = ""
    timestamp: str = ""  # ISO 8601
    description: str = ""
    files_count: int = 0
    total_size: int = 0
    created_at: str = ""  # ISO 8601


# =============================================================================
# Consolidation — Résultat du pipeline LLM
# =============================================================================


class ConsolidationResult(BaseModel):
    """
    Résultat d'une consolidation LLM.

    Retourné par bank_consolidate avec les métriques d'exécution.
    """

    notes_processed: int = 0
    notes_remaining: int = 0  # Si > consolidation_max_notes
    bank_files_updated: int = 0
    bank_files_created: int = 0
    bank_files_unchanged: int = 0
    synthesis_size: int = 0
    llm_tokens_used: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    duration_seconds: float = 0.0
