# ZFS-Medienspeicher auf `media-1`

Dieses Dokument beschreibt den sauberen Umbau von `media-1`, damit kalte Mediendaten auf die drei 14-TB-HDDs wandern, ohne den bestehenden Media-Stack neu aufzubauen.

Das wichtigste Architekturprinzip ist:

* Die Apps behalten ihre bekannten Containerpfade unter `/data`
* Kalte Daten kommen aus einem **neuen lokalen PVC** auf ZFS
* Heiße Daten bleiben auf dem **bestehenden lokalen PVC** auf der NVMe

Damit vermeiden wir:

* Host-Symlinks unterhalb des bestehenden PVC-Mounts
* verschachtelte Host-Mounts, die im Pod nicht sauber auftauchen
* Path-Mapping-Gefrickel in Sonarr/Radarr/Jellyfin

---

## Zielbild

### Auf dem Host

* NVMe bleibt auf `/data`
* ZFS-RAIDZ1 der drei HDDs mountet nach `/srv/media-hdd`

### Im Pod

* Kaltes PVC `media-cold-data` wird nach `/data` gemountet
* Heißes PVC `media-local-data` wird nur dort eingehängt, wo es gebraucht wird

Konkret:

* `/data/media` kommt von ZFS
* `/data/torrents/complete` kommt von ZFS
* `/data/torrents/incomplete` bleibt auf NVMe
* `/data/transcode` bleibt auf NVMe

Damit bleiben alle bestehenden App-Pfade aus [`media-ui-setup.md`](./media-ui-setup.md) gültig:

* `/data/torrents/incomplete`
* `/data/torrents/complete/sonarr`
* `/data/torrents/complete/radarr`
* `/data/media/shows`
* `/data/media/movies`
* `/data/transcode`

Und der wichtige *arr-Punkt bleibt erhalten:

* `/data/torrents/complete`
* `/data/media`

liegen im Pod auf **demselben Dateisystem**, also funktionieren Hardlinks weiter.

---

## Warum der erste Symlink-Ansatz nicht sauber war

Der zwischenzeitliche Ansatz mit:

* ZFS-Mount unter `/data/.cold`
* Symlinks `/data/media -> .cold/media`

scheitert in Kubernetes praktisch daran, dass der verschachtelte Host-Mount im Pod unter dem bestehenden PVC-Mount nicht sauber sichtbar wird.

Deshalb ist der robustere Weg:

* ZFS außen am Host unter `/srv/media-hdd`
* eigenes lokales PV/PVC dafür
* dieses kalte PVC direkt in den Pod nach `/data`
* heiße NVMe-Pfade gezielt als weitere Unter-Mounts darüberlegen

---

## Ausgangslage

Stand zum Zeitpunkt dieser Doku:

* Root auf `/dev/sdb2`
* NVMe-Daten auf `/dev/nvme0n1p1`
* `/data` auf ext4 auf der NVMe
* drei neue HDDs:
  * `/dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_Z2KEEM7T`
  * `/dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_9JJURDZT`
  * `/dev/disk/by-id/ata-WDC_WD140EDFZ-11A0VA0_9LG0PHYE`
* aktuelle Datenmenge:
  * `/data/media` ca. `1.4T`
  * `/data/torrents` ca. `6.1G`
  * `/data/transcode` praktisch leer

---

## Designentscheidungen

### 1. ZFS-Layout

Es wird ein `RAIDZ1`-Pool gebaut:

* Poolname: `media`
* Datasetname: `media/cold`
* Mountpoint am Host: `/srv/media-hdd`

### 2. ZFS-RAM klein halten

Konservatives Tuning fuer die 30-GiB-Kiste:

* `zfs_arc_min = 512 MiB`
* `zfs_arc_max = 2 GiB`
* `zfs_prefetch_disable = 1`
* `primarycache=metadata`
* `secondarycache=none`
* kein Dedup
* kein L2ARC
* kein SLOG

### 3. Kalt gegen heiß trennen

Kalt auf ZFS:

* `/data/media`
* `/data/torrents/complete`
* spaeter Immich-Originale

Heiß auf NVMe:

* `/data/torrents/incomplete`
* `/data/transcode`
* Gameserver-Daten
* spaeter Immich-DB, Thumbs, Encoded, Backups

---

## Phase 0: Istzustand sichern

Auf `media-1`:

```bash
hostnamectl
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL
findmnt -R /data
df -hT / /data
sudo du -sh /data/media /data/torrents /data/transcode 2>/dev/null
kubectl -n svc-media get pvc,pods -o wide
```

---

## Phase 1: ZFS installieren und konservativ tunen

```bash
sudo apt update
sudo apt install -y zfsutils-linux gdisk rsync
```

```bash
sudo tee /etc/modprobe.d/zfs-media-1.conf >/dev/null <<'EOF'
options zfs zfs_arc_min=536870912
options zfs zfs_arc_max=2147483648
options zfs zfs_prefetch_disable=1
EOF
```

```bash
sudo update-initramfs -u
sudo modprobe zfs
echo 536870912 | sudo tee /sys/module/zfs/parameters/zfs_arc_min
echo 2147483648 | sudo tee /sys/module/zfs/parameters/zfs_arc_max
echo 1 | sudo tee /sys/module/zfs/parameters/zfs_prefetch_disable
```

Prüfen:

```bash
cat /sys/module/zfs/parameters/zfs_arc_min
cat /sys/module/zfs/parameters/zfs_arc_max
cat /sys/module/zfs/parameters/zfs_prefetch_disable
```

---

## Phase 2: HDDs prüfen und löschen

Nur diese drei Disks dürfen weg:

```bash
ls -l /dev/disk/by-id/ | egrep 'Z2KEEM7T|9JJURDZT|9LG0PHYE'
```

Lesend prüfen:

```bash
sudo wipefs -n /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_Z2KEEM7T
sudo wipefs -n /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_9JJURDZT
sudo wipefs -n /dev/disk/by-id/ata-WDC_WD140EDFZ-11A0VA0_9LG0PHYE
```

Dann löschen:

```bash
sudo sgdisk --zap-all /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_Z2KEEM7T
sudo sgdisk --zap-all /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_9JJURDZT
sudo sgdisk --zap-all /dev/disk/by-id/ata-WDC_WD140EDFZ-11A0VA0_9LG0PHYE

sudo wipefs -a /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_Z2KEEM7T
sudo wipefs -a /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_9JJURDZT
sudo wipefs -a /dev/disk/by-id/ata-WDC_WD140EDFZ-11A0VA0_9LG0PHYE
```

---

## Phase 3: Pool und Dataset anlegen

### 1. Pool

```bash
sudo zpool create -f \
  -o ashift=12 \
  -O mountpoint=none \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  -O acltype=posixacl \
  -O dnodesize=auto \
  media raidz1 \
  /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_Z2KEEM7T \
  /dev/disk/by-id/ata-WDC_WD140EMFZ-11A0WA0_9JJURDZT \
  /dev/disk/by-id/ata-WDC_WD140EDFZ-11A0VA0_9LG0PHYE
```

### 2. Dataset

```bash
sudo zfs create \
  -o mountpoint=/srv/media-hdd \
  -o recordsize=1M \
  -o primarycache=metadata \
  -o secondarycache=none \
  media/cold
```

### 3. Struktur

```bash
sudo mkdir -p /srv/media-hdd/media/shows
sudo mkdir -p /srv/media-hdd/media/movies
sudo mkdir -p /srv/media-hdd/media/music
sudo mkdir -p /srv/media-hdd/media/books
sudo mkdir -p /srv/media-hdd/torrents/complete/sonarr
sudo mkdir -p /srv/media-hdd/torrents/complete/radarr
sudo mkdir -p /srv/media-hdd/torrents/complete/lidarr
sudo mkdir -p /srv/media-hdd/torrents/complete/readarr
sudo mkdir -p /srv/media-hdd/immich
```

### 4. Prüfen

```bash
sudo zpool status -v media
sudo zpool list media
sudo zfs get mountpoint,recordsize,primarycache,secondarycache,compression,atime media/cold
findmnt /srv/media-hdd
```

---

## Phase 4: Erste Datenkopie im laufenden Betrieb

