# x86-Media-Node im bestehenden ARM-K3s-Cluster

## Ziel

Das bestehende K3s-Cluster besteht aktuell aus ARM-basierten Control-Plane- und Worker-Nodes (Raspberry Pi).
Zusätzlich soll eine leistungsstärkere x86-Worker-Node aufgenommen werden, um einen dedizierten Media-Stack mit höherer CPU-/I/O-Leistung und optionaler GPU-Beschleunigung zu hosten.

Die neue Node soll:

* als reguläre K3s-Worker-Node dem bestehenden Cluster beitreten
* Netzwerkfunktionalität im Cluster vollständig mitnutzen
* dediziert für Media-Workloads verwendet werden
* große Mediendaten lokal speichern
* kleine, wichtige App-Daten weiterhin über Longhorn persistent halten
* primär Dienste wie qBittorrent, Sonarr, Radarr, Prowlarr und Jellyfin tragen

---

## Ausgangslage im aktuellen Cluster

### Bestehende Nodes

* `cp-1`, `cp-2`, `cp-3`: `control-plane,etcd`
* `wk-1`, `wk-2`, `wk-3`: `worker`

### Wichtige Eigenschaften

* Alle bestehenden Nodes sind aktuell `arm64`
* Control-Plane-Nodes sind mit `NoSchedule` getaintet
* Worker-Nodes sind aktuell **nicht** getaintet
* Longhorn läuft auf den drei Worker-Nodes
* Worker-Nodes tragen das Label:

```yaml
longhorn: storage
```

### Relevante DaemonSets

Im Cluster laufen DaemonSets, die grundsätzlich auf allen geeigneten Nodes laufen sollen:

* `kube-flannel`
* `metallb speaker`

Zusätzlich laufen mehrere Ingress-NGINX-Controller als DaemonSets.

---

## Zielarchitektur

Die neue x86-Node wird als **dedizierte Media-Node** betrieben.

### Grundidee

* **Cluster-Netzwerk-Komponenten** dürfen auf der Node laufen
* **Media-Workloads** werden gezielt auf diese Node gelegt
* **Große Mediendaten** liegen auf einem lokalen Datenträger der x86-Node
* **Kleine Konfigurationsdaten** bleiben auf Longhorn
* Die x86-Node wird **nicht** als allgemeiner Longhorn-Storage-Node für das ganze Cluster genutzt

### Warum diese Trennung?

Longhorn ist sehr gut für:

* Konfigurationsdaten
* kleine App-Daten
* Datenbanken mit überschaubarem Volumen
* verteilte, replizierte Persistenz

Longhorn ist weniger attraktiv für:

* sehr große Mediendateien
* hohe Dauerlast durch Reads/Writes
* große Download-Verzeichnisse
* Transcode-Cache
* reine Bulk-Daten ohne Replikationsbedarf

Für Mediendaten ist ein lokaler Datenträger auf der x86-Node deutlich sinnvoller.

---

## Architekturentscheidungen

## 1. Mixed-Architecture-Cluster ist erlaubt

Ein x86-Worker kann problemlos einem ARM-basierten K3s-Cluster beitreten.

Kubernetes erkennt die Architektur pro Node automatisch, z. B. über:

```yaml
kubernetes.io/arch=amd64
kubernetes.io/arch=arm64
```

Wichtig ist nur, dass die eingesetzten Container-Images für die jeweilige Architektur verfügbar sind oder explizit passende Images verwendet werden.

---

## 2. Die x86-Node wird dediziert für Media-Workloads markiert

Die neue Node soll nicht einfach wie ein normaler Worker offen im Cluster stehen, sondern gezielt markiert und getaintet werden.

### Ziel

* keine versehentliche Belegung durch beliebige Workloads
* bewusste Platzierung von Media-Stacks
* klare Trennung zwischen Pi-Workern und x86-Media-Node

### Empfohlene Labels/Taints

```yaml
label:
  dedicated=media

taint:
  dedicated=media:NoSchedule
```

Dadurch landen nur Pods auf der Node, die explizit dafür gebaut wurden.

---

## 3. Netzwerk-DaemonSets sollen auf der Media-Node laufen

Die neue Node soll vollwertig am Cluster teilnehmen.
Deshalb sollen grundlegende Netzwerk-DaemonSets dort weiterhin laufen:

* Flannel
* MetalLB Speaker

Das ist gewünscht und korrekt.

### Hinweis zu Ingress

Ingress muss **nicht zwingend** auf derselben Node wie Jellyfin laufen.
Ein Ingress routet auf einen Service, der dann an die passenden Pods weiterleitet.

Ob Ingress-NGINX zusätzlich auf der Media-Node laufen soll, ist eine Designentscheidung:

* **okay**, wenn die Node ganz normal Teil des Ingress-Footprints sein soll
* **nicht nötig**, wenn sie wirklich nur Media hosten soll

Für den Start kann das so bleiben und später bei Bedarf eingeschränkt werden.

---

## 4. Longhorn bleibt ein gemeinsames Cluster-Storage für Konfigurationen

Longhorn soll weiterhin verwendet werden für:

* qBittorrent-Konfiguration
* Sonarr/Radarr/Prowlarr-Konfiguration
* Jellyfin-Konfiguration
* Bazarr-/Seerr-/Recyclarr-Konfiguration
* kleinere App-Daten
* ggf. Datenbanken, sofern sinnvoll

### Wichtige Abgrenzung

Longhorn soll **nicht** der primäre Speicherort für die eigentliche Medienbibliothek werden.

### Wichtiger Longhorn-Punkt

Auch wenn Pods auf der x86-Media-Node laufen, ist das **keine zweite Longhorn-Instanz**.
Es bleibt ein gemeinsames Longhorn-Cluster.

Das gewünschte Verhalten ist:

* die Media-Node darf Longhorn-PVCs **nutzen**
* die eigentlichen Replikas liegen weiter auf den bisherigen Storage-Workern
* die x86-Node wird **nicht** als allgemeiner Replica-Host verwendet

Das bedeutet praktisch:

* Config-PVCs können auf der Media-Node gemountet werden
* deren Daten liegen physisch weiter auf den Pi-Workern
* Reads/Writes auf diese kleinen PVCs gehen dann über das Cluster-Netzwerk

Für kleine Konfigurationsdaten ist das völlig in Ordnung.

---

## 5. Große Mediendaten liegen lokal auf der x86-Node

Die eigentlichen Medien sollen auf einem lokalen Datenträger der x86-Node liegen, z. B.:

* HDD/SSD/NVMe
* gemountet direkt im Host-OS
* in Kubernetes als lokales Persistent Volume bereitgestellt

### Beispiele für Verzeichnisse

```text
/data/downloads
/data/media
/data/transcode
```

### Empfohlene interne Struktur

```text
/data/
├── torrents/
│   ├── incomplete/
│   └── complete/
├── media/
│   ├── movies/
│   ├── shows/
│   └── music/
└── transcode/
```

### Wichtiger Punkt

qBittorrent, die *arr-Apps und Jellyfin sollten denselben Datenträger bzw. dieselbe Dateisystemsicht verwenden.

So funktionieren:

* Hardlinks
* atomare Verschiebungen
* effiziente Imports ohne Copy+Delete

---

## 6. Kein allgemeines `longhorn=storage` auf der x86-Node setzen

Die bestehenden Pi-Worker tragen:

```yaml
longhorn=storage
```

Die neue x86-Media-Node soll dieses Label **zunächst nicht** bekommen.

### Grund

Sonst könnte Longhorn anfangen, Replikas oder Volumes auch dort zu platzieren, obwohl die Node primär für Media-Workloads gedacht ist.

---

## 7. Empfohlener Media-Stack

Für den ersten sinnvollen Ausbau wird folgender Stack empfohlen:

### Kern-Stack

* **qBittorrent** als Download-Client
* **Sonarr** für Serien
* **Radarr** für Filme
* **Prowlarr** für zentrale Indexer-Verwaltung
* **Jellyfin** als Media-Server

### Sinnvolle Erweiterungen

* **Bazarr** für Untertitel
* **Seerr** als Request-Frontend
* **Recyclarr** für automatisierte Syncs von Qualitätsprofilen und ähnlichen Regeln
* optional später **Lidarr** und **Readarr**, falls Musik oder Bücher relevant werden

### Empfehlung zum Start

Für den ersten Schritt ist sinnvoll:

* qBittorrent
* Sonarr
* Radarr
* Prowlarr
* Jellyfin

