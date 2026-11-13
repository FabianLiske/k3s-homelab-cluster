"""Qdrant-REST-Store (kein qdrant-client, nur requests).

Endpoints (alle per Probe an v1.20.0 verifiziert):
  PUT    /collections/{c}                    Create
  GET    /collections/{c}                     Info/Exists
  PUT    /collections/{c}/index?wait=true     Full-Text-Index (BM25)
  PUT    /collections/{c}/points              Upsert
  POST   /collections/{c}/points/delete      Delete by id
  POST   /collections/{c}/points/scroll      Scroll (Reconciliation)
  POST   /collections/{c}/points/query       Hybrid (prefetch + RRF)
"""

from __future__ import annotations

import logging
import uuid

import requests

log = logging.getLogger(__name__)

# Fixer Namespace fuer stabile UUIDv5-Point-IDs.
# Punkt-ID = f(Not-ID, utcDateModified, Chunk-Index): Bei Aenderung bekommt
# die Note neue IDs; die alten werden per Reconciliation geloescht.
KB_NAMESPACE = uuid.UUID("b3f1c2a4-7d9e-5a86-4f0b-9c2d3e4f5a6b")


class QdrantError(RuntimeError):
    pass


class QdrantStore:
    def __init__(self, url: str, api_key: str = "", timeout: float = 60.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers["api-key"] = api_key

    # ---------- Collection-Verwaltung ----------

    def ensure_collection(self, name: str, dim: int) -> None:
        r = self.session.get(f"{self.url}/collections/{name}", timeout=self.timeout)
        if r.status_code == 404:
            body = {
                "vectors": {"dense": {"size": dim, "distance": "Cosine"}},
            }
            r2 = self.session.put(
                f"{self.url}/collections/{name}", json=body, timeout=self.timeout
            )
            if r2.status_code not in (200, 201):
                raise QdrantError(
                    f"Collection '{name}' nicht anlegbar: HTTP {r2.status_code}: {r2.text[:300]}"
                )
            log.info("Qdrant-Collection '%s' angelegt (dim=%d, Cosine)", name, dim)
        elif r.status_code != 200:
            raise QdrantError(f"Collection-Check '{name}': HTTP {r.status_code}: {r.text[:300]}")
        self.ensure_fulltext_index(name, "content")

    def ensure_fulltext_index(self, name: str, field: str) -> None:
        """BM25-Index auf dem Content-Feld. Idempotent (erneutes PUT = Update)."""
        r = self.session.put(
            f"{self.url}/collections/{name}/index?wait=true",
            json={
                "field_name": field,
                "field_schema": {"type": "text", "tokenizer": "word", "scoring": True},
            },
            timeout=120,
        )
        # 2xx: gesetzt. 4xx darf bei vorhandener Index-Konfiguration vorkommen —
        # dann ist der Index bereits da. Nur 5xx/Netzwerk ist ein Fehler.
        if r.status_code >= 500:
            raise QdrantError(f"Full-Text-Index '{name}/{field}': HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code >= 400:
            log.debug("Full-Text-Index-PUT %s/%s: HTTP %s (vermutlich vorhanden)", name, field, r.status_code)

    def collection_info(self, name: str) -> dict:
        r = self.session.get(f"{self.url}/collections/{name}", timeout=self.timeout)
        if r.status_code != 200:
            return {"exists": False}
        d = r.json().get("result", {})
        return {
            "exists": True,
            "points_count": d.get("points_count"),
            "status": d.get("status"),
        }

    # ---------- Punkte ----------

    @staticmethod
    def point_id(note_id: str, modified: str, chunk_index: int) -> str:
        return str(uuid.uuid5(KB_NAMESPACE, f"trilium:{note_id}:{modified}:{chunk_index}"))

    def upsert_points(self, name: str, points: list[dict]) -> None:
        if not points:
            return
        r = self.session.put(
            f"{self.url}/collections/{name}/points",
            json={"points": points, "wait": True},
            timeout=120,
        )
        if r.status_code not in (200, 201):
            raise QdrantError(f"Points-Upsert: HTTP {r.status_code}: {r.text[:300]}")

    def delete_points(self, name: str, ids: list[str]) -> None:
        if not ids:
            return
        r = self.session.post(
            f"{self.url}/collections/{name}/points/delete",
            json={"points": ids, "wait": True},
            timeout=120,
        )
        if r.status_code not in (200, 201, 204):
            raise QdrantError(f"Points-Delete: HTTP {r.status_code}: {r.text[:300]}")

    def scroll_note_ids(self, name: str) -> dict[str, list[str]]:
        """{note_id: [point_id, ...]} — Basis der Reconciliation.

        Paginierung ueber 'offset' (Request) / 'next_page_offset' (Response,
        Punkt-ID der letzten Seite). Hinweis: ein anderes Feld wird von
        Qdrant still ignoriert und fuehrt zu einem Endlos-Loop auf derselben
        Seite — das hat schon einmal zum OOM des kb-sync-Pods gefuehrt.
        """
        by_note: dict[str, list[str]] = {}
        offset: str | int | None = None
        pages = 0
        while True:
            pages += 1
            if pages > 10000:  # Schutz: 1M Punkte reichen hier mit grossem Vorrat
                raise QdrantError(
                    f"Scroll ueber 10000 Seiten in '{name}' — Abbruch aus Sicherheitsgruenden"
                )
            body: dict = {"limit": 100, "with_payload": ["note_id"]}
            if offset is not None:
                body["offset"] = offset
            r = self.session.post(
                f"{self.url}/collections/{name}/points/scroll", json=body, timeout=120
            )
            if r.status_code == 404:
                return {}
            if r.status_code != 200:
                raise QdrantError(f"Scroll: HTTP {r.status_code}: {r.text[:300]}")
            d = r.json().get("result", {})
            points = d.get("points", [])
            for p in points:
                nid = (p.get("payload") or {}).get("note_id")
                if nid:
                    by_note.setdefault(nid, []).append(p["id"])
            offset = d.get("next_page_offset")
            if not points or offset is None:
                break
        return by_note

    def hybrid_search(
        self,
        name: str,
        query_text: str,
        dense_vec: list[float],
        limit: int = 10,
        with_payload: bool = True,
    ) -> list[dict]:
        """Hybrid-Suche: BM25-Präfetch + dichte Vektoren, Fusion RRF.

        Qdrant >= 1.20: Text-Query ist {"text": ...}, RRF ist {"rrf": {}};
        die Antwort liegt unter result.points.
        """
        body = {
            "prefetch": [
                {"query": {"text": query_text}, "using": "content", "limit": limit},
                {"query": dense_vec, "using": "dense", "limit": limit},
            ],
            "query": {"rrf": {}},
            "limit": limit,
            "with_payload": with_payload,
        }
        r = self.session.post(
            f"{self.url}/collections/{name}/points/query", json=body, timeout=60
        )
        if r.status_code != 200:
            raise QdrantError(f"Query: HTTP {r.status_code}: {r.text[:300]}")
        result = r.json().get("result")
        if isinstance(result, dict):
            return result.get("points", [])
        return result or []

    # ---------- Sync-State (Collection kb_meta) ----------

    def ensure_meta_collection(self, meta_name: str) -> None:
        r = self.session.get(f"{self.url}/collections/{meta_name}", timeout=self.timeout)
        if r.status_code == 404:
            body = {"vectors": {"v": {"size": 1, "distance": "Cosine"}}}
            r2 = self.session.put(
                f"{self.url}/collections/{meta_name}", json=body, timeout=self.timeout
            )
            if r2.status_code not in (200, 201):
                raise QdrantError(
                    f"Meta-Collection '{meta_name}' nicht anlegbar: HTTP {r2.status_code}: {r2.text[:300]}"
                )

    def upsert_sync_state(self, meta_name: str, state: dict) -> None:
        self.ensure_meta_collection(meta_name)
        self.upsert_points(
            meta_name,
            [
                {
                    "id": "sync_state",
                    "vector": {"v": [0.0]},
                    "payload": state,
                }
            ],
        )

    def read_sync_state(self, meta_name: str) -> dict | None:
        r = self.session.get(
            f"{self.url}/collections/{meta_name}/points/sync_state", timeout=30
        )
        if r.status_code != 200:
            return None
        result = r.json().get("result", {})
        return result.get("payload")
