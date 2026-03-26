# Pelican auf `media-1`

## Zielbild

Pelican laeuft als normale interne App im Cluster.
Wings und die eigentlichen Gameserver laufen hostseitig auf `media-1`.

Die Netztrennung ist dabei:

* Panel-Webzugriff: ueber `nginx-internal` auf VLAN20
* Host-Management von `media-1`: ueber VLAN100 auf `172.26.100.31`
* Game-Traffic: ueber `vlan50` mit `172.26.50.31`

---

## Ist-Zustand

Dieser Guide geht von deinem aktuellen Stand aus:

* `media-1` laeuft mit Ubuntu Server 24.04 LTS.
* K3s ist auf `media-1` bereits als Agent installiert.
* `media-1` hat im Cluster die Node-IP `172.26.100.31`.
* `media-1` wurde bereits mit `dedicated=media` gelabelt und mit `dedicated=media:NoSchedule` getaintet.
* Das Parent-Interface ist `enp8s0`.
* Auf `media-1` sind `vlan10`, `vlan20` und `vlan30` bereits wie in [`setup.md`](./setup.md) bzw. [`../temp.md`](../temp.md) eingerichtet.
* Die Basis-Pakete aus `setup.md` sind bereits installiert.

Mit echten Werten arbeite ich im Rest dieses Guides direkt so:

* Management-IP von `media-1`: `172.26.100.31`
* Game-VLAN: `50`
* Game-Interface: `vlan50`
* Game-IP von `media-1`: `172.26.50.31/24`
* Game-Gateway: `172.26.50.1`
* Panel-FQDN: `pelican.intern.rohrbom.be`
* Panel-IP: `172.26.20.151`
* Wings-FQDN: `wings-media-1.intern.rohrbom.be`
* Wings-Port: `8080`
* Wings-SFTP-Port: `2022`

Wichtige Annahme:

* Ich gehe hier bewusst von `172.26.50.31/24` auf `vlan50` aus, passend zur Node-Endung `.31`.

---

## Harte Reihenfolge

Bitte genau in dieser Reihenfolge arbeiten:

1. `media-1`-Istzustand pruefen.
2. `vlan50` mit `172.26.50.31/24` auf `media-1` einrichten.
3. Source-Based Routing fuer `172.26.50.31` fertigstellen und testen.
4. Nur die zusaetzlichen Pelican-/Wings-Abhaengigkeiten installieren.
5. Docker installieren und testen.
6. Wings-Binary und Verzeichnisse vorbereiten, aber Wings noch nicht starten.
7. Host-Firewall fuer `media-1` bewusst **nicht** global dichtmachen.
8. DNS fuer Panel und Wings vorbereiten.
9. Erst dann Pelican im Cluster deployen.
10. Danach den Pelican-Web-Installer ausfuehren.
11. Danach Wings per Pelican-Konfiguration aktivieren.
12. Erst ganz am Ende Router-Portforwards fuer Spielports oeffnen.

---

## Phase 1: `media-1` verifizieren

Alle Befehle in dieser Phase laufen direkt auf `media-1`.

### 1. Host-Check

```bash
hostnamectl
lsb_release -a
uname -m
ip -br addr
ip route
```

Erwartung:

* Hostname ist `media-1`
* Architektur ist `x86_64`
* `enp8s0` existiert
* `vlan10`, `vlan20` und `vlan30` existieren bereits
* die Default-Route bleibt auf dem Management-/Node-Netz

### 2. Bereits vorhandene Sysctls pruefen

```bash
sysctl net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
```

Erwartung:

* `net.ipv4.ip_forward = 1`
* `net.ipv4.conf.all.rp_filter = 2`
* `net.ipv4.conf.default.rp_filter = 2`

Wenn das nicht passt, zieh zuerst den Sysctl-Teil aus [`setup.md`](./setup.md) nach.

### 3. Bestehende Netplan-Datei sichern

```bash
ls -1 /etc/netplan
sudo cp /etc/netplan/90-net.yaml "/etc/netplan/90-net.yaml.bak.$(date +%F-%H%M%S)"
```

