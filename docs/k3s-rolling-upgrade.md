# Rolling Upgrades fuer Ubuntu und K3s

[`tools/k3s-rolling-upgrade.sh`](../tools/k3s-rolling-upgrade.sh) aktualisiert die
Cluster-Nodes seriell per SSH. Control-Plane-Nodes werden immer vor Agents
bearbeitet. Erst wenn eine Node wieder `Ready` ist, ihr Kubelet-Lease erneuert
wurde und sie die erwartete K3s-Version meldet, beginnt die naechste Node.

## Voraussetzungen

- `kubectl` greift vom Admin-PC auf den richtigen Cluster zu.
- Der SSH-Key `~/.ssh/id_ed25519` funktioniert fuer den User `faba`.
- `faba` darf auf allen Nodes `sudo -n` (ohne Passwortabfrage) verwenden.
- Die Ubuntu-Nodes erreichen `github.com` per HTTPS, um K3s samt offizieller
  SHA-256-Datei herunterzuladen.
- Genuegend freie Cluster-Kapazitaet ist vorhanden, um immer eine Node zu
  drainen.

Das Skript fuehrt ein `apt-get full-upgrade` innerhalb der installierten
Ubuntu-Version aus. Es fuehrt bewusst **kein** Ubuntu Release-Upgrade auf eine
neue LTS-Version durch.

## Erster Lauf

Zuerst Discovery, SSH, `sudo`, Rollen und Versionen ohne Aenderungen pruefen:

```bash
./tools/k3s-rolling-upgrade.sh --dry-run
```

Ohne Versionsangabe wird der offizielle K3s-Channel `stable` aufgeloest. Fuer
einen reproduzierbaren Lauf ist eine explizite Version besser (Version hier nur
als Beispiel):

```bash
./tools/k3s-rolling-upgrade.sh \
  --k3s-version v1.33.3+k3s1 \
  --dry-run
```

Wenn der Plan stimmt:

```bash
./tools/k3s-rolling-upgrade.sh \
  --k3s-version v1.33.3+k3s1
```

Das Skript fragt einmal nach Bestaetigung. Fuer einen bereits kontrollierten
Plan kann `--yes` verwendet werden.

Standardmaessig werden alle Kubernetes-Nodes eingeschlossen, in diesem Cluster
also auch `media-1`. Vor dessen Reboot gegebenenfalls laufende Pelican-/Wings-
Gameserver anwendungsspezifisch sauber stoppen. Kubernetes `drain` verwaltet
keine direkt auf dem Host laufenden Prozesse.

## Ablauf und Sicherheitsmechanismen

Vor der ersten Node wird auf einer Control Plane ein etcd-Snapshot erzeugt. Das
Snapshot und der fuer eine Wiederherstellung zwingend benoetigte K3s-Server-
Token werden nach
`~/.local/state/k3s-upgrade/backups/<Zeitstempel>-<Version>/` kopiert. Der
Ordner und seine Dateien sind nur fuer den aktuellen User lesbar; die
Snapshot-Pruefsumme wird lokal und remote verglichen.

Pro Node geschieht danach:

1. API- und Cluster-Health pruefen.
2. Node cordonen und mit Respekt vor PodDisruptionBudgets drainen.
3. `apt-get update` und `apt-get full-upgrade` ausfuehren.
4. K3s-Release und offizielle SHA-256-Datei laden, pruefen und das Binary
   atomar ersetzen. systemd-Argumente und K3s-Konfiguration bleiben erhalten.
5. Genau einmal rebooten und eine neue Boot-ID abwarten.
6. K3s-Service, neues Kubelet-Lease, Node-`Ready` und Zielversion pruefen.
7. Node wieder uncordonen und den gesamten Cluster vor der naechsten Node
   pruefen.

`kubectl drain` nutzt `--delete-emptydir-data`, aber weder `--force` noch
`--disable-eviction`. Temporaere `emptyDir`-Daten duerfen damit geloescht
werden; PodDisruptionBudgets werden nicht umgangen. Blockiert etwa ein PDB oder
eine Longhorn-Einstellung den Drain, stoppt der Lauf anstatt die Eviction zu
erzwingen.

Kubernetes-Minor-Versionen duerfen nicht uebersprungen und K3s-Versionen nicht
automatisch heruntergestuft werden. Das Skript lehnt beides ab. Upgrades ueber
mehrere Minor-Versionen daher in mehreren vollstaendigen Laeufen ausfuehren.

## Auswahl und Sonderfaelle

Nur bestimmte Nodes, weiterhin mit Control Planes vor Agents:

```bash
./tools/k3s-rolling-upgrade.sh \
  --k3s-version v1.33.3+k3s1 \
  --nodes cp-1,cp-2,cp-3
```

Abweichendes SSH-Ziel, beispielsweise wenn die Kubernetes-InternalIP nicht vom
Admin-PC erreichbar ist:

```bash
./tools/k3s-rolling-upgrade.sh \
  --ssh-host cp-1=cp-1.intern.rohrbom.be \
  --ssh-host cp-2=cp-2.intern.rohrbom.be
```

Nur Ubuntu-Pakete aktualisieren:

```bash
./tools/k3s-rolling-upgrade.sh --skip-k3s
```

Nur K3s aktualisieren:

```bash
./tools/k3s-rolling-upgrade.sh --skip-os --k3s-version v1.33.3+k3s1
```

Alle Optionen zeigt `./tools/k3s-rolling-upgrade.sh --help`.

## Fehlerfall

Bei einem Fehler bleibt die aktive Node absichtlich cordoned und der Lauf
stoppt. Nicht blind uncordonen: zuerst SSH, systemd und Kubernetes pruefen:

```bash
ssh -i ~/.ssh/id_ed25519 faba@NODE-IP 'sudo systemctl status k3s k3s-agent --no-pager'
kubectl get node NODE -o wide
kubectl get pods -A -o wide --field-selector spec.nodeName=NODE
```

Das vorherige K3s-Binary liegt auf der Node neben dem aktiven Binary als
`k3s.pre-upgrade-<Zeitstempel>`. Ein Downgrade sollte nicht automatisiert durch
Zurueckkopieren erfolgen: Bei einem Minor-Downgrade kann auch eine vollstaendige
Datastore-Wiederherstellung aus dem gesicherten Snapshot notwendig sein. Die
offizielle K3s-Rollback-Anleitung ist dafuer massgeblich:
<https://docs.k3s.io/upgrades/roll-back>.

Erst wenn die Node gesund ist und vorher nicht bereits absichtlich cordoned
war:

```bash
kubectl uncordon NODE
```
