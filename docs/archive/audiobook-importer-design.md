# Design: Automatischer Audiobook-Importer

## Status

Entwurf für einen eigenständigen Dienst, der in einem separaten Repository entwickelt, als Container-Image veröffentlicht und anschließend über Kubernetes betrieben werden kann.

---

## 1. Ziel

Der Audiobook-Importer verarbeitet Hörbuchdateien aus einem Eingangsverzeichnis und überführt sie in eine konsistente Bibliotheksstruktur.

Der Dienst soll:

* verschachtelte und flache Importstrukturen akzeptieren
* Hörbücher anhand eingebetteter Metadaten erkennen
* mehrteilige Hörbücher zusammenhalten
* Dateien deterministisch benennen und einsortieren
* Cover und relevante Begleitdateien übernehmen
* Duplikate und Kollisionen sicher behandeln
* unklare oder fehlerhafte Importe in Quarantäne verschieben
* nach erfolgreichem Import optional einen Jellyfin-Scan auslösen
* ohne eigene Benutzeroberfläche und ohne eigene Medienbibliothek auskommen

Jellyfin bleibt das System für Bibliotheksanzeige und Konsum. Der Importer ist ausschließlich für Dateimanagement zuständig.

---

## 2. Nicht-Ziele

Der Dienst ist nicht vorgesehen als:

* Audiobook-Player
* Benutzer- oder Fortschrittsverwaltung
* Download-Client
* Indexer-Manager
* Ersatz für Jellyfin
* allgemeiner Musik-Organizer
* vollautomatischer Metadaten-Scraper mit ungeprüften externen Treffern
* DRM-Entferner

Das MVP soll keine Dateien anhand unsicherer Suchergebnisse automatisch einem fremden Buch zuordnen.

---

## 3. Zielablauf

```text
Beliebige Importstruktur
        |
        v
Dateien vollständig und stabil?
        |
        v
Format und Metadaten analysieren
        |
        +---- unklar/fehlerhaft ----> Quarantäne + Bericht
        |
        v
Hörbuch und Dateireihenfolge bestimmen
        |
        v
In temporäres Zielverzeichnis kopieren
        |
        v
Kopie und Metadaten verifizieren
        |
        v
Atomar in Bibliothek übernehmen
        |
        v
Quelle entfernen oder archivieren
        |
        v
Optional Jellyfin-Scan auslösen
```

---

## 4. Verzeichnisvertrag

Der Dienst arbeitet mit vier getrennten Bereichen:

```text
/import
/library
/work
/quarantine
```

### `/import`

Überwachtes Eingangsverzeichnis.

Es darf:

* einzelne Dateien
* einen Ordner pro Hörbuch
* Collection-Ordner
* Format-Unterordner
* beliebig tiefe Verzeichnisstrukturen

enthalten.

Der Importer darf Quelldateien erst entfernen, nachdem der Zielimport vollständig verifiziert wurde.

### `/library`

Finale, von Jellyfin gelesene Bibliothek.

Empfohlene Struktur:

```text
/library/
└── Autor/
    └── [Serie 01 - ]Titel/
        ├── 01 - Titel.m4b
        ├── 02 - Titel.m4b
        ├── cover.jpg
        └── metadata.json
```

Für einteilige Hörbücher:

```text
/library/
└── Autor/
    └── Titel/
        ├── Titel.m4b
        └── cover.jpg
```

### `/work`

Temporärer Arbeitsbereich für:

* Transaktionsverzeichnisse
* Metadatenanalyse
* Cover-Extraktion
* Prüfsummen
* optionale Konvertierung

`/work` darf nach einem Neustart bereinigt oder erneut verarbeitet werden.

### `/quarantine`

Ziel für Importe, die nicht sicher verarbeitet werden können.

Beispiel:

```text
/quarantine/
└── 2026-06-23T194500Z-invalid-metadata/
    ├── original/
    └── import-report.json
```

Die Originaldateien und ein maschinenlesbarer Fehlerbericht müssen erhalten bleiben.

---

## 5. Unterstützte Formate

