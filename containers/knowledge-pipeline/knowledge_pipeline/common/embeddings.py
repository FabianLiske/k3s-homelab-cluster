"""Embedding-Client (Qwen3-Embedding-0.6B, OpenAI-kompatibel via TEI /v1/embeddings).

TEI 1.9 akzeptiert auf /embed nur das strukturierte EmbedRequest; wir nutzen
bewusst den OpenAI-kompatiblen Endpunkt, weil derselbe Request-Formatweg auch
ueber LiteLLM (local/qwen-3-embedding-0.6b) und damit Open-WebUI laeuft —
identischer Vektorraum auf allen Wegen.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

# TEI limitiert Batch-Input auf 8192 Token; unsere Chunks bleiben weit
# darunter. 32/Call ist ein ruhiger Wert fuer den CPU-Service
# (--max-client-batch-size=32).
BATCH_SIZE = 32

# Gesprochener Modell-Name des TEI-Services (--served-model-name)
SERVED_MODEL = "local-embedding"


class EmbedError(RuntimeError):
    pass


class Embedder:
    def __init__(self, url: str, timeout: float = 120.0, max_attempts: int = 4):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = requests.Session()
        self.calls = 0

    def _post(self, payload: list[str]) -> list[list[float]]:
        last_err: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = self.session.post(
                    f"{self.url}/v1/embeddings",
                    json={"model": SERVED_MODEL, "input": payload},
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    self.calls += 1
                    body = r.json()
                    data = body.get("data")
                    if not isinstance(data, list):
                        raise EmbedError(f"Unerwartetes Embedding-Format: {str(body)[:200]}")
                    if len(data) != len(payload):
                        raise EmbedError(
                            f"Embedding-Anzahl passt nicht: {len(data)} fuer {len(payload)} Inputs"
                        )
                    return [[float(x) for x in item.get("embedding", [])] for item in data]
                log.warning(
                    "Embedding %d: HTTP %s (%s)",
                    attempt,
                    r.status_code,
                    r.text[:200],
                )
                last_err = EmbedError(f"HTTP {r.status_code}: {r.text[:200]}")
            except requests.RequestException as exc:
                last_err = exc
                log.warning("Embedding %d: %s", attempt, exc)
            if attempt < self.max_attempts:
                time.sleep(2 * attempt)
        raise EmbedError(f"Embedding fehlgeschlagen nach {self.max_attempts} Versuchen: {last_err}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            out.extend(self._post(texts[i : i + BATCH_SIZE]))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._post([text])[0]
