# UI-Einrichtung des Media-Stacks

Dieses Dokument beschreibt die Einrichtung der aktuell vorhandenen Media-Dienste im Cluster:

* qBittorrent
* Prowlarr
* Sonarr
* Radarr
* Bazarr
* Jellyfin
* Seerr (technisch Jellyseerr)

Ziel ist, dass die Dienste intern sauber zusammenarbeiten:

* **Dienst-zu-Dienst-Kommunikation nur über Kubernetes-Service-Namen**
* **`*.intern.rohrbom.be` nur für deinen Browserzugriff**
* **keine Kommunikation zwischen den Apps über Ingress-FQDNs**

---

## 1. Grundregeln

### Interne Service-Adressen

Diese Adressen werden **in den Apps** für interne Verbindungen verwendet:

* `http://qbittorrent:8080`
* `http://prowlarr:9696`
* `http://sonarr:8989`
* `http://radarr:7878`
* `http://bazarr:6767`
* `http://jellyfin:8096`
* `http://seerr:5055`

### UI-Adressen für deinen Browser

Diese Adressen verwendest **du im Browser**:

* `https://prowlarr.intern.rohrbom.be`
* `https://sonarr.intern.rohrbom.be`
* `https://radarr.intern.rohrbom.be`
* `https://bazarr.intern.rohrbom.be`
* `https://jellyfin.intern.rohrbom.be`
* `https://seerr.intern.rohrbom.be`

qBittorrent hat absichtlich keinen Ingress. Für die UI bei Bedarf:

```bash
kubectl -n svc-media port-forward service/qbittorrent 8080:8080
```

Dann im Browser:

```text
http://127.0.0.1:8080
```

### Wichtige Pfade im Stack

Diese Pfade sind der gemeinsame Nenner aller Apps:

* Downloads unvollständig: `/data/torrents/incomplete`
* Sonarr-Downloads: `/data/torrents/complete/sonarr`
* Radarr-Downloads: `/data/torrents/complete/radarr`
* Serien-Library: `/data/media/shows`
* Filme-Library: `/data/media/movies`
* Jellyfin-Transcode: `/data/transcode`

### API-Keys

Du brauchst API-Keys aus:

* Sonarr
* Radarr

Du findest sie jeweils unter:

```text
Settings -> General -> Security -> API Key
```

Am besten kopierst du beide Keys frühzeitig in einen temporären Notizzettel.

---

## 2. Empfohlene Reihenfolge

Richte die Apps in dieser Reihenfolge ein:

1. qBittorrent
2. Sonarr
3. Radarr
4. Prowlarr
5. Bazarr
6. Jellyfin
7. Seerr

So sind die jeweils benötigten API-Keys und Backend-Dienste schon vorhanden.

---

## 3. qBittorrent einrichten

Öffne qBittorrent per Port-Forward.

### Downloads

Gehe zu:

```text
Tools -> Options -> Downloads
```

Setze oder prüfe:

* `Default Torrent Management Mode`: `Automatic`
* `Category mode` bzw. automatische Pfadverwaltung: aktiv
* `Default Save Path`: `/data/torrents/complete`
* `Keep incomplete torrents in`: aktiv
* Pfad für unvollständige Downloads: `/data/torrents/incomplete`

### Kategorien anlegen

Lege links unter `Categories` mindestens diese beiden Kategorien an:

* `sonarr`
  Save Path: `sonarr`
* `radarr`
  Save Path: `radarr`

Wichtig:

* Trage **nicht** den kompletten Pfad ein, sondern nur den relativen Unterordner, wenn qBittorrent bereits mit `Default Save Path` arbeitet.
* Ziel ist am Ende:
  * `sonarr` -> `/data/torrents/complete/sonarr`
  * `radarr` -> `/data/torrents/complete/radarr`

### Was du hier nicht tun solltest

* Kein Speichern direkt nach `/data/media/...`
* Keine FQDNs für interne Verweise
* Kein separates Download-Verzeichnis außerhalb von `/data`