MVP:

* M4B
* M4A
* MP3
* FLAC

Optional später:

* OGG
* OPUS
* AAC

Nicht unterstützte Dateien dürfen nicht stillschweigend gelöscht werden.

Relevante Begleitdateien:

* `cover.jpg`
* `cover.png`
* `folder.jpg`
* `metadata.json`
* `metadata.opf`
* Kapiteldateien, sofern sie einem unterstützten Format eindeutig zugeordnet werden können

Andere Dateien werden entweder konfigurierbar übernommen oder im Importbericht als ignoriert dokumentiert.

---

## 6. Metadatenmodell

Der Importer verwendet ein internes, formatunabhängiges Modell:

```yaml
title: string
authors:
  - string
narrators:
  - string
series: string | null
series_index: number | null
year: integer | null
language: string | null
isbn: string | null
asin: string | null
description: string | null
publisher: string | null
genres:
  - string
part_number: integer | null
part_total: integer | null
disc_number: integer | null
track_number: integer | null
duration_seconds: number
source_files:
  - string
```

### Priorität der Metadatenquellen

1. eingebettete Audio-Tags
2. vorhandene lokale Sidecar-Dateien
3. konsistente Tags anderer Dateien derselben Gruppe
4. Verzeichnis- und Dateinamen als Fallback
5. optional später: explizit aktivierte externe Metadatenanbieter

Externe Suchergebnisse dürfen ohne ausreichend eindeutige Kennung wie ISBN oder ASIN keine bestehende Identität überschreiben.

---

## 7. Erkennung eines Hörbuchs

### Kandidatengruppe

Der Importer bildet zunächst Kandidatengruppen:

* Ein einzelner M4B-Container ist standardmäßig ein Hörbuch.
* Mehrere Audiodateien in einem Blattverzeichnis bilden eine Kandidatengruppe.
* Dateien in tieferen Unterverzeichnissen werden rekursiv untersucht.
* Lose Dateien in einem gemeinsamen Collection-Ordner werden anhand normalisierter Tags gruppiert.

### Gruppierungsschlüssel

Bevorzugt:

```text
normalisierter Autor + normalisierter Titel + normalisierte Serie
```

Fallback:

```text
Quellverzeichnis + gemeinsamer Dateinamenspräfix
```

Eine Gruppe wird in Quarantäne verschoben, wenn Dateien widersprüchliche Titel oder Autoren besitzen und keine sichere Auflösung möglich ist.

### Reihenfolge mehrteiliger Hörbücher

Priorität:

1. `disc_number`
2. `part_number`
3. `track_number`
4. numerischer Dateinamenspräfix
5. lexikografischer Dateiname

Wenn keine eindeutige Reihenfolge bestimmbar ist, darf der Import nicht stillschweigend mit einer zufälligen Reihenfolge abgeschlossen werden.

---

## 8. Normalisierung und Zielpfade

Zielpfade müssen deterministisch und plattformverträglich erzeugt werden.

### Standardtemplate

```text
{author}/{series_prefix}{title}
```

Mit Serie:

```text
{author}/{series} {series_index:02} - {title}
```

Ohne Serie:

```text
{author}/{title}
```

### Dateinamen

Einteilig:

```text
{title}.{extension}
```

Mehrteilig:

```text
{part_number:02} - {title}.{extension}
```

### Bereinigung

* führende und abschließende Leerzeichen entfernen
* mehrfache Leerzeichen reduzieren
* Pfadtrenner ersetzen
* Steuerzeichen entfernen
* reservierte Namen vermeiden
* Pfad- und Dateinamenlängen begrenzen
* Unicode normalisieren

Die ursprünglichen Namen bleiben im Importbericht erhalten.

---

## 9. Importtransaktion

Ein Import darf niemals direkt in das endgültige Zielverzeichnis schreiben.

### Ablauf

