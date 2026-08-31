# LiteLLM

LiteLLM exposes the OpenAI-compatible gateway at
`https://llm.intern.rohrbom.be` and routes `local-chat` to the internal vLLM
service.

## Master key

Replace the placeholder in `litellm-secret.yaml` before deployment. The value
must start with `sk-`. Generate a suitable key with:

```bash
printf 'sk-%s\n' "$(openssl rand -hex 32)"
```

An example manifest is available in `litellm-secret.example.yaml`. It is not
included by Kustomize and is never deployed.

To encrypt the real secret with the repository's SOPS configuration:

```bash
sops --encrypt --in-place apps/internal/llm/litellm/litellm-secret.yaml
```

## PostgreSQL

LiteLLM uses PostgreSQL for its admin UI, virtual keys and persistent usage
data. Replace the placeholder in `litellm-database-secret.yaml` with a URL-safe
password:

```bash
openssl rand -hex 32
```

Then encrypt it:

```bash
sops --encrypt --in-place apps/internal/llm/litellm/litellm-database-secret.yaml
```

The database uses a 5 GiB Longhorn volume with hourly and daily backups. It is
only exposed inside the cluster.

## API test

```bash
curl -s https://llm.intern.rohrbom.be/v1/models \
  -H 'Authorization: Bearer <LITELLM_MASTER_KEY>' | jq
```

```bash
curl -s https://llm.intern.rohrbom.be/v1/chat/completions \
  -H 'Authorization: Bearer <LITELLM_MASTER_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local-chat",
    "messages": [{"role": "user", "content": "Antworte nur mit: LiteLLM läuft"}],
    "max_tokens": 64
  }' | jq
```
