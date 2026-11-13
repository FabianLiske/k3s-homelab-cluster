"""MCP-Server (FastMCP, streamable HTTP unter /mcp).

Werkzeuge:
  search_knowledge  Suche im kuratierten Index (readonly + readwrite)
  remember        Note in Trilium anlegen (readwrite)
  forget          Note loeschen, nur unter Agent-Notizen (readwrite)
  status          Index-Gesundheit und Sync-Zustand (readonly + readwrite)

Auth: Bearer-Token ueber den gesamten /mcp-Pfad (Middleware in api.py);
die Rolle wird pro Anfrage gesetzt und hier ausgewertet.
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from .roles import current_role
from .search import SearchError, run_search, read_sync_state
from .trilium_write import TriliumWriter, TriliumWriteError

log = logging.getLogger(__name__)


def create_mcp_server(qdrant, embedder, cfg, writer: TriliumWriter) -> FastMCP:
    mcp = FastMCP(
        "knowledge",
        instructions=(
            "Kuratierte Wissensbasis (Trilium, per kb-sync indexiert): "
            "Hybrid-Suche ueber Projekte, Finances, Dokumente. "
            "remember() legt dauerhafte Notizen unter Resources/Agent-Notizen/<agent>/ ab."
        ),
    )

    def _dump(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=1)

    @mcp.tool()
    def search_knowledge(
        query: str,
        top_k: int = 5,
        source: str | None = None,
        path: str | None = None,
        label: str | None = None,
        include_full_note: bool = False,
    ) -> str:
        """Suche in der kuratierten Wissensbasis (hybrid: dichte Vektoren + Volltext).

        Args:
            query: Natuerlichsprachliche Frage oder Suchbegriffe.
            top_k: Anzahl der Ergebnisse (1-50, Default 5).
            source: Filter nach Quelle (z.B. "trilium").
            path: Prefix-Filter auf den Not-Pfad (z.B. "Areas > Finances").
            label: Filter nach Label, als "name" oder "name:wert".
            include_full_note: True = vollen Not-Text mitliefern (grossere Antwort).
        """
        try:
            results = run_search(
                qdrant,
                embedder,
                cfg,
                query=query,
                top_k=top_k,
                source=source,
                path=path,
                label=label,
                include_full_note=include_full_note,
            )
        except (SearchError, Exception) as exc:  # noqa: BLE001
            if isinstance(exc, SearchError):
                return _dump({"error": str(exc)})
            log.exception("Suche fehlgeschlagen")
            return _dump({"error": f"Suche fehlgeschlagen: {exc}"})
        return _dump({"count": len(results), "results": results})

    @mcp.tool()
    def remember(
        title: str,
        content: str,
        agent: str = "unknown",
        topic: str | None = None,
    ) -> str:
        """Dauerhafte Notiz in der Wissensbasis speichern (benoetigt Rolle 'readwrite').

        Die Note erscheint unter Resources/Agent-Notizen/<agent>/ und wird
        kurz darauf von der Suche erfasst (Single-Note-Sync).

        Args:
            title: Kurzer, praeziser Titel der Notiz.
            content: Inhalt als Markdown.
            agent: Name des Agents (kleingeschrieben, a-z 0-9 _ -), z.B. "hermes".
            topic: Optionales Thema/Label.
        """
        try:
            result = writer.remember(title=title, content=content, agent=agent, topic=topic)
            return _dump(result)
        except PermissionError as exc:
            return _dump({"error": f"Berechtigung fehlt: {exc}"})
        except (TriliumWriteError, Exception) as exc:  # noqa: BLE001
            if isinstance(exc, TriliumWriteError):
                return _dump({"error": str(exc)})
            log.exception("remember() fehlgeschlagen")
            return _dump({"error": f"remember() fehlgeschlagen: {exc}"})

    @mcp.tool()
    def forget(note_id: str) -> str:
        """Eine zuvor mit remember() angelegte Notiz loeschen (Rolle 'readwrite').

        Erlaubt ist das ausschliesslich fuer Notes unter Resources/Agent-Notizen/.

        Args:
            note_id: Trilium-Note-ID (wie in remember()-Antwort/Ergebnissen).
        """
        try:
            result = writer.forget(note_id)
            return _dump(result)
        except PermissionError as exc:
            return _dump({"error": f"Berechtigung fehlt: {exc}"})
        except (TriliumWriteError, Exception) as exc:  # noqa: BLE001
            if isinstance(exc, TriliumWriteError):
                return _dump({"error": str(exc)})
            log.exception("forget() fehlgeschlagen")
            return _dump({"error": f"forget() fehlgeschlagen: {exc}"})

    @mcp.tool()
    def status() -> str:
        """Index-Gesundheit: letzter Sync, Noten-/Chunk-Zahlen, Fehler.

        Hilft zu beurteilen, ob Suchergebnisse aktuell sein koennen.
        """
        state = read_sync_state(qdrant)
        info: dict = {"sync_state": state}
        try:
            info["collection"] = qdrant.collection_info(cfg.collection)
        except Exception as exc:  # noqa: BLE001
            info["collection"] = {"error": str(exc)}
        role = current_role.get()
        info["role"] = role
        return _dump(info)

    return mcp
