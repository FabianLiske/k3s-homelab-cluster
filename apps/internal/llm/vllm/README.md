# vLLM

The deployment serves `openai/gpt-oss-20b` as `local-chat` through the
OpenAI-compatible API. The first startup downloads the model to the local LLM
volume and compiles XPU kernels, so it can take significantly longer than later
starts.

Watch the initial rollout and logs:

```bash
kubectl get pods -n svc-llm -w
kubectl logs -n svc-llm -f deployment/vllm
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
