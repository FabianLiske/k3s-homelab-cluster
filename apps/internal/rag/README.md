# RAG-Infrastruktur (svc-rag)

## Zweck und Abgrenzung

Dies ist die **Infrastruktur-Basis** für den späteren Knowledge-Store:

- **Qdrant v1.20.0** — Vektordatenbank (Collections, Embeddings, Snapshots)
- **Docling-Serve v1.38.2 (CPU)** — Dokument-Konvertierung (u.a. PDF → strukturiertes Markdown) inkl. Web-UI

**Noch NICHT enthalten:** RAG-Pipeline, Knowledge-Service, Trilium-Sync,
Retrieval/Embedding-Orchestrierung und die Embedding-Modellumstellung.
Die Dienste sind isoliert deploybar und einzeln betreibbar; die Pipeline
kommt in einem separaten Schritt.

## Platzierung und Scheduling

| Dienst | Node | Scheduling | Storage |
|---|---|---|---|
| Qdrant | wk-4 | `node.rohrbom.be/heavy-compute: "true"` | Longhorn-PVC `qdrant-data` (RWO, 10Gi) |
| Docling | wk-5 | `node.rohrbom.be/workload: llm` + Toleration `dedicated=llm:NoSchedule` (Muster des Embeddings-Deployments) | keiner (Modelle im Image) |

Qdrant bleibt auf wk-4: wk-5 hat **keinen Longhorn-CSI-Treiber**
(nur Local-PVs für die LLM-Modelle). Den Taint/Selector von wk-5 nicht
verändern; Longhorn auf wk-5 nachzurüsten war ausdrücklich kein Teil
dieser Ausbaustufe.

**Kapazitätshinweis:** wk-5 hat aktuell RAM-Reserve, ist anhand der
bestehenden Requests/Limits aber bereits übercommittet. Für Docling gilt
keine pauschale Kapazitätsgarantie; bei paralleler Auslastung mit
vLLM/Chat muss das Verhalten gemessen werden.

## Modellbereitstellung und Docling-Parallelität

Das Image `ghcr.io/docling-project/docling-serve-cpu:v1.38.2` bringt
seine Modelle mit (Containerpfad
`/opt/app-root/src/.cache/docling/models`). Es gibt **keinen
Download beim Erststart** und **kein Modell-PVC** — früherer
`DOCLING_SERVE_ARTIFACTS_PATH`-Override und Modell-PVC wurden entfernt.
Das reicht für den DNS-only-Egress (keine Hugging-Face-Zugriffe nötig).

Parallelität ist explizit begrenzt (Startkonfiguration, **zu messen** —
nicht final):

| Variable | Wert | Bedeutung |
|---|---|---|
| `UVICORN_WORKERS` | 1 | ein API-Prozess |
| `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` | 1 | ein Konvertierungs-Worker (Standard wären 2, ohne Modell-Sharing → doppelte Modellinstanzen) |
| `DOCLING_NUM_THREADS` | 4 | Torch-CPU-Threads passend zum Vier-CPU-Limit |
| `DOCLING_SERVE_OPTIONS_CACHE_SIZE` | 1 | ein Converter-Cache-Eintrag |

Ressourcen: Requests 500m/2Gi, Limits 4 CPU/8Gi. Der RAM-Zuwachs während
des Processings ist bekannt: **Ein OOM-Restart heilt den Pod, garantiert
aber nicht die erfolgreiche Verarbeitung des Dokuments.** Bei grossen
Dokumenten sind Limit und Worker-Anzahl zu justieren und zu messen.

Kein GPU-Request, keine GPU-Device-Mounts.

Docling verwendet bei Updates `Recreate`: Der alte Pod wird beendet, bevor
der neue startet. So laden nicht zwei Modellinstanzen parallel auf wk-5.
Der Dienst ist bis zum abgeschlossenen Modell-Warmup des neuen Pods
unterbrochen; laufende Konvertierungen können abbrechen. Updates daher
außerhalb aktiver Konvertierungen durchführen.

## API-Authentifizierung

Beide Dienste haben native API-Key-Auth aktiviert (Betreiberentscheidung:
Firewall regelt den Client-Zugriff auf den internen Ingress, die Keys sind
zusätzlich ausdrücklich gewünscht). Die Keys liegen **ausschließlich** in
SOPS-verschlüsselten Secrets und werden per `secretKeyRef` injiziert:

| Dienst | Secret | Env | Header |
|---|---|---|---|
| Qdrant | `svc-rag/qdrant-secret` (`api_key`) | `QDRANT__SERVICE__API_KEY` | `api-key: <key>` oder `Authorization: Bearer <key>` |
| Docling | `svc-rag/docling-serve-secret` (`api_key`) | `DOCLING_SERVE_API_KEY` | `X-Api-Key: <key>` |

Die Web-UI unter
`docling.liske.cc/ui` fragt nach dem Key in einem Eingabefeld und sendet
ihn als `X-Api-Key` (sessionStorage, kein Cookie, kein Cache).

**Key-Bedienung (ohne echten Key im Commit/Log):**

