# Pi OLED DaemonSet

`pi-oled` laeuft als DaemonSet im Namespace `ops-monitoring` und zeigt lokale Pi- und Kubernetes-Informationen auf einem SSD1306-OLED an.

## Ziel-Nodes

Das DaemonSet laeuft auf `arm64`-Nodes, die explizit als OLED-faehig gelabelt sind:

- `cp-2`
- `cp-3`
- `wk-1`
- `wk-2`
- `wk-3`

Die Control-Plane-Nodes werden ueber eine `NoSchedule`-Toleration bewusst mit abgedeckt.

Node-Label:

```bash
kubectl label node <node> pi-oled.rohrbom.be/enabled=true
```

Wenn ein OLED fehlt, falsch verkabelt ist oder am I2C-Bus nicht antwortet, darf dieses Label nicht gesetzt sein. Sonst startet der Pod in einen I2C-Timeout-CrashLoop.

## Voraussetzungen pro Node

- I2C ist auf dem Host aktiviert.
- Das OLED ist als SSD1306 an `/dev/i2c-1` erreichbar.
- Der Node ist mit `pi-oled.rohrbom.be/enabled=true` gelabelt.
- Das private GHCR-Image `ghcr.io/fabianliske/pi-sysinfo-oled:latest` ist ueber das Secret `ghcr-cred` im Namespace `ops-monitoring` pullbar.

## Laufzeitverhalten

- Das DaemonSet mountet `/dev/i2c-1`, `/proc`, `/sys` und `/` vom Host read-only in den Container.
- Kubernetes-Zugriff ist read-only auf `nodes` und `pods` beschraenkt.
- Der Container laeuft `privileged`, damit der Zugriff auf das I2C-Character-Device `/dev/i2c-1` auf den Pis funktioniert.
- Es wird weiterhin weder `hostNetwork` noch `hostPID` benoetigt.

## Pruefen

Nach dem Rollout:

```bash
kubectl get ds -n ops-monitoring pi-oled
kubectl get pods -n ops-monitoring -o wide | grep pi-oled
kubectl logs -n ops-monitoring daemonset/pi-oled
```
