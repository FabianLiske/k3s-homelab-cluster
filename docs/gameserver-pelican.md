# Pelican als Hybrid-Gameserver-Panel

## Zielbild

Pelican laeuft als normale interne App im Cluster.
Wings und die eigentlichen Gameserver laufen hostseitig auf `media-1`.

Die Netztrennung in dieser Variante ist:

* Panel-Webzugriff: ueber `nginx-internal` auf VLAN20
* Host-Management von `media-1`: weiter ueber VLAN100
* Game-Traffic: ueber eine eigene Game-IP auf einem separaten VLAN nur auf `media-1`

Das Repo automatisiert nur den Cluster-Teil.
Alles, was direkt auf `media-1` oder im Router passieren muss, bleibt bewusst manuell.

---

## Was im Repo enthalten ist

Der Cluster-Teil liegt unter [`../apps/internal/pelican`](../apps/internal/pelican):

* eigener Namespace `svc-games`
* Pelican Deployment auf der dedizierten Media-Node
* Longhorn-PVC fuer Panel-Daten
* interner Ingress auf `https://pelican.intern.rohrbom.be`
* optionales Secret-Beispiel unter [`../apps/internal/pelican/pelican-secret.yaml.example`](../apps/internal/pelican/pelican-secret.yaml.example)

Wichtige Defaults:

* SQLite-first
* `ghcr.io/pelican-dev/panel:latest`
* `BEHIND_PROXY=true`
* `TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12`
* persistente Daten unter `/pelican-data`

---

## Harte Reihenfolge

Die wichtigste Regel fuer dieses Setup:

**Zieh Pelican nicht per Flux hoch, bevor `media-1` hostseitig fertig vorbereitet ist.**

Die empfohlene Reihenfolge ist:

1. Werte fuer `media-1`, VLANs und IPs festziehen.
2. `media-1` auf Ubuntu 24.04 vorbereiten.
3. Game-VLAN und Source-Based Routing auf `media-1` fertigstellen.
4. Docker und Wings-Binary auf `media-1` vorbereiten.
5. Host-Firewall fuer SSH, Wings und interne Verwaltung setzen.
6. Node im Cluster labeln/tainten und DNS vorbereiten.
7. Erst dann Repo pushen bzw. Flux fuer Pelican reconciliieren.
8. Dann Pelican Web-Installer ausfuehren.
9. Danach Wings mit der von Pelican erzeugten Konfiguration aktivieren.
10. Erst wenn intern alles funktioniert, Router-Portforwards fuer Spielports oeffnen.

Wenn du dich an diese Reihenfolge haeltst, vermeidest du genau das Problem, dass Pelican schon laeuft, waehrend die Media-Node netzseitig noch gar nicht sauber vorbereitet ist.

---

## Werte vor dem Start festlegen

Passe diese Shell-Variablen zuerst an deine echte Umgebung an.
Die Beispiele gehen von einem Game-VLAN 50 aus.

```bash
export MEDIA_NODE="media-1"
export PARENT_IF="enp8s0"            # auf manchen Hosts auch eth0
export GAME_VLAN_ID="50"
export GAME_IF="vlan${GAME_VLAN_ID}"
export GAME_IP="172.26.50.10"
export GAME_PREFIX="24"
export GAME_IP_CIDR="${GAME_IP}/${GAME_PREFIX}"
export GAME_GW="172.26.50.1"
export GAME_TABLE="50"
export PANEL_HOST="pelican.intern.rohrbom.be"
export PANEL_IP="172.26.20.151"
export WINGS_FQDN="wings-media-1.intern.rohrbom.be"
export WINGS_PORT="8080"
export WINGS_SFTP_PORT="2022"
export MGMT_NET="172.26.100.0/24"
export CLUSTER_NODE_NET="172.26.0.0/16"
export CLUSTER_POD_NET="10.42.0.0/16"
```

Hinweis:

* `CLUSTER_POD_NET=10.42.0.0/16` ist der K3s-Default.
* `CLUSTER_NODE_NET=172.26.0.0/16` ist hier absichtlich etwas grob, damit Wings sicher aus dem Cluster erreichbar bleibt.
* Wenn du spaeter tighter werden willst, kannst du die Netze spaeter enger schneiden.

---

## Phase 1: Admin-PC und Cluster-Preflight

Diese Schritte machst du **vor** dem eigentlichen Pelican-Deploy.

### 1. Node-Status pruefen

```bash
kubectl get node "${MEDIA_NODE}" -o wide
kubectl get node "${MEDIA_NODE}" --show-labels
```

