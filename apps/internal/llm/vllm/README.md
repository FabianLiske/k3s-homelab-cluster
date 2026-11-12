# vLLM

The deployment serves the pre-quantized `Qwen/Qwen3.8-27B-FP8` checkpoint,
pinned to Hugging Face revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`,
under both the compatibility name `local-chat` and its real model ID through the
OpenAI-compatible API. It runs only on `wk-5` and uses both Intel Arc Pro B60
GPUs as one tensor-parallel vLLM instance (`TP=2`). Model weights and the KV
cache use FP8; the initial maximum context is 131,072 tokens.

The workload uses Intel's pinned `llm-scaler-vllm` image for Arc Pro B-series
multi-GPU inference. Prefix caching is enabled, requests are serialized for the
single-user/large-context use case, and Qwen's reasoning and tool-call parsers
are enabled. The model is served in language-only mode to reserve GPU memory for
text workloads and KV cache.

The first startup downloads roughly 31 GB of model data to the local LLM volume
and initializes both XPU workers, so it can take significantly longer than later
starts.

> **Image upgrades:** the Triton/TorchInductor JIT caches under
> `/var/lib/llm/cache/` are persisted on the `llm-storage` PVC across image
> versions. A stale cache compiled against an older image's SYCL runtime can
> fail to load under a newer image (e.g. `libsycl.so.9` missing when the new
> image only ships `libsycl.so.8`), crashing the container on startup with an
> `OSError` during model architecture inspection. Symptom looks model-specific
> but isn't ([intel/llm-scaler#665](https://github.com/intel/llm-scaler/issues/665)).
> Clear the cache before/while rolling out a new `llm-scaler-vllm` image tag:
> ```bash
> kubectl exec -n svc-llm deployment/vllm -- rm -rf /var/lib/llm/cache/triton /var/lib/llm/cache/torchinductor
> ```

Watch the initial rollout and logs:

```bash
kubectl get pods -n svc-llm -w
kubectl logs -n svc-llm -f deployment/vllm
```

Verify that the deployment requests both GPUs and is scheduled on `wk-5`:

```bash
kubectl get pod -n svc-llm -l app.kubernetes.io/name=vllm \
  -o 'custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,GPU:.spec.containers[0].resources.limits.gpu\.intel\.com/xe'
```

Test the internal API from a workstation:

```bash
kubectl port-forward -n svc-llm service/vllm 8000:8000
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local-chat",
    "messages": [{"role": "user", "content": "Antworte kurz: Läuft die lokale B60-Inferenz?"}],
    "max_tokens": 128
  }'
```

The in-cluster endpoint for LiteLLM is:

```text
http://vllm.svc-llm.svc.cluster.local:8000/v1
```

LiteLLM exposes this backend publicly as `local/qwen-3.8-27b` at
`https://llm.liske.cc/v1`. The `local-chat` name above is an internal
vLLM compatibility ID; clients of LiteLLM use the explicit public name.

## Reasoning effort through LiteLLM

The pinned [Qwen chat template](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a/chat_template.jinja)
accepts only `low`, `medium`, and `xhigh` while thinking is enabled. vLLM
passes the top-level OpenAI-compatible `reasoning_effort` to this template;
LiteLLM forwards it from Hermes, OpenCode, and other clients. `high` and
`minimal` previously failed with HTTP 400 inside the template, not at the
LiteLLM ingress. The existing LiteLLM `drop_params: true` is not a remedy.

The deployment mounts a copy of that exact pinned template from
`chat-template.jinja`; the only change is a compatibility mapping before its
existing effort validation: `minimal -> low`, `high -> medium`, and
`max -> xhigh`. Native `low`, `medium`, and `xhigh` retain their behavior.
`none` disables thinking in vLLM (by setting `enable_thinking=false`) and is
not remapped. The default without an explicit effort is still `xhigh`.
This maps to the nearest non-stronger Qwen tier where possible; `minimal`
uses the lowest thinking tier rather than silently turning thinking off.
When changing the pinned Qwen revision, compare its upstream chat template
against this copy and re-apply the small mapping rather than retaining an
outdated full template.

Send `reasoning_effort` at the **top level** of `/v1/chat/completions`, for
example `"reasoning_effort": "high"`; the mapping turns it into Qwen's
`medium` tier. To disable thinking explicitly through vLLM, send
`"reasoning_effort": "none"` or
`"chat_template_kwargs": {"enable_thinking": false}` (for clients using
OpenAI SDKs, the latter belongs in `extra_body`). The latter has precedence
if both are present. Do not set `enable_thinking` as a standalone OpenAI field.
LiteLLM's route continues to use the existing `openai/` backend: live tests
confirmed that it passes the top-level effort through; no global proxy
parameter setting or unrelated model route was changed.

After rollout, verify `high` and `minimal` over the LiteLLM endpoint as well
as `low`, `medium`, `xhigh`, `max`, and `none`. A generated ConfigMap name
changes with the template contents and restarts the vLLM pod automatically.
This is a Recreate deployment: the local model is unavailable during startup
and GPU model loading. The proxy and other models remain separate.