---

## Phase 2: `vlan50` auf `media-1` einrichten

Deine bestehende Netplan-Datei verwendet bereits `enp8s0` und `vlan10`/`vlan20`/`vlan30`.
Jetzt wird derselbe Stil um `vlan50` erweitert.

### 1. `90-net.yaml` bearbeiten

```bash
sudo nano /etc/netplan/90-net.yaml
```

Erweitere den bestehenden `vlans:`-Block um genau diesen Eintrag:

```yaml
    vlan50:
      id: 50
      link: enp8s0
      addresses:
        - 172.26.50.31/24
      dhcp4: false
      dhcp6: false
      routes:
        - to: 0.0.0.0/0
          via: 172.26.50.1
          table: 50
      routing-policy:
        - from: 172.26.50.31/32
          table: 50
```

Wichtig:

* Keine normale zweite Default-Route im `main` Table bauen.
* Die Default-Route fuer das Game-Netz existiert nur in Routing-Tabelle `50`.
* Genau dadurch geht Antwort-Traffic fuer `172.26.50.31` spaeter auch wirklich ueber `vlan50` raus.

### 2. Netplan anwenden

```bash
sudo chmod 600 /etc/netplan/90-net.yaml
sudo netplan generate
sudo netplan try
sudo netplan apply
```

### 3. Routing pruefen

```bash
ip -br addr show dev vlan50
ip rule show | grep '172.26.50.31/32'
ip route show table 50
ip route get 1.1.1.1 from 172.26.50.31
ping -c 3 172.26.50.1
```

Die wichtigste Ausgabe ist:

```bash
ip route get 1.1.1.1 from 172.26.50.31
```

Erwartung:

* die Route geht ueber `dev vlan50`
* Source ist `172.26.50.31`

Wenn das nicht stimmt, **nicht** mit Pelican weitermachen.

---

## Phase 3: Zusaetzliche Host-Pakete fuer Pelican/Wings

Die Basis aus `setup.md` ist schon da.
Hier kommt nur noch das dazu, was du fuer Pelican/Wings wirklich extra brauchst.

```bash
sudo apt update
sudo apt install -y \
  certbot \
  curl \
  jq \
  ufw \
  unzip
```

Kurzer Check:

```bash
dpkg -l certbot jq ufw unzip | grep '^ii'
```

---

## Phase 4: Docker auf `media-1`

Pelican Wings nutzt Docker direkt auf dem Host.

### 1. Docker installieren

```bash
curl -fsSL https://get.docker.com/ | CHANNEL=stable sudo sh
sudo systemctl enable --now docker
```

### 2. Docker pruefen

```bash
sudo docker info >/dev/null && echo "Docker OK"
sudo docker run --rm hello-world
```

Wenn `hello-world` sauber laeuft, ist Docker bereit.

---

## Phase 5: Wings vorbereiten, aber noch nicht starten

### 1. Verzeichnisse anlegen

Wings nutzt standardmaessig:

* `/etc/pelican/config.yml`
* `/var/lib/pelican`
* `/var/lib/pelican/volumes`
* `/var/lib/pelican/archives`
* `/var/lib/pelican/backups`
* `/var/log/pelican`

Anlegen:

```bash
sudo install -d -m 755 /etc/pelican
sudo install -d -m 755 /var/run/wings
sudo install -d -m 755 /var/log/pelican
sudo install -d -m 755 /var/lib/pelican
sudo install -d -m 755 /var/lib/pelican/volumes
sudo install -d -m 755 /var/lib/pelican/archives
sudo install -d -m 755 /var/lib/pelican/backups
```

### 2. Wings-Binary installieren

```bash
sudo curl -L -o /usr/local/bin/wings \
  https://github.com/pelican-dev/wings/releases/latest/download/wings_linux_amd64
sudo chmod 0755 /usr/local/bin/wings
wings version
```