```bash
# Key auslesen (nur im Terminal, nie in Datei/Commit):
KEY=$(sops -d apps/internal/rag/qdrant/qdrant-secret.yaml \
  | yq '.stringData.api_key')

# Qdrant abfragen:
curl -H "api-key: $KEY" https://qdrant.liske.cc/collections
# Web-UI: https://qdrant.liske.cc/dashboard → API-Key-Eingabefeld
#   (Key dort nur in den Browser-Tab/Clipboard kurzzeitig bringen)

# Docling: eigene kleine Test-PDF unter ./test.pdf bereitstellen.
# Geschützten Konvertierungs-Endpoint per Multipart-POST aufrufen:
KEYD=$(sops -d apps/internal/rag/docling-serve/docling-serve-secret.yaml \
  | yq '.stringData.api_key')
curl -H "X-Api-Key: $KEYD" -F 'files=@./test.pdf' https://docling.liske.cc/v1/convert/file
# UI: https://docling.liske.cc/ui → Key-Eingabefeld
```

Probes/Health-Endpunkte sind in beiden Versionen explicitly auth-frei
(Qdrant: `/healthz`, `/readyz`, `/livez` + Web-UI-Pfad; Docling:
`/health`, `/ready`, `/readyz`, `/livez`) — es werden **keine
geheimen Header als Literale** in den Manifesten getragen.

Snapshot-Restore aus Remote-URLs ist bei Qdrant abgeschaltet
(`ENABLE_SNAPSHOT_URL_RECOVERY=false`); Restore geht nur aus lokalen
Dateien/Uploads.

## Storage, Snapshots und Aufbewahrung

- Qdrant läuft als UID/GID 1000 (non-root), Daten-Mount `/qdrant/storage`
  (PVC `qdrant-data`).
- **Snapshot-Pfad:** `/qdrant/storage/snapshots`
  (`QDRANT__STORAGE__SNAPSHOTS_PATH`). Der Image-Standard
  `/qdrant/snapshots` liegt ausserhalb des Mounts und ist für UID 1000
  nicht beschreibbar. Temporäre Pfade (u.a. hochgeladene Snapshots vor
  dem Restore) liegen unter `/qdrant/storage/temp`
  (`QDRANT__STORAGE__TEMP_PATH`).
- **Qdrant-Snapshot ≠ Volume-Backup:** Ein Qdrant-Snapshot ist eine
  konsistente Momentaufnahme einer Collection (bzw. aller Collections)
  **innerhalb** des Daten-Volumes; es ist kein Ersatz für Longhorn
  Volume-Backups des gesamten PVC. Für die spätere Backup-Strategie
  beides vorsehen: Snapshots über die API exportierbar (auch zu remote
  Storage), Volume-Backups über Longhorn/Flux-Schedule.
- **Aufbewahrung bei Stack-Entfernung:** Namespace `svc-rag` und PVC
  `qdrant-data` tragen die Annotation
  `kustomize.toolkit.fluxcd.io/prune: disabled`. Wird der Stack aus dem
  Repo entfernt, pruned Flux die Deployments/Services etc., **lässt
  Namespace und Daten-PVC aber bewusst zurück** (Longhorn `longhorn-2r`
  hätte bei PVC-Entfernung `reclaimPolicy: Delete` → Daten weg).
  **Wichtig:** Eine explizite manuelle `kubectl delete namespace svc-rag`
  umgeht diesen Schutz weiterhin und löscht die Daten mit.
- Docling hat keinen PVC: Modelle aus dem Image, temporäre Dateien in
  `emptyDir`.

## Prüfungen vor dem Rollout (Checkliste)

Stand 12.11.2026: Punkte 1–4 in isolierten lokalen Container-Smoke-Tests
(qdrant/qdrant:v1.20.0 als UID 1000, docling-serve-cpu:v1.38.2 ohne
Modell-PVC) erfolgreich ausgeführt — inkl. echter 1-Seiten-PDF-Konversion
und Snapshot/Restore am neuen Pfad. Punkt 5 (Lasttest) bleibt dem
Rollout vorbehalten.

1. **Authentifizierter Zugriff:** Qdrant `GET /collections` mit dem SOPS-Key
   → 200; Docling `POST /v1/convert/file` mit SOPS-Key → 2xx.
2. **Abgewiesener Zugriff:** ohne Key bzw. mit falschem Key → 401
   (Qdrant und Docling). Probes bleiben ohne Key erreichbar.
   Hinweis: `/health*`, `/v1/capabilities` (Docling) und `/version` sind
   in v1.38.2 bewusst ohne Auth (Health-/Discovery-Endpoints) — sie
   eignen sich nicht als Auth-Indikator.
3. **Echte PDF-Konversion:** kleine PDF authentifiziert über
   `POST /v1/convert/file` (sync) bzw. `/v1/convert/file/async`
   (mit Task-Polling); RAM-Verhalten beobachten (Limits/OOM).
4. **Qdrant-Snapshot/Restore:** Collection anlegen, Snapshot erstellen
   (`POST /collections/<name>/snapshots`), Snapshot-Datei unter
   `/qdrant/storage/snapshots/<name>/` prüfen, Restore per
   `PUT /collections/<ziel>/snapshots/recover` mit
   `{"location":"file:///qdrant/storage/snapshots/<name>/<datei>.snapshot"}`
   (lokale `file://`-Pfade funktionieren auch mit deaktiviertem
   URL-Restore; `http(s)://`-Quellen werden mit 403 abgewiesen).
5. **Lasttest parallel zu Chat/Embeddings:** Docling-Konvertierung
   während vLLM-/Embedding-Last auf wk-5; bei Degradation
   Request/Limit-Werte anpassen.
