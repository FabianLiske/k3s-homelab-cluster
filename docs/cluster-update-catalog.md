# Prüfkatalog für Cluster-Updates

[`update-catalog.yaml`](../update-catalog.yaml) enthält die explizite Eingabeliste,
geprüfte feste Quellen und fertige Leseabfragen für den Hermes-Update-Checker.
Der Status ist `approved_for_checker`. Der gespeicherte Prompt von
`Daily Cluster Update Check` (`18e7f87d24fa`) entspricht
[`hermes-cluster-update-cron-prompt.md`](hermes-cluster-update-cron-prompt.md).
Der Job läuft täglich um 08:00 Uhr und liefert seinen Bericht nach WhatsApp.
Flux wertet den Katalog nicht aus; der Cron-Agent verwendet ihn ausdrücklich.

Nur dieser Job nutzt `reasoning_effort: low` und die Provider-Route
`custom:cluster-update-check`. Sie verwendet denselben LiteLLM-Endpunkt, Zugang
und Modellnamen wie der normale Chat, ergänzt aber ausdrücklich
`extra_body.chat_template_kwargs.reasoning_effort: low`. LiteLLM verwirft bei
diesem Modellnamen den normalen OpenAI-Parameter; das lokale Qwen-Template
verwendet ohne Template-Vorgabe standardmäßig `xhigh`. Die Weiterleitung der
Template-Vorgabe wurde mit einem simulierten HTTP-Client ohne Modellgenerierung
geprüft. Die normale Hermes-Chat-Konfiguration bleibt unverändert.

Die Testläufe vom 2026-11-04 wurden auf Betreiberwunsch abgebrochen. Der zweite
Lauf erzeugte acht gesperrte Tickets für sechs Dienste. Diese Karten bleiben
erhalten. Nach der Umstellung auf den knappen Ablauf wurde kein neuer Run gestartet.
Der Prompt verbietet alte Prüfskripte und ungeprüfte Scratch-Daten.

## Zuständigkeit und Update-Einheiten

`category` unterscheidet vier Gruppen: `application` (Anwendungen),
`custom_image` (eigene Images), `platform` (Plattformdienste) und `cluster`
(Cluster-Komponenten). Davon unabhängig beschreibt `management`, ob und wie die
Update-Einheit geprüft wird.

Zusätzlich benennt **`update_track` ausdrücklich den vorgesehenen Update-Ablauf**:

| `update_track` | Bedeutung |
| --- | --- |
| `routine` | Reguläres Update über die Repo-Manifeste und einen Flux-Rollout im laufenden Cluster. |
| `coordinated` | Gesondert abgestimmtes Update mehrerer Komponenten oder kritischer Plattformdienste. |
| `cluster_maintenance` | Eigener Cluster-/Netzwerk-Wartungsablauf, gegebenenfalls mit Node-Arbeiten. |
| `external` | Eigener Build-Workflow beziehungsweise ausdrücklich ausgeschlossene temporäre Ressource. |
| `bundled` | Wird über die übergeordnete Update-Einheit aktualisiert. |

Alle Einträge tragen dieses Feld explizit. Normale Anwendungs- und
Monitoring-Updates sind als `routine` gekennzeichnet. Immich und das Intel/XPU-
Inference-Image sowie cert-manager, ingress-nginx, Longhorn, MetalLB, Flux und
der Intel-GPU-Plugin werden zunächst `coordinated` zugeordnet. Für diese Einträge
steht der konkrete Grund direkt in `update_track_reason`.

`routine` bezeichnet den üblichen Umsetzungsweg, keine pauschale Freigabe jeder
neuen Version und keine Zusage eines unterbrechungsfreien Dienstes. Vor einem
konkreten Update bleiben Release-Hinweise, Image-Variante und Kompatibilität zu
prüfen. Eine erforderliche Datenbank-Migration, ein Major-Wechsel oder ein
Wechsel des bisherigen Release-Kanals hebt das konkrete Ticket in einen
gesondert zu planenden Ablauf. Normale kompatible Updates von Datenbank-Images
sind damit nicht pauschal vom Routinepfad ausgeschlossen.