1. Kandidatengruppe sperren.
2. Prüfen, dass alle Dateien stabil sind.
3. Metadaten lesen und validieren.
4. Zielpfad bestimmen.
5. Transaktionsverzeichnis unter `/work` anlegen.
6. Dateien in das Transaktionsverzeichnis kopieren.
7. Größe und optional Prüfsumme vergleichen.
8. Metadaten und Abspielbarkeit der Kopien erneut prüfen.
9. Cover und Sidecars erzeugen oder übernehmen.
10. Transaktionsverzeichnis atomar in `/library` verschieben.
11. Quelldateien entfernen oder archivieren.
12. Ergebnis protokollieren.
13. Optional Jellyfin benachrichtigen.

Wenn `/work` und `/library` auf demselben Dateisystem liegen, soll die finale Übernahme per atomarem `rename` erfolgen.

### Stabilitätsprüfung

Eine Datei gilt erst als stabil, wenn:

* Größe und Änderungszeit über ein konfigurierbares Zeitfenster unverändert bleiben
* sie nicht mehr unter einem temporären Suffix wie `.partial`, `.tmp` oder `.uploading` vorliegt
* sie lesbar ist
* der Medienparser sie vollständig öffnen kann

---

## 10. Duplikate und Kollisionen

Der Dienst muss idempotent sein. Derselbe Import darf nicht zu beliebig vielen Kopien führen.

### Identifikation

Empfohlene Reihenfolge:

1. Prüfsumme der Audiodatei
2. eindeutige Kennung wie ASIN oder ISBN
3. normalisierte Kombination aus Autor, Titel, Dauer und Dateigröße

### Verhalten

Konfigurierbare Modi:

* `skip`: vorhandene identische Dateien überspringen
* `merge`: zusätzliche Teile oder Formate ergänzen
* `replace`: nur bei expliziter Freigabe ersetzen
* `quarantine`: jede unklare Kollision zur Prüfung ablegen

Standard sollte `quarantine` sein.

Bestehende Bibliotheksdateien dürfen niemals aufgrund einer bloßen Titelähnlichkeit überschrieben werden.

---

## 11. Cover-Verarbeitung

Priorität:

1. explizite Coverdatei im Quellordner
2. eingebettetes Cover
3. lokales Sidecar-Cover
4. kein Cover

Das gewählte Cover wird normalisiert als:

```text
cover.jpg
```

Eine Konvertierung nach JPEG ist optional. Das Originalcover kann zusätzlich erhalten bleiben.

Im MVP erfolgt kein automatischer Download fremder Cover ohne eindeutige Medienkennung.

---

## 12. Umgang mit der Quelle

Unterstützte Betriebsarten:

### `move`

Nach erfolgreicher Verifikation werden die Quelldateien entfernt.

Geeignet für ein echtes Drop-Verzeichnis.

### `copy`

Die Quelle bleibt erhalten.

Geeignet für Tests oder wenn der Importordner selbst ein Archiv ist.

### `archive`

Die Quelle wird nach erfolgreichem Import in ein Archivverzeichnis verschoben.

Empfohlener Standard für die erste produktive Phase:

```text
archive
```

Nach ausreichend Betriebserfahrung kann auf `move` umgestellt werden.

---

## 13. Prozessmodell

Der Dienst kombiniert zwei Mechanismen:

### File-Watcher

Reagiert schnell auf neu angelegte oder verschobene Dateien und Verzeichnisse.

### Periodischer Reconcile

Durchsucht `/import` regelmäßig vollständig.

Der Reconcile ist notwendig, weil Dateisystem-Events verloren gehen können oder ein kompletter Ordner atomar in das Importverzeichnis verschoben werden kann.

Beispiel:

```text
Reconcile-Intervall: 5 Minuten
Stabilitätsfenster: 60 Sekunden
```

Pro Kandidatengruppe darf immer nur ein Importprozess aktiv sein.

---

## 14. Persistenter Zustand

Der Dienst sollte möglichst wenig eigenen Zustand benötigen.

MVP:

* transaktionale Zustandsdateien unter `/work`
* `import-report.json` pro Import
* strukturierte Logs

Optional später:

* SQLite-Datenbank für Importhistorie
* Prüfsummenindex
* Retry-Zähler
* Jellyfin-Synchronisationsstatus

