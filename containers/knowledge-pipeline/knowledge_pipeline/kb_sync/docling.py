"""Docling-Serve-Client: PDF -> Markdown (v1/convert/file)."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class DoclingError(RuntimeError):
    pass


class DoclingClient:
    def __init__(self, url: str, api_key: str = "", timeout: float = 900.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            # Docling erwartet den Key im Header "X-Api-Key"
            self.session.headers["X-Api-Key"] = api_key
        self.conversions = 0

    def ready(self) -> bool:
        try:
            r = self.session.get(f"{self.url}/readyz", timeout=15)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def pdf_to_markdown(self, data: bytes, filename: str) -> str:
        """Konvertiert ein PDF in Markdown. Liefert '' wenn leer."""
        try:
            r = self.session.post(
                f"{self.url}/v1/convert/file",
                files={"files": (filename, data, "application/pdf")},
                data={"to_formats": "md"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DoclingError(f"Docling nicht erreichbar: {exc}") from exc
        if r.status_code >= 400:
            raise DoclingError(f"Docling Konvertierung: HTTP {r.status_code}: {r.text[:300]}")
        try:
            d = r.json().get("document", {})
        except ValueError as exc:
            raise DoclingError(f"Docling-Antwort nicht JSON: {r.text[:200]}") from exc
        md = d.get("md_content") or (d.get("content") or {}).get("md_content") or ""
        if not md.strip():
            log.warning("Docling lieferte kein Markdown fuer '%s'", filename)
        self.conversions += 1
        return md