Der Checker soll `update_track` in jedes Ticket und den Bericht übernehmen.
Auch Routine-Tickets werden gesperrt angelegt und benötigen das ausdrückliche
Go. Die anderen Prüfaufträge bleiben im Katalog und werden entsprechend ihres
Ablaufs getrennt ausgewiesen; `coordinated` bedeutet keinen Ausschluss von der
Update-Suche.

| `management` | Bedeutung |
| --- | --- |
| `check` | Diese Einheit prüfen und belegte Updates als gesperrte Tickets vorschlagen. |
| `external` | Bewusst ausgeschlossen; eigener Entwicklungs- oder Build-Workflow. |
| `bundled` | Gehört zur Einheit aus `managed_by`; kein eigenständiges Update-Ticket. |

Nicht aufgeführte Komponenten werden als Kataloglücke gemeldet und übersprungen.
Eine neue Datei oder ein unbekanntes Live-Image erweitert den Prüfauftrag nicht
automatisch. Der Katalog erlaubt Prüfungen, keine Änderungen oder Rollouts.

Die sechs aktuell ausgeschlossenen eigenen Images stehen einzeln im Katalog:
Image Compressor, Kochen, Mampftracker, UniFi MCP, Pi OLED und Telegraf Custom.
Die Zuordnung folgt den konkreten Images in den aktiven Manifesten, keinem
pauschalen Ausschluss von GHCR. Bei neuen Fremdkomponenten innerhalb dieser
Dienste muss die Zuständigkeit ausdrücklich pro Komponente aufgeteilt werden.

Zusätzlich ist der bereits abgeschlossene einzelne Diagnose-Pod `netprobe-wk-1`
als temporäre Plattform-Ressource ausdrücklich vom Update-Auftrag ausgeschlossen.

## Offene Tickets schließen weitere Prüfungen aus

Vor Quellenzugriffen wird das Board `cluster-updates` geprüft. Solange irgendeine
Karte einer Komponente weder `done` noch `archived` ist, wird der gesamte Dienst
übersprungen, einschließlich seiner übrigen Images und Abhängigkeiten. Das gilt
auch für `blocked`, `running`, `scheduled` und `review`. Es werden weder neuere
Versionen gesucht noch weitere Karten oder Erweiterungen für diesen Dienst erzeugt.
Der Board-Zustand ist maßgeblich, unabhängig von Datum, Katalog-Hash oder Journal.

Die Zuordnung erfolgt über `cluster-update:<component-id>:` im Idempotenzschlüssel
oder die erste Body-Zeile `component_id: <id>`. Die acht vorhandenen Karten haben
bereits zuordenbare Schlüssel und Legacy-Zeilen `- Komponente: <id>`. Da die
aktuelle CLI-Liste den Schlüssel nicht ausgibt, wertet die fertige Abfrage
zusätzlich diese alten Body-Zeilen aus. `open_update_tasks` und `open_component_tasks`
liefern nur kleine Metadaten, keine vollständigen Bodies. Die fertige Abfrage
`component_context_command` prüft den Gate vor jeder neuen Komponente erneut.

Nach dem ersten neuen gesperrten Ticket wird ebenfalls zum nächsten Dienst
gewechselt. Weitere Images dieses Dienstes werden bis zur Erledigung der Karte
zurückgestellt und nicht als bereits vollständig geprüft ausgegeben.

## Quellen und Versionen

- `path` und `images[].manifests` zeigen auf die aktiven lokalen Ressourcen.
  Init-Container und Datenbanken sind eingeschlossen. Archivierte Ressourcen,
  nicht eingebundene Test-Jobs und das unbenutzte qBittorrent-Backup sind nicht
  Teil des Katalogs. Die InfluxDB-Initialisierungs-Jobs sind InfluxDB zugeordnet.
  Separat installierte Cluster-Komponenten ohne Repo-Manifest verwenden
  `live_resources` und benötigen vor einer Umsetzung versionierte Manifeste.
