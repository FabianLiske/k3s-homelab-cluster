"""kb-sync Entry-Point: Sync-Loop + Admin/Metrics-HTTP (METRICS_PORT)."""

from __future__ import annotations

import logging
import os
import time

from .docling import DoclingClient
from .server import MetricsState, start_server
from .state import State
from .sync import SyncEngine
from .trilium import TriliumClient
from ..common.config import SyncConfig
from ..common.embeddings import Embedder
from ..common.qdrant_store import QdrantStore


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("kb_sync")

    cfg = SyncConfig.from_env()
    qdrant = QdrantStore(cfg.qdrant_url, cfg.qdrant_api_key, timeout=cfg.http_timeout)
    trilium = TriliumClient(cfg.trilium_url, cfg.trilium_token, timeout=cfg.http_timeout)
    docling = DoclingClient(cfg.docling_url, cfg.docling_api_key, timeout=900)
    embedder = Embedder(cfg.embed_url, timeout=cfg.http_timeout)
    state = State(cfg.state_db)
    engine = SyncEngine(cfg, qdrant, trilium, docling, embedder, state)
    metrics = MetricsState()

    server = start_server(cfg.metrics_port, metrics, engine)
    log.info("kb-sync HTTP auf Port %d (/healthz /metrics /admin/sync)", cfg.metrics_port)

    def report(stats) -> None:
        metrics.update(stats)
        metrics.embedding_calls = embedder.calls
        metrics.docling_conversions = docling.conversions

    while True:
        started = time.time()
        try:
            report(engine.run())
        except Exception as exc:  # noqa: BLE001
            log.error("Sync-Zyklus fehlgeschlagen (wiederhole in %.0fs): %s", cfg.sync_interval, exc)
        # Restliche Zeit bis zum naechsten Lauf; Laeufe ueberlappen nie
        elapsed = time.time() - started
        sleep_s = max(1.0, cfg.sync_interval - elapsed)
        if elapsed > cfg.sync_interval:
            log.warning("Sync-Lauf (%.1fs) uebertraf Intervall %.0fs", elapsed, cfg.sync_interval)
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
