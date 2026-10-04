# Home Assistant

Home Assistant (Container, no OS/Supervisor) is available at
`https://ha.intern.rohrbom.be`. It runs `ghcr.io/home-assistant/home-assistant`
pinned to a stable release (`2026.9.4`), one replica with a `Recreate`
strategy, on the regular cluster network (no host networking, no special
VLAN interfaces).

## Storage

- `/config`: 10 GiB Longhorn RWO volume (`home-assistant-config`,
  `longhorn-2r`) with daily backups and weekly trimming. The PVC carries
  `kustomize.toolkit.fluxcd.io/prune: disabled`, so the claim (and the
  volume) survive Flux pruning.

## Networking

Inbound is restricted by `netpol-ingress.yaml` to the `ingress-20` namespace
(the `nginx-internal` ingress pods) on port 8123. There is deliberately no
egress policy: Home Assistant needs to reach a variety of devices and APIs
in the LAN. Cross-VLAN discovery (mDNS/SSDP) is not set up; devices should
be added by IP or via other services.

## Initial setup (manual, one time)

Since 2026.8 the HTTP server is configured in the UI (Settings > System >
Network > HTTP server); the `http:` block in `configuration.yaml` is
deprecated and only imported on upgrades. Until the trusted proxy is
configured, Home Assistant rejects every request that carries an
`X-Forwarded-For` header with a 400 — i.e. everything coming through the
ingress. Direct pod access is unaffected.

1. Onboard via a temporary port-forward:

   ```bash
   kubectl -n svc-home-assistant port-forward svc/home-assistant 8123:8123
   ```

   then open `http://127.0.0.1:8123` and complete onboarding.

2. Tell Home Assistant to trust the ingress: Settings > System > Network >
   HTTP server:
   - **Trust X-Forwarded-For**: on
   - **Trusted proxies**: `10.42.0.0/16` (the cluster pod network; the
     ingress-20 pods are the only pods that can reach Home Assistant in
     the first place, see `netpol-ingress.yaml`)

   Saving restarts Home Assistant; confirm the new settings when prompted
   (they roll back after 5 minutes if not confirmed).

3. Verify via the ingress: `https://ha.intern.rohrbom.be`.

## Upgrades

Bump the `image:` tag in `deployment.yaml` to the next stable release.
Home Assistant migrates its database automatically on startup; the startup
probe allows up to 5 minutes for that.
