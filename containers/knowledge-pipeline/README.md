# Knowledge Pipeline

Zwei Komponenten in einem Image
(`ghcr.io/fabianliske/k3s-homelab-cluster/knowledge-pipeline`, Tags `latest` + voller Commit-SHA):

| Komponente | Rolle | Deployment (svc-rag) | Port |
|---|---|---|---|
| `kb-sync` | Indexer: Trilium-Notizen → Qdrant-Kollektion `kb` (dense + BM25) | `kb-sync` | 9101 (healthz/metrics) |
| `knowledge-service` | Query-Schicht: REST `/search` + MCP unter `/mcp` | `knowledge-service` | 8000 (Service: 80) |

Einbauort: `apps/internal/rag/` (Flux). Node-Selector `heavy-compute` (wk-4), direkt
neben Qdrant. Build: GitHub-Action `build-knowledge-pipeline-image` (Push auf main,
Pfad `containers/knowledge-pipeline/**`) → Tags `latest` + `sha-<commit>`.

## Datenfluss

```
Trilium (ETAPI, #noIndex-Ausnahme, Calendar exkl.)
  → kb-sync: Markdown-Extraktion (PDF via Docling-Serve), Chunking
  → Embedding: Qwen3-Embedding-0.6B (1024d) via TEI (embeddings.svc-llm:8080)
  → Qdrant `kb` (named vector "dense" + BM25-Sparse) + Parent-Text für Zitate

knowledge-service:
  /search    Hybrid (dense + BM25, RRF), Filter source/path/label, optional parent_text
  /mcp       MCP-Tools (Streamable HTTP): search_knowledge, remember, forget, status
```

## Secrets (SOPS, `apps/internal/rag/knowledge-pipeline-secret.yaml`)

- `TRILIUM_TOKEN`: ETAPI-Token für kb-sync (Read) und knowledge-service (remember/forget)
- `KB_READ_ONLY_KEY` / `KB_READ_WRITE_KEY`: Bearer-Tokens des knowledge-service
  (`KNOWLEDGE_API_KEYS` im Format `read:<token>,readwrite:<token>`)

LiteLLM-Gateway nutzt einen eigenen Readwrite-Key aus
`apps/internal/llm/litellm/knowledge-mcp-secret.yaml` (`KNOWLEDGE_RW_TOKEN`).

## Indexierung

- Initial: Full-Sync beim ersten Start; danach inkrementell (SHA-256 über
  Chunker-Version + Embed-Modell + Text), Poll-Intervall `SYNC_INTERVAL` (300 s).
- Ausschlüsse: `KB_EXCLUDE_PATHS` (Pfadpräfixe, komma-separiert, Default `Calendar`)
  und das Notiz-Label `#noIndex` (pro Note, überschreibt beide).
- Finances sind indexiert (Betreiberentscheidung 2026-11); Calendar bewusst draußen.
- `STATE_DB` liegt auf `emptyDir`: Pod-Neustart ⇒ einmaliger Full-Reindex (bewusst,
  hält den Index konsistent mit dem aktuellen Trilium-Stand).
- Single-Note-Sync aus dem knowledge-service: `POST http://kb-sync.svc-rag:9101/admin/sync`
  (Rolle `readwrite` erforderlich; z. B. nach manuellem Trilium-Edit).

## Zugriff & Absicherung

- NetPols: kb-sync/knowledge-service sprechen nur DNS, Qdrant, Docling, Trilium-ETAPI,
  TEI-Embeddings; Ingress auf knowledge-service nur aus `svc-rag` und `svc-llm`;
  Qdrant zusätzlich von `svc-llm` (OWUI External Knowledge Source).
- Alle API-/MCP-Pfade außer `/healthz`, `/metrics` erfordern Bearer-Token
  (`Authorization: Bearer <key>`); Rollen `read` / `readwrite` via `KNOWLEDGE_API_KEYS`.
- OWUI-Zugang zur Wissensbasis läuft in-cluster über ClusterIP (kein Ingress nötig).

## Anbindung Agenten & Open WebUI

- **LiteLLM** (`apps/internal/llm/litellm/configmap.yaml`): `mcp_servers.knowledge`
  → `https://llm.liske.cc/mcp/knowledge` (virtuelle Keys mit Tool-ACLs möglich).
- **OpenCode**: `mcp.servers.knowledge` in `~/.config/opencode/opencode.jsonc`
  (url `https://llm.liske.cc/mcp/knowledge`, Header `Authorization: Bearer {env:LITELLM_API_KEY}`).
- **Hermes**: `mcp_servers."Knowledge Store"` in `~/.hermes/config.yaml`,
  Token via `${MCP_KNOWLEDGE_API_KEY}` in `~/.hermes/.env`.
- **Open WebUI v0.11.1** (siehe `tools/kb-eval/owui-setup.py`, idempotent):
  1. MCP-Tool-Server: `POST /v1/configs/tool_servers` mit
     `{url: http://knowledge-service.svc-rag:80/mcp, type: mcp, auth_type: bearer, key: <read-key>}`
     (Achtung: POST ersetzt die komplette Liste ⇒ vorher GET + merge).
  2. External Knowledge Source: Qdrant-Connection
     (`provider: qdrant`, endpoint ClusterIP, api_key) + Knowledge-Base mit
     `source.config: {content_field: payload.content, metadata_field: payload.metadata,
     document_id_field: payload.note_id, vector_field: dense}`.
     Embedding-Modell muss identisch zum Index sein
     (`RAG_EMBEDDING_MODEL=local/qwen-3-embedding-0.6b` via LiteLLM).
     Die EKS läuft direkt gegen Qdrant (NetPol svc-llm → 6333), nicht über
     knowledge-service.

## Betrieb

```bash
# Status (Pod-Logs; Index-Status auch per MCP-Tool `status`)
kubectl logs -n svc-rag deploy/kb-sync --tail=50

# Golden-Set-Evaluation (lokal vom Control-Node mit Port-Forward)
kubectl port-forward -n svc-rag svc/knowledge-service 8000:80
python3 tools/kb-eval/eval.py --base-url http://127.0.0.1:8000 --token <read-key>

# OWUI-Anbindung (nach befülltem Index)
python3 tools/kb-eval/owui-setup.py
```

## Bekannte Einschränkungen

- Deployment ist auf den CI-Build gepinnt (Tag = voller Commit-SHA des main-Merge,
  `imagePullPolicy: IfNotPresent`, wie bei unifi-mcp): Fuer ein Update nach dem
  Build den Tag in beiden Deployments auf die neue SHA setzen und mergen.
- Embedding-Modellwechsel ⇒ `CHUNKER_VERSION`/`embed_model` ändert den Inhalt-Hash,
  d. h. vollständiger Reindex (wie oben bei Neustart) — kein manuelles Aufräumen nötig.
- OWUI EKS = reine Dense-Retrieval (kein RRF); die Hybrid-Qualität kommt über
  den MCP-Weg (`search_knowledge`).
