# Archived ntfy service

ntfy was removed from the active `apps/public` kustomization. The manifests in
this directory are retained for reference and are not reconciled by Flux.

The `svc-ntfy` Namespace and `ntfy-data` PVC were annotated with
`kustomize.toolkit.fluxcd.io/prune: disabled` before archival so the existing
Longhorn volume remains available. The Deployment, Service, Ingress, ConfigMap,
Secret, and NetworkPolicy are pruned from the cluster.
