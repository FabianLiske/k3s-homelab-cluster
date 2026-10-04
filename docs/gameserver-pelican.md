# Wings-Node einrichten (Pelican)

Anleitung fuer die Einrichtung einer neuen Pelican/Wings-Node.
Referenz ist der aktuelle Ist-Zustand: die Wings-Node ist `wk-4`.

## Zielbild

Pelican laeuft als normale interne App im Cluster (Namespace `svc-games`).
Wings und die eigentlichen Gameserver laufen hostseitig auf der Wings-Node
als Docker-Container, nicht als Kubernetes-Workloads.

Die Netztrennung ist dabei:

* Panel-Webzugriff: ueber `nginx-internal` auf VLAN20
  (`pelican.intern.rohrbom.be` → `172.26.20.151`)
* Host-Management: ueber VLAN100 (Management-IP der Node)
* Wings (API + SFTP): ueber VLAN100, Name `wings.cluster.rohrbom.be`
* Game-Traffic: ueber `vlan50` mit der Game-IP `172.26.50.<Endung>`

## Referenz: aktueller Stand (wk-4)

| | |
|---|---|
| Node | `wk-4` (x86_64, Ubuntu 24.04 LTS) |
| Parent-Interface | `ens3` |
| Management-IP | `172.26.100.24` (VLAN100, DHCP) |
| Game-Interface | `vlan50` |
| Game-IP | `172.26.50.24/24` |
| Game-Gateway | `172.26.50.1` |
| Wings-FQDN | `wings.cluster.rohrbom.be` → `172.26.100.24` |
| Wings-Port | `8080` (TLS, Let's Encrypt via DNS-01) |
| Wings-SFTP-Port | `2022` |
| Wings-Version | `v1.0.0-beta27` |
| Panel | `ghcr.io/pelican-dev/panel:latest` in `svc-games` |
| Storage | NFS von `172.26.60.223` (NAS, `/mnt/fast/…`) |

Merksaetze:

* Game-IP = `172.26.50.<gleiche Endstelle wie die Management-IP der Node>`.
* `wings.cluster.rohrbom.be` ist ein Cluster-weiter Name, der auf die
  aktive Wings-Node zeigt. Beim Node-Tausch wird nur der A-Record neu
  gepunktet; das DNS-01-Zertifikat bleibt gueltig.
* Es werden **kein** dediziertes Label und **kein** Taint auf der Node
  gesetzt. Gameserver laufen hostseitig und unterliegen nicht der
  Kubernetes-Scheduling. Die aktuelle Wings-Node `wk-4` traegt nur das
  Label `node.rohrbom.be/heavy-compute=true` fuer regulaere
  k8s-Workloads (u. a. Jellyfin), das mit Wings nichts zu tun hat.

## Voraussetzungen

* Node laeuft mit Ubuntu Server 24.04 LTS und ist als k3s-Agent
  gejoint (siehe [`setup.md`](./setup.md)).
* Die Standard-Netplan-Dateien sind vorhanden:
  `50-cloud-init.yaml` (Management-Interface, DHCP) und `90-net.yaml`
  (vlan10/20/30).
* Sysctls aus `setup.md`: `ip_forward=1`, `rp_filter=2`.
* `faba` mit Passwortlos-Sudo (`/etc/sudoers.d/90-cloud-init-users`).
* Das NAS (`172.26.60.223`) exportiert zwei Shares an die neue Node.
* Das Pelican-Panel laeuft bereits im Cluster (Standardfall).
  Fuer einen komplett neuen Cluster siehe [Anhang](#anhang-panel-auf-fremdem-cluster-deployen).

## Harte Reihenfolge

1. Node-Istzustand pruefen (Phase 1).
2. NAS-Shares anlegen und NFS-Mounts einrichten (Phase 2).
3. `vlan50` mit der Game-IP und Source-Based Routing einrichten (Phase 3).
4. Pelican-/Wings-Pakete und Docker installieren (Phase 4).
5. Wings-Binary und Systemd-Unit vorbereiten, aber noch nicht starten (Phase 5).
6. Host-Firewall bewusst **nicht** global dichtmachen (Phase 6).
7. DNS und Let's-Encrypt-Zertifikat fuer den Wings-FQDN (Phase 7).
8. Node in Pelican anlegen, Config holen, Wings starten (Phase 8).
9. Allokationen und einen Testserver pruefen (Phase 9).
10. Erst ganz am Ende Router-Portforwards fuer Spielports oeffnen (Phase 10).

---

## Phase 1: Node verifizieren

Alle Befehle laufen direkt auf der Node.

```bash
hostnamectl
lsb_release -ds
uname -m
ip -br addr
ip route
sysctl net.ipv4.ip_forward net.ipv4.conf.all.rp_filter net.ipv4.conf.default.rp_filter
```

Erwartung:

* Architektur ist `x86_64` (das Wings-Binary ist amd64).
* Das Parent-Interface (z. B. `ens3` oder `eth0`) ist UP.
* `vlan10`, `vlan20` und `vlan30` existieren bereits.
* Die Default-Route laeuft ueber das Management-/Node-Netz (VLAN100).
* `ip_forward = 1`, `rp_filter = 2`.

Notieren:

* Parent-Interface-Name (fuer die Netplan-Datei in Phase 3)
* Management-IP (bestimmt die Game-IP und den DNS-Eintrag)

Bestehende Netplan-Datei sichern:

```bash
ls -1 /etc/netplan
sudo cp /etc/netplan/90-net.yaml "/etc/netplan/90-net.yaml.bak.$(date +%F-%H%M%S)"
```

---

## Phase 2: Storage als NFS-Mount vom NAS

Wings legt Server-Dateien, Backups und Archives unter `/var/lib/pelican`
an. Das liegt im aktuellen Setup nicht lokal auf der Node, sondern als
zwei NFS-Mounts auf dem NAS:

| Mountpoint | Export |
|---|---|
| `/var/lib/pelican` | `172.26.60.223:/mnt/fast/data/pelican` |
| `/var/lib/pelican/backups` | `172.26.60.223:/mnt/fast/data/backups/pelican` |

### 1. NAS-Seite

Auf dem NAS (TrueNAS) beide Shares anlegen und an die Management-IP der
neuen Node exportieren. Die Unterordner (`volumes/`, `archives/`, …)
legt Wings beim ersten Start selbst an.

### 2. fstab-Eintraege

```bash
sudo tee -a /etc/fstab >>/dev/null <<'EOF'
172.26.60.223:/mnt/fast/data/pelican /var/lib/pelican nfs rw,nfsvers=4.2,hard,timeo=600,retrans=2,_netdev,noatime,x-systemd.automount,x-systemd.mount-timeout=60s 0 0
172.26.60.223:/mnt/fast/data/backups/pelican /var/lib/pelican/backups nfs rw,nfsvers=4.2,hard,timeo=600,retrans=2,_netdev,noatime,x-systemd.automount,x-systemd.mount-timeout=60s 0 0
EOF
```

Wichtig: `tee -a` (appenden), **nicht** `tee` — das wuerde die
bestehenden Mount-Eintraege aus `fstab` ueberschreiben.

Wichtig:

* `_netdev` + `x-systemd.automount`: Mount wird erst waehrend des
  Bootprozesses ausgefuehrt, wenn das Netz da ist (wichtig, weil der
  Wings-Service auf den Mount wartet, siehe Phase 5).
* `hard,timeo=600,retrans=2`: gleiche Optionen wie die anderen NFS-Mounts
  im Cluster (z. B. `media-data`).

### 3. Mounten und pruefen

```bash
sudo systemctl daemon-reload
sudo mount -a
findmnt -T /var/lib/pelican
findmnt -T /var/lib/pelican/backups
df -h /var/lib/pelican
```

Erwartung: beide Mountpoints zeigen auf `172.26.60.223` (nfs4).

---

## Phase 3: `vlan50` mit der Game-IP einrichten

Die Game-IP ergibt sich aus der Management-IP: gleiche Endstelle.
Fuer `wk-4` (`172.26.100.24`) also `172.26.50.24/24`.

Die vlan50-Konfiguration liegt als **eigene Datei** `/etc/netplan/90-vlan50.yaml`
neben der Standard-Datei. Netplan merget mehrere Dateien; `90-net.yaml`
bleibt unangetastet.

### 1. `90-vlan50.yaml` anlegen

```bash
sudo tee /etc/netplan/90-vlan50.yaml >/dev/null <<'EOF'
network:
  version: 2
  renderer: networkd

  vlans:
    vlan50:
      id: 50
      link: ens3
      addresses:
        - 172.26.50.24/24
      dhcp4: false
      dhcp6: false
      routes:
        - to: 172.26.50.0/24
          scope: link
          table: 50
        - to: 0.0.0.0/0
          via: 172.26.50.1
          table: 50
      routing-policy:
        - from: 172.26.50.24/32
          table: 50
          priority: 100
EOF
```

Anpassen: `link` auf das Parent-Interface der Node, `addresses` und
`from` auf die Game-IP.

Wichtig:

* Keine normale zweite Default-Route im `main`-Table bauen.
* Die Default-Route fuer das Game-Netz existiert nur in Routing-Tabelle `50`.
* Die Policy-Routing-Regel (Priority 100) stellt sicher, dass
  Antwort-Traffic von der Game-IP auch wirklich ueber `vlan50` rausgeht.

### 2. Netplan anwenden

```bash
sudo chmod 600 /etc/netplan/90-vlan50.yaml
sudo netplan generate
sudo netplan try
sudo netplan apply
```

### 3. Routing pruefen

```bash
ip -br addr show dev vlan50
ip rule show | grep '172.26.50.24/32'
ip route show table 50
ip route get 1.1.1.1 from 172.26.50.24
ping -c 3 172.26.50.1
```

Die wichtigste Ausgabe ist:

```bash
ip route get 1.1.1.1 from 172.26.50.24
```

Erwartung:

* die Route geht ueber `dev vlan50`
* Source ist `172.26.50.24`

Wenn das nicht stimmt, **nicht** mit Pelican weitermachen.

---

## Phase 4: Pakete und Docker

```bash
sudo apt update
sudo apt install -y certbot curl jq ufw unzip
dpkg -l certbot jq ufw unzip | grep '^ii'
```

Docker (Pelican Wings nutzt Docker direkt auf dem Host):

```bash
curl -fsSL https://get.docker.com/ | CHANNEL=stable sudo sh
sudo systemctl enable --now docker
sudo docker info >/dev/null && echo "Docker OK"
sudo docker run --rm hello-world
```

---

## Phase 5: Wings installieren, aber noch nicht starten

### 1. Binary

```bash
sudo curl -L -o /usr/local/bin/wings \
  https://github.com/pelican-dev/wings/releases/latest/download/wings_linux_amd64
sudo chmod 0755 /usr/local/bin/wings
wings version
```

Aktuell im Einsatz: `v1.0.0-beta27`.

### 2. Systemd-Unit

Die Unit prueft ueber `ExecStartPre`, dass die NFS-Mounts aus Phase 2
aktiv sind, und wird erst gestartet, wenn Docker und die Mounts bereit
sind:

```bash
sudo tee /etc/systemd/system/wings.service >/dev/null <<'EOF'
[Unit]
Description=Pelican Wings Daemon
Wants=network-online.target
After=network-online.target remote-fs.target docker.service
Requires=docker.service
RequiresMountsFor=/var/lib/pelican /var/lib/pelican/backups
PartOf=docker.service

[Service]
User=root
WorkingDirectory=/etc/pelican
LimitNOFILE=4096
PIDFile=/var/run/wings/daemon.pid
ExecStartPre=/usr/bin/mountpoint -q /var/lib/pelican
ExecStartPre=/usr/bin/mountpoint -q /var/lib/pelican/backups
ExecStart=/usr/local/bin/wings
Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=180
StartLimitBurst=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
```

Zusaetzlich das PID-Verzeichnis aus der Unit anlegen:

```bash
sudo mkdir -p /var/run/wings
```

`/etc/pelican` (Config, SFTP-`passwd`/`group`, Machine-ID) und
`/var/log/pelican` legt Wings beim ersten Start selbst an; die
Server-Verzeichnisse (`volumes/`, `archives/`, …) entstehen auf dem
NFS-Mount aus Phase 2.

### 3. Noch nicht starten

An dieser Stelle **nicht**:

```bash
sudo systemctl enable --now wings
```

Wings startet erst, wenn Pelican die Node-Konfiguration erzeugt hat
(Phase 8).

---

## Phase 6: Firewall

* Auf der Wings-Node **keine** globale UFW-Deny-Policy aktivieren.
  Die Node ist k3s-Agent und transportiert neben SSH/Wings auch
  k3s-, kube-proxy-, CNI- und Ingress-Traffic.
* Sicherheit traegen stattdessen: internes DNS, VLAN-Trennung und der
  Router (WAN-Forwards nur fuer einzelne Spielports).

```bash
sudo ufw disable
sudo systemctl disable ufw --now || true
sudo ufw status
```

Erwartung: `Status: inactive`.

---

## Phase 7: DNS und TLS fuer Wings

Das Panel laeuft ueber HTTPS, daher bekommt Wings ebenfalls einen
TLS-faehigen Namen. Das Setup hat keine interne CA und DNS liegt in
Cloudflare, daher: DNS-01 via Cloudflare.

### 1. DNS-Eintrag

* `wings.cluster.rohrbom.be` → Management-IP der Node
* Cloudflare-Eintrag auf **DNS only**, nicht proxied.

Der Name ist cluster-weit und zeigt auf die aktive Wings-Node.
Laufen spaeter zwei Wings-Nodes parallel, Namen pro Node ableiten
(z. B. `wings-wk-4.cluster.rohrbom.be`) und in Phase 8 den passenden
Namen verwenden.

### 2. Certbot mit Cloudflare-Plugin

```bash
sudo apt update
sudo apt install -y python3-certbot-dns-cloudflare
```

In Cloudflare einen API-Token mit DNS-Edit-Recht fuer die Zone
`cluster.rohrbom.be` anlegen, dann auf der Node:

```bash
sudo install -d -m 700 /root/.secrets/certbot
sudo nano /root/.secrets/certbot/cloudflare.ini
sudo chmod 600 /root/.secrets/certbot/cloudflare.ini
```

Inhalt:

```ini
dns_cloudflare_api_token = <CLOUDFLARE_API_TOKEN>
```

### 3. Zertifikat holen

```bash
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.secrets/certbot/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 60 \
  -d wings.cluster.rohrbom.be
```

Pruefen:

```bash
sudo ls -l /etc/letsencrypt/live/wings.cluster.rohrbom.be/
sudo certbot certificates
```

---

## Phase 8: Node in Pelican anlegen und Wings starten

### 1. Node im Panel anlegen

Im Pelican-Adminbereich (`https://pelican.intern.rohrbom.be`):

1. **Admin → Nodes → Create New Node**
2. Name: Node-Name (z. B. `wk-4`)
3. Host/FQDN: `wings.cluster.rohrbom.be`
4. Scheme: `https`
5. Daemon Port: `8080`
6. SFTP Port: `2022`

### 2. Config auf die Node bringen

Im Panel: Node oeffnen → Tab `Configuration` → Config kopieren oder den
`Auto Deploy Command` ausfuehren. Der Command legt `/etc/pelican/config.yml`
(Token, UUID, Machine-ID) direkt an.

Alternativ die Config manuell nach `/etc/pelican/config.yml` eintragen
(`sudo nano /etc/pelican/config.yml`, Rechte `600`).

In der erzeugten Config pruefen:

* `api.ssl.enabled: true`, `api.port: 8080`
* `api.ssl.cert`/`key` zeigen auf
  `/etc/letsencrypt/live/wings.cluster.rohrbom.be/{fullchain,privkey}.pem`
* `remote: https://pelican.intern.rohrbom.be`
* `system.root_directory: /var/lib/pelican` (NFS-Mount aus Phase 2)
* `sftp.bind_port: 2022`
* `docker.network.name: pelican_nw` — diese Docker-Netz (Bridge
  `172.18.0.0/16` inkl. IPv6) legt Wings beim Start selbst an.

### 3. Erst lokal testen, dann Service starten

```bash
sudo wings --debug
```

Wenn das sauber startet: `CTRL+C`, dann:

```bash
sudo systemctl enable --now wings
sudo systemctl status wings --no-pager
sudo journalctl -u wings -n 100 --no-pager
```

Im Panel sollte die Node danach als verbunden (gruen) erscheinen.

---

## Phase 9: Allokationen und Testserver

Allokationen gehoeren auf die **Game-IP**, nie auf die Management-IP:

* richtig: `172.26.50.24`
* falsch: `172.26.100.24`

Merksatz:

* Wings/Node = Management-IP bzw. `wings.cluster.rohrbom.be`
* Spielports = Game-IP `172.26.50.24`

Fuer den ersten Check einen Testserver anlegen (z. B. Paper, siehe
[`minecraft-paper-pelican.md`](./minecraft-paper-pelican.md)), starten
und auf der Node pruefen:

```bash
ss -tlnp | grep 25565
```

Erwartung: der Server lauscht auf `172.26.50.24:25565`.

---

## Phase 10: Router erst ganz am Ende

Sobald intern alles funktioniert und ein Testserver sauber laeuft:

* WAN → ausgewaehlte TCP/UDP-Spielports → `172.26.50.24`
* kein WAN-Forward auf SSH
* kein WAN-Forward auf Wings
* kein WAN-Forward auf `pelican.intern.rohrbom.be`

Bei Cloudflare-SRV-Eintraegen: Cloudflare nur als DNS, kein HTTP-Proxy.

---

## Schnelle Checks

### Host

```bash
ip -br addr show dev vlan50
ip route get 1.1.1.1 from 172.26.50.24
findmnt -T /var/lib/pelican
sudo docker info >/dev/null && echo "Docker OK"
sudo systemctl status wings --no-pager
sudo ufw status
curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1:8080
```

Erwartung:

* die Route fuer die Source-Game-IP geht ueber `vlan50`
* NFS-Mount ist aktiv (Quelle `172.26.60.223`)
* Docker meldet `Docker OK`
* `wings` ist `active (running)`
* UFW steht auf `Status: inactive`
* `https://127.0.0.1:8080` meldet `401` (TLS laeuft, Auth erwartet)

### Cluster

```bash
kubectl -n svc-games get pods
kubectl -n svc-games get ingress pelican
kubectl -n svc-games logs deploy/pelican --tail=200
```

### Erfolgskriterien

* `vlan50` hat die Game-IP, Source-IP routet ueber `vlan50`
* beide NFS-Mounts sind aktiv
* Docker laeuft
* UFW ist inactive
* Pelican ist intern ueber `https://pelican.intern.rohrbom.be` erreichbar
* Wings ist intern ueber `wings.cluster.rohrbom.be:8080` (HTTPS) erreichbar
* Node im Panel ist verbunden
* Spielserver binden an die Game-IP, nicht an die Management-IP

---

## Anhang: Panel auf fremdem Cluster deployen

Nur fuer einen komplett neuen Cluster, in dem noch kein Pelican laeuft.
Im aktuellen Cluster laeuft das Panel bereits in `svc-games`.

* Manifeste: [`../apps/internal/pelican`](../apps/internal/pelican)
  (Namespace `svc-games`, Deployment, Service, Ingress
  `pelican.intern.rohrbom.be` mit `ingressClassName: nginx-internal`,
  PVC, optionales SOPS-Secret `pelican-secret.yaml`).
* Optionalen `APP_KEY` selbst vorgeben:
  `pelican-secret.yaml.example` kopieren, fuellen, mit `sops -e -i`
  verschluesseln und in der `kustomization.yaml` entkommentieren.
  Ohne Secret erzeugt Pelican den Key selbst und legt ihn im PVC ab.
* Commit + Push, Flux deployed es im Kustomization `apps`.
* Danach `https://pelican.intern.rohrbom.be/installer` durchlaufen:
  Cache `Filesystem`, Database `SQLite`, Queue `Database`,
  Session `Filesystem`, Admin-Benutzer anlegen.

---

## Referenzen

* [`setup.md`](./setup.md)
* [`minecraft-paper-pelican.md`](./minecraft-paper-pelican.md)
* [`k3s-rolling-upgrade.md`](./k3s-rolling-upgrade.md) (Vor Reboot der Wings-Node: laufende Gameserver hostseitig stoppen)
* [`../apps/internal/pelican`](../apps/internal/pelican)
* Pelican Panel Docker: https://pelican.dev/docs/panel/advanced/docker/
* Pelican Wings Install: https://pelican.dev/docs/wings/install/