Wenn `media-1` noch nicht sauber im Cluster ist, ziehe zuerst die allgemeinen Schritte aus [`media-node.md`](./media-node.md) nach.

### 2. Media-Node labeln und tainten

Pelican ist im Repo fest auf `dedicated=media` plus `amd64` gelegt.

```bash
kubectl label node "${MEDIA_NODE}" dedicated=media --overwrite
kubectl taint node "${MEDIA_NODE}" dedicated=media:NoSchedule --overwrite
kubectl get node "${MEDIA_NODE}" --show-labels
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

Wichtig:

* Setze **nicht** `longhorn=storage` auf `media-1`.
* Longhorn soll auf der Media-Node nur konsumiert werden, nicht dort replizieren.

### 3. DNS vorab planen

Du brauchst mindestens diese beiden Eintraege:

* `pelican.intern.rohrbom.be -> 172.26.20.151`
* `${WINGS_FQDN} -> VLAN100-IP-von-media-1`

Den ersten Eintrag brauchst du fuer das Panel.
Den zweiten brauchst du spaeter fuer Wings, weil Pelican bei einem HTTPS-Panel auch fuer Wings ein TLS-faehiges Ziel erwartet.

Noch nicht deployen.
Jetzt geht es erst an `media-1`.

---

## Phase 2: `media-1` auf Ubuntu Server 24.04 vorbereiten

Alle folgenden Schritte laufen direkt auf `media-1`.

### 1. Basis-Update und Grundpakete

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y \
  ca-certificates \
  curl \
  jq \
  unzip \
  ufw \
  open-iscsi \
  nfs-common \
  smartmontools
sudo systemctl enable --now iscsid
sudo timedatectl set-timezone Europe/Berlin
```

Kurzer Host-Check:

```bash
lsb_release -a
uname -m
ip -br addr
ip route
```

Erwartung:

* Architektur ist `x86_64`
* der Host hat bereits seine normale Management-Erreichbarkeit
* die Default-Route bleibt auf dem Management-/Node-Netz

### 2. Sysctls fuer Multi-VLAN und Routing

Das Repo arbeitet bereits mit diesen Sysctls fuer Multi-VLAN-Betrieb, siehe auch [`setup.md`](./setup.md).

```bash
sudo tee /etc/sysctl.d/100-multivlan.conf >/dev/null <<'EOF'
net.bridge.bridge-nf-call-iptables=1
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1

net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
EOF

sudo sysctl --system
sysctl net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
```

Wichtig:

* `rp_filter=2` ist hier absichtlich locker genug fuer Multi-Homing.
* Mit strengem Reverse Path Filtering machen mehrere VLANs und Source-Based Routing oft Aerger.

### 3. Parent-Interface sicher identifizieren

Bevor du Netplan anfasst, pruefe nochmal das echte Parent-Interface.

```bash
ip -br link
ip route
```

Wenn du dir unsicher bist:

```bash
printf 'PARENT_IF=%s\n' "${PARENT_IF}"
```

Typisch ist auf deiner x86-Node eher `enp8s0` als `eth0`.

### 4. Netplan-Datei finden und sichern

Finde zuerst heraus, welche Datei das Parent-Interface bereits definiert.
Lege danach ein Backup an.

```bash
ls -1 /etc/netplan
sudo grep -R "^[[:space:]]*${PARENT_IF}:$" /etc/netplan/*.yaml
```

Beispiel-Backup:

```bash
sudo cp /etc/netplan/90-net.yaml "/etc/netplan/90-net.yaml.bak.$(date +%F-%H%M%S)"
```

Wenn dein Parent-Interface in einer anderen Datei liegt, sichere **diese** Datei statt `90-net.yaml`.

### 5. Game-VLAN in Netplan eintragen

Fuege in die Netplan-Datei, die dein Parent-Interface verwaltet, das Game-VLAN ein.

Das Beispiel unten geht davon aus:

* Parent-Interface: `${PARENT_IF}`
* Game-VLAN: `${GAME_VLAN_ID}`
* Game-IP: `${GAME_IP_CIDR}`
* Router/Gateway im Game-VLAN: `${GAME_GW}`
* Policy-Routing-Tabelle: `${GAME_TABLE}`

Wichtig:

* **keine** zweite normale Default-Route im `main` Table setzen
* die Default-Route fuer das Game-VLAN kommt **nur** in die eigene Routing-Tabelle
* genau dadurch laeuft Antwort-Traffic fuer die Game-IP ueber das Game-VLAN und nicht versehentlich ueber VLAN100 zurueck

Netplan-Snippet zum Einbauen:

```yaml
network:
  version: 2
  renderer: networkd

  vlans:
    vlan50:
      id: 50
      link: enp8s0
      addresses:
        - 172.26.50.10/24
      dhcp4: false
      dhcp6: false
      routes:
        - to: 0.0.0.0/0
          via: 172.26.50.1
          table: 50
      routing-policy:
        - from: 172.26.50.10/32
          table: 50
```

Passe das Snippet an deine echten Variablen an.
Wenn in deiner Datei schon `vlans:` existiert, fuege nur den neuen VLAN-Block darunter ein.

### 6. Netplan anwenden und Routing pruefen

```bash
sudo netplan generate
sudo netplan try
sudo netplan apply
```

Danach pruefen:

```bash
ip -br addr show dev "${GAME_IF}"
ip rule show | grep "${GAME_IP}/32"
ip route show table "${GAME_TABLE}"
ip route get 1.1.1.1 from "${GAME_IP}"
ping -c 3 "${GAME_GW}"
```

Das Entscheidende ist die Ausgabe von:

```bash
ip route get 1.1.1.1 from "${GAME_IP}"
```

Erwartung:

* die Route geht ueber `dev ${GAME_IF}`
* der Traffic mit Source `${GAME_IP}` verlaesst den Host also wirklich ueber das Game-VLAN

Wenn das nicht stimmt, **nicht** mit Pelican weitermachen.

### 7. Docker CE installieren

Pelican Wings erwartet Docker auf dem Host.
Fuer Ubuntu 24.04 kannst du den offiziellen Quick-Installer verwenden.

```bash
curl -fsSL https://get.docker.com/ | CHANNEL=stable sudo sh
sudo systemctl enable --now docker
sudo docker info >/dev/null && echo "Docker OK"
sudo docker run --rm hello-world
```

### 8. Wings-Binary und Verzeichnisse vorbereiten

Wings speichert standardmaessig unter:

* Config: `/etc/pelican/config.yml`
* Root: `/var/lib/pelican`
* Volumes: `/var/lib/pelican/volumes`
* Backups: `/var/lib/pelican/backups`
* Archives: `/var/lib/pelican/archives`

Lege diese Verzeichnisse vorher sauber an:

```bash
sudo install -d -m 755 /etc/pelican /var/run/wings /var/log/pelican /var/lib/pelican
sudo install -d -m 755 /var/lib/pelican/volumes /var/lib/pelican/archives /var/lib/pelican/backups
```

Wings selbst herunterladen:

```bash
ARCH="$([ "$(uname -m)" = "x86_64" ] && echo amd64 || echo arm64)"
sudo curl -L -o /usr/local/bin/wings "https://github.com/pelican-dev/wings/releases/latest/download/wings_linux_${ARCH}"
sudo chmod 0755 /usr/local/bin/wings
wings version
```

### 9. Systemd-Unit fuer Wings anlegen, aber noch nicht starten

```bash
sudo tee /etc/systemd/system/wings.service >/dev/null <<'EOF'
[Unit]
Description=Wings Daemon
After=docker.service
Requires=docker.service
PartOf=docker.service

[Service]
User=root
WorkingDirectory=/etc/pelican
LimitNOFILE=4096
PIDFile=/var/run/wings/daemon.pid
ExecStart=/usr/local/bin/wings
Restart=on-failure
StartLimitInterval=180
StartLimitBurst=30
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl status wings --no-pager || true
```

Wichtig:

* **noch nicht** `systemctl enable --now wings`
* zuerst muss spaeter die Konfiguration aus dem Panel kommen

### 10. Host-Firewall setzen

Auf Ubuntu ist `ufw` hier die pragmatischste Basis.
Damit schuetzt du vor allem SSH und Wings.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow from "${MGMT_NET}" to any port 22 proto tcp
sudo ufw allow from "${CLUSTER_NODE_NET}" to any port "${WINGS_PORT}" proto tcp
sudo ufw allow from "${CLUSTER_POD_NET}" to any port "${WINGS_PORT}" proto tcp
sudo ufw allow from "${MGMT_NET}" to any port "${WINGS_SFTP_PORT}" proto tcp

