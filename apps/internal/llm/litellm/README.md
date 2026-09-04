# LiteLLM

LiteLLM exposes the OpenAI-compatible gateway at
`https://llm.intern.rohrbom.be` and routes the stable `local-chat` alias to
`Qwen/Qwen3.6-27B-FP8` on the internal vLLM service. Existing consumers keep the
same endpoint and model name. `local-embedding` continues to use the unchanged
CPU-based Text Embeddings Inference service on `wk-5`.

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

Test the embedding route and verify Qwen's 1024-dimensional output:

```bash
curl -s https://llm.intern.rohrbom.be/v1/embeddings \
  -H 'Authorization: Bearer <LITELLM_MASTER_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local-embedding",
    "input": "LiteLLM routet dieses Embedding lokal."
  }' | jq '.data[0].embedding | length'
```

Virtual keys used by OpenClaw must allow both `local-chat` and
`local-embedding`.
