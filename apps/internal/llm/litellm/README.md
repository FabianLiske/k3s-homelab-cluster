# LiteLLM

LiteLLM exposes the OpenAI-compatible gateway at
`https://llm.intern.rohrbom.be` with explicit names for local and external models:

| Public model name | Backend model | Service |
| --- | --- | --- |
| `local/qwen-3.8-27b` | `Qwen/Qwen3.8-27B-FP8` | vLLM on `wk-5` |
| `local/qwen-3-embedding-0.6b` | `Qwen/Qwen3-Embedding-0.6B` | CPU Text Embeddings Inference on `wk-5` |
| `external/jev-1.14` | `typesafe/jev-1.14` | OpenRouter Decisions API |

The gateway image is pinned to `v1.108.3`, the latest stable LTS release checked
on 2026-11-08. See the [release notes](https://github.com/BerriAI/litellm/releases/tag/v1.108.3).

The Qwen chat route defaults to `presence_penalty: 0.5`. Clients can override
this per request. This default is applied by LiteLLM; direct requests to vLLM
bypass it. Other sampling parameters retain the backend defaults.

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

## OpenRouter decisions (Jev)

Before deploying this change, add `OPENROUTER_API_KEY` under `stringData` in
the existing encrypted `litellm-secret.yaml`. Preserve `LITELLM_MASTER_KEY`.
Open the secret in SOPS so it is encrypted again when saved:

```bash
sops apps/internal/llm/litellm/litellm-secret.yaml
```

The example manifest documents the required field. The deployment requires
this secret field before its new pod can start.

The deployment injects the key as `OPENROUTER_API_KEY`; `configmap.yaml`
references it through `os.environ/OPENROUTER_API_KEY`. Clients authenticate
with their LiteLLM virtual key and request `external/jev-1.14`. Add that alias
to any model-restricted virtual keys that should be allowed to use Jev.

Jev returns structured decisions and probabilities. Use `/v1/systemone` for
TypeSafe's `state`/`questions` format or `/v1/decisions` for OpenAI's Decisions
format. `/v1/chat/completions` cannot serve this model, so selecting it in an
ordinary chat client is insufficient. LiteLLM forwards requests to OpenRouter's
`/api/alpha/decisions` endpoint. The decision routes require LiteLLM v1.104.2
or later; v1.104.3 adds OpenRouter's reported `usage.cost` to cost tracking.
See [LiteLLM's OpenRouter decision integration](https://docs.litellm.ai/docs/providers/openrouter#decisions-jev).

After deployment, test with a LiteLLM key allowed to use `external/jev-1.14`:

```bash
curl --fail-with-body -sS https://llm.intern.rohrbom.be/v1/systemone \
  -H "Authorization: Bearer ${LITELLM_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "external/jev-1.14",
    "state": "The database is reachable and all service health checks passed.",
    "questions": {
      "healthy": {
        "type": "noul",
        "instructions": "Is the service healthy according to the supplied state?"
      }
    }
  }' | jq
```

The response contains an `answers.healthy.noul` probability. Local chat and
embedding routes keep their existing backends; no fallback to OpenRouter is
configured. Additional OpenRouter models can reuse the same secret through
explicit entries in `model_list`.

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
