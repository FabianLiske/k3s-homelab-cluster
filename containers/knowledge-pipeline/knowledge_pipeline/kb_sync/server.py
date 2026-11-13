"""Minimales HTTP-Interface fuer kb-sync (nur intern, per NetPol begrenzt):
  GET  /healthz      K8s-Probe + letzter Sync-Zustand
  GET  /metrics      Prometheus-Textformat
  POST /admin/sync   Sync-Lauf ausloesen (?note_id=<id> fuer Einzel-Note,
                     z.B. nach remember() aus dem knowledge-service)
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .sync import SyncStats


class MetricsState:
    """Thread-sicherer Blick auf die Sync-Statistik fuer /metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict = {}
        self.embedding_calls = 0
        self.docling_conversions = 0

    def update(self, stats: SyncStats) -> None:
        with self._lock:
            self._last = stats.as_dict()

    def last(self) -> dict:
        with self._lock:
            return dict(self._last)

    def render_metrics(self) -> str:
        last = self.last()
        now = _now_ts()
        age = round(now - last.get("ts_epoch", now), 1) if last else ""

        def f(key: str, default: float = 0.0) -> float:
            v = last.get(key, default)
            return v if isinstance(v, (int, float)) else default

        lines = [
            "# HELP kbsync_last_sync_timestamp_seconds Unix-Zeit des letzten Sync-Laufs",
            "# TYPE kbsync_last_sync_timestamp_seconds gauge",
            f"kbsync_last_sync_timestamp_seconds {last.get('ts_epoch', 0)}",
            "# HELP kbsync_last_sync_age_seconds Sekunden seit dem letzten Sync-Lauf",
            "# TYPE kbsync_last_sync_age_seconds gauge",
            f"kbsync_last_sync_age_seconds {age if age != '' else 0}",
            "# HELP kbsync_notes_total Notes im letzten Lauf (alle Typen)",
            "# TYPE kbsync_notes_total gauge",
            f"kbsync_notes_total {f('notes_total')}",
            "# HELP kbsync_notes_indexed Neu indexierte Notes im letzten Lauf",
            "# TYPE kbsync_notes_indexed gauge",
            f"kbsync_notes_indexed {f('notes_indexed')}",
            "# HELP kbsync_notes_unchanged Unveraenderte Notes (Hash-Treffer)",
            "# TYPE kbsync_notes_unchanged gauge",
            f"kbsync_notes_unchanged {f('notes_unchanged')}",
            "# HELP kbsync_notes_skipped_empty Notes ohne Content",
            "# TYPE kbsync_notes_skipped_empty gauge",
            f"kbsync_notes_skipped_empty {f('notes_skipped_empty')}",
            "# HELP kbsync_notes_skipped_excluded Per #noIndex/Pfad-Konfig ausgeschlossen",
            "# TYPE kbsync_notes_skipped_excluded gauge",
            f"kbsync_notes_skipped_excluded {f('notes_skipped_excluded')}",
            "# HELP kbsync_notes_errors Fehlerhaefftiges bei der Verarbeitung",
            "# TYPE kbsync_notes_errors gauge",
            f"kbsync_notes_errors {f('notes_errors')}",
            "# HELP kbsync_notes_removed Geloeschte/entfernte Notes im letzten Lauf",
            "# TYPE kbsync_notes_removed gauge",
            f"kbsync_notes_removed {f('notes_removed')}",
            "# HELP kbsync_chunks_indexed Chunks im Index nach letztem Lauf",
            "# TYPE kbsync_chunks_indexed gauge",
            f"kbsync_chunks_indexed {f('chunks_indexed')}",
            "# HELP kbsync_embedding_calls_total Embedding-API-Aufrufe seit Start",
            "# TYPE kbsync_embedding_calls_total counter",
            f"kbsync_embedding_calls_total {self.embedding_calls}",
            "# HELP kbsync_docling_conversions_total PDF-Konvertierungen seit Start",
            "# TYPE kbsync_docling_conversions_total counter",
            f"kbsync_docling_conversions_total {self.docling_conversions}",
        ]
        return "\n".join(lines) + "\n"


def _now_ts() -> float:
    import time

    return time.time()


class _Handler(BaseHTTPRequestHandler):
    server_version = "kb-sync/0.1"
    # Von aussen gesetzt:
    metrics: MetricsState = MetricsState()
    engine = None
    sync_in_progress = threading.Lock()

    def log_message(self, format: str, *args) -> None:  # noqa: N802
        pass  # stdout wird von K8s gefasst; hier nur Fehler

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            last = self.metrics.last()
            body = json.dumps(
                {
                    "status": "ok",
                    "last_sync": last or None,
                }
            ).encode()
            self._send(200, body, "application/json")
        elif path == "/metrics":
            self._send(200, self.metrics.render_metrics().encode(), "text/plain; version=0.0.4")
        else:
            self._send(404, b"{}", "application/json")

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/admin/sync":
            self._send(404, b"{}", "application/json")
            return
        if self.engine is None:
            self._send(503, b'{"error":"engine not ready"}', "application/json")
            return
        params = parse_qs(url.query)
        note_id = (params.get("note_id") or [None])[0]
        if not self.sync_in_progress.acquire(blocking=False):
            self._send(409, b'{"error":"sync already running"}', "application/json")
            return
        try:
            stats = self.engine.run(only_note_id=note_id)
            self.metrics.update(stats)
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        finally:
            self.sync_in_progress.release()
        self._send(200, json.dumps(stats.as_dict()).encode(), "application/json")


def start_server(port: int, metrics: MetricsState, engine) -> ThreadingHTTPServer:
    _Handler.metrics = metrics
    _Handler.engine = engine
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, name="kb-sync-http", daemon=True)
    t.start()
    return server
