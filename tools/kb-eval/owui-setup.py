#!/usr/bin/env python3
"""Open-WebUI: Knowledge-Store-Anbindung idempotent einrichten (v0.11.1-API).

Einrichtet beides in einem Durchlauf:
  1. MCP-Tool-Server "Knowledge Store" (/v1/configs/tool_servers)
  2. External Knowledge Source (Qdrant-Kollektion "kb") inkl. Live-Test

Voraussetzung: Index muss Daten enthalten (sonst liefert der EKS-Test
keine Treffer und das Script beendet mit Exit 1).

Nutzung (vom Control-Node aus, kubectl + cluster-internetz erreichbar):
    python3 owui-setup.py

Credentials werden zur Laufzeit aus K8s-Secrets gelesen:
    svc-llm/open-webui-secrets   (WEBUI_ADMIN_EMAIL, WEBUI_ADMIN_PASSWORD)
    svc-rag/knowledge-pipeline-secret (KNOWLEDGE_API_KEYS, Rolle readonly)
    svc-rag/qdrant-secret        (api_key)
Es werden keine Zugangsdaten in Dateien oder Logs gespeichert.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

OWUI_BASE = "http://open-webui.svc-llm.svc.cluster.local:8080"
KB_MCP_URL = "http://knowledge-service.svc-rag.svc.cluster.local:80"
KB_MCP_PATH = "/mcp"
QDRANT_ENDPOINT = "http://qdrant.svc-rag.svc.cluster.local:80"
COLLECTION = "kb"
MCP_ID = "knowledge-store"
KB_NAME = "Wissensbasis (Trilium RAG)"
TEST_QUERY = "B60 Power Limit wk-5 vLLM Benchmark"


def k8s_secret(namespace: str, name: str, key: str) -> str:
    raw = subprocess.check_output(
        [
            "kubectl", "get", "secret", "-n", namespace, name,
            "-o", f"jsonpath={{.data.{key}}}",
        ],
        text=True,
    ).strip()
    return base64.b64decode(raw).decode()


def kb_read_token() -> str:
    for part in k8s_secret("svc-rag", "knowledge-pipeline-secret", "KNOWLEDGE_API_KEYS").split(","):
        if ":" in part:
            role, _, token = part.partition(":")
            if role.strip() == "readonly":
                return token.strip()
    raise SystemExit("Kein readonly-Token in KNOWLEDGE_API_KEYS gefunden")


def api(method: str, path: str, token: str, payload=None, base: str | None = None):
    base = base or OWUI_BASE
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise SystemExit(f"OWUI {method} {path} -> HTTP {e.code}: {detail}")


def signin() -> str:
    email = k8s_secret("svc-llm", "open-webui-secrets", "WEBUI_ADMIN_EMAIL")
    password = k8s_secret("svc-llm", "open-webui-secrets", "WEBUI_ADMIN_PASSWORD")
    status, res = api("POST", "/api/v1/auths/signin", "", {"email": email, "password": password})
    if not isinstance(res, dict) or not res.get("token"):
        raise SystemExit(f"OWUI-Signin fehlgeschlagen: {status} {res}")
    return res["token"]


# ---------- 1) MCP-Tool-Server ----------

def setup_mcp_server(token: str) -> None:
    status, res = api("GET", "/api/v1/configs/tool_servers", token)
    servers = res.get("TOOL_SERVER_CONNECTIONS", []) if isinstance(res, dict) else []

    existing = next((s for s in servers if (s.get("info") or {}).get("id") == MCP_ID), None)
    conn = {
        "url": KB_MCP_URL,
        "path": KB_MCP_PATH,
        "type": "mcp",
        "auth_type": "bearer",
        "key": kb_read_token(),
        "config": {
            "enable": True,
            "access_grants": [
                {"id": uuid.uuid4().hex, "role": "admin", "permission": "read"},
                {"id": uuid.uuid4().hex, "role": "user", "permission": "read"},
            ],
        },
        "info": {
            "id": MCP_ID,
            "name": "Knowledge Store (Wissensbasis)",
            "description": (
                "Suche und notieren in der Trilium-Wissensbasis (RAG-Index): "
                "search_knowledge, remember, forget, status."
            ),
        },
    }
    if existing:
        print("[mcp] Server existiert bereits, ueberschreibe Eintrag.")
        servers = [s for s in servers if (s.get("info") or {}).get("id") != MCP_ID]
    else:
        print("[mcp] Server wird angelegt.")
    servers.append(conn)
    status, res = api("POST", "/api/v1/configs/tool_servers", token, {"TOOL_SERVER_CONNECTIONS": servers})
    names = [(s.get("info") or {}).get("name") for s in (res or {}).get("TOOL_SERVER_CONNECTIONS", [])]
    print(f"[mcp] OK, registrierte Server: {names}")


# ---------- 2) External Knowledge Source ----------

def eks_source_form() -> dict:
    return {
        "type": "collection",
        "name": COLLECTION,
        "config": {
            "content_field": "payload.content",
            "metadata_field": "payload.metadata",
            "document_id_field": "payload.note_id",
            "vector_field": "dense",
        },
    }


def eks_connection_form() -> dict:
    return {
        "name": "RAG Qdrant (svc-rag)",
        "provider": "qdrant",
        "endpoint": QDRANT_ENDPOINT,
        "auth_config": {"api_key": k8s_secret("svc-rag", "qdrant-secret", "api_key")},
        "config": {"timeout": 30},
        "capabilities": {},
        "enabled": True,
    }


def setup_eks(token: str) -> None:
    # Connection (idempotent via endpoint+provider)
    status, res = api("GET", "/api/v1/knowledge/external/connections", token)
    items = res.get("items", []) if isinstance(res, dict) else []
    conn = next(
        (c for c in items if c.get("provider") == "qdrant" and c.get("endpoint") == QDRANT_ENDPOINT),
        None,
    )
    if conn:
        print(f"[eks] Connection existiert bereits: {conn.get('name')} ({conn.get('id')})")
        connection_id = conn["id"]
    else:
        print("[eks] Connection wird angelegt.")
        status, res = api("POST", "/api/v1/knowledge/external/connections", token, eks_connection_form())
        if not isinstance(res, dict):
            raise SystemExit(f"[eks] Connection-Antwort unerwartet: {status} {res!r}")
        connection_id = res.get("id")
        if not connection_id:
            raise SystemExit(f"[eks] Connection ohne ID zurueck: {res}")
        print(f"[eks] Connection angelegt: {connection_id}")

    # Live-Test vor Anlage des Knowledge-Bases
    print(f"[eks] Test-Query: {TEST_QUERY!r}")
    status, res = api(
        "POST",
        "/api/v1/knowledge/external/source/test",
        token,
        {
            "connection": eks_connection_form(),
            "source": eks_source_form(),
            "query": TEST_QUERY,
            "count": 5,
        },
    )
    docs = res.get("documents", []) if isinstance(res, dict) else []
    if not docs:
        raise SystemExit(
            "[eks] Test lieferte keine Treffer - Index ist vermutlich noch leer. "
            "Erst kb-sync ausfuehren, dann owui-setup.py neu starten."
        )
    if isinstance(docs[0], str):
        print(f"[eks] Test erfolgreich: {len(docs)} Treffer; Top: {docs[0][:80]!r}")
    else:
        md = (docs[0] or {}).get("metadata")
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except ValueError:
                md = None
        top_note = (md or {}).get("note_id") if isinstance(md, dict) else None
        print(
            f"[eks] Test erfolgreich: {len(docs)} Treffer"
            + (f", top note_id: {top_note}" if top_note else "")
        )

    # Knowledge-Base (idempotent via meta.external.connection_id + collection)
    status, res = api("GET", "/api/v1/knowledge/", token)
    kbs = res.get("items", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    kb = next(
        (
            k
            for k in kbs
            if ((k.get("meta") or {}).get("external") or {}).get("connection_id") == connection_id
            and ((k.get("meta") or {}).get("external") or {}).get("source", {}).get("name") == COLLECTION
        ),
        None,
    )
    if kb:
        print(f"[eks] Knowledge-Base existiert bereits: {kb.get('name')} ({kb.get('id')})")
        return
    print("[eks] Knowledge-Base wird angelegt.")
    status, res = api(
        "POST",
        "/api/v1/knowledge/external/knowledge/create",
        token,
        {
            "name": KB_NAME,
            "description": (
                "RAG-Index der Trilium-Wissensbasis (Kollektion 'kb', Qdrant in svc-rag). "
                "Dense-Suche ueber alle indexierten Notizen."
            ),
            "connection_id": connection_id,
            "source": eks_source_form(),
            "access_grants": [
                {"id": uuid.uuid4().hex, "role": "admin", "permission": "read"},
                {"id": uuid.uuid4().hex, "role": "user", "permission": "read"},
            ],
        },
    )
    if isinstance(res, dict) and res.get("id"):
        print(f"[eks] Knowledge-Base angelegt: {res.get('name')} ({res.get('id')})")
    else:
        raise SystemExit(f"[eks] Knowledge-Base-Antwort unerwartet: {res}")


def main() -> None:
    global OWUI_BASE
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-url",
        default=OWUI_BASE,
        help="OWUI-Basis-URL (Default: Cluster-Service; vom Control-Node "
        "z. B. http://127.0.0.1:8089 per kubectl port-forward)",
    )
    args = p.parse_args()
    OWUI_BASE = args.base_url

    print(f"OWUI: {OWUI_BASE}")
    token = signin()
    print("[owui] Angemeldet (Admin).")
    setup_mcp_server(token)
    setup_eks(token)
    print("\nFertig: MCP-Tool-Server + External Knowledge Source sind eingerichtet.")


if __name__ == "__main__":
    main()