Bazarr und Seerr können später gut ergänzt werden.

---

## 8. Netzwerk- und Privacy-Strategie für den Stack

### Grundsatz

Nur der eigentliche Torrent-Client soll hinter einem VPN laufen.
Die übrigen Dienste sollen normal im Cluster kommunizieren.

### Zielbild

* **qBittorrent** läuft mit eingebautem VPN-Client
* **Sonarr/Radarr/Prowlarr/Bazarr/Jellyfin** laufen **nicht** hinter diesem VPN
* alle Dienste kommunizieren intern im Cluster
* externe Admin-Zugriffe werden nicht über öffentlich erreichbare Endpunkte gelöst

### Begründung

Das VPN wird dort eingesetzt, wo BitTorrent-Traffic sichtbar wäre.
Die übrigen Dienste erzeugen dieses Problem nicht in derselben Form und werden durch ein VPN eher unnötig komplizierter.

### qBittorrent-spezifisch

Empfohlen ist:

* das bestehende **Hotio-qBittorrent-Image** kann beibehalten werden
* qBittorrent sollte intern zusätzlich auf das **VPN-Interface gebunden** werden
* dauerhaftes öffentliches oder allgemeines internes Exposing des qBittorrent-WebUIs ist **nicht nötig**

### Zugriff auf qBittorrent-WebUI

Für qBittorrent ist folgende Betriebsweise sinnvoll:

* **kein regulärer Ingress**
* nur **ClusterIP-Service**
* temporärer Zugriff bei Bedarf per `kubectl port-forward`

Damit bleibt qBittorrent im Normalbetrieb intern und nur für andere Dienste erreichbar.

---

## 9. Namespace- und Repo-Struktur des Media-Stacks

Der Media-Stack soll als **gemeinsamer interner Stack** aufgebaut werden und **nicht** in viele voneinander getrennte Namespaces zerfallen.

### Empfohlener Namespace

```text
svc-media
```

### Begründung

Die Dienste sind fachlich eng gekoppelt und kommunizieren regelmäßig miteinander.
Ein gemeinsamer Namespace vereinfacht:

* Service-Namen
* interne Erreichbarkeit
* gemeinsames Troubleshooting
* Kustomize-Struktur
* spätere NetworkPolicies

### Empfohlene Repo-Struktur

```text
apps/
└── internal/
    ├── ...
    └── media/
        ├── kustomization.yaml
        ├── namespace.yaml
        ├── qbittorrent/
        ├── sonarr/
        ├── radarr/
        ├── prowlarr/
        ├── jellyfin/
        ├── bazarr/
        └── seerr/
```

### Ziel

Der gesamte Media-Stack hängt logisch unter:

```text
apps/internal/media
```

und wird über eine gemeinsame `kustomization.yaml` zusammengebaut.

---

## Umsetzungsschritte

## Schritt 1: x86-Node vorbereiten

Auf der neuen Hardware:

* Linux installieren
* statische IP oder DHCP-Reservierung einrichten
* Hostname setzen
* Zeitsynchronisation aktiv
* Zugriff ins Cluster-Netz sicherstellen
* K3s-Voraussetzungen erfüllen

Beispiel-Hostname:

```text
media-1
```

---

## Schritt 2: Node dem Cluster als Worker hinzufügen

Auf einem bestehenden Server das Join-Token lesen:

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

Auf der neuen x86-Node dann K3s-Agent installieren und joinen:

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://<CONTROL-PLANE-VIP>:6443 K3S_TOKEN=<TOKEN> sh -
```

Danach prüfen:

```bash
kubectl get nodes -o wide
```

Erwartung:

* neue Node erscheint als `Ready`
* Architektur ist `amd64`

Prüfen:

```bash
kubectl get nodes --show-labels | grep media-1
```

---

## Schritt 3: Media-Node labeln und tainten

### Label setzen

```bash
kubectl label node media-1 dedicated=media
```

### Taint setzen

```bash
kubectl taint node media-1 dedicated=media:NoSchedule
```

### Kontrolle

```bash
kubectl get nodes --show-labels
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

---

## Schritt 4: Prüfen, welche DaemonSets auf der neuen Node landen

Nach dem Join prüfen:

```bash
kubectl get pods -A -o wide | grep media-1
```

