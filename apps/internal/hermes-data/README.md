# Retained Hermes data

Hermes was retired from the cluster on 2026-11-04. The previous deployment
is archived in `archive/hermes/` and is not included in the active Flux build.

Only namespace `svc-hermes` and PVC `hermes-data` remain managed here. Both
have Flux pruning disabled; retaining the namespace prevents its deletion
from cascading to the PVC. The PVC's Longhorn backup labels remain intact.

Do not delete the namespace or PVC until the old data is explicitly no
longer needed. No Hermes workload is deployed by this directory.
