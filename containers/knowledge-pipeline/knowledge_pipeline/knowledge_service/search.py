"""Hybrid-Suche (REST + MCP geteilter Codepfad).

Filter werden client-seitig auf die Kandidate-Menge angewendet
(top_k * 4), weil Qdrant-Textfilter kein Prafix-Semantik fuer Pfad
bieten; bei der aktuellen Datenmenge (113 Notes) ist das vernachlaessigbar.
"""

from __future__ import annotations

from ..common.config import ServiceConfig
from ..common.embeddings import Embedder
from ..common.qdrant_store import QdrantStore
from ..kb_sync.sync import META_COLLECTION


class SearchError(RuntimeError):
    pass


def _match_filter(item: dict, source: str | None, path: str | None, label: str | None) -> bool:
    payload = item.get("payload") or {}
    if source:
        if (payload.get("source") or "") != source:
            return False
    if path:
        p = payload.get("path") or ""
        if not (p == path or p.startswith(path + " > ")):
            return False
    if label:
        labels = payload.get("labels") or {}
        # label=NAME oder label=NAME:VALUE
        if ":" in label:
            name, _, value = label.partition(":")
            if labels.get(name) != value:
                return False
        elif label not in labels:
            return False
    return True


def run_search(
    qdrant: QdrantStore,
    embedder: Embedder,
    cfg: ServiceConfig,
    query: str,
    top_k: int = 5,
    source: str | None = None,
    path: str | None = None,
    label: str | None = None,
    include_full_note: bool = False,
) -> list[dict]:
    """Fuehrt die Hybrid-Suche aus und liefert rankierte Treffer."""
    query = (query or "").strip()
    if not query:
        raise SearchError("query darf nicht leer sein")
    top_k = max(1, min(int(top_k), 50))

    dense = embedder.embed_query(query)
    candidates = qdrant.hybrid_search(
        cfg.collection,
        query,
        dense,
        limit=top_k * 4,
        with_payload=True,
    )

    results: list[dict] = []
    for rank, c in enumerate(candidates, start=1):
        payload = c.get("payload") or {}
        if not _match_filter(payload, source, path, label):
            continue
        entry = {
            "rank": rank,
            "score": round(float(c.get("score") or 0.0), 6),
            "note_id": payload.get("note_id"),
            "title": payload.get("title", ""),
            "path": payload.get("path", ""),
            "section": payload.get("section", ""),
            "content": payload.get("content", ""),
            "note_type": payload.get("note_type"),
            "modified": payload.get("modified"),
            "embed_model": payload.get("embed_model"),
        }
        if include_full_note and payload.get("parent_text"):
            entry["parent_text"] = payload["parent_text"]
        results.append(entry)
        if len(results) >= top_k:
            break
    return results


def read_sync_state(qdrant: QdrantStore) -> dict | None:
    try:
        return qdrant.read_sync_state(META_COLLECTION)
    except Exception:  # noqa: BLE001 - Status darf wegen fehlender Meta nicht scheitern
        return None
