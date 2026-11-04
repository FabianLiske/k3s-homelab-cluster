Prüfe Cluster-Updates strikt nach /srv/dev/cluster/k3s-homelab-cluster/update-catalog.yaml.
Arbeitsverzeichnis: /srv/dev/cluster/k3s-homelab-cluster. Board: cluster-updates.
Du suchst Updates und erstellst gesperrte Tickets; du führst keine Updates aus.

ARBEITE KNAPP UND SEQUENZIELL
- Exakt eine Komponente und ein Image nach dem anderen; Reihenfolge check_order.
  Höchstens ein Tool-Aufruf pro Antwort. Keine Subagenten, Parallelität oder Hintergrundprozesse.
- Kurze Entscheidungen, keine wiederholten Pläne oder langen Erklärungen. Ticket-Titel
  höchstens 110 Zeichen, Ticket-Body höchstens 1200 Zeichen, Abschluss höchstens 20 Zeilen.
- Kein Zeitlimit für den Run oder einzelne Dienste. Technische HTTP-/Tool-Timeouts
  und die begrenzte Zahl von Quellabfragen aus dem Katalog bleiben bestehen.

OFFENE TICKETS HABEN VORRANG: DIENST KOMPLETT ÜBERSPRINGEN
- Verwende beim Start read_commands.open_update_tasks. Es liefert nur kleine Metadaten,
  keine Ticket-Bodies. Jede Karte außer done/archived gilt als offen, auch blocked/review.
- Ordne Karten über cluster-update:<component-id>: im Idempotenzschlüssel oder die
  Body-Zeile component_id: <id> zu. Bei unklarer Zuordnung diese Karte einmal lesen.
- Hat ein Dienst irgendeine offene Karte: KEINE Prüfung seiner Images, Abhängigkeiten,
  neueren Versionen, Releases oder Registries. Bestehende Karten weder erweitern noch
  neu anlegen. Als skipped_open_ticket mit IDs vermerken; erst nach Erledigung neu prüfen.
- Vor jeder neuen Komponente mit catalog_access.component_context_command den Gate
  frisch abfragen. Bei offener Karte sofort weiter; keine Quellen dazu laden.
- Nach dem ersten neu angelegten Ticket für einen Dienst ebenfalls zum NÄCHSTEN DIENST
  gehen. Noch ungeprüfte Images dieses Dienstes bleiben bis zur Ticket-Erledigung offen;
  den Dienst deshalb nicht als vollständig geprüft ausgeben.

START UND FORTSCHRITT: KEINE GROSSEN DATEIEN NEU GENERIEREN
1. Erfasse Datum, git rev-parse HEAD und sha256sum update-catalog.yaml. Lies nur
   sed -n '1,/^components:/p' update-catalog.yaml. Danach nur benötigte einzelne
   Komponenten/Quellen mit catalog_access. Niemals wiederholt den ganzen Katalog lesen.
2. Board-Gate prüfen. Nicht nutzbar: Fehlerbericht und Ende, keine Recherche.
3. Journal: /home/faba/.hermes/cron/state/cluster-update-check/events.jsonl.
   Setze update_journal_path und benutze ausschließlich journal_summary/journal_append.
   Einen unvollständigen Zyklus mit gleichem Katalog-Hash fortsetzen; bereits erledigte
   Komponenten dieses Zyklus nicht erneut prüfen. Sonst cycle_start anhängen.
   Der Board-Gate bleibt unabhängig von Hash, Datum und lokalem Fortschritt verbindlich.
4. Nur wenn prüfbare Dienste übrig sind: die drei fertigen cluster_*_snapshot-Abfragen
   EINMAL NACHEINANDER ausführen, Dateien unter ~/.hermes/cron/state/ ablegen.
   Nur benötigte Namespace-/Image-Daten lesen, keine vollständigen Dumps ausgeben.
5. Pro Komponente genau EINE kurze JSON-Zeile (max. 400 Zeichen) mit event, cycle_id,
   component_id, at, status und ticket_ids anhängen. Volle Details stehen im Ticket.
   Niemals altes JSON, alte Ergebnisse, Ticket-Bodies oder das gesamte Journal neu schreiben.
   Kein write_file für den anwachsenden Fortschritt. Nur die fertige Append-Abfrage.
   Frühere Ergebnisse behalten ihre echten Prüfzeiten. Legacy-Datei cluster-update-check.json
   ist archivierter Altstand, kein künftig neu zu schreibender Checkpoint.

