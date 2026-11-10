# Archivierter Paperless-ngx-Stack

Dokumentenverwaltung (Paperless-ngx) mit Webserver, Tika, Gotenberg,
Redis-Broker und PostgreSQL, Namespace `svc-paperless-ngx`, bisher erreichbar
unter `paperless.intern.rohrbom.be`.

Am 2026-11-10 auf Anordnung des Users aus `apps/internal/paperless-ngx/`
hierher verschoben: nie richtig genutzt, Ressourcen (6 Longhorn-PVCs,
insgesamt 12 GiB) sollen freigeben. Ein Backup der Daten war nicht
erforderlich; die PVCs/PVs werden mit dem Namespace bei der Flux-Prune
entsorgt. Das SOPS-verschlüsselte `paperless-secret.yaml` bleibt wie beim
qbittorrent-backup-Archiv als Referenz erhalten.

Der `update-catalog.yaml`-Eintrag wurde nicht in diesem Commit entfernt, da
zu diesem Zeitpunkt eine größere uncommittete Katalog-Umstrukturierung offen
war; die Komponente ist im Katalog noch einzutragen zu streichen.