---

## 4. Sonarr einrichten

Öffne:

```text
https://sonarr.intern.rohrbom.be
```

### API-Key notieren

Gehe zu:

```text
Settings -> General -> Security
```

Kopiere den API-Key.

### Media Management

Gehe zu:

```text
Settings -> Media Management
```

Empfohlen:

* `Rename Episodes`: aktiv
* `Use Hardlinks instead of Copy`: aktiv

### Download Client

Gehe zu:

```text
Settings -> Download Clients
```

Prüfe zuerst:

* `Completed Download Handling`: aktiviert

Füge dann qBittorrent hinzu:

* Host: `qbittorrent`
* Port: `8080`
* Username / Passwort: deine bestehenden qBittorrent-Zugangsdaten
* Use SSL: aus
* URL Base: leer
* Category: `sonarr`

Danach:

* `Test`
* `Save`

### Root Folder

Wenn du die erste Serie anlegst oder Root Folders verwaltest, verwende:

```text
/data/media/shows
```

### Indexer

Indexer in Sonarr **nicht manuell** pflegen, wenn Prowlarr sie synchronisieren soll.

---

## 5. Radarr einrichten

Öffne:

```text
https://radarr.intern.rohrbom.be
```

### API-Key notieren

Gehe zu:

```text
Settings -> General -> Security
```

Kopiere den API-Key.

### Media Management

Gehe zu:

```text
Settings -> Media Management
```

Empfohlen:

* `Rename Movies`: aktiv
* `Use Hardlinks instead of Copy`: aktiv

### Download Client

Gehe zu:

```text
Settings -> Download Clients
```

Prüfe zuerst:

* `Completed Download Handling`: aktiviert

Füge dann qBittorrent hinzu:

* Host: `qbittorrent`
* Port: `8080`
* Username / Passwort: deine bestehenden qBittorrent-Zugangsdaten
* Use SSL: aus
* URL Base: leer
* Category: `radarr`

Danach:

* `Test`
* `Save`

### Root Folder

Wenn du den ersten Film anlegst oder Root Folders verwaltest, verwende:

```text
/data/media/movies
```

### Indexer

Indexer in Radarr ebenfalls **nicht manuell** pflegen, wenn Prowlarr das übernimmt.

---

## 6. Prowlarr einrichten

Öffne:

```text
https://prowlarr.intern.rohrbom.be
```

Prowlarr ist dein zentraler Indexer-Manager.
Ab hier sollen Sonarr und Radarr ihre Indexer von Prowlarr bekommen.

### Indexer hinzufügen

Gehe zu:

```text
Indexers
```

Füge dort deine gewünschten Torrent-Indexer hinzu und teste jede Verbindung.

### Sonarr als App anbinden

Gehe zu:

```text
Settings -> Apps
```

Füge `Sonarr` hinzu.

Nutze intern:

* App Server / Base URL / Host: `http://sonarr:8989`
* API-Key: aus Sonarr
* Sync Level: `Full Sync`
* Tags: leer lassen, solange du keine getrennte Indexer-Steuerung brauchst

Falls die UI getrennte Felder statt URL zeigt:

* Host: `sonarr`
* Port: `8989`
* SSL: aus
* URL Base: leer

Dann:

* `Test`
* `Save`

### Radarr als App anbinden

Füge `Radarr` analog hinzu:

* App Server / Base URL / Host: `http://radarr:7878`
* API-Key: aus Radarr
* Sync Level: `Full Sync`
* Tags: leer

Dann:

* `Test`
* `Save`

### Indexer synchronisieren

Nach dem Speichern:

* `Sync App Indexers`

### Kontrolle

Prüfe danach in Sonarr und Radarr unter:

```text
Settings -> Indexers
```

Dort sollten die von Prowlarr synchronisierten Indexer erscheinen.

Wenn dort schon alte manuell gepflegte Indexer vorhanden sind:

* Doppelungen vermeiden
* langfristig nur noch Prowlarr als Quelle benutzen

---

## 7. Bazarr einrichten

Öffne:

```text
https://bazarr.intern.rohrbom.be
```

Bazarr bindest du an Sonarr und Radarr an, nicht an Jellyfin.

### Sonarr anbinden

Gehe zu:

```text
Settings -> Sonarr
```

Setze:

* `Enabled`: an
* Hostname / IP: `sonarr`
* Port: `8989`
* URL Base: leer
* API-Key: aus Sonarr
* SSL: aus

Dann:

* `Test`
* `Save`

### Radarr anbinden

Gehe zu:

```text
Settings -> Radarr
```

Setze:

* `Enabled`: an
* Hostname / IP: `radarr`
* Port: `7878`
* URL Base: leer
* API-Key: aus Radarr
* SSL: aus

Dann:

* `Test`
* `Save`

### Subtitles-Grundeinstellungen

Gehe zu:

```text
Settings -> Subtitles
```

Empfohlen:

* `Subtitle Folder`: `Alongside Media File`
* gewünschte Untertitelsprachen auswählen

### Path Mappings

In diesem Setup normalerweise **keine Path Mappings** anlegen.

Grund:

* Sonarr, Radarr und Bazarr sehen dieselben Containerpfade
* Serien liegen unter `/data/media/shows`
* Filme liegen unter `/data/media/movies`

### Warten auf die erste Synchronisation

Nach dem Speichern braucht Bazarr etwas Zeit, um Serien und Filme aus Sonarr/Radarr einzulesen.

---

## 8. Jellyfin einrichten

Öffne:

```text
https://jellyfin.intern.rohrbom.be
```

### Setup Wizard

Lege zuerst deinen Admin-Benutzer an.

### Bibliotheken anlegen

Lege mindestens diese Libraries an:

* Typ `Movies`
  Pfad: `/data/media/movies`
* Typ `Shows`
  Pfad: `/data/media/shows`

Wichtig:

* **nicht** `/data/torrents/...` als Library einbinden
* **nicht** `/data` als gemischte Gesamtbibliothek einbinden

### Bibliotheken später verwalten

Falls du den Wizard übersprungen hast:

```text
Dashboard -> Libraries
```

Dort kannst du die Libraries jederzeit anlegen oder korrigieren.

### Scan anstoßen

Nach dem Anlegen:

* einmal `Scan All Libraries` ausführen

### Für Seerr wichtig

Das Jellyfin-Admin-Konto brauchst du anschließend für die erste Seerr-Einrichtung.

---

## 9. Seerr einrichten

Öffne:

```text
https://seerr.intern.rohrbom.be
```

Seerr ist hier technisch Jellyseerr.

### General / Application URL

Setze unter den allgemeinen Einstellungen:

* `Application URL`: `https://seerr.intern.rohrbom.be`

### Jellyfin anbinden

Wähle als Mediaserver `Jellyfin`.

Interne Verbindung:

* Internal URL: `http://jellyfin:8096`

Externe URL für Browser-Links:

* External URL: `https://jellyfin.intern.rohrbom.be`

Dann:

* mit dem Jellyfin-Admin-Konto anmelden
* gewünschte Libraries auswählen
* `Sync Libraries` ausführen
* beim ersten Einrichten zusätzlich einen manuellen kompletten Library-Scan anstoßen

### Radarr anbinden

Gehe zu:

```text
Settings -> Services
```

Füge einen Radarr-Server hinzu.

Nutze intern:

* Host / URL: `radarr` oder `http://radarr:7878`
* Port: `7878`, falls getrennt abgefragt
* SSL: aus
* URL Base: leer
* API-Key: aus Radarr
* `Default Server`: an
* `4K Server`: aus
* Root Folder: `/data/media/movies`
* `Enable Scan`: an
* `Enable Automatic Search`: an

Zusätzlich:

* ein bestehendes Quality Profile auswählen
* das gewünschte Minimum Availability auswählen