Erwartbar sind u. a.:

* Flannel
* MetalLB Speaker
* ggf. Ingress-Controller-DaemonSets

Das ist erstmal normal.

---

## Schritt 5: Lokalen Medienspeicher auf der x86-Node einrichten

Auf dem Host-OS:

* Datenträger partitionieren
* Dateisystem anlegen
* Mountpoint erzeugen
* persistent in `/etc/fstab` eintragen

Fuer den inzwischen konkreten Umbau von `media-1` mit:

* NVMe weiter fuer Hot-Daten
* 3x HDD als ZFS-RAIDZ1 fuer kalte Mediendaten
* einem zweiten lokalen PVC fuer kalte Daten
* kaltem `/data` im Pod plus gezielten heißen Unter-Mounts fuer `incomplete` und `transcode`

siehe die detaillierte Schritt-fuer-Schritt-Anleitung in [`media-storage-zfs.md`](./media-storage-zfs.md).

Beispiel:

```bash
sudo mkfs.ext4 /dev/nvme0n1p1
sudo mkdir -p /data
sudo mount /dev/nvme0n1p1 /data
```

Unterverzeichnisse anlegen:

```bash
sudo mkdir -p /data/torrents/incomplete
sudo mkdir -p /data/torrents/complete
sudo mkdir -p /data/media/movies
sudo mkdir -p /data/media/shows
sudo mkdir -p /data/media/music
sudo mkdir -p /data/transcode
```

Berechtigungen passend setzen.

---

## Schritt 6: Lokales Persistent Volume für Mediendaten bereitstellen

Für große Mediendaten ist ein **Local Persistent Volume** sinnvoller als ein einfaches `hostPath`.

### Beispiel StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: media-local
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
```

### Beispiel PersistentVolume

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: media-local-pv-1
spec:
  capacity:
    storage: 4Ti
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: media-local
  local:
    path: /data
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - media-1
```

### Beispiel PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: media-local-pvc
  namespace: svc-media
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: media-local
  resources:
    requests:
      storage: 4Ti
```

### Hinweis

In der Praxis ist es oft sinnvoll, nicht nur ein einziges großes PVC zu verwenden, sondern die lokale Datensicht logisch zu trennen, z. B. für:

* Downloads
* Medienbibliothek
* Transcode

Die Verzeichnisse können dabei trotzdem auf demselben lokalen Datenträger liegen.

### Wichtiger Scheduler-Hinweis

Wenn die Media-Node **kein** Longhorn-Disk-Node ist, aber Media-Pods hart auf diese Node gepinnt werden, dann können Longhorn-Konfigurations-PVCs mit `WaitForFirstConsumer` in einen Scheduling-Deadlock laufen:

* der Pod kann nur auf die Media-Node
* der PVC wartet auf ein geplantes Pod
* der Scheduler prüft die Longhorn-Kapazität auf genau dieser Node
* hat die Media-Node dort `0` Kapazität, bleibt das Pod mit `did not have enough free storage` hängen

Für solche Config-PVCs ist daher eine **Longhorn-StorageClass mit `Immediate` Binding** sinnvoll.

---

## Schritt 7: Longhorn für Konfigurationsdaten weiterverwenden

Für kleine und wichtige Persistenzdaten bleibt Longhorn aktiv.

Beispiele:

* `qbittorrent-config`
* `sonarr-config`
* `radarr-config`
* `prowlarr-config`
* `jellyfin-config`
* `bazarr-config`
* `seerr-config`

Diese PVCs nutzen weiterhin eine Longhorn-StorageClass.

Für Media-Workloads, die ausschließlich auf einer dedizierten Media-Node laufen, sollte diese StorageClass für die kleinen Config-PVCs **`Immediate`** verwenden, damit die Volumes bereits vor dem Pod-Scheduling auf den regulären Longhorn-Storage-Nodes provisioniert werden können.

---

## Schritt 8: Media-Workloads gezielt auf die x86-Node pinnen

Alle Media-nahen Apps sollen auf die neue Node gelegt werden:

* qBittorrent
* Sonarr
* Radarr
* Prowlarr
* Jellyfin
* optional Bazarr, Seerr, Recyclarr usw.

### Empfohlenes Scheduling

```yaml
nodeSelector:
  dedicated: media
  kubernetes.io/arch: amd64

