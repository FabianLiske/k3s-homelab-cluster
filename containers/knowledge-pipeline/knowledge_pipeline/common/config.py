"""Umgebungs-Konfiguration fuer kb-sync und knowledge-service.

Alle Werte kommen aus Environment-Variables (siehe Deployment-Manifeste).
Keine Secrets in Logs/Commits: Tokens werden nie ausgegeben.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Umfeldvariable {name} fehlt oder ist leer")
    return value


def _url(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().rstrip("/")


@dataclass(frozen=True)
class SyncConfig:
    """Konfiguration des Indexers (kb-sync)."""

    qdrant_url: str
    qdrant_api_key: str
    collection: str
    trilium_url: str
    trilium_token: str
    docling_url: str
    docling_api_key: str
    embed_url: str
    embed_model: str
    embed_dim: int
    sync_interval: float
    exclude_paths: tuple[str, ...]
    state_db: str
    metrics_port: int
    http_timeout: float
    parent_text_max_chars: int

    @classmethod
    def from_env(cls) -> "SyncConfig":
        return cls(
            qdrant_url=_url("QDRANT_URL", "http://qdrant.svc-rag.svc.cluster.local:80"),
            qdrant_api_key=os.environ.get("QDRANT_API_KEY", "").strip(),
            collection=os.environ.get("QDRANT_COLLECTION", "kb").strip(),
            trilium_url=_url("TRILIUM_URL"),
            trilium_token=_require("TRILIUM_TOKEN"),
            docling_url=_url("DOCLING_URL", "http://docling-serve.svc-rag.svc.cluster.local:80"),
            docling_api_key=os.environ.get("DOCLING_API_KEY", "").strip(),
            embed_url=_url("EMBED_URL", "http://embeddings.svc-llm.svc.cluster.local:8080"),
            embed_model=os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B").strip(),
            embed_dim=int(os.environ.get("EMBED_DIM", "1024")),
            sync_interval=float(os.environ.get("SYNC_INTERVAL", "300")),
            exclude_paths=tuple(
                p.strip()
                for p in os.environ.get("KB_EXCLUDE_PATHS", "Calendar").split(",")
                if p.strip()
            ),
            state_db=os.environ.get("STATE_DB", "/data/kbsync.sqlite"),
            metrics_port=int(os.environ.get("METRICS_PORT", "9101")),
            http_timeout=float(os.environ.get("HTTP_TIMEOUT", "120")),
            # Small-to-Big: Voller Not-Text als parent_text nur bei begrenzter Groesze
            # (Belege/PDFs werden sonst pro Chunk verdoppelt).
            parent_text_max_chars=int(os.environ.get("PARENT_TEXT_MAX_CHARS", "100000")),
        )


@dataclass(frozen=True)
class ServiceConfig:
    """Konfiguration der Query-Schicht (knowledge-service)."""

    port: int
    qdrant_url: str
    qdrant_api_key: str
    collection: str
    trilium_url: str
    trilium_token: str
    embed_url: str
    embed_model: str
    # token -> Rolle ("readonly" | "readwrite")
    api_keys: dict[str, str] = field(default_factory=dict)
    sync_admin_url: str = ""
    http_timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        keys: dict[str, str] = {}
        for part in os.environ.get("KNOWLEDGE_API_KEYS", "").split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise RuntimeError(
                    f"KNOWLEDGE_API_KEYS-Eintrag '{part}' ungültig "
                    "(erwartet: roleteil:token)"
                )
            role, _, token = part.partition(":")
            role, token = role.strip(), token.strip()
            if role not in ("readonly", "readwrite") or not token:
                raise RuntimeError(f"KNOWLEDGE_API_KEYS-Eintrag '{part}' ungültig")
            keys[token] = role
        return cls(
            port=int(os.environ.get("PORT", "8000")),
            qdrant_url=_url("QDRANT_URL", "http://qdrant.svc-rag.svc.cluster.local:80"),
            qdrant_api_key=os.environ.get("QDRANT_API_KEY", "").strip(),
            collection=os.environ.get("QDRANT_COLLECTION", "kb").strip(),
            trilium_url=_url("TRILIUM_URL"),
            trilium_token=_require("TRILIUM_TOKEN"),
            embed_url=_url("EMBED_URL", "http://embeddings.svc-llm.svc.cluster.local:8080"),
            embed_model=os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B").strip(),
            api_keys=keys,
            sync_admin_url=_url(
                "KB_SYNC_ADMIN_URL",
                "http://kb-sync.svc-rag.svc.cluster.local:9101",
            ),
            http_timeout=float(os.environ.get("HTTP_TIMEOUT", "60")),
        )