sudo ufw enable
sudo ufw status verbose
```

Wichtige Einordnung:

* Port `22/tcp`: nur SSH aus dem Management-Netz
* Port `${WINGS_PORT}/tcp`: fuer die Kommunikation Panel -> Wings aus dem Cluster
* Port `${WINGS_SFTP_PORT}/tcp`: fuer SFTP nur intern aus dem Management-Netz
* **keine** Freigabe fuer Spielports an dieser Stelle

Noch wichtiger:

* Docker-published Ports koennen `ufw` teilweise umgehen
* die eigentliche Freigabe deiner Gameserver kontrollierst du primaer ueber Router/NAT und ueber die in Pelican angelegten Allokationen
* `ufw` ist hier vor allem fuer Host-Management und Wings sinnvoll

### 11. Host-Readiness-Check

Bevor du irgendetwas von Pelican deployest, sollten diese Checks alle gruen sein:

```bash
ip route get 1.1.1.1 from "${GAME_IP}"
sudo docker info >/dev/null && echo "Docker OK"
test -x /usr/local/bin/wings && echo "Wings binary OK"
test -d /etc/pelican && echo "/etc/pelican OK"
test -d /var/lib/pelican/volumes && echo "Pelican volumes dir OK"
sudo ufw status verbose
```

Erst wenn das passt, geht es wieder zurueck an den Cluster.

---

## Phase 3: Erst jetzt Pelican im Cluster deployen

### 1. Interne DNS-Aufloesung fuer das Panel sicherstellen

Der interne Ingress liegt heute auf `172.26.20.151`, siehe [`../infrastructure/controllers/ingress-nginx/vlan20/helmrelease.yaml`](../infrastructure/controllers/ingress-nginx/vlan20/helmrelease.yaml).

Lege vor dem Rollout mindestens diesen Eintrag an:

* `${PANEL_HOST} -> ${PANEL_IP}`

### 2. Optionales Secret vorbereiten

Das Deployment funktioniert auch **ohne** zusaetzliches Secret.

Ohne Secret passiert Folgendes:

* Pelican erzeugt beim ersten Start selbst ein `APP_KEY`
* der Schluessel wird in `/pelican-data/.env` gespeichert
* die App bleibt dadurch nach Pod-Neustarts stabil

Wenn du den Schluessel lieber von Anfang an selbst kontrollieren willst:

1. Kopiere [`../apps/internal/pelican/pelican-secret.yaml.example`](../apps/internal/pelican/pelican-secret.yaml.example) nach `apps/internal/pelican/pelican-secret.yaml`.
2. Fuelle die Werte aus.
3. Verschluessle die Datei mit SOPS:

```bash
sops --encrypt --in-place apps/internal/pelican/pelican-secret.yaml
```

4. Entferne in [`../apps/internal/pelican/kustomization.yaml`](../apps/internal/pelican/kustomization.yaml) den Kommentar vor `pelican-secret.yaml`.

### 3. Erst jetzt pushen und Flux reconciliieren

```bash
flux reconcile kustomization apps -n flux-system --with-source
kubectl -n svc-games get all
kubectl -n svc-games get pvc
kubectl -n svc-games get ingress
kubectl -n svc-games logs deploy/pelican --tail=200
```

Pruefen:

* Pod ist `Running`
* PVC ist `Bound`
* Ingress ist vorhanden
* die ersten Logs zeigen keinen offensichtlichen Startfehler

### 4. Panel-URL pruefen

```bash
curl -Ik "https://${PANEL_HOST}"
```

Danach im Browser:

* `https://${PANEL_HOST}/installer`

---

## Phase 4: Pelican Web-Installer

Sobald Pod, PVC und Ingress sauber stehen:

1. Oeffne `https://${PANEL_HOST}/installer`
2. Fuehre den Installer im Browser durch
3. Nutze fuer v1 die einfachen Defaults:

* Cache Driver: `Filesystem`
* Database Driver: `SQLite`
* Queue Driver: `Database`
* Session Driver: `Filesystem`

4. Lege den ersten Admin-Benutzer an

Warte nach dem ersten Start ruhig ein paar Minuten, wenn Pelican noch Migrations ausfuehrt.

---

## Phase 5: Wings erst nach dem Panel aktivieren

### Wichtig vorab

Da dein Panel ueber `https://` laeuft, solltest du fuer Wings ebenfalls ein TLS-faehiges Ziel verwenden.
Plane deshalb Wings mit einem internen FQDN wie `${WINGS_FQDN}` auf der VLAN100-IP von `media-1`.

### 1. Zertifikat fuer Wings vorbereiten

Wenn du keine interne PKI hast, ist ein DNS-Challenge-Zertifikat der pragmatischste Weg.

```bash
sudo apt install -y certbot
```

Danach ein Zertifikat fuer `${WINGS_FQDN}` holen, zum Beispiel per DNS-Challenge.
Der genaue Ablauf haengt von deinem DNS-Setup ab.

Ziel:

* Zertifikat liegt z. B. unter `/etc/letsencrypt/live/${WINGS_FQDN}/fullchain.pem`
* Key liegt z. B. unter `/etc/letsencrypt/live/${WINGS_FQDN}/privkey.pem`