```bash
sudo rsync -aHAX --numeric-ids --info=progress2 /data/media/ /srv/media-hdd/media/
sudo rsync -aHAX --numeric-ids --info=progress2 /data/torrents/complete/ /srv/media-hdd/torrents/complete/
```

Prüfen:

```bash
sudo du -sh /data/media /srv/media-hdd/media 2>/dev/null
sudo du -sh /data/torrents/complete /srv/media-hdd/torrents/complete 2>/dev/null
```

---

## Phase 5: Media-Deployments anhalten und final syncen

```bash
MEDIA_DEPLOYMENTS="bazarr jellyfin lidarr prowlarr qbittorrent radarr readarr seerr sonarr"
kubectl -n svc-media scale deployment ${MEDIA_DEPLOYMENTS} --replicas=0
kubectl -n svc-media get pods -o wide
```

Wenn die Pods unten sind:

```bash
sudo rsync -aHAX --numeric-ids --delete --info=progress2 /data/media/ /srv/media-hdd/media/
sudo rsync -aHAX --numeric-ids --delete --info=progress2 /data/torrents/complete/ /srv/media-hdd/torrents/complete/
```

Optional die alten Host-Verzeichnisse nur als Backup umbenennen:

```bash
STAMP="$(date +%F-%H%M%S)"
sudo mv /data/media "/data/media.nvme-backup-${STAMP}"
sudo mv /data/torrents/complete "/data/torrents.complete.nvme-backup-${STAMP}"
sudo mkdir -p /data/media
sudo mkdir -p /data/torrents/complete
```

Wichtig:

* Diese Host-Pfade werden vom neuen Pod-Layout **nicht mehr** als Primärspeicher genutzt
* Sie dürfen leer bleiben
* Das Backup ist nur für Rollback und Beruhigung da

---

## Phase 6: Neues kaltes PV/PVC im Cluster verwenden

Im Repo gibt es dafür jetzt zusätzliche Ressourcen:

* `media-cold-data-pv`
* `media-cold-data`

Konzept:

* `media-cold-data` zeigt auf `/srv/media-hdd`
* das bisherige `media-local-data` bleibt der heiße NVMe-Speicher

Deployments sind so umgestellt:

* `Sonarr`, `Radarr`, `Lidarr`, `Readarr`, `Bazarr` sehen kaltes ZFS unter `/data`
* `qBittorrent` sieht kaltes ZFS unter `/data`, aber `/data/torrents/incomplete` zusätzlich vom heißen NVMe-PVC
* `Jellyfin` sieht kaltes ZFS unter `/data`, aber `/data/transcode` zusätzlich vom heißen NVMe-PVC

Dadurch bleiben die bekannten UI-Pfade **unverändert**.

Cluster-Manifest anwenden:

```bash
kubectl apply -k apps/internal/media
```

Dann kurz prüfen:

```bash
kubectl -n svc-media get pv,pvc
```

Erwartung:

* `media-cold-data-pv` ist `Available` oder direkt `Bound`
* `media-cold-data` ist `Bound`
* `media-local-data` bleibt `Bound`

---

## Phase 7: Media-Deployments wieder starten

```bash
MEDIA_DEPLOYMENTS="bazarr jellyfin lidarr prowlarr qbittorrent radarr readarr seerr sonarr"
kubectl -n svc-media scale deployment ${MEDIA_DEPLOYMENTS} --replicas=1
kubectl -n svc-media get pods -o wide -w
```

Mit `Ctrl-C` kannst du das Watching beenden.

Dann Rollouts prüfen:

```bash
kubectl -n svc-media rollout status deployment/bazarr
kubectl -n svc-media rollout status deployment/jellyfin
kubectl -n svc-media rollout status deployment/lidarr
kubectl -n svc-media rollout status deployment/prowlarr
kubectl -n svc-media rollout status deployment/qbittorrent
kubectl -n svc-media rollout status deployment/radarr
kubectl -n svc-media rollout status deployment/readarr
kubectl -n svc-media rollout status deployment/seerr
kubectl -n svc-media rollout status deployment/sonarr
```

---

## Phase 8: Funktionstests

