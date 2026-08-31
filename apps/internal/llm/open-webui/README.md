# Open WebUI

Open WebUI is available at `https://chat.intern.rohrbom.be` and uses LiteLLM
as its only model backend. It runs on a regular worker and does not request the
Intel GPU.

## Secrets

Replace every placeholder in `open-webui-secret.yaml`:

- `OPENAI_API_KEY`: the LiteLLM virtual key restricted to `local-chat`
- `WEBUI_SECRET_KEY`: output of `openssl rand -hex 32`
- `WEBUI_ADMIN_EMAIL`: email used to sign in
- `WEBUI_ADMIN_PASSWORD`: a strong initial admin password
- `POSTGRES_PASSWORD`: output of `openssl rand -hex 32`

Then encrypt the manifest:

```bash
sops --encrypt --in-place apps/internal/llm/open-webui/open-webui-secret.yaml
```

On the first startup Open WebUI creates the administrator automatically and
keeps public signup disabled.

## Storage

- PostgreSQL: 5 GiB Longhorn volume with hourly and daily backups
- Open WebUI data, uploads and local caches: 20 GiB Longhorn volume with daily
  backups