- `images[].repository` bezeichnet das genaue Registry-Repository ohne Tag oder
  Digest. Das ist die Quelle für veröffentlichte Images; ein Upstream-Release
  allein beweist kein verfügbares kompatibles Image dieses Publishers.
- `lookup.sources` und `release_sources` geben die konkreten geprüften Quellen
  einer Einheit an. `sources` enthält deren vollständige URLs, Datenformat,
  Abfragerezept und Prüfzeitpunkt. Umgezogene Projekte verwenden die geprüften
  kanonischen Feed-Adressen. Ein Projektumzug erlaubt keinen automatischen
  Wechsel des Image-Publishers.
- Jedes prüfbare Image verweist zusätzlich auf einen Eintrag in `image_sources`.
  Dort stehen die konkret getestete Tag-URL, der Token-Endpunkt, die Manifest-
  und Config-Blob-URL-Vorlagen sowie die eigenen Release-/Changelog-Quellen.
  Auch PostgreSQL, Redis/Valkey, BusyBox, nginx, Tika, Gotenberg, curl und die
  Flannel-CNI-Images haben eigene Zuordnungen. Die regulären PostgreSQL-Images
  kommen von Docker Hub; das spezielle Immich-Postgres-Image wird über GHCR und
  die Immich-Kompatibilitätsvorgaben geprüft.
- `chart`, `git_source` und `bundle` beschreiben alternative Update-Einheiten.
  Helm-Controller-Images, MetalLB-Unterkomponenten und die generierten
  Flux-Controller werden nicht zusätzlich als unabhängige Images behandelt.
- Aktuelle Tags, Digests und Versionen werden weiterhin aus Manifesten und
  Cluster gelesen. Eine zweite Versionsliste im Katalog würde veralten.
  Bei Helm-Wildcards wie Longhorns `*` zählt zusätzlich die tatsächlich
  installierte Chart-Version.

## Fertige Abfragen, keine Scanner-Entwicklung

`read_commands` enthält gemeinsame fertige Shell-Abfragen mit den bereits
vorhandenen Programmen `curl`, `jq`, `sed` und `awk`. `read_recipe` beziehungsweise
`tags_read_recipe`, `digest_read_recipe` und `manifest_read_recipe` benennen die
zu verwendende Abfrage. `lookup_recipes` erklärt die einzusetzenden `update_*`-
Variablen und die Reihenfolge. Dafür müssen weder Python-Skripte noch zusätzliche
Registry-Clients oder XML-/YAML-Parser installiert oder programmiert werden.

`catalog_access` enthält fertige Abfragen für einzelne Komponenten und
Quelleneinträge. Der Agent liest die gemeinsamen Regeln einmal und danach nur
die benötigten kleinen Abschnitte, statt den vollständigen Katalog oder ganze
Release-Feeds wiederholt in den Kontext zu laden.

Die Abfragen liefern kurze Zusammenfassungen: GitHub-Feeds nur Titel, Zeitstempel
und Release-Links, Helm-Indizes zehn Versionen mit appVersion/Digest und
Registry-Abfragen begrenzte Tag-Listen. Digest-Abfragen lösen Docker Hub korrekt
auf `registry-1.docker.io` auf. Authentifizierung und das besondere Token-Realm
von Stirling PDF sind bereits hinterlegt. Architektur-Übersichten werden auf
Linux/amd64 und Linux/arm64 begrenzt; Image-Layer werden nicht geladen.