### Sonarr

```bash
kubectl -n svc-media exec deployment/sonarr -- sh -c 'ls -ld /data /data/media /data/media/shows /data/torrents /data/torrents/complete /data/torrents/complete/sonarr'
kubectl -n svc-media exec deployment/sonarr -- sh -c 'touch /data/media/shows/.write-test && rm /data/media/shows/.write-test'
```

### Radarr

```bash
kubectl -n svc-media exec deployment/radarr -- sh -c 'ls -ld /data/media /data/media/movies /data/torrents/complete /data/torrents/complete/radarr'
kubectl -n svc-media exec deployment/radarr -- sh -c 'touch /data/media/movies/.write-test && rm /data/media/movies/.write-test'
```

### qBittorrent

```bash
kubectl -n svc-media exec deployment/qbittorrent -- sh -c 'ls -ld /data/torrents /data/torrents/incomplete /data/torrents/complete /data/torrents/complete/sonarr'
kubectl -n svc-media exec deployment/qbittorrent -- sh -c 'touch /data/torrents/incomplete/.write-test && rm /data/torrents/incomplete/.write-test'
kubectl -n svc-media exec deployment/qbittorrent -- sh -c 'touch /data/torrents/complete/sonarr/.write-test && rm /data/torrents/complete/sonarr/.write-test'
```

### Hardlink-Test im Pod

```bash
kubectl -n svc-media exec deployment/sonarr -- sh -c '
  mkdir -p /data/torrents/complete/.hardlink-test /data/media/.hardlink-test &&
  truncate -s 1M /data/torrents/complete/.hardlink-test/test.bin &&
  ln /data/torrents/complete/.hardlink-test/test.bin /data/media/.hardlink-test/test.bin &&
  stat -c "%h %n" /data/torrents/complete/.hardlink-test/test.bin /data/media/.hardlink-test/test.bin &&
  rm -f /data/media/.hardlink-test/test.bin /data/torrents/complete/.hardlink-test/test.bin &&
  rmdir /data/media/.hardlink-test /data/torrents/complete/.hardlink-test
'
```

Erwartung:

* Link-Count `2`

---

## Phase 9: Reboot-Test

```bash
sudo reboot
```

Danach:

```bash
cat /sys/module/zfs/parameters/zfs_arc_min
cat /sys/module/zfs/parameters/zfs_arc_max
cat /sys/module/zfs/parameters/zfs_prefetch_disable
sudo zpool status -v media
findmnt /srv/media-hdd
kubectl -n svc-media get pv,pvc,pods -o wide
```

---

## Phase 10: Alte NVMe-Daten später löschen

Wenn alles sauber läuft:

* Jellyfin liest
* Sonarr/Radarr importieren
* qBittorrent seeded
* Hardlinks funktionieren
* Reboot war sauber

dann kannst du die alten Host-Backups später löschen:

```bash
sudo rm -rf /data/media.nvme-backup-YYYY-MM-DD-HHMMSS
sudo rm -rf /data/torrents.complete.nvme-backup-YYYY-MM-DD-HHMMSS
```

---

## Rollback

Wenn etwas schiefläuft:

```bash
MEDIA_DEPLOYMENTS="bazarr jellyfin lidarr prowlarr qbittorrent radarr readarr seerr sonarr"
kubectl -n svc-media scale deployment ${MEDIA_DEPLOYMENTS} --replicas=0
```

Dann die alten Host-Verzeichnisse zurückholen:

```bash
sudo rm -rf /data/media
sudo rm -rf /data/torrents/complete
sudo mv /data/media.nvme-backup-YYYY-MM-DD-HHMMSS /data/media
sudo mv /data/torrents.complete.nvme-backup-YYYY-MM-DD-HHMMSS /data/torrents/complete
```

Und die alten Media-Manifeste wieder deployen.

---

## Referenzen

* [x86-Media-Node im bestehenden ARM-K3s-Cluster](./media-node.md)
* [UI-Einrichtung des Media-Stacks](./media-ui-setup.md)
* OpenZFS RAIDZ: <https://openzfs.github.io/openzfs-docs/Basic%20Concepts/RAIDZ.html>
