# Cluster Health

## Node Health (from node-exporter)

- `node_cpu_seconds_total`: CPU usage per core.
```promql
1 - avg by (node) (
  label_replace(
    rate(node_cpu_seconds_total{mode="idle", instance=~"cp-1:9100|cp-2:9100|cp-3:9100"}[5m]),
    "node", "$1", "instance", "(.+):\\d+"
  )
)
```
- `node_memory_MemAvailable_bytes`: Available memory.
```promql
1 - (
  sum by (node) (label_replace(node_memory_MemAvailable_bytes{instance=~"cp-1:9100|cp-2:9100|cp-3:9100"}, "node", "$1", "instance", "(.+):\\d+")) /
  sum by (node) (label_replace(node_memory_MemTotal_bytes{instance=~"cp-1:9100|cp-2:9100|cp-3:9100"}, "node", "$1", "instance", "(.+):\\d+"))
)
```
- `node_filesystem_free_bytes`: Free disk space.
```promql
1 - (label_replace(node_filesystem_free_bytes{mountpoint="/", instance=~"cp-1:9100|cp-2:9100|cp-3:9100"}, "node", "$1", "instance", "(.+):\\d+") / label_replace(node_filesystem_size_bytes{mountpoint="/", instance=~"cp-1:9100|cp-2:9100|cp-3:9100"}, "node", "$1", "instance", "(.+):\\d+"))
```

## Kubernetes API Server (from kubernetes-apiserver)

- `apiserver_request_duration_seconds`: Latency of API requests.
```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|WATCHLIST|CONNECT"}[1m])
  )
)
```
- `apiserver_request_total`: Total number of requests.
```promql
sum by(verb) (rate(apiserver_request_total{verb=~"PUT|GET"}[5m]))
```

## Cluster State (from kube-state-metrics)

- `kube_node_status_condition`: Node readiness and conditions.
- `kube_pod_status_ready`: Pod readiness status.
- `kube_deployment_status_replicas_available`: Available replicas in deployments.
```promql
sum(kube_deployment_status_replicas_available)
/
sum(kube_deployment_status_replicas_available + kube_deployment_status_replicas_unavailable)
```

## DNS Health (from coredns)

- `coredns_dns_request_duration_seconds`: DNS query latency.
- `coredns_dns_responses_total`: Number of DNS responses.

## Ingress Health (from nginx-ingress)

- `nginx_ingress_controller_requests`: Number of requests handled.
- `nginx_ingress_controller_response_time_seconds`: Response time.

## Longhorn Storage (from longhorn)

- `longhorn_volume_status`: Volume health status.
- `longhorn_node_status`: Node storage health.

## Prometheus Health

- `prometheus_target_interval_length_seconds`: Scrape interval health.
- `prometheus_tsdb_head_samples_appended_total`: Sample ingestion rate.