tolerations:
  - key: dedicated
    operator: Equal
    value: media
    effect: NoSchedule
```

Optional zusätzlich `affinity`, falls später feiner gesteuert werden soll.

---

## Schritt 9: PVCs pro Anwendung sinnvoll trennen

### qBittorrent

* **Config** auf Longhorn
* **Downloads** lokal auf `media-local`

### Sonarr / Radarr / Prowlarr

* **Config** auf Longhorn
* Zugriff auf denselben lokalen Medienspeicher wie qBittorrent

### Jellyfin

* **Config** auf Longhorn
* **Library** lokal auf `media-local`
* **Transcode-Ordner** ebenfalls lokal auf x86

### Bazarr / Seerr / Recyclarr

* **Config** auf Longhorn
* nur dort lokale Daten mounten, wo es fachlich nötig ist

---

## Schritt 10: Service-Exposition sinnvoll begrenzen

### qBittorrent

Empfohlenes Zielbild:

* **kein Ingress**
* **Service vom Typ ClusterIP**
* Zugriff anderer Media-Dienste intern über den Service
* Admin-Zugriff nur temporär per `kubectl port-forward`

### Sonarr / Radarr / Prowlarr / Bazarr / Jellyfin / Seerr

Hier ist interner Ingress sinnvoll, wenn die UIs regulär genutzt werden sollen.

### Wichtiger Punkt

Ein `ClusterIP`-Service ohne Ingress ist **cluster-intern**, aber nicht automatisch auf ein Namespace beschränkt.
Falls später stärker eingeschränkt werden soll, können ergänzend **NetworkPolicies** genutzt werden.

---

## Schritt 11: Beispiel für die interne Erreichbarkeit der Dienste

Bei einem gemeinsamen Namespace `svc-media` können sich die Dienste einfach über kurze Service-Namen erreichen, z. B.:

```text
http://qbittorrent:8080
http://sonarr:8989
http://radarr:7878
http://prowlarr:9696
```

Dadurch wird der Stack intern sehr einfach konfigurierbar.

---

## Schritt 12: Beispiel: Deployment-Schema für einen Media-Workload

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jellyfin
  namespace: svc-media
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jellyfin
  template:
    metadata:
      labels:
        app: jellyfin
    spec:
      nodeSelector:
        dedicated: media
        kubernetes.io/arch: amd64
      tolerations:
        - key: dedicated
          operator: Equal
          value: media
          effect: NoSchedule
      containers:
        - name: jellyfin
          image: jellyfin/jellyfin:latest
          volumeMounts:
            - name: config
              mountPath: /config
            - name: media
              mountPath: /data/media
            - name: transcode
              mountPath: /data/transcode
      volumes:
        - name: config
          persistentVolumeClaim:
            claimName: jellyfin-config
        - name: media
          persistentVolumeClaim:
            claimName: media-local-pvc
        - name: transcode
          persistentVolumeClaim:
            claimName: media-local-pvc
```

Hinweis: In der Praxis sollten `media` und `transcode` meist unterschiedliche Unterpfade oder getrennte PVCs/PV-Mounts nutzen.

---

## Schritt 13: qBittorrent-Migrationsziel festlegen

Aktuell läuft qBittorrent bereits mit einem Longhorn-PVC.

### Zielbild

* qBittorrent selbst läuft künftig auf der x86-Node
* Config bleibt auf Longhorn
* Download-Daten liegen lokal auf `/data/torrents`
* Sonarr/Radarr importieren von dort in `/data/media`

### Konsequenz

Die bestehende Longhorn-Nutzung für große Downloads sollte perspektivisch abgelöst werden.

### Hotio-/VPN-Zielbild

Das bestehende Hotio-Image kann grundsätzlich weiterverwendet werden.

Empfohlenes Zielbild:

* Hotio qBittorrent mit WireGuard-VPN
* qBittorrent bindet zusätzlich intern auf das VPN-Interface
* kein regulärer qBittorrent-Ingress
* Zugriff bei Bedarf nur temporär per Port-Forward

---

## Schritt 14: Longhorn-Nutzung bewusst begrenzen

### Wichtig

Die x86-Media-Node soll **zunächst kein allgemeiner Longhorn-Storage-Node** sein.

