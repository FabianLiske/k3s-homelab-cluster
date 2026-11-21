# Ingress-Rückrouting auf edge-1

Seit dem 21.11.2026 leitet `edge-1` (`172.26.100.31`) Antworten auf
Ingress-Verbindungen über das VLAN zurück, auf dem die Anfrage eingetroffen ist.
Die Konfiguration liegt unter [infrastructure/hosts/edge-1](../infrastructure/hosts/edge-1/)
und wird direkt auf der Node installiert, nicht durch Flux.

## Ursache und Lösung

Clients (VLAN 40) und Kubernetes (VLAN 100) werden vom USW Pro HD 24 geroutet,
die Ingress-VLANs 10/20/30 vom UniFi-Gateway. Ohne zusätzliche Regeln kamen
Anfragen beispielsweise über `vlan20` an, während Antworten über die
Standardroute `172.26.100.1` auf `enp3s0` das Gateway umgingen. TCP konnte sich
verbinden, HTTPS blieb beim TLS-Handshake hängen.

nftables merkt sich das Eingangs-VLAN im Conntrack-Mark für IPv4-Verbindungen
an die jeweilige Ingress-IP `.151`, TCP-Port 80/443. Nur Antwortpakete erhalten
daraus einen Paket-Mark; `ip rule` wählt damit die Rückroute:

| VLAN | Mark | Routingtabelle | Regelpriorität | Gateway und Interface |
| --- | --- | --- | --- | --- |
| 10 | `0x0a000000` | `10110` | `11010` | `172.26.10.1`, `vlan10` |
| 20 | `0x14000000` | `10120` | `11020` | `172.26.20.1`, `vlan20` |
| 30 | `0x1e000000` | `10130` | `11030` | `172.26.30.1`, `vlan30` |

Jede Tabelle enthält außerdem eine direkte Route für ihr eigenes `/24`-Netz.
Die Maske `0xff000000` reserviert das höchste Byte; die unteren Bits für
Kubernetes und Flannel bleiben erhalten. Die Regeln benötigen keine festen
Pod-IP-Adressen: Beim Routing der Antwort ist die Quelladresse noch die Pod-IP,
die Rückübersetzung zur Ingress-IP erfolgt erst danach.

## Dateien auf der Node

| Quelle unter `infrastructure/hosts/edge-1/` | Installationspfad |
| --- | --- |
| `edge-ingress-routing.nft` | `/etc/nftables.d/edge-ingress-routing.nft` |
| `edge-ingress-routing.service` | `/etc/systemd/system/edge-ingress-routing.service` |
| `vlan10-routing.conf` | `/etc/systemd/network/10-netplan-vlan10.network.d/50-ingress-routing.conf` |
| `vlan20-routing.conf` | `/etc/systemd/network/10-netplan-vlan20.network.d/50-ingress-routing.conf` |
| `vlan30-routing.conf` | `/etc/systemd/network/10-netplan-vlan30.network.d/50-ingress-routing.conf` |

Der aktivierte systemd-Dienst lädt beim Boot ausschließlich die eigene
nftables-Tabelle `ip edge_ingress_routing`. Die networkd-Drop-ins ergänzen
Netplans erzeugte Konfiguration um Routen und Regeln. Die vorhandenen Werte
`net.ipv4.ip_forward=1` und `net.ipv4.conf.{all,default}.rp_filter=2` sind bereits
in `/etc/sysctl.d/100-k3s-edge.conf` hinterlegt.

## Installation und Prüfung

Für eine **Erstinstallation** eine Kopie des Repositorys auf `edge-1` bereitstellen
und dort im Repository-Root ausführen:

```bash
sudo bash tools/install-edge-ingress-routing.sh
```

Das [Installationsskript](../tools/install-edge-ingress-routing.sh) prüft freie
Tabellen und Regelprioritäten, sichert den Ausgangszustand und aktiviert einen
automatischen Rollback nach fünf Minuten. Bestehende Installationen werden
nicht überschrieben. Anschließend vom Client HTTPS in allen drei VLANs prüfen:

```bash
for host in grafana.liske.cc ha.liske.cc vault.rohrbom.be; do
  curl --noproxy '*' --connect-timeout 3 --max-time 10 -sS -o /dev/null \
    -w "$host: HTTP %{http_code}\n" "https://$host/"
done
```

Auf der Node den Zustand kontrollieren und **erst nach erfolgreichen Tests**
den Rollback-Timer stoppen:

```bash
systemctl status edge-ingress-routing.service
ip -4 rule show
ip -4 route show table 10120
sudo nft list table ip edge_ingress_routing
sudo systemctl stop edge-ingress-routing-rollback.timer
```

Spätere Änderungen an den installierten Dateien mit einem Rollback absichern;
vor dem Laden `sudo nft -c -f /etc/nftables.d/edge-ingress-routing.nft` ausführen.
Routen mit `sudo networkctl reload`, nftables-Regeln mit
`sudo systemctl reload edge-ingress-routing.service` übernehmen.
Kein globales `nft flush ruleset` verwenden: Die übrigen Tabellen gehören
unter anderem kube-proxy.

## Rollback und verifizierter Stand

Das Installationsskript legt `rollback.sh` unter
`/var/backups/edge-ingress-routing/<Zeitstempel>-<PID>/` an. Es entfernt die
eigene Konfiguration einschließlich Dienst, Routingregeln und Tabellen.
Für die Installation vom 21.11.2026 lautet der Befehl auf `edge-1`:

```bash
sudo bash /var/backups/edge-ingress-routing/20261121T170724Z-3409548/rollback.sh
```

Am 21.11.2026 waren nach der Korrektur alle 27 Ingress-Hosts mit gültigem TLS
erreichbar; Vaultwarden, Immich und Trilium zusätzlich über Cloudflare.
Regel-Reload und erneutes Anwenden der VLAN-Konfiguration wurden getestet,
ein Reboot nicht. Der Rollback-Timer wurde nach den Tests deaktiviert;
der Browserzugriff wurde ebenfalls bestätigt.