### 3. Systemd-Unit anlegen

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
```

### 4. Noch nicht starten

An dieser Stelle **nicht**:

```bash
sudo systemctl enable --now wings
```

Wings startet erst spaeter, wenn Pelican die passende Node-Konfiguration erzeugt hat.

---

## Phase 6: Firewall auf `media-1`

Die erste Version des Guides hatte hier ein pauschales `ufw default deny incoming`.
Das ist fuer `media-1` in deinem Cluster zu grob, weil die Node nicht nur SSH und Wings spricht, sondern auch ganz normalen k3s-, kube-proxy-, CNI- und Ingress-Traffic fuer andere Dienste auf VLAN20/VLAN30/VLAN100 transportiert.

Kurz gesagt:

* Auf `media-1` **keine** globale UFW-Deny-Policy aktivieren.
* Die Erreichbarkeit deiner bestehenden Media-Dienste soll erhalten bleiben.
* Die eigentliche Abschottung fuer Pelican/Wings/Games erfolgt in v1 ueber internes DNS, VLAN-Trennung und Router/NAT, nicht ueber eine hostweite Default-Deny-Firewall auf dem k3s-Worker.

### 1. UFW auf `media-1` fuer diesen Schritt deaktiviert lassen

Wenn UFW bereits aktiv ist:

```bash
sudo ufw disable
sudo systemctl disable ufw --now || true
sudo ufw status verbose
```

Erwartung:

* `Status: inactive`

### 2. Was stattdessen in v1 die Sicherheit traegt

* `pelican.intern.rohrbom.be` bleibt ein interner Ingress-Host auf VLAN20.
* `wings-media-1.intern.rohrbom.be` zeigt intern auf `172.26.100.31`.
* Es gibt **keine** WAN-Portforwards auf SSH, Wings oder das Panel.
* WAN-Portforwards kommen spaeter nur fuer ausgewaehlte Spielports auf `172.26.50.31`.
* Das Game-VLAN liegt nur auf `media-1`.

### 3. Warum ich das hier so drehe

Die offiziellen k3s-Hinweise sind bei Host-Firewalls ziemlich klar: wenn man sie nicht komplett deaktiviert, muss man mindestens die Pod-/Service-CIDRs und die noetigen Node-Ports sauber freigeben, und je nach Setup kommen weitere Ports dazu.

In deinem Cluster ist `media-1` gleichzeitig:

* k3s-Worker
* Ingress-Footprint fuer interne Dienste
* Media-Node fuer bestehende Services
* spaeter Gameserver-Host

Fuer so eine Node ist ein sauberer Host-Firewall-Plan moeglich, aber deutlich breiter als die wenigen Ports `22`, `8080` und `2022`.
Fuer den Pelican-Start ist es sicherer, UFW hier erstmal **nicht** als globale Node-Firewall zu benutzen.

---

## Phase 7: DNS vorbereiten

Bevor du Pelican oder Wings wirklich nutzt, sollten diese Namen bereits stimmen:

* `pelican.intern.rohrbom.be -> 172.26.20.151`
* `wings-media-1.intern.rohrbom.be -> 172.26.100.31`

Der erste Name zeigt auf deinen internen Ingress.
Der zweite Name zeigt auf die Management-IP von `media-1`.

Wichtig:

* Der Cloudflare-Eintrag fuer `wings-media-1.intern.rohrbom.be` muss auf `DNS only` stehen, nicht auf proxied.
* Wings bleibt damit sauber im Management-Netz auf VLAN100.
* Die spaeteren Spielserver-Allokationen bleiben trotzdem auf `172.26.50.31`.

---

## Phase 8: Cluster-Seite nur verifizieren

Weil `media-1` laut deinem Stand bereits mit Label und Taint gejoint wurde, pruefen wir hier nur noch.

Auf deinem Admin-PC:

```bash
kubectl get node media-1 -o wide
kubectl get node media-1 --show-labels
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

Erwartung:

* Node-IP ist `172.26.100.31`
* Label `dedicated=media` ist vorhanden
* Taint `dedicated=media:NoSchedule` ist vorhanden

