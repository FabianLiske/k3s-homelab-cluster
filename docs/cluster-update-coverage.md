# Live-Abgleich des Update-Katalogs

Stand: 2026-11-04T21:12:39.559593+01:00

Alle 166 laufenden Pods sind einer Update-Einheit und einer der vier
Kategorien zugeordnet. Zusätzlich geprüft: 67 Deployments (einschließlich
auf null skalierter), 19 DaemonSets, 4 CronJobs, 5 vorhandene
Jobs und 5 abgeschlossene Pods. Keine unzugeordneten Workloads im
Snapshot. Alte ReplicaSets wurden als Eigentümerketten berücksichtigt, nicht als
zusätzliche Update-Aufträge gezählt.

Das ist ein Abgleich der Kubernetes-Workloads und Images. Host-Prozesse, auf Nodes
installierte Pakete sowie innerhalb von Anwendungen installierte Plugins sind
nicht vollständig inventarisiert. K3s und seine eingebetteten Komponenten stehen
als eigener Cluster-Prüfauftrag im Katalog; ihre Node-Konfiguration wurde dabei
nicht vollständig geprüft.

Flannel läuft als separater DaemonSet. Die vorherige pauschale Zuordnung zum
K3s-Bundle ist korrigiert. Flannel und kube-vip haben kein aktives Manifest in
diesem Repo; vor Updates muss ihre Installationsquelle geklärt und versioniert
werden. Eine eventuelle zusätzliche eingebettete Flannel-Instanz lässt sich aus
den Kubernetes-Pods allein nicht ausschließen.

Longhorn-Hilfsimages, CSI-Komponenten, erzeugte Jobs und mehrere parallel laufende
Engine-Versionen gehören zur Longhorn-Einheit. Die Zuordnung ist kein Auftrag,
alte Engine-Versionen zu entfernen oder deren Verwendung zu ändern.

## Zuordnung der Controller