Die Bibliothek selbst bleibt die maßgebliche Quelle für erfolgreich importierte Dateien.

---

## 15. Konfiguration

Konfiguration über Umgebungsvariablen und optional eine YAML-Datei.

Beispiel:

```yaml
paths:
  import: /import
  library: /library
  work: /work
  quarantine: /quarantine
  archive: /archive

import:
  source_mode: archive
  stability_seconds: 60
  reconcile_interval_seconds: 300
  checksum: sha256
  collision_policy: quarantine

naming:
  directory_template: "{author}/{series_prefix}{title}"
  single_file_template: "{title}"
  multi_file_template: "{part_number:02} - {title}"

sidecars:
  write_metadata_json: true
  extract_cover: true
  copy_unknown_files: false

jellyfin:
  enabled: false
  url: http://jellyfin:8096
  library_id: null
  api_key_file: /run/secrets/jellyfin-api-key
```

Secrets dürfen nicht direkt in der normalen Konfigurationsdatei oder in Logs erscheinen.

---

## 16. Jellyfin-Integration

Die Integration ist optional. Der Import funktioniert auch ohne erreichbares Jellyfin.

Nach erfolgreichem Import kann der Dienst:

* einen vollständigen Bibliotheksscan anfordern
* bevorzugt nur die betroffene Bibliothek aktualisieren, sofern die API dies unterstützt
* mehrere Importe innerhalb eines Zeitfensters zu einer Scan-Anforderung bündeln

Ein fehlgeschlagener Jellyfin-Aufruf darf einen bereits erfolgreichen Dateiimport nicht zurückrollen.

Der Scan wird separat protokolliert und mit Backoff erneut versucht.

---

## 17. API und Health Endpoints

Eine Benutzeroberfläche ist nicht erforderlich. Eine kleine HTTP-API erleichtert den Containerbetrieb.

Empfohlene Endpoints:

```text
GET  /health/live
GET  /health/ready
GET  /metrics
GET  /api/v1/status
POST /api/v1/reconcile
POST /api/v1/import
```

### Liveness

Der Prozess läuft und interne Worker reagieren.

### Readiness

* Importverzeichnis ist lesbar
* Bibliothek ist beschreibbar
* Arbeits- und Quarantäneverzeichnis sind beschreibbar
* Konfiguration ist gültig

Jellyfin darf keine Readiness-Voraussetzung sein.

---

## 18. Observability

### Logging

Strukturierte JSON-Logs nach stdout.

Pflichtfelder:

```text
timestamp
level
event
import_id
source_path
target_path
duration_ms
result
error_code
```

Keine vollständigen API-Keys oder vertraulichen Header protokollieren.

### Metriken

Empfohlene Prometheus-Metriken:

```text
audiobook_importer_imports_total{result="success|failed|quarantined|duplicate"}
audiobook_importer_files_total{format="m4b|mp3|flac|m4a"}
audiobook_importer_import_duration_seconds
audiobook_importer_pending_groups
audiobook_importer_quarantine_items
audiobook_importer_jellyfin_scans_total{result="success|failed"}
```

---

## 19. Fehlerklassen

Maschinenlesbare Fehlercodes:

```text
UNSUPPORTED_FORMAT
FILE_NOT_STABLE
MEDIA_CORRUPT
MISSING_TITLE
MISSING_AUTHOR
CONFLICTING_METADATA
ORDER_UNDETERMINED
DUPLICATE
TARGET_COLLISION
COPY_FAILED
VERIFICATION_FAILED
PERMISSION_DENIED
JELLYFIN_SCAN_FAILED
```

Fehler vor Abschluss der Zieltransaktion führen zur Quarantäne oder zu einem Retry. Fehler beim nachgelagerten Jellyfin-Scan beeinflussen den Importstatus nicht.

---

## 20. Sicherheit

Der Container soll:

* als nicht privilegierter Benutzer laufen
* eine feste UID/GID unterstützen
* keine Shell oder externen Netzwerkzugriffe benötigen, sofern Jellyfin und Metadatenanbieter deaktiviert sind
* ein read-only Root-Dateisystem ermöglichen
* keine Linux-Capabilities benötigen
* temporäre Daten ausschließlich unter `/work` und `/tmp` schreiben
* Secrets nur über Dateien oder Secret-Mounts erhalten

Empfohlener Kubernetes Security Context:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
```

Container:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL
```

---

## 21. Container-Image

Das Image sollte:

* reproduzierbar gebaut werden
* eine feste Runtime-Version verwenden
* als Multi-Arch-Image für `linux/amd64` und optional `linux/arm64` erscheinen
* Versions- und Commit-Metadaten als OCI-Labels enthalten
* einen Healthcheck bereitstellen
* keine Compiler oder Build-Werkzeuge im Runtime-Layer enthalten

Sinnvolle Werkzeuge beziehungsweise Bibliotheken:

* FFmpeg/ffprobe zur Medienanalyse
* eine Tag-Bibliothek für MP3, MP4/M4B und FLAC
* ein Dateisystem-Watcher

Die konkrete Programmiersprache ist nicht Teil dieses Designs. Python, Go oder Rust sind geeignet, solange Medienparser und Transaktionsverhalten sauber testbar sind.

---

## 22. GitHub-Workflow

Der Build-Workflow im Dienst-Repository soll:

1. Linting ausführen.
2. Unit-Tests ausführen.
3. Integrationstests mit temporären Verzeichnissen ausführen.
4. Container-Image bauen.
5. Image als unprivilegierten Container testen.
6. Image auf bekannte Schwachstellen scannen.
7. Software Bill of Materials erzeugen.
8. Image nach GHCR pushen.
9. Nach Möglichkeit das Image signieren.

### Tags

Für Releases:

```text
ghcr.io/<owner>/audiobook-importer:1.2.3
ghcr.io/<owner>/audiobook-importer:1.2
ghcr.io/<owner>/audiobook-importer:1
ghcr.io/<owner>/audiobook-importer:latest
```

Für den Hauptbranch optional:

```text
ghcr.io/<owner>/audiobook-importer:main
ghcr.io/<owner>/audiobook-importer:sha-<commit>
```

Das Kubernetes-Manifest sollte eine feste Version oder einen Image-Digest verwenden, nicht ausschließlich `latest`.

---

## 23. Teststrategie

### Unit-Tests

* Tag-Normalisierung
* Pfadbereinigung
* Template-Auflösung
* Gruppierung
* Dateireihenfolge
* Kollisionserkennung
* Fehlerklassifikation

### Integrationstests

* einzelnes M4B
* mehrteiliges MP3-Hörbuch
* verschachtelte Collection
* lose Dateien in einem flachen Ordner
* Cover als Sidecar
* eingebettetes Cover
* widersprüchliche Tags
* fehlender Autor oder Titel
* beschädigte Datei
* identischer erneuter Import
* Dateikollision mit anderem Inhalt
* Prozessabbruch während der Kopie
* Neustart mit bestehender Transaktion unter `/work`

### End-to-End-Test

1. Testhörbuch nach `/import` kopieren.
2. Importabschluss abwarten.
3. Zielstruktur und Metadaten prüfen.
4. Quelle entsprechend dem Modus prüfen.
5. Jellyfin-Scan simulieren oder gegen eine Testinstanz ausführen.

Testmedien müssen entweder selbst erzeugt oder lizenzrechtlich für das Repository geeignet sein.

---

## 24. Kubernetes-Betriebsmodell

Der Dienst läuft als einzelnes Deployment mit einer Replik.

Mehrere Replikate sind erst sinnvoll, wenn ein verteiltes Locking implementiert wurde.

Benötigte Volumes:

```text
/config       kleine persistente Konfiguration, optional
/import       gemeinsamer Medienspeicher
/library      gemeinsamer Medienspeicher
/work         lokaler oder gemeinsamer Arbeitsbereich
/quarantine   gemeinsamer Medienspeicher
/archive      gemeinsamer Medienspeicher, optional
```