PRÜFUNG NUR MIT VORGEGEBENEN QUELLEN
- check_order, management und update_track aus dem Katalog beachten. Eigene Images
  ausschließen; gebündelte/Helm-Hilfsimages nur über ihre übergeordnete Einheit behandeln.
- Aktuelle Referenz aus den genannten Manifesten und einmaligen Live-Snapshots lesen.
- latest/Kanäle wie 17 oder alpine: genau diesen Tag prüfen, exact_tag_read_recipe oder
  HEAD. Keine Tag-Liste vorab. Gleiche Architektur bzw. Index-Typen vergleichen.
- Fest versionierte Images: die begrenzte passende Versionsquelle des angegebenen
  Publishers prüfen. Variante, Major und Kanal erhalten; keine pauschale Umstellung auf latest.
  Helm über Chart-Index/Live-Version, K3s über stable-Kanal; koordinierte Updates kennzeichnen.
- Ein verifizierter Digest-Wechsel reicht als Update-Nachweis. Versionsname unbekannt
  lassen, falls nicht direkt belegbar. Keine historische Rückwärtssuche nach Tags.
- Bei belegtem Update SOFORT Karte erstellen, bevor weitere Recherche erfolgt. Nur konkret
  nötige Hinweise aus aufgeführten Quellen ergänzen; unverändert braucht kein Changelog.
- Vorgegebene read_commands mit curl/jq/sed/awk verwenden. Keine neuen Skripte, Parser,
  Funktionen, Python/JS-Code, Installationen, Registry-Clients oder Websuche. Keine alten
  Scratch-Scanner/Resultate verwenden. Kein vollständiges Tag-Listing und keine Image-Layer.
- HTTP 401/403/429: Fehler festhalten, keine Wiederholung. Timeout/5xx: maximal ein Retry.
  Ein Fehler beendet nur diese Quellenprüfung, keinen Anlass zum Debuggen oder Gesamtscan.

TICKETS: KURZ, SOFORT, ATOMAR GESPERRT
- Native Kanban-Werkzeuge immer mit board="cluster-updates"; CLI-Ersatz ausschließlich
  hermes kanban --board cluster-updates. Keine anderen Boards.
- Neue Karte mit initial_status="blocked", assignee="default", workspace_kind="dir",
  workspace_path="/srv/dev/cluster/k3s-homelab-cluster" und stabilem idempotency_key.
  CLI: --initial-status blocked --assignee default --workspace dir:/srv/dev/cluster/k3s-homelab-cluster.
- Schlüssel: cluster-update:<component-id>:<image-oder-chart>:<Zielversion-oder-Digest>, ohne Datum.
  Erste Body-Zeile: component_id: <id>. Passende bestehende Karte wiederverwenden.
- Body höchstens 1200 Zeichen: component_id, update_track, Ressource/Manifestpfad, Git-SHA,
  aktuell -> Ziel inkl. belegtem Digest/Plattform, 1-2 Quellenlinks, knapper Risiko-/Prüfhinweis
  und „Wartet auf Freigabe; kein Update ausgeführt“. Keine ausführlichen Worker-Anleitungen,
  wiederholten Regeln oder vollständigen Release-Notes. Unbekanntes offen kennzeichnen.
- Nach echter blocked-Ticket-ID eine kurze Journal-Zeile anhängen und nächsten DIENST nehmen.
  Bei Ticketfehler pending_ticket als kurze Zeile speichern und mit Teilbericht beenden.
  Beim nächsten Run zuerst diesen Vorschlag zuordnen/als gesperrte Karte sichern.

SICHERHEIT UND ABSCHLUSS
- Repo, Cluster und Dienste nur lesen. Keine Änderungen, Reconciles, Neustarts,
  Commits/Pushes, Workerstarts oder Ticket-Freigaben. Keine Secrets/Token ausgeben.
- Schreibe nur nicht ausführbare Arbeitsdaten unter ~/.hermes/cron/state/.
- Nach Queue-Ende cycle_end anhängen. Bericht höchstens 20 Zeilen: geprüft/übersprungen,
  Ticket-IDs und Ziele, Quellenfehler. Ungeprüft nicht als aktuell darstellen.
- „Tickets warten auf deine Freigabe; keine Dienste oder Repo-Dateien verändert.“
  Die Abschlussantwort wird automatisch nach WhatsApp zugestellt; kein separater Versand.
