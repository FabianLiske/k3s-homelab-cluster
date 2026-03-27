# Homepage

## Ziel

`Homepage` laeuft intern im Cluster und wird ueber den VLAN20-Ingress bereitgestellt.

* Hostname: `home.rohrbom.be`
* Ingress-Class: `nginx-internal`
* Erwartete interne Ziel-IP: `172.26.20.151`

Wichtig: `home.rohrbom.be` muss intern auf den 20er-Ingress zeigen. Das bedeutet in der Praxis Split-DNS oder einen lokalen DNS-Override. Die Domain darf dabei trotz des Namens **nicht** ueber den Public-Ingress laufen.

## Dateien

Die App liegt unter:

* `apps/internal/homepage/`

Aufteilung der Konfiguration:

* `configmap.yaml`: nicht-sensitive Dateien wie `kubernetes.yaml`
* `homepage-secret.yaml`: sensitive Homepage-Konfig wie `services.yaml`, `settings.yaml`, `widgets.yaml`
* `homepage-secret.yaml.example`: Vorlage fuer Aenderungen

## Secret bearbeiten

Voraussetzung:

```bash
export SOPS_AGE_KEY_FILE=./age.cluster.key
```

Das Repo enthaelt bereits eine verschluesselte `homepage-secret.yaml`.

Am einfachsten bearbeitest du sie direkt mit SOPS:

```bash
sops apps/internal/homepage/homepage-secret.yaml
```

Wenn du von der Vorlage neu starten willst:

```bash
cp apps/internal/homepage/homepage-secret.yaml.example apps/internal/homepage/homepage-secret.yaml
```

Optional zum Lesen/Pruefen entschluesseln:

```bash
sops --decrypt apps/internal/homepage/homepage-secret.yaml
```

Falls du eine unverschluesselte Arbeitskopie erstellt hast, danach wieder verschluesseln:

```bash
sops --encrypt --in-place apps/internal/homepage/homepage-secret.yaml
```

## Erste Konfiguration

Die erste Version ist absichtlich konservativ:

* Links, Site-Monitoring und Kubernetes-Pod-Stats funktionieren sofort
* nur das Prometheus-Widget ist direkt aktiv, weil es in deinem Setup kein zusaetzliches Secret braucht
* native Widgets fuer Jellyfin, *arr, qBittorrent, Paperless, Trilium und Grafana sind bereits als Kommentar vorbereitet

So bleibt die Startseite direkt nutzbar, ohne dass ungueltige API-Keys Fehler produzieren.

## Checks

```bash
kubectl -n svc-homepage get pods,svc,ingress
kubectl -n svc-homepage describe ingress homepage
curl -Ik https://home.rohrbom.be
```

Wenn Homepage laeuft, solltest du danach im Browser pruefen:

* `home.rohrbom.be` ist intern erreichbar
* die Service-Links oeffnen korrekt
* Site-Monitoring wird angezeigt
* das Kubernetes-Widget zeigt Cluster- und Node-CPU/RAM
