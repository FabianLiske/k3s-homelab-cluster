# LiteLLM

LiteLLM exposes the OpenAI-compatible gateway at
`https://llm.intern.rohrbom.be` with explicit names for each local model:

| Public model name | Backend model | Service |
| --- | --- | --- |
| `local/qwen-3.8-27b` | `Qwen/Qwen3.8-27B-FP8` | vLLM on `wk-5` |
| `local/qwen-3-embedding-0.6b` | `Qwen/Qwen3-Embedding-0.6B` | CPU Text Embeddings Inference on `wk-5` |

Use `local/<model-family-and-version>-<size>` for future local models, with
`embedding` in the name for embedding models. The old public aliases
`local-chat` and `local-embedding` were retired on 2026-11-04. Clients and
model-restricted virtual keys must use the new public names; the API endpoint
stays the same. Upstream served-model IDs are independent of these public names.

For LiteLLM cost tracking, `local/qwen-3.8-27b` still carries the cloud-equivalent
reference price from FP8 Qwen3.6-27B (USD 0.30 per million input tokens, USD
3.20 per million output tokens, checked 2026-09-04) as a placeholder — no
confirmed SiliconFlow listing for Qwen3.8-27B was available yet at update time.
Re-check and update once real pricing shows up; the requests themselves continue
to run exclusively on the local vLLM backend.

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
    "model": "local/qwen-3.8-27b",
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
    "model": "local/qwen-3-embedding-0.6b",
    "input": "LiteLLM routet dieses Embedding lokal."
  }' | jq '.data[0].embedding | length'
```

Virtual keys for clients that use both chat and embeddings must allow
`local/qwen-3.8-27b` and `local/qwen-3-embedding-0.6b`. Replace the old names
in existing model allowlists through LiteLLM's key management API or admin UI;
the virtual key itself does not need to be rotated.