Deshalb:

* **kein** `longhorn=storage` auf dieser Node setzen
* keine Replikaplatzierung auf dieser Node erzwingen
* keine generischen Cluster-Volumes auf dieser Node hosten

Falls später gewünscht, kann das bewusst erweitert werden.
Für den ersten Ausbau ist die klare Trennung sauberer.

---

## Empfohlene Verzeichnisstrategie für Media-Apps

Alle relevanten Apps sollten dieselbe Datensicht bekommen.

### Beispiel-Mounts im Container

```text
/data/torrents
/data/media
/data/transcode
```

### Ziel

* qBittorrent schreibt nach `/data/torrents`
* Sonarr/Radarr lesen von `/data/torrents`
* Sonarr/Radarr verschieben oder hardlinken nach `/data/media`
* Jellyfin liest aus `/data/media`
* Bazarr greift auf dieselbe Library-Sicht zu

---

## Backup-Strategie

### Longhorn-Daten

Weiterhin wie bisher über Longhorn absichern.

### Lokale Mediendaten

Da die Medien lokal auf der x86-Node liegen, braucht es eine separate Backup- oder Replikationsstrategie, z. B.:

* rsync auf NAS
* Snapshots auf Host-Ebene
* periodische Sicherung auf externen Speicher

### Wichtige Anmerkung

Die Media-Library ist absichtlich **nicht hochverfügbar** wie ein repliziertes Longhorn-Volume.
Das ist eine bewusste Designentscheidung zugunsten von I/O, Einfachheit und Kapazität.

### Realistische Einordnung

Für ein Homelab ist das ein sinnvoller Tradeoff.
Der Fokus liegt auf brauchbarer Datensicherung gegen wahrscheinliche Ausfallszenarien wie SSD-Ausfall, nicht auf vollständiger Ende-zu-Ende-Hochverfügbarkeit des gesamten Hauses.

---

## Offene Folgearbeiten

* Entscheidung, ob Ingress-DaemonSets auch auf der Media-Node laufen sollen
* Auswahl einer GPU und Einbindung ins Cluster
* Auswahl geeigneter Container-Images für Jellyfin und die übrigen Media-Dienste
* Anlegen des Namespace `svc-media`
* Aufbau der Repo-Struktur unter `apps/internal/media`
* Migration von qBittorrent aus `svc-qbittorrent` in den Media-Stack
* Entscheidung, ob Bazarr und Seerr direkt mit umgesetzt werden
* optionale NetworkPolicies für den Media-Stack
* separate Monitoring-Regeln für Temperatur, Disk und GPU

---

## Konkrete Befehle

### Node prüfen

```bash
kubectl get nodes -o wide
kubectl get nodes --show-labels
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

### Neue Node labeln/tainten

```bash
kubectl label node media-1 dedicated=media
kubectl taint node media-1 dedicated=media:NoSchedule
```

### Pods auf der neuen Node prüfen

```bash
kubectl get pods -A -o wide | grep media-1
```

### Temporärer Zugriff auf qBittorrent ohne Ingress

```bash
kubectl -n svc-media port-forward service/qbittorrent 8080:80
```

---

## Zusammenfassung

Die empfohlene Architektur ist:

* x86-Node als dedizierte Media-Worker-Node
* Netzwerk-DaemonSets laufen weiterhin auf der Node
* große Mediendaten lokal auf der x86-Node
* kleine Konfigurationsdaten weiter auf Longhorn
* Longhorn bleibt ein gemeinsames Cluster-Storage, aber ohne Storage-Rolle für die x86-Node
* Media-Workloads werden gezielt per Label/Taint auf die Node gescheduled
* qBittorrent läuft mit VPN und ohne regulären Ingress
* Sonarr, Radarr, Prowlarr und Jellyfin laufen im selben Stack und Namespace
* der Stack wird sauber unter `apps/internal/media` organisiert

Damit bleibt das Cluster sauber getrennt:

* Pis = verteilte Clusterbasis + Longhorn-Storage
* x86 = Media-Compute + lokaler Bulk-Storage

Wenn du willst, mach ich dir daraus im nächsten Schritt direkt noch die **passende Repo-Struktur als konkreten Tree plus `kustomization.yaml`-Skeleton für `apps/internal/media`**.