Wenn einer der beiden Punkte fehlt:

```bash
kubectl label node media-1 dedicated=media --overwrite
kubectl taint node media-1 dedicated=media:NoSchedule --overwrite
```

Wichtig:

* **kein** `longhorn=storage` auf `media-1` setzen

---

## Phase 9: Erst jetzt Pelican im Cluster deployen

### 1. Optionales Secret vorbereiten

Das Deployment funktioniert auch ohne zusaetzliches Secret.
Pelican erzeugt dann den `APP_KEY` selbst und speichert ihn im PVC.

Wenn du den Schluessel lieber selbst vorgeben willst:

1. Kopiere [`../apps/internal/pelican/pelican-secret.yaml.example`](../apps/internal/pelican/pelican-secret.yaml.example) nach `apps/internal/pelican/pelican-secret.yaml`.
2. Fuelle die Werte aus.
3. Verschluessle die Datei:

```bash
sops --encrypt --in-place apps/internal/pelican/pelican-secret.yaml
```

4. Entkommentiere `pelican-secret.yaml` in [`../apps/internal/pelican/kustomization.yaml`](../apps/internal/pelican/kustomization.yaml).

### 2. Flux reconciliieren

```bash
flux reconcile kustomization apps -n flux-system --with-source
kubectl -n svc-games get all
kubectl -n svc-games get pvc
kubectl -n svc-games get ingress
kubectl -n svc-games logs deploy/pelican --tail=200
```

### 3. Panel pruefen

```bash
curl -Ik https://pelican.intern.rohrbom.be
```

Danach im Browser:

* `https://pelican.intern.rohrbom.be/installer`

---

## Phase 10: Pelican Web-Installer

Wenn Pod, PVC und Ingress sauber stehen:

1. `https://pelican.intern.rohrbom.be/installer` oeffnen
2. Installer durchlaufen
3. fuer v1 folgende Defaults verwenden:

* Cache Driver: `Filesystem`
* Database Driver: `SQLite`
* Queue Driver: `Database`
* Session Driver: `Filesystem`

4. ersten Admin-Benutzer anlegen

---

## Phase 11: Wings mit echter Pelican-Konfiguration aktivieren

### 1. TLS fuer Wings vorbereiten

Da dein Panel ueber HTTPS laeuft, solltest du Wings ebenfalls ueber einen TLS-faehigen Namen anbinden.
Du hast keine interne CA, und dein DNS liegt in Cloudflare. Deshalb ist fuer dich der sinnvolle Weg:

* `DNS-01` via Cloudflare
* `wings-media-1.intern.rohrbom.be -> 172.26.100.31`
* Cloudflare-Eintrag auf `DNS only`

Der A-Record darf dabei ruhig auf einer privaten IP liegen.
Bei `DNS-01` ist entscheidend, dass Cloudflare die Zone autoritativ verwaltet, nicht dass die Ziel-IP oeffentlich erreichbar ist.

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-dns-cloudflare
```

### 2. Cloudflare-API-Token fuer Certbot hinterlegen

Lege in Cloudflare einen API-Token an, der mindestens DNS-Edit-Rechte fuer die Zone `intern.rohrbom.be` hat.

Dann auf `media-1`:

```bash
sudo install -d -m 700 /root/.secrets/certbot
sudo nano /root/.secrets/certbot/cloudflare.ini
sudo chmod 600 /root/.secrets/certbot/cloudflare.ini
```

Inhalt der Datei:

```ini
dns_cloudflare_api_token = <CLOUDFLARE_API_TOKEN>
```

### 3. Zertifikat fuer Wings holen

```bash
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.secrets/certbot/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 60 \
  -d wings-media-1.intern.rohrbom.be