| Namespace | Art | Name | Update-Einheit | Kategorie |
| --- | --- | --- | --- | --- |
| cert-manager | Deployment | cert-manager-cert-manager | cert-manager | platform |
| cert-manager | Deployment | cert-manager-cert-manager-cainjector | cert-manager | platform |
| cert-manager | Deployment | cert-manager-cert-manager-webhook | cert-manager | platform |
| flux-system | Deployment | helm-controller | flux | platform |
| flux-system | Deployment | kustomize-controller | flux | platform |
| flux-system | Deployment | notification-controller | flux | platform |
| flux-system | Deployment | source-controller | flux | platform |
| ingress-10 | DaemonSet | ingress-10-ingress-10-ingress-nginx-controller | ingress-nginx | platform |
| ingress-100 | DaemonSet | ingress-100-ingress-100-ingress-nginx-controller | ingress-nginx | platform |
| ingress-20 | DaemonSet | ingress-20-ingress-20-ingress-nginx-controller | ingress-nginx | platform |
| ingress-30 | DaemonSet | ingress-30-ingress-30-ingress-nginx-controller | ingress-nginx | platform |
| intel-gpu-system | DaemonSet | intel-gpu-plugin | intel-gpu | platform |
| kube-flannel | DaemonSet | kube-flannel-ds | flannel | cluster |
| kube-system | DaemonSet | kube-vip-ds | kube-vip | cluster |
| kube-system | Deployment | coredns | k3s-bundled-components | cluster |
| kube-system | Deployment | local-path-provisioner | k3s-bundled-components | cluster |
| kube-system | Deployment | metrics-server | k3s-bundled-components | cluster |
| longhorn-system | CronJob | backup-daily | longhorn | platform |
| longhorn-system | CronJob | backup-hourly | longhorn | platform |
| longhorn-system | CronJob | trim-daily | longhorn | platform |
| longhorn-system | CronJob | trim-weekly | longhorn | platform |
| longhorn-system | DaemonSet | engine-image-ei-2f3240cb | longhorn | platform |
| longhorn-system | DaemonSet | engine-image-ei-3154f3aa | longhorn | platform |
| longhorn-system | DaemonSet | engine-image-ei-493e04e7 | longhorn | platform |
| longhorn-system | DaemonSet | engine-image-ei-75a03ec3 | longhorn | platform |
| longhorn-system | DaemonSet | engine-image-ei-a4d05f02 | longhorn | platform |
| longhorn-system | DaemonSet | longhorn-csi-plugin | longhorn | platform |
| longhorn-system | DaemonSet | longhorn-manager | longhorn | platform |
| longhorn-system | Deployment | csi-attacher | longhorn | platform |
| longhorn-system | Deployment | csi-provisioner | longhorn | platform |
| longhorn-system | Deployment | csi-resizer | longhorn | platform |
| longhorn-system | Deployment | csi-snapshotter | longhorn | platform |
| longhorn-system | Deployment | longhorn-driver-deployer | longhorn | platform |
| longhorn-system | Deployment | longhorn-global-manager | longhorn | platform |
| longhorn-system | Deployment | longhorn-ui | longhorn | platform |
| metallb-system | DaemonSet | speaker | metallb | platform |
| metallb-system | Deployment | controller | metallb | platform |
| ops-monitoring | DaemonSet | node-exporter | node-exporter | platform |
| ops-monitoring | DaemonSet | pi-oled | pi-oled | custom_image |
| ops-monitoring | DaemonSet | promtail | promtail | platform |
| ops-monitoring | DaemonSet | xpu-smi-exporter | xpu-smi-exporter | platform |
| ops-monitoring | Deployment | grafana | grafana | platform |
| ops-monitoring | Deployment | influxdb | influxdb | platform |
| ops-monitoring | Deployment | kube-state-metrics | kube-state-metrics | platform |
| ops-monitoring | Deployment | loki | loki | platform |
| ops-monitoring | Deployment | ping-exporter | ping-exporter | platform |
| ops-monitoring | Deployment | prometheus | prometheus | platform |
| ops-monitoring | Deployment | speedtest-exporter | speedtest-exporter | platform |
| ops-monitoring | Deployment | telegraf | telegraf | custom_image |
| ops-monitoring | Deployment | unpoller | unpoller | platform |
| svc-ddns | Deployment | cloudflare-ddns | cloudflare-ddns | platform |
| svc-games | Deployment | pelican | pelican | application |
| svc-home-assistant | Deployment | home-assistant | home-assistant | application |
| svc-homepage | Deployment | homepage | homepage | application |
| svc-image-compressor | Deployment | image-compressor | image-compressor | custom_image |
| svc-immich | Deployment | immich-database | immich.rohrbom.be | application |
| svc-immich | Deployment | immich-machine-learning | immich.rohrbom.be | application |
| svc-immich | Deployment | immich-redis | immich.rohrbom.be | application |
| svc-immich | Deployment | immich-server | immich.rohrbom.be | application |
| svc-jirafeau | Deployment | jirafeau | share.rohrbom.be | application |
| svc-jupyter | Deployment | jupyter | jupyter | application |
| svc-kochen | Deployment | kochen | kochen.mitschen.de | custom_image |
| svc-linkding | Deployment | linkding | linkding | application |
| svc-llm | Deployment | embeddings | embeddings | application |
| svc-llm | Deployment | litellm | litellm | application |
| svc-llm | Deployment | litellm-postgresql | litellm | application |
| svc-llm | Deployment | open-webui | open-webui | application |
| svc-llm | Deployment | open-webui-postgresql | open-webui | application |
| svc-llm | Deployment | unifi-mcp | unifi-mcp | custom_image |
| svc-llm | Deployment | vllm | vllm | application |
| svc-mampftracker | Deployment | mampftracker | mampf.rohrbom.be | custom_image |
| svc-media | Deployment | calibre | calibre | application |
| svc-media | Deployment | jellyfin | jellyfin | application |
| svc-media | Deployment | lidarr | lidarr | application |
| svc-media | Deployment | prowlarr | prowlarr | application |
| svc-media | Deployment | qbittorrent | qbittorrent | application |
| svc-media | Deployment | radarr | radarr | application |
| svc-media | Deployment | seerr | seerr | application |
| svc-media | Deployment | sonarr | sonarr | application |
| svc-paperless-ngx | Deployment | paperless-broker | paperless-ngx | application |
| svc-paperless-ngx | Deployment | paperless-db | paperless-ngx | application |
| svc-paperless-ngx | Deployment | paperless-gotenberg | paperless-ngx | application |
| svc-paperless-ngx | Deployment | paperless-tika | paperless-ngx | application |
| svc-paperless-ngx | Deployment | paperless-webserver | paperless-ngx | application |
| svc-stirling | Deployment | stirling-pdf | stirling-pdf | application |
| svc-trilium | Deployment | trilium | trilium.rohrbom.be | application |
| svc-vaultwarden | Deployment | vaultwarden | vault.rohrbom.be | application |
| svc-vaultwarden | Deployment | vaultwarden-admin-deny | vault.rohrbom.be | application |
