"""Trilium ETAPI-Client (Nur-Lese fuer den Sync).

Verifiziert gegen TriliumNext v0.106.0 (apps/server/src/etapi/notes.ts):
  GET /etapi/notes?search=<q>&limit=<n>   Search, POJO inkl. attributes
  GET /etapi/notes/{id}/content            Not-Content (text/Markdown oder Blob)

Die Suchabfrage `note.type = <typ>` liefert nur sichtbare Notes — den
_Hidden-Baum und Archiviertes schliesst Trilium nativ aus.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

NOTE_TYPES = ("text", "code", "file", "doc", "book")
SEARCH_LIMIT = 500


class TriliumError(RuntimeError):
    pass


class TriliumClient:
    def __init__(self, url: str, token: str, timeout: float = 60.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, timeout: float | None = None) -> requests.Response:
        try:
            r = self.session.get(
                f"{self.url}{path}", timeout=timeout or self.timeout
            )
        except requests.RequestException as exc:
            raise TriliumError(f"Trilium nicht erreichbar: {exc}") from exc
        if r.status_code >= 400:
            raise TriliumError(f"Trilium {path}: HTTP {r.status_code}: {r.text[:200]}")
        return r

    def list_visible_notes(self) -> list[dict]:
        """Alle indexierbaren Notes (alle Typen, einmalig dedupliziert)."""
        notes: dict[str, dict] = {}
        for note_type in NOTE_TYPES:
            q = f"note.type = {note_type}"
            path = f"/etapi/notes?search={quote(q)}&limit={SEARCH_LIMIT}"
            results = self._get(path).json().get("results", [])
            if len(results) >= SEARCH_LIMIT:
                log.warning(
                    "Suche '%s' erreicht Limit %d — moeglich Truncation",
                    q,
                    SEARCH_LIMIT,
                )
            for n in results:
                nid = n.get("noteId")
                if nid:
                    notes[nid] = n
        return list(notes.values())

    def get_content(self, note_id: str) -> bytes:
        """Not-Content als rohe Bytes (Markdown-Text oder Binär-Blob)."""
        r = self._get(f"/etapi/notes/{note_id}/content", timeout=max(self.timeout, 120))
        return r.content