Bei `latest` oder anderen verfolgten Kanälen wie PostgreSQL `17` wird zuerst
**genau dieser Tag** geprüft, ohne Tag-Liste: über
`exact_tag_url_template`/`exact_tag_read_recipe` bei Docker Hub oder eine
Manifest-HEAD-Abfrage bei den übrigen Registries. Die direkte Docker-Hub-
Metadatenantwort enthält auch die plattformspezifischen Digests. Ein Vergleich
berücksichtigt dieselbe Architektur beziehungsweise denselben Manifest-Typ.
Ein geänderter Digest genügt als Update-Nachweis; eine historische Rückwärtssuche
nach allen Tags ist nicht nötig. Ein Versionsname aus Labels oder Release-Notes
wird nur bei Bedarf zusätzlich ermittelt. Ein Datenbank-Kanal wie `17` wird
nicht durch das globale `latest` ersetzt.

Bei fest versionierten Images wird bei Bedarf die begrenzte Versionsquelle
gelesen; für Helm dient der konkrete Chart-Index als Ausgangspunkt.
Unveränderte Images benötigen keine Changelog-Recherche. Upstream-Quellen werden
nur für die Suche nach einem passenden Kandidaten oder dessen Bewertung gelesen.
Für Longhorn-Hilfsimages und andere Bundles gilt ausschließlich der Prüfauftrag
der übergeordneten Einheit, kein zusätzlicher vollständiger Image-Scan.

Beim einmaligen Quellencheck am 2026-11-04 lieferten alle 51 prüfbaren
Image-Repositories nichtleere Tag-Listen. Die eingetragenen offiziellen
Release-/Dokumentations-/Chart-Quellen wurden erfolgreich geladen. Die fertigen
Leseabfragen wurden zusätzlich mit repräsentativen Quellen und allen drei
Helm-Indizes geprüft. Stirling PDF liefert beim konfigurierten Registry-Proxy
für Manifest-Abfragen aktuell HTTP 429. Die explizit hinterlegte Docker-Hub-
Metadatenabfrage für denselben Image-Publisher und Tag `latest` liefert dagegen
HTTP 200 mit amd64-/arm64-Digests. Der tägliche Vergleich verwendet diese
Metadatenquelle; der Deployment-Publisher bleibt unverändert.