### 2. Node in Pelican anlegen

Im Pelican-Adminbereich:

1. neue Node fuer `media-1` anlegen
2. Host/FQDN: `${WINGS_FQDN}`
3. Scheme: `https`
4. Daemon Port: `${WINGS_PORT}`
5. SFTP Port: `${WINGS_SFTP_PORT}`

Merksatz:

* Node/Wings = Management-IP bzw. Management-FQDN auf VLAN100
* Server-Allokationen = Game-IP auf dem Game-VLAN

### 3. Allokationen fuer die Game-IP anlegen

Lege in Pelican die Allokationen mit der **Game-IP von `media-1`** an.

Damit landen:

* Minecraft, Valheim, Terraria, Factorio usw. auf der Game-IP
* das Panel selbst **nicht**

### 4. Wings-Konfiguration von Pelican holen

Sobald die Node in Pelican existiert:

1. in Pelican auf die Node gehen
2. Tab `Configuration` oeffnen
3. entweder den Config-Block kopieren
4. oder den `Auto Deploy Command` verwenden

Wenn du die Config manuell uebernimmst:

```bash
sudo nano /etc/pelican/config.yml
```

Danach die von Pelican erzeugte YAML dort eintragen und speichern.

### 5. Wings erst lokal im Debug starten

Vor dem Daemonizing einmal testen:

```bash
sudo wings --debug
```

Wenn das sauber startet:

* mit `CTRL+C` wieder beenden
* dann erst als Service aktivieren

### 6. Wings als Service aktivieren

```bash
sudo systemctl enable --now wings
sudo systemctl status wings --no-pager
sudo journalctl -u wings -n 100 --no-pager
```

Jetzt sollte Pelican die Node als erreichbar sehen.

---

## Phase 6: Router und WAN-Freigaben erst ganz am Ende

### Zielbild

Nur die eigentlichen Spielports werden aus dem Internet weitergeleitet.
Management bleibt intern.

### Reihenfolge

1. zuerst intern pruefen, dass Pelican <-> Wings funktioniert
2. dann einen Testserver starten
3. erst dann WAN-Portforwards anlegen

### Empfohlene Regeln

* WAN -> ausgewaehlte TCP/UDP-Spielports -> `${GAME_IP}`
* kein WAN-Forward auf SSH
* kein WAN-Forward auf Wings
* kein WAN-Forward auf das Pelican-Webpanel

Wenn du pro Spiel DNS-Eintraege mit SRV-Records nutzen willst:

* Cloudflare nur als DNS verwenden
* kein normaler HTTP-Proxy dazwischen
* fuer echtes TCP-/UDP-Proxying waere Cloudflare Spectrum eine andere Produktklasse

---

## Verifikation

### Cluster

```bash
kubectl -n svc-games get pods
kubectl -n svc-games logs deploy/pelican --tail=200
kubectl -n svc-games get ingress pelican
```

Pruefen:

* Pod ist `Running`
* PVC ist `Bound`
* `https://${PANEL_HOST}/installer` ist intern erreichbar

### Host

```bash
ip route get 1.1.1.1 from "${GAME_IP}"
sudo systemctl status docker --no-pager
sudo systemctl status wings --no-pager
```

Pruefen:

* Source `${GAME_IP}` geht wirklich ueber `${GAME_IF}`
* Docker laeuft
* Wings laeuft

### Nach dem ersten Testserver

Pruefen:

* Pelican erreicht Wings auf der VLAN100-IP bzw. `${WINGS_FQDN}`
* ein Testserver startet erfolgreich
* der Testserver lauscht auf der Game-IP, nicht auf der Management-IP
* von aussen sind nur die explizit weitergeleiteten Spielports erreichbar

---

## Bekannte Annahmen

Dieses Setup basiert bewusst auf folgenden Entscheidungen:

* Pelican-Webpanel laeuft ueber `nginx-internal` auf VLAN20
* Host-Management von `media-1` bleibt auf VLAN100
* Game-VLAN liegt nur auf `media-1`
* v1 startet mit genau einer Game-IP
* die erste Initialisierung erfolgt manuell ueber den offiziellen Web-Installer

---

## Referenzen

* Pelican Panel Docker: https://pelican.dev/docs/panel/advanced/docker/
* Pelican Wings Install: https://pelican.dev/docs/wings/install/
* Repo-Setup fuer Multi-VLAN: [`setup.md`](./setup.md)
* Media-Node-Hintergrund: [`media-node.md`](./media-node.md)
