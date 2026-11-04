# Cluster-Update-Workflow

Stand: 2026-11-04.

Der erste Testlauf entwickelte und reparierte einen eigenen Registry-Scanner,
wiederholte vollständige Prüfungen und erzeugte keine Tickets. Der Betreiber
hat ihn abgebrochen. Die daraus abgeleiteten Regeln stehen jetzt ausdrücklich
im Katalog und im überarbeiteten Cron-Prompt:

- [`update-catalog.yaml`](../update-catalog.yaml): Zuständigkeiten, feste Quellen,
  Abfragerezepte und die explizite Reihenfolge `check_order`.
- [`cluster-update-catalog.md`](cluster-update-catalog.md): Format, Grenzen und Ablauf.
- [`cluster-update-coverage.md`](cluster-update-coverage.md): Live-Abgleich aller
  Kubernetes-Workloads zum dokumentierten Zeitpunkt.
- [`hermes-cluster-update-cron-prompt.md`](hermes-cluster-update-cron-prompt.md):
  vollständiger versionierter Prompt des täglichen Hermes-Jobs.

Der Checker bearbeitet einen Dienst und dessen Images nacheinander. Sobald ein
Update belegt ist, erzeugt er unmittelbar ein gesperrtes Ticket und sichert
seinen Arbeitsstand. Bei Quellenfehlern geht er weiter; bei fehlender Möglichkeit,
ein Ticket sicher anzulegen, speichert er den Vorschlag und beendet den Lauf
mit einem Teilbericht. Er entwickelt keine Skripte oder neuen Prüfwerkzeuge.

Eigene Images sind explizit ihrem Entwicklungs-/Build-Workflow zugeordnet und
werden nicht von diesem Checker aktualisiert. Zusätzliche Drittanbieter-Images
innerhalb solcher Dienste benötigen eine eigene ausdrückliche Zuordnung.

Noch separat auszuarbeiten ist der spätere Update-Worker: Erst nach Betreiber-Go
soll er Änderungen pinnen, validieren, committen/pushen und den Flux-Rollout sowie
die Dienstfunktion prüfen. RSS-/Advisory-Abos und automatische Notfallmaßnahmen
sind ebenfalls kein Teil des jetzigen Update-Checkers.
