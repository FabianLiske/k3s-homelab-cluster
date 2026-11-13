"""knowledge-service: FastAPI-App + ASGI-Auth-Middleware + MCP-Mount unter /mcp.

Offene Pfade (intern, per NetPol eingeschraenkt): /healthz, /metrics.
Authentifiziert (Bearer-Token): POST /search, alle Pfade unter /mcp.
"""

from __future__ import annotations

import logging
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .. import __version__
from ..common.config import ServiceConfig
from ..common.embeddings import Embedder
from ..common.qdrant_store import QdrantStore
from ..kb_sync.trilium import TriliumClient
from .mcp import create_mcp_server
from .roles import current_role
from .search import SearchError, read_sync_state, run_search
from .trilium_write import TriliumWriter

log = logging.getLogger(__name__)

# Pfade ohne Token (intern, durch NetPol eingeschraenkt)
_OPEN_PATHS = {"/healthz", "/metrics"}


class AuthMiddleware:
    """ASGI-Middleware: Bearer-Token -> Rolle (ContextVar) oder 401."""

    def __init__(self, app, api_keys: dict[str, str]):
        self.app = app
        self.api_keys = api_keys

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in _OPEN_PATHS or not (path == "/search" or path.startswith("/mcp")):
            await self.app(scope, receive, send)
            return

        header = next(
            (v for k, v in scope.get("headers", []) if k == b"authorization"), b""
        ).decode("latin-1")
        token = (
            header[len("Bearer ") :].strip() if header.lower().startswith("bearer ") else ""
        )
        role = self.api_keys.get(token)
        if not role:
            body = b'{"detail":"ungueltiges oder fehlendes Bearer-Token"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        token_ctx = current_role.set(role)
        try:
            await self.app(scope, receive, send)
        finally:
            current_role.reset(token_ctx)


class Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.queries = 0
        self.errors = 0

    def bump(self, ok: bool) -> None:
        with self._lock:
            self.queries += 1
            if not ok:
                self.errors += 1

    def render_metrics(self, last_sync_age: float | None) -> str:
        with self._lock:
            q, e = self.queries, self.errors
        lines = [
            "# HELP knowledge_queries_total Suchanfragen seit Start",
            "# TYPE knowledge_queries_total counter",
            f"knowledge_queries_total {q}",
            "# HELP knowledge_query_errors_total Fehlgeschlagene Suchanfragen seit Start",
            "# TYPE knowledge_query_errors_total counter",
            f"knowledge_query_errors_total {e}",
        ]
        if last_sync_age is not None:
            lines += [
                "# HELP knowledge_last_sync_age_seconds Sekunden seit letztem Index-Sync",
                "# TYPE knowledge_last_sync_age_seconds gauge",
                f"knowledge_last_sync_age_seconds {last_sync_age:.1f}",
            ]
        return "\n".join(lines) + "\n"


def _sync_age(state: dict | None) -> float | None:
    if state and state.get("ts_epoch"):
        return round(time.time() - float(state["ts_epoch"]), 1)
    return None


def build_app(cfg: ServiceConfig) -> "AuthMiddleware":
    """Baut die komplette ASGI-App (FastAPI + Auth + MCP)."""
    qdrant = QdrantStore(cfg.qdrant_url, cfg.qdrant_api_key, timeout=cfg.http_timeout)
    embedder = Embedder(cfg.embed_url, timeout=cfg.http_timeout)
    writer = TriliumWriter(
        TriliumClient(cfg.trilium_url, cfg.trilium_token, timeout=cfg.http_timeout),
        cfg.sync_admin_url,
        timeout=cfg.http_timeout,
    )
    counters = Counters()

    app = FastAPI(title="knowledge-service", version=__version__)

    @app.get("/healthz")
    async def healthz():
        state = read_sync_state(qdrant)
        return {
            "status": "ok",
            "version": __version__,
            "last_sync_age_s": _sync_age(state),
        }

    @app.post("/search")
    async def search(request: Request):
        try:
            body = await request.json()
        except ValueError:
            counters.bump(False)
            return JSONResponse(status_code=400, content={"detail": "ungueltiges JSON"})
        if not isinstance(body, dict):
            counters.bump(False)
            return JSONResponse(status_code=400, content={"detail": "JSON-Objekt erwartet"})
        try:
            results = run_search(
                qdrant,
                embedder,
                cfg,
                query=str(body.get("query", "")),
                top_k=int(body.get("top_k", 5)),
                source=body.get("source"),
                path=body.get("path"),
                label=body.get("label"),
                include_full_note=bool(body.get("include_full_note", False)),
            )
        except SearchError as exc:
            counters.bump(False)
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            counters.bump(False)
            log.exception("Suche fehlgeschlagen")
            return JSONResponse(
                status_code=502, content={"detail": f"Suche fehlgeschlagen: {exc}"}
            )
        counters.bump(True)
        return JSONResponse({"count": len(results), "results": results})

    @app.get("/metrics")
    async def metrics():
        state = read_sync_state(qdrant)
        text = counters.render_metrics(_sync_age(state))
        return Response(content=text, media_type="text/plain; version=0.0.4")

    # MCP unter /mcp (streamable HTTP); Auth laeuft ueber die Middleware.
    mcp = create_mcp_server(qdrant, embedder, cfg, writer)
    app.mount("/mcp", mcp.streamable_http_app())

    return AuthMiddleware(app, cfg.api_keys)


def main() -> int:
    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = ServiceConfig.from_env()
    app = build_app(cfg)
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
