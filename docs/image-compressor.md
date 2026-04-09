# Image Compressor

Das Upstream-Repo `abue-ammar/image-compressor` ist fuer den Web-Betrieb eine statische Vite/React-App.
Der Web-Build wurde am `2026-04-09` gegen Commit `75ec0dc3970307c531d90ae525ed2108e8426ae0` erfolgreich mit `npm ci && npm run build` getestet.

## Image-Build wie bei Telegraf

Der Container unter `containers/image-compressor/` baut das Upstream-Repo direkt aus GitHub und liefert das `dist/` ueber unprivileged Nginx auf Port `8080` aus.
Build und Push laufen jetzt wie bei `telegraf` ueber GitHub Actions.

Der Workflow liegt in `.github/workflows/build-image-compressor-image.yaml` und pusht nach:

```bash
ghcr.io/fabianliske/k3s-homelab-cluster/image-compressor:latest
ghcr.io/fabianliske/k3s-homelab-cluster/image-compressor:<git-sha>
```

Er wird automatisch bei Pushes auf `main` mit Aenderungen unter `containers/image-compressor/` ausgefuehrt und kann zusaetzlich manuell per `workflow_dispatch` gestartet werden.

Wenn du lieber erst lokal testest:

```bash
docker build -t image-compressor:local ./containers/image-compressor
docker run --rm -p 18080:8080 image-compressor:local
curl http://127.0.0.1:18080/healthz
```

## Cluster aktivieren

Die App-Manifeste liegen unter `apps/internal/image-compressor/`, sind aber absichtlich noch nicht in `apps/internal/kustomization.yaml` aktiviert. So zieht Flux nicht schon vor dem ersten Image-Push an einem nicht vorhandenen Tag.

1. Den Workflow einmal laufen lassen, damit `ghcr.io/fabianliske/k3s-homelab-cluster/image-compressor:latest` existiert.
2. Falls das GHCR-Package privat bleibt, ein `ghcr-cred` Secret fuer `svc-image-compressor` anlegen. Eine Vorlage liegt unter `apps/internal/image-compressor/ghcr-cred-secret.yaml.example`.
3. `./image-compressor/` in `apps/internal/kustomization.yaml` einkommentieren.
4. Danach Flux neu reconciliieren.

```bash
flux reconcile kustomization apps --with-source -n flux-system
```

## Hinweise

- Das Deployment verwendet jetzt bewusst dasselbe GHCR-Schema wie `telegraf`: `ghcr.io/fabianliske/k3s-homelab-cluster/image-compressor:latest`.
- Wenn dein GHCR-Package public ist, kannst du `imagePullSecrets` aus dem Deployment auch wieder entfernen.
- Wenn du das Package privat laesst, brauchst du im Namespace `svc-image-compressor` zusaetzlich ein passendes `ghcr-cred` Secret.
- Der Ingress ist aktuell auf `compressor.intern.rohrbom.be` konfiguriert.

## Pruefen

```bash
kubectl get deploy,pods,svc,ingress -n svc-image-compressor
kubectl logs -n svc-image-compressor deploy/image-compressor
```