Wenn Import, Library, Quarantäne und Archiv auf demselben Dateisystem liegen, sind atomare Verschiebeoperationen und spätere Hardlink-Optimierungen möglich.

### Ressourcen als Startwert

```yaml
resources:
  requests:
    cpu: 50m
    memory: 128Mi
  limits:
    cpu: "2"
    memory: 1Gi
```

Die CPU-Last steigt erheblich, sobald Konvertierung oder Audioanalyse über reine Metadaten hinaus aktiviert wird.

---

## 25. Beispiel für den bestehenden Media-Stack

Host auf der Media-Node:

```text
/srv/media-hdd/import/audiobooks
/srv/media-hdd/media/audiobooks
/srv/media-hdd/work/audiobook-importer
/srv/media-hdd/quarantine/audiobooks
/srv/media-hdd/archive/audiobooks
```

Container:

```text
/import
/library
/work
/quarantine
/archive
```

Jellyfin erhält ausschließlich:

```text
/data/media/audiobooks
```

Der Importer und Jellyfin teilen damit die finalen Dateien, aber nicht die Verantwortung für deren Organisation.

---

## 26. MVP

Das erste produktive Release umfasst:

* M4B, M4A, MP3 und FLAC
* rekursive Verarbeitung
* eingebettete Metadaten
* Gruppierung mehrteiliger Hörbücher
* deterministische Zielpfade
* Cover-Übernahme oder -Extraktion
* transaktionales Kopieren und Verifizieren
* Quarantäne mit JSON-Bericht
* File-Watcher plus Reconcile
* strukturierte Logs
* Health Endpoints
* optionalen Jellyfin-Scan
* unprivilegiertes Container-Image

Nicht Teil des MVP:

* Web-UI
* externe Metadatensuche
* Audio-Konvertierung
* Zusammenfügen mehrerer Dateien zu einem M4B
* verteilte Verarbeitung mit mehreren Replikaten

---

## 27. Spätere Erweiterungen

* externe Metadatenprovider mit Confidence Score
* manuelle Freigabe-API für Quarantänefälle
* Zusammenführen mehrteiliger Audiodateien
* Kapitelgenerierung
* Lautstärkeanalyse
* automatische Formatkonvertierung
* Benachrichtigungen über ntfy
* OpenTelemetry-Traces
* eingeschränkte Verwaltungsoberfläche
* SQLite-Importhistorie

---

## 28. Abnahmekriterien

Das MVP gilt als einsatzbereit, wenn:

* ein verschachtelter Collection-Ordner vollständig erkannt wird
* einteilige und mehrteilige Hörbücher korrekt einsortiert werden
* ein abgebrochener Import keine halbfertigen Bibliotheksordner hinterlässt
* ein identischer erneuter Import kein Duplikat erzeugt
* unklare Metadaten nicht zu einer willkürlichen Zuordnung führen
* jede Quarantäneentscheidung einen verständlichen Bericht erzeugt
* ein Jellyfin-Ausfall den Dateiimport nicht verhindert
* der Container ohne Root-Rechte und ohne zusätzliche Capabilities läuft
* Neustarts keine bereits erfolgreichen Importe beschädigen

---

## 29. Zentrale Architekturentscheidungen

1. **Dateisicherheit vor Automatisierungsgrad:** Unsichere Fälle werden nicht geraten, sondern in Quarantäne verschoben.
2. **Jellyfin bleibt Consumer:** Der Importer verwaltet Dateien, nicht Benutzer oder Wiedergabestatus.
3. **Lokale Metadaten zuerst:** Eingebettete Tags und Sidecars haben Vorrang vor externen Suchergebnissen.
4. **Transaktionale Übernahme:** Die Bibliothek sieht nur vollständig verifizierte Importe.
5. **Idempotenz:** Wiederholte Events und Neustarts dürfen keine Duplikate erzeugen.
6. **Watcher plus Reconcile:** Dateisystem-Events allein gelten nicht als zuverlässig genug.
7. **Eine Replik im MVP:** Parallele Replikate benötigen ein späteres Locking-Konzept.
