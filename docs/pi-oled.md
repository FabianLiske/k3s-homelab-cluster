# Pi OLED DaemonSet

`pi-oled` laeuft als DaemonSet im Namespace `ops-monitoring` und zeigt lokale Pi- und Kubernetes-Informationen auf einem SSD1306-OLED an.

## Ziel-Nodes

Das DaemonSet ist fuer alle `arm64`-Nodes vorgesehen. Im aktuellen Cluster sind das:

- `cp-1`
- `cp-2`
- `cp-3`
- `wk-1`
- `wk-2`
- `wk-3`

Die Control-Plane-Nodes werden ueber eine `NoSchedule`-Toleration bewusst mit abgedeckt.

## Voraussetzungen pro Node

- I2C ist auf dem Host aktiviert.
- Das OLED ist als SSD1306 an `/dev/i2c-1` erreichbar.
- Das private GHCR-Image `ghcr.io/fabianliske/pi-sysinfo-oled:latest` ist ueber das Secret `ghcr-cred` im Namespace `ops-monitoring` pullbar.

## Laufzeitverhalten

- Das DaemonSet mountet `/dev/i2c-1`, `/proc`, `/sys` und `/` vom Host read-only in den Container.
- Kubernetes-Zugriff ist read-only auf `nodes` und `pods` beschraenkt.
- Es wird weder `privileged` noch `hostNetwork` oder `hostPID` benoetigt.

## Pruefen

Nach dem Rollout:

```bash
kubectl get ds -n ops-monitoring pi-oled
kubectl get pods -n ops-monitoring -o wide | grep pi-oled
kubectl logs -n ops-monitoring daemonset/pi-oled
```
