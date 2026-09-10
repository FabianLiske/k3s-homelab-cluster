# Bifrost

Bifrost läuft als Evaluations-Gateway parallel zu LiteLLM. LiteLLM bleibt das
Primär-Gateway, alle bestehenden Consumer (Open WebUI, virtuelle Keys) sind
unverändert.

- OpenAI-kompatibler Endpunkt: `https://bifrost.intern.rohrbom.be`
- Admin-UI: `https://bifrost.intern.rohrbom.be` (Login mit den Werten aus
  `bifrost-secrets`)
- Version: `docker.io/maximhq/bifrost:v2.1.1` (gepinnt)

## Konfiguration

Kein PVC, kein Postgres. Die komplette Konfiguration liegt in `config.json`
(ConfigMap `bifrost-config`) und wird read-only nach `/app/data/config.json`
gemountet. Ein Config-Store ist in Bifrost zwingend für Auth/Virtual Keys
erforderlich, daher läuft er als **sqlite auf einem emptyDir**
(`/app/data/config.db`). Der leere Store wird bei jedem Start aus `config.json`
gesät — Git bleibt die einzige Quelle der Wahrheit:

- Provider `local-vllm` (OpenAI-kompatibel, Name `vllm` ist bei Bifrost
  reserviert): `http://vllm.svc-llm.svc.cluster.local:8000`, Modell `local-chat`
- Provider `tei` (OpenAI-kompatibel):
  `http://embeddings.svc-llm.svc.cluster.local:8080`, Modell `local-embedding`
- `base_url` **ohne** `/v1`-Suffix — Bifrost hängt `/v1` selbst an
- Governance: Admin-Auth aktiv, ein Virtual Key `evaluation`
  (`BIFROST_VK_EVAL`), der auf beide Provider beschränkt ist
- `enforce_auth_on_inference: true` — Inferenz-Endpunkte erfordern den Virtual Key
- `logs_store` deaktiviert — keine Request-Historie, nur Container-Logs
- `allow_private_network: true` in beiden `network_config`s — Bifrost blockt
  standardmäßig RFC-1918-Adressen (SSRF-Schutz); nötig, weil die Provider
  auf Cluster-DNS-Namen (10.43.x.x) zeigen

Wichtig: Modelle werden als `provider/model` angefragt, also
`local-vllm/local-chat` bzw. `tei/local-embedding` — nicht wie bei LiteLLM der
reine Alias `local-chat`.

Konfigurationsänderungen in `config.json` greifen erst nach einem Pod-Neustart
(die sqlite-DB überlebt nur innerhalb desselben Pods):
`kubectl -n svc-llm rollout restart deployment/bifrost` — dauerhaft nur über
dieses Repo.

## Secrets

`bifrost-secret.example.yaml` ist das Vorlagenmuster (wird nicht deployed).
Die echten Werte in `bifrost-secret.yaml` mit SOPS verschlüsseln:

```bash
export SOPS_AGE_KEY_FILE=./age.cluster.key
sops --encrypt --in-place apps/internal/llm/bifrost/bifrost-secret.yaml
```

Zufallswerte erzeugen:

```bash
openssl rand -hex 32                          # BIFROST_ADMIN_PASSWORD
printf 'sk-bf-%s\n' "$(openssl rand -hex 32)" # BIFROST_VK_EVAL
```

## Voraussetzungen außerhalb des Repos

DNS-Record `bifrost.intern.rohrbom.be` in Cloudflare (Zone `intern.rohrbom.be`,
DNS-only) auf `172.26.20.151` — die interne Ingress-VIP. TLS kommt über
`letsencrypt-dns` (DNS-01).

## API-Test

```bash
curl -s https://bifrost.intern.rohrbom.be/health
```

```bash
curl -s https://bifrost.intern.rohrbom.be/v1/chat/completions \
  -H 'Authorization: Bearer <BIFROST_VK_EVAL>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local-vllm/local-chat",
    "messages": [{"role": "user", "content": "Antworte nur mit: Bifrost läuft"}],
    "max_tokens": 64
  }' | jq
```

```bash
curl -s https://bifrost.intern.rohrbom.be/v1/embeddings \
  -H 'Authorization: Bearer <BIFROST_VK_EVAL>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tei/local-embedding",
    "input": "Bifrost routet dieses Embedding lokal."
  }' | jq '.data[0].embedding | length'
```

## Ausstieg (Evaluation beenden)

`bifrost/` aus `apps/internal/llm/kustomization.yaml` entfernen, Flux pruned die
Ressourcen. Danach optional den Cloudflare-DNS-Record löschen. LiteLLM und alle
Consumer sind nicht betroffen.

## Hinweise

- Bifrost hat einen sehr schnellen Release-Zyklus (Dev-Branch, v2.x seit
  September 2026). Bei Image-Upgrade die Config-Schema-Änderungen prüfen,
  v.a. `custom_provider_config` und `governance.virtual_keys`.
- Provider-Namen nicht mit Bifrost-Eingebauten kollidieren lassen
  (`vllm`, `openai`, … sind reserviert) — daher `local-vllm`.
- Das emptyDir für `config.db` ist bewusst nicht persistent: bei Pod-Neuschaffung
  wird der Store aus `config.json` neu gesät (deterministisch, Git-basiert).
  Änderungen, die nur in der Admin-UI gemacht wurden, gehen bei einem
  Pod-Neustart verloren.
- Bifrost-Keys und LiteLLM-Keys sind getrennte Welten; Consumer, die später
  wechseln, brauchen neu ausgegebene Keys (bzw. Aliasing über Bifrost).