Laut [Docker-Dokumentation](https://docs.docker.com/docker-hub/usage/pulls/)
zählen Manifest-GETs gegen das Pull-Limit, HEAD-Abfragen dagegen nicht. Das
Herunterladen von Image-Layern ist also keine Voraussetzung dafür, ein Pull-Limit
zu erreichen. Auch Metadatenabfragen bleiben endlich und werden nicht in einer
Fehlerschleife wiederholt.

Pro HTTP-Aufruf gelten fünf Sekunden Verbindungs- und zwanzig Sekunden
Gesamt-Timeout. Es wird keine komplette Registry paginiert. HTTP 401/403/429
beendet die Prüfung dieser Quelle ohne Wiederholung; bei Timeouts/5xx ist
höchstens eine Wiederholung erlaubt. Das Schreiben,
Reparieren oder Installieren von Scannern, Hilfsskripten oder Parsern ist im
täglichen Run ausdrücklich verboten. Ein Fehler stoppt nur die betroffene
Einheit, keinen vollständigen Gesamtscan.

## Cluster-Komponenten

K3s ist ein eigener Prüfauftrag mit dem vorhandenen
[`k3s-rolling-upgrade.md`](k3s-rolling-upgrade.md) als späterem Upgrade-Verfahren.
Die [K3s-Release-Notes](https://docs.k3s.io/release-notes/v1.36.X) dokumentieren auch die
gebündelten Komponentenversionen. Tatsächlich gebündelte Komponenten wie CoreDNS
und containerd werden im K3s-Kontext bewertet; daraus entstehen keine unabhängigen
Updates auf die jeweils neueste Upstream-Version.

Der Live-Abgleich zeigt zusätzlich einen eigenständigen Flannel-DaemonSet im
Namespace `kube-flannel`. Er ist deshalb als eigener Cluster-Prüfauftrag erfasst,
einschließlich seines CNI-Init-Containers. Die vorherige pauschale Zuordnung von
Flannel zum K3s-Bundle war für diesen Cluster unzureichend. Ob die eingebettete
Flannel-Instanz auf den Nodes deaktiviert ist, muss vor Änderungen anhand der
K3s-Konfiguration geprüft werden. Auch kube-vip läuft als eigenständiger
DaemonSet. Für beide fehlen aktive Manifeste in diesem Repo; deren Übernahme ist
eine Voraussetzung für spätere nachvollziehbare GitOps-Updates.

Nur tatsächlich aktivierte Komponenten berücksichtigen. Beispielsweise ist
Traefik im dokumentierten Setup deaktiviert. Für einen später separat
installierten Ersatz muss ein eigener Eintrag ergänzt werden. Sicherheits- und
Kompatibilitätshinweise können weiterhin relevant sein, auch wenn die Umsetzung
über ein K3s-Upgrade erfolgt.

Der [Live-Abgleich](cluster-update-coverage.md) dokumentiert die konkrete
Zuordnung aller derzeit vorhandenen Controller. `runtime_inventory` ordnet die
beobachteten Helm-/Bundle-Images ihrer Einheit zu; es enthält keine zweite
Versionsliste. Neue Images oder Controller müssen weiterhin auf eine passende
Zuständigkeit geprüft werden, auch in bereits bekannten Namespaces.

## Ablauf des Cronjobs

Die explizite Reihenfolge steht unter `check_order`: zuerst 34 Routine-Einträge,
dann acht koordinierte Einheiten und anschließend drei Cluster-Prüfaufträge.
Ausgeschlossene eigene Images und gebündelte Einträge sind kein eigener
Prüfauftrag. Alle 45 Prüfaufträge werden strikt nacheinander bearbeitet; keine
Subagenten, parallelen Tool-Aufrufe oder Hintergrundprozesse.

1. Katalog-Kopf, kompakten Board-Zustand und Journal-Zusammenfassung laden.
   Offene Dienste vor Recherche ausschließen. Versionsstand von Repo und Cluster
   mit den drei fertigen Snapshot-Abfragen einmal nacheinander erfassen.
2. Eine verbleibende Einheit mit ihren festen Quellen prüfen. Gleiche Abfragen
   innerhalb des Runs wiederverwenden, etwa für PostgreSQL.
3. Ein belegtes Update sofort als gesperrtes Ticket sichern. Ticket-ID und Status
   als eine kurze JSON-Zeile an
   `/home/faba/.hermes/cron/state/cluster-update-check/events.jsonl` anhängen.
   Danach zum nächsten Dienst wechseln. Bei Board-Fehler einen knappen
   `pending_ticket`-Eintrag anhängen und mit Teilbericht beenden.
4. Bei Quellenfehlern nach den begrenzten Versuchen weitergehen; bei 401/429
   nicht wiederholen. Keine Zeitgrenze für einzelne Dienste oder den gesamten Run.
5. Nach Queue-Ende `cycle_end` anhängen und knapp berichten. Bei Unterbrechung
   denselben Zyklus mit gleichem Katalog-Hash aus dem Journal fortsetzen.

`journal_append` validiert und kompaktifiziert genau ein Ereignis (höchstens
400 Zeichen). `journal_summary` liest vorhandene Daten mit `jq`; der Agent
regeneriert sie nicht. Die frühere Datei `cluster-update-check.json` bleibt
als Legacy-Stand erhalten und wird nicht weitergeschrieben. Ticket-Bodies sind
auf 1200 Zeichen und Titel auf 110 Zeichen begrenzt. Der Bericht hat höchstens
20 Zeilen. Ausführliche Ticket-Inhalte und der anwachsende Fortschritt müssen
nicht bei jeder Komponente erneut vom Modell erzeugt werden.

HTTP-/kubectl-Timeouts und die vorhandene globale Hermes-Turn-Grenze bleiben
wirksam. Es gibt weder einen Gesamt-/Dienst-Timer noch einen zusätzlichen
Watchdog. Recherchefehler oder ein nicht erreichbares Board dürfen keine Updates
auslösen; gesperrte Tickets warten weiter auf ein ausdrückliches Go.