Wenn ein Feld `External URL` vorhanden ist, setze:

```text
https://radarr.intern.rohrbom.be
```

### Sonarr anbinden

Füge Sonarr analog hinzu:

* Host / URL: `sonarr` oder `http://sonarr:8989`
* Port: `8989`
* SSL: aus
* URL Base: leer
* API-Key: aus Sonarr
* `Default Server`: an
* `4K Server`: aus
* Root Folder: `/data/media/shows`
* `Enable Scan`: an
* `Enable Automatic Search`: an

Wenn ein Feld `External URL` vorhanden ist, setze:

```text
https://sonarr.intern.rohrbom.be
```

### Wichtig für dieses Setup

Da du nur **eine** Sonarr- und **eine** Radarr-Instanz hast:

* jeweils genau einen Default-Server setzen
* **keine** 4K-Server markieren

---

## 10. Abschlussprüfung

Wenn alles eingerichtet ist, sollte dieser Ablauf funktionieren:

1. Anfrage in Seerr anlegen oder Film direkt in Radarr hinzufügen.
2. Radarr nutzt die von Prowlarr synchronisierten Indexer.
3. Radarr schickt den Download an qBittorrent mit Kategorie `radarr`.
4. qBittorrent lädt nach `/data/torrents/complete/radarr`.
5. Radarr importiert nach `/data/media/movies`.
6. Jellyfin sieht den Film nach Library-Scan.
7. Bazarr sieht den Film über Radarr und kann Untertitel dazu verwalten.

Für Serien entsprechend:

1. Serie in Sonarr hinzufügen.
2. Sonarr nutzt die von Prowlarr synchronisierten Indexer.
3. Sonarr schickt den Download an qBittorrent mit Kategorie `sonarr`.
4. qBittorrent lädt nach `/data/torrents/complete/sonarr`.
5. Sonarr importiert nach `/data/media/shows`.
6. Jellyfin sieht die Serie nach Scan.
7. Bazarr sieht die Serie über Sonarr.

---

## 11. Typische Fehler

### Falsche interne URL

Falsch:

* `https://radarr.intern.rohrbom.be`
* `https://sonarr.intern.rohrbom.be`
* `localhost`
* `127.0.0.1`

Richtig für interne Verbindungen:

* `radarr` / `http://radarr:7878`
* `sonarr` / `http://sonarr:8989`
* `jellyfin` / `http://jellyfin:8096`
* `qbittorrent` / `http://qbittorrent:8080`

### Falsche Downloadpfade

Falsch:

* qBittorrent speichert direkt in `/data/media/...`

Richtig:

* qBittorrent lädt nur nach `/data/torrents/...`
* Sonarr/Radarr importieren anschließend in `/data/media/...`

### Unnötige Path Mappings

In diesem Stack sind Path Mappings normalerweise nicht nötig, weil die Containerpfade konsistent sind.

### Manuelle Indexer zusätzlich zu Prowlarr

Wenn du Prowlarr als zentrale Quelle nutzt, dann Sonarr/Radarr-Indexer nicht zusätzlich separat pflegen.

---

## 12. Kurzreferenz

### Browserzugriff

* Prowlarr: `https://prowlarr.intern.rohrbom.be`
* Sonarr: `https://sonarr.intern.rohrbom.be`
* Radarr: `https://radarr.intern.rohrbom.be`
* Bazarr: `https://bazarr.intern.rohrbom.be`
* Jellyfin: `https://jellyfin.intern.rohrbom.be`
* Seerr: `https://seerr.intern.rohrbom.be`
* qBittorrent: Port-Forward auf `http://127.0.0.1:8080`

### Interne Backend-Ziele

* qBittorrent: `qbittorrent:8080`
* Prowlarr: `prowlarr:9696`
* Sonarr: `sonarr:8989`
* Radarr: `radarr:7878`
* Bazarr: `bazarr:6767`
* Jellyfin: `jellyfin:8096`
* Seerr: `seerr:5055`
