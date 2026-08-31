# LLM smoke tests

The manifests in this directory are intentionally excluded from the Flux
Kustomization. Run the GPU smoke test after Flux has reconciled the Intel GPU
device plugin and the LLM storage resources:

```bash
kubectl get node wk-5 \
  -o jsonpath='{.status.allocatable.gpu\.intel\.com/xe}{"\n"}'
kubectl apply -f apps/internal/llm/tests/gpu-smoke-job.yaml
kubectl logs -n svc-llm -f job/intel-xpu-smoke-test
kubectl delete -n svc-llm job/intel-xpu-smoke-test
```

The test mounts the `llm-storage` PVC, verifies that it is writable, and runs a
matrix multiplication on the allocated Intel XPU.