```

Erwartung:

* Zertifikat unter `/etc/letsencrypt/live/wings-media-1.intern.rohrbom.be/fullchain.pem`
* Key unter `/etc/letsencrypt/live/wings-media-1.intern.rohrbom.be/privkey.pem`

Pruefen:

```bash
sudo ls -l /etc/letsencrypt/live/wings-media-1.intern.rohrbom.be/
sudo certbot certificates
```

### 4. Node in Pelican anlegen

Im Pelican-Adminbereich:

1. neue Node fuer `media-1` anlegen
2. Host/FQDN: `wings-media-1.intern.rohrbom.be`
3. Scheme: `https`
4. Daemon Port: `8080`
5. SFTP Port: `2022`

### 5. Game-Allokationen anlegen

Die Allokationen gehoeren auf die Game-IP:

* `172.26.50.31`

Nicht auf:

* `172.26.100.31`

Merksatz:

* Wings/Node = `172.26.100.31` bzw. `wings-media-1.intern.rohrbom.be`
* Spielports = `172.26.50.31`

### 6. Konfiguration aus Pelican holen

In Pelican:

1. Node `media-1` oeffnen
2. `Configuration`-Tab oeffnen
3. Config kopieren oder den `Auto Deploy Command` verwenden

Wenn du die Config manuell eintraegst:

```bash
sudo nano /etc/pelican/config.yml
```

Pruefe in der erzeugten Config besonders diese Punkte:

* API-/Daemon-Host passt zu `wings-media-1.intern.rohrbom.be`
* TLS-Zertifikat zeigt auf `/etc/letsencrypt/live/wings-media-1.intern.rohrbom.be/fullchain.pem`
* TLS-Key zeigt auf `/etc/letsencrypt/live/wings-media-1.intern.rohrbom.be/privkey.pem`

### 7. Wings erst lokal testen

```bash
sudo wings --debug
```

Wenn das sauber startet:

* mit `CTRL+C` beenden
* dann erst als Service aktivieren

### 8. Wings als Service starten

```bash
sudo systemctl enable --now wings
sudo systemctl status wings --no-pager
sudo journalctl -u wings -n 100 --no-pager
```

---

## Phase 12: Router erst ganz am Ende

Sobald intern alles funktioniert und ein Testserver sauber startet:

* WAN -> ausgewaehlte TCP/UDP-Spielports -> `172.26.50.31`
* kein WAN-Forward auf SSH
* kein WAN-Forward auf Wings
* kein WAN-Forward auf `pelican.intern.rohrbom.be`

Wenn du spaeter Cloudflare-SRV-Eintraege verwendest:

* Cloudflare nur als DNS
* kein normaler HTTP-Proxy dazwischen

---

## Schnelle Checks

### Host

```bash
ip -br addr show dev vlan50
ip route get 1.1.1.1 from 172.26.50.31
sudo docker info >/dev/null && echo "Docker OK"
sudo systemctl status wings --no-pager
sudo ufw status verbose
```

Erwartung:

* die Route fuer Source `172.26.50.31` geht ueber `vlan50`
* Docker meldet `Docker OK`
* `wings` ist nach Phase 11 `active (running)`
* UFW steht fuer diesen Startzustand auf `Status: inactive`

### Cluster

```bash
kubectl -n svc-games get pods
kubectl -n svc-games get ingress pelican
kubectl -n svc-games logs deploy/pelican --tail=200
```

### Erfolgskriterien

* `vlan50` hat `172.26.50.31/24`
* Source `172.26.50.31` routet ueber `vlan50`
* Docker laeuft
* UFW ist auf `media-1` fuer diesen Startzustand inactive
* Pelican ist intern ueber `https://pelican.intern.rohrbom.be` erreichbar
* Wings ist intern ueber `wings-media-1.intern.rohrbom.be:8080` erreichbar
* Spielserver binden an `172.26.50.31`, nicht an `172.26.100.31`

---

## Referenzen

* [`setup.md`](./setup.md)
* [`media-node.md`](./media-node.md)
* [`../apps/internal/pelican`](../apps/internal/pelican)
* Pelican Panel Docker: https://pelican.dev/docs/panel/advanced/docker/
* Pelican Wings Install: https://pelican.dev/docs/wings/install/
