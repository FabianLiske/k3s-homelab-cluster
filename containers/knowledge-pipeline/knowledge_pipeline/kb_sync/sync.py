"""Sync-Engine: Trilium -> Chunks -> Embedding -> Qdrant, mit Reconciliation.

Prinzipien (Design-Doku knowledge-store-architektur.md):
- UUIDv5-Point-IDs aus (noteId, utcDateModified, Chunk-Index): Aenderungen
  erzeugen neue IDs, alte werden geloescht.
- Vollreconciliation pro Zyklus: Notes, die in Qdrant vorkommen aber in
  Trilium nicht mehr (geloescht/umbenannt), werden entfernt.
- Content-Hash-Cache (SQLite) verhindert Re-Embedding unveraenderter Notes.
- #noIndex-Label (Note) und KB_EXCLUDE_PATHS (Pfad-Segment) schliessen aus.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import threading
import time
from datetime import datetime, timezone

from ..common.chunking import CHUNKER_VERSION, chunk_note
from ..common.config import SyncConfig
from ..common.embeddings import Embedder
from ..common.qdrant_store import QdrantStore
from .docling import DoclingClient, DoclingError
from .state import State
from .trilium import TriliumClient, TriliumError

log = logging.getLogger(__name__)

META_COLLECTION = "kb_meta"


class SyncStats:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.notes_total = 0
        self.indexed = 0
        self.unchanged = 0
        self.skipped_empty = 0
        self.skipped_excluded = 0
        self.errors = 0
        self.removed_notes = 0
        self.removed_points = 0
        self.chunks = 0
        self.duration_s = 0.0
        self.last_error = ""

    def as_dict(self) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ts_epoch": time.time(),
            "duration_s": self.duration_s,
            "notes_total": self.notes_total,
            "notes_indexed": self.indexed,
            "notes_unchanged": self.unchanged,
            "notes_skipped_empty": self.skipped_empty,
            "notes_skipped_excluded": self.skipped_excluded,
            "notes_errors": self.errors,
            "notes_removed": self.removed_notes,
            "points_removed": self.removed_points,
            "chunks_indexed": self.chunks,
            "last_error": self.last_error,
        }


def _html_to_text(value: str) -> str:
    """Grobe HTML->Text-Konvertierung fuer Rich-Notes (doc-Typ)."""
    value = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(p|div|h[1-6]|li|tr)>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


class SyncEngine:
    def __init__(
        self,
        cfg: SyncConfig,
        qdrant: QdrantStore,
        trilium: TriliumClient,
        docling: DoclingClient,
        embedder: Embedder,
        state: State,
    ):
        self.cfg = cfg
        self.qdrant = qdrant
        self.trilium = trilium
        self.docling = docling
        self.embedder = embedder
        self.state = state
        self._lock = threading.Lock()

    # ---------- Ausschluss ----------

    def _excluded(self, note: dict, path: str) -> bool:
        labels = {
            a.get("name"): (a.get("value") or "")
            for a in note.get("attributes", [])
            if a.get("type") == "label"
        }
        if "noIndex" in labels:
            return True
        segments = [s.strip() for s in path.split(">")]
        return any(seg in self.cfg.exclude_paths for seg in segments)

    # ---------- Content ----------

    def _fetch_text(self, note: dict) -> tuple[str | None, str | None, str | None]:
        """Liefert (text, quelle, fehler)."""
        try:
            raw = self.trilium.get_content(note["noteId"])
        except TriliumError as exc:
            return None, None, str(exc)
        if not raw:
            return "", "empty", None
        note_type = note.get("type") or ""
        mime = note.get("mime") or ""
        if note_type == "file":
            if "pdf" not in mime:
                return None, None, f"nicht unterstuetztes File-MIME: {mime}"
            filename = f"{note['noteId']}.pdf"
            try:
                return self.docling.pdf_to_markdown(raw, filename), "docling", None
            except DoclingError as exc:
                return None, None, str(exc)
        text = raw.decode("utf-8", "replace")
        if note_type == "doc":
            text = _html_to_text(text)
        return text, "raw", None

    @staticmethod
    def _content_hash(text: str, embed_model: str) -> str:
        h = hashlib.sha256()
        h.update(CHUNKER_VERSION.encode())
        h.update(b"|")
        h.update(embed_model.encode())
        h.update(b"|")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    # ---------- Punkte ----------

    def _build_point(
        self,
        note: dict,
        path: str,
        labels: dict[str, str],
        chunk,
        vector: list[float],
        full_text: str,
    ) -> dict:
        payload: dict = {
            "note_id": note["noteId"],
            "title": note.get("title", ""),
            "path": path,
            "section": chunk.heading_path,
            "content": chunk.text,
            "source": "trilium",
            "note_type": note.get("type"),
            "mime": note.get("mime"),
            "labels": labels,
            "modified": note.get("utcDateModified") or "",
            "chunk_index": chunk.index,
            "chunker": CHUNKER_VERSION,
            "embed_model": self.cfg.embed_model,
            # Nested fuer Open-WebUI-External-Knowledge-Source (Defaults:
            # content_field=payload.content, metadata_field=payload.metadata);
            # "name" dort wird als Zitat-Titel angezeigt.
            "metadata": {"name": note.get("title", ""), "path": path},
        }
        if len(full_text) <= self.cfg.parent_text_max_chars:
            payload["parent_text"] = full_text
        return {
            "id": QdrantStore.point_id(
                note["noteId"], note.get("utcDateModified") or "", chunk.index
            ),
            "vector": {"dense": vector},
            "payload": payload,
        }

    # ---------- Hauptlauf ----------

    def run(self, only_note_id: str | None = None) -> SyncStats:
        stats = SyncStats()
        with self._lock:
            try:
                self._run_locked(stats, only_note_id)
            finally:
                stats.duration_s = round(time.time() - stats.started_at, 2)
                try:
                    self.qdrant.upsert_sync_state(META_COLLECTION, stats.as_dict())
                except Exception as exc:  # noqa: BLE001 - Meta-Schreiben darf den Sync nicht killen
                    log.error("Sync-State-Upload fehlgeschlagen: %s", exc)
                log.info(
                    "Sync fertig: %d gesamt, %d indexiert, %d unveraendert, "
                    "%d leer, %d ausgeschlossen, %d Fehler, %d entfernt, "
                    "%d Chunks, %.1fs",
                    stats.notes_total,
                    stats.indexed,
                    stats.unchanged,
                    stats.skipped_empty,
                    stats.skipped_excluded,
                    stats.errors,
                    stats.removed_notes,
                    stats.chunks,
                    stats.duration_s,
                )
        return stats

    def _run_locked(self, stats: SyncStats, only_note_id: str | None) -> None:
        self.qdrant.ensure_collection(self.cfg.collection, self.cfg.embed_dim)

        notes = self.trilium.list_visible_notes()
        stats.notes_total = len(notes)
        paths = self._build_paths(notes)

        current: dict[str, list[str]] = {}
        if only_note_id is None:
            current = self.qdrant.scroll_note_ids(self.cfg.collection)

        processed: set[str] = set()
        for note in notes:
            nid = note["noteId"]
            if only_note_id is not None and nid != only_note_id:
                continue
            path = paths.get(nid, "")
            try:
                self._process_note(note, path, current, processed, stats)
            except Exception as exc:  # noqa: BLE001 - eine kaputte Note duerft den Rest nicht blockieren
                stats.errors += 1
                stats.last_error = f"{nid}: {exc}"
                log.warning("Note %s (%s) fehlgeschlagen: %s", note.get("title"), nid, exc)

        # Reconciliation: Notes, die es in Qdrant gibt, aber nicht mehr
        # (oder nicht mehr indexierbar) in Trilium.
        if only_note_id is None:
            for nid, point_ids in current.items():
                if nid in processed:
                    continue
                self.qdrant.delete_points(self.cfg.collection, point_ids)
                self.state.delete(nid)
                stats.removed_notes += 1
                stats.removed_points += len(point_ids)
                log.info("Geloeschte Note entfernt: %s (%d Punkte)", nid, len(point_ids))

    def _process_note(
        self,
        note: dict,
        path: str,
        current: dict[str, list[str]],
        processed: set[str],
        stats: SyncStats,
    ) -> None:
        nid = note["noteId"]
        if self._excluded(note, path):
            stats.skipped_excluded += 1
            processed.add(nid)
            # Falls sie aus einem frueheren Lauf noch indexiert ist: entfernen
            stale = current.get(nid, [])
            if stale:
                self.qdrant.delete_points(self.cfg.collection, stale)
                self.state.delete(nid)
                stats.removed_notes += 1
                stats.removed_points += len(stale)
            return

        text, _quelle, err = self._fetch_text(note)
        if err:
            raise RuntimeError(err)
        if text is None or not text.strip():
            stats.skipped_empty += 1
            processed.add(nid)
            stale = current.get(nid, [])
            if stale:
                self.qdrant.delete_points(self.cfg.collection, stale)
                self.state.delete(nid)
                stats.removed_points += len(stale)
            return

        digest = self._content_hash(text, self.cfg.embed_model)
        existing_ids = set(current.get(nid, []))
        if self.state.hash(nid) == digest and existing_ids:
            stats.unchanged += 1
            processed.add(nid)
            return

        chunks = chunk_note(note.get("title", ""), path, text)
        if not chunks:
            stats.skipped_empty += 1
            processed.add(nid)
            stale = existing_ids
            if stale:
                self.qdrant.delete_points(self.cfg.collection, list(stale))
                self.state.delete(nid)
                stats.removed_points += len(stale)
            return

        vectors = self.embedder.embed_batch([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedding-Anzahl {len(vectors)} != Chunk-Anzahl {len(chunks)}"
            )

        labels = {
            a.get("name"): (a.get("value") or "")
            for a in note.get("attributes", [])
            if a.get("type") == "label"
        }
        points = [
            self._build_point(note, path, labels, c, v, text)
            for c, v in zip(chunks, vectors)
        ]
        new_ids = {p["id"] for p in points}

        self.qdrant.upsert_points(self.cfg.collection, points)
        stale = existing_ids - new_ids
        if stale:
            self.qdrant.delete_points(self.cfg.collection, list(stale))
            stats.removed_points += len(stale)

        self.state.set(nid, digest, len(points), note.get("utcDateModified", ""))
        processed.add(nid)
        stats.indexed += 1
        stats.chunks += len(points)

    # ---------- Pfade ----------

    @staticmethod
    def _build_paths(notes: list[dict]) -> dict[str, str]:
        by_id = {n["noteId"]: n for n in notes}
        memo: dict[str, str] = {}

        def path_of(nid: str) -> str:
            if nid in memo:
                return memo[nid]
            chain: list[str] = []
            cur: str | None = nid
            seen: set[str] = set()
            while cur and cur in by_id and cur not in seen and len(chain) < 24:
                seen.add(cur)
                chain.append(by_id[cur].get("title", "") or "")
                parents = by_id[cur].get("parentNoteIds") or []
                cur = parents[0] if parents else None
            result = " > ".join(reversed([t for t in chain if t]))
            memo[nid] = result
            return result

        return {n["noteId"]: path_of(n["noteId"]) for n in notes}
