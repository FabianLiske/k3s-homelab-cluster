# Hermes Agent

[Hermes Agent](https://hermes-agent.nousresearch.com/docs/) (Nous Research)
läuft zentral in **einem Pod** (`svc-hermes`, eine Replica, `Recreate`) mit
Gateway, Agent und Web-Dashboard. Offizielles Container-Image,
versionsscharf per Tag **und** Manifest-Digest gepinnt (Stand: `v2026.9.24`,
multi-arch amd64/arm64 — passt zur gemischten Node-Pool-Architektur).

- Dashboard: `https://hermes.intern.rohrbom.be` (VLAN-20-Interna-Host,
  `nginx-internal` Ingress, TLS via `letsencrypt-dns`)
- Inferenz: LiteLLM-Router im Cluster
  (`http://litellm.svc-llm.svc.cluster.local:4000/v1`, Modell-Alias
  `local-chat` — identisch zu `apps/internal/llm/litellm`)
- Zeitzone: `Europe/Berlin`

## Aufbau / Dateien

| Datei | Zweck |
| --- | --- |
| `namespace.yaml` | Namespace `svc-hermes` |
| `pvc-data.yaml` | 10 GiB Longhorn RWO (`longhorn-2r`) mit täglichen Backups + wöchentlichem Trim; `prune: disabled`, damit Flux das Volume nicht mitlöscht |
| `configmap.yaml` | Start-`config.yaml` (nicht-vertraulich) — wird **einmalig** eingespielt |
| `hermes-secret.yaml` / `.example` | SOPS+age-verschlüsselt: LiteLLM-Master-Key, API-Server-Key, Dashboard-Basic-Auth |
| `deployment.yaml` | Gateway + Dashboard + Agent in einem Container, s6-supervidiert |
| `service.yaml` | ClusterIP `hermes` mit Ports `dashboard` (9119) und `api` (8642) |
| `ingress.yaml` | `hermes.intern.rohrbom.be` → Port 9119 (nur Dashboard) |
| `netpol-ingress.yaml` | Inbound nur aus `ingress-20` auf Port 9119 |

Kein Egress-NetworkPolicy: wie bei Home Assistant braucht der Agent
breiten Outbound (Web, Skills, `uvx`/`npx`-Tool-Installs, LiteLLM).

## Container-Verhalten (offizielles Image)

Der offizielle Entrypoint (`docker/entrypoint-dispatch.sh`) wird **nicht**
überschrieben; das Deployment übergibt nur `args: [gateway, run]`. Als PID 1
exec der Dispatcher s6-overlay `/init`, das:

1. als root startet, `/opt/data` bei Erststart chown-t (UID/GID 10000,
   User `hermes`), seedet fehlende `config.yaml`/`.env`/`SOUL.md` und
   führt non-interactive Config-Schema-Migrationen aus (mit
   Zeitstempel-Backups),
2. die Profile-Gateways reconciliert (`02-reconcile-profiles`),
3. Gateway und Dashboard als s6-rc-Service supervidiert (Crash →
   Neustart nach ~1 s Backoff),
4. `gateway run` als Hauptprozess läuft (intern ein `sleep infinity`-
   Heartbeat) — der Container bleibt also stabil, SIGTERM fährt alles
   sauber herunter.

Deshalb: kein systemd, kein `entrypoint:`-Override im Deployment (würde
s6-Supervision und Zombie-Reaping entfernen), `Recreate`-Strategie (nie
zwei Gateways auf demselben Datenverzeichnis; SQLite-WAL + Session-Dateien
sind Single-Writer).

## Ports & Probes

| Port | Dienst | Erreichbar |
| --- | --- | --- |
| 9119 | Web-Dashboard (supervidiert, `HERMES_DASHBOARD=1`) | Ingress + Cluster |
| 8642 | OpenAI-kompatibler API-Server (Gateway) | nur In-Cluster |

- **startupProbe** `GET /health` (8642, 5 s × 120): Der öffentliche
  Liveness-Endpoint des API-Servers, ohne Auth, **ohne Modellanfrage**.
  Läuft erst, wenn der Gateway-Prozess den API-Server gebracht hat;
  ~10 min Budget für Erststart (chown, Migration, Skill-Sync).
- **readinessProbe** TCP 9119: Dashboard lauscht → Ingress routet.
- **livenessProbe** `GET /health` (8642, 30 s × 3): Backstop für den Fall,
  dass s6 selbst hängt.

Geprüft wird also: Gateway-Prozess läuft (API-Server up) und Dashboard
läuscht. Nicht geprüft (und ausdrücklich nicht ausgelöst): Modellanfragen /
LiteLLM-Erreichbarkeit.

## Sicherheit (SecurityContext)

Das Image benötigt beim Bootstrap Root (s6 `/init` chown-t das Volume und
droppt per `s6-setuidgid` auf `hermes` UID 10000). Konfiguriert daher:

- Pod: `runAsUser: 0`, `runAsNonRoot: false`, `fsGroup: 10000`
  (`OnRootMismatch`), `seccompProfile: RuntimeDefault`
- Hauptcontainer: Caps `drop: ALL` + `add: CHOWN, SETUID, SETGID`
  (First-Boot-chown und setuid-Drop), `allowPrivilegeEscalation: true`
  (notwendig für den s6-Bootstrap); **kein** `privileged: true`
- Init-Container `seed-config` (BusyBox): nur Cap `CHOWN`, kein
  Privilege-Escalation, spielt die ConfigMap-Config einmalig ein

## Secrets (SOPS)

`hermes-secret.yaml` liegt age-verschlüsselt im Repo (Regex in
`.sops.yaml`); Vorlage mit Platzhaltern in `hermes-secret.yaml.example`.
**Vor dem ersten Laufen** die echten Werte setzen (und neu verschlüsseln):

```bash
# echte Werte in hermes-secret.yaml eintragen, dann:
sops --encrypt --in-place apps/internal/hermes/hermes-secret.yaml
```

| Key | Wert / Herkunft |
| --- | --- |
| `LITELLM_API_KEY` | = `LITELLM_MASTER_KEY` aus Secret `litellm-secrets` (Namespace `svc-llm`); ohne Ableiten aus dem verschlüsselten Repo-File im Rancher-UI/`kubectl` in `svc-llm` ablesen (Secret nicht ins Repo kopieren) |
| `API_SERVER_KEY` | `printf '%s\n' "$(openssl rand -hex 32)"` |
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` | z. B. `faba` |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` | starkes Passwort |
| `HERMES_DASHBOARD_BASIC_AUTH_SECRET` | `openssl rand -base64 32` |

Der interne Ingress ersetzt die Hermes-Auth **nicht**: Ohne
Basic-Auth-Provider scheitert das Dashboard auf nicht-Loopback-Bind
fail-closed (Stand Juni 2026 ist `HERMES_DASHBOARD_INSECURE` ein No-op).

## Erstkonfiguration

1. Secrets befüllen (s. o.), commit + push (Flux deployt).
2. Pod startet; `seed-config` legt `/opt/data/config.yaml` an (Modell =
   `local-chat` via LiteLLM, Dashboard public_url + trusted proxies).
3. Optional einmalig per `kubectl -n svc-hermes port-forward
   svc/hermes 9119:9119` das Dashboard direkt prüfen (ohne Ingress-DNS),
   dann über `https://hermes.intern.rohrbom.be` mit den
   Basic-Auth-Credentials anmelden.
4. Im Dashboard bei Bedarf noch: `SOUL.md` (Agent-Persönlichkeit)
   anpassen, Skills verwalten, ggf. Messaging-Plattformen anbinden.
   `hermes setup` (Wizard) ist in dieser Deployment-Form nicht
   erforderlich, da Modell + Auth deklarativ vorliegen.

## Konfigurationsänderungen

- **Laufzeit (kanonisch):** Dashboard oder
  `kubectl -n svc-hermes exec deploy/hermes -- hermes config set
  <section.key> <value>` — schreibt auf das PVC (`/opt/data/config.yaml`),
  übersteht Neustarts. `hermes config get model --json` zum Prüfen.
- **Seed (GitOps):** Änderungen an `configmap.yaml` wirken **nicht**
  automatisch (No-Clobber!). Zum Re-Spielen: ConfigMap ändern →
  `/opt/data/config.yaml` auf dem Volume löschen (z. B. per `kubectl
  exec`-one-shot) → Pod neu starten.
- **Secrets ändern:** Wert in `hermes-secret.yaml` setzen,
  `sops --encrypt --in-place`, commit + push → Pod-Rollout (Recreate).

## Logs & Updates

- `kubectl -n svc-hermes logs -f deploy/hermes` — Dashboard + Gateway
  (supervidierte Prozesse werden hier tee't); persistiert auf dem PVC unter
  `/opt/data/logs/gateways/<profil>/current` (rotiert) sowie
  `/opt/data/logs/agent.log`, `errors.log`.
- `kubectl -n svc-hermes exec deploy/hermes -- hermes logs --follow`
- `hermes doctor` / `hermes status --full` (zeigt `Manager: s6`) für
  Health-Checks im Container.
- **Update:** `image:`-Tag/Digest in `deployment.yaml` auf die nächste
  Stable-Version bumpen, commit + push. Hermes migriert die Config
  automatisch beim Boot (Backups neben `config.yaml`/`.env`); `Recreate`
  stellt sicher, dass nie zwei Instanzen parallel laufen.

## Offene Punkte / Container-Einschränkungen

- **`LITELLM_API_KEY` & Dashboard-Credentials sind Platzhalter** — erst
  befüllen, dann deployen (siehe Secrets).
- **Terminal-Backend = lokal im Container** (Default). Die spätere
  Anbindung an die Dev-VM per SSH-Backend (`terminal.backend: ssh` in
  `config.yaml` inkl. Key-Mount) ist bewusst noch nicht eingerichtet;
  keine SSH-Keys in diesem Repo. Solange das SSH-Backend fehlt, führt der
  Agent `terminal`/`execute_code` **im Pod** aus.
- **Kein Egress-NetPol** (Agent braucht breiten Outbound) — vgl. Home
  Assistant. Wer das ändern will, braucht eine Allowlist inkl. DNS +
  LiteLLM + Internet.
- **API-Server (8642) ist aktiviert** (für Probes + späteres
  OpenAI-kompatibles Frontend, z. B. Open WebUI) — nur in-cluster
  erreichbar, Bearer-Key-pflichtig. Bei Bedarf via
  `API_SERVER_ENABLED=false` + TCP-Probe auf 9119 abschaltbar.
- **LiteLLM-Session-Affinity nicht gesetzt:** Der Agent nutzt
  `provider: custom` + `base_url` (das dokumentierte Recept für lokale
  OpenAI-kompatible Endpoints). LiteLLM unterstützt darüber hinaus
  `session_affinity_header: x-litellm-session-id` (per benanntem
  `providers:`-Eintrag), damit der Router die Konversation als eine
  Session sieht und nicht jede Agent-Loop-Runde die komplette History
  neu upstream sendet. Für den lokalen Router unkritisch; bei Bedarf in
  der Seed-Config ergänzen (siehe „Konfigurationsänderungen").
- **Browser-Tools:** Chromium läuft im Container (Shared Memory 1 GiB
  via `/dev/shm`-emptyDir). Headed-Betrieb/Bot-Screens ist in einem
  Headless-Cluster nicht sinnvoll; Voice-Mode braucht Audio-Bridge
  (nicht vorhanden).
- **Keine Chat-Plattformen** (Telegram/Discord/…) konfiguriert — Gateway
  läuft ohne Plattformen; Dashboard + API-Server sind die Oberflächen.
- **Validierung:** statisch (Kustomize-Build, Server-Side-Dry-Run gegen
  die API) geprüft; Laufzeitverhalten (Probe-Verhalten, s6-Bootstrap auf
  Longhorn, Dashboard-Login, LiteLLM-Runde) erst nach Merge/Deploy
  verifiziert (Checkliste in der PR/Below).
