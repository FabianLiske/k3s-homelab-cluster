#!/usr/bin/env bash
# First installation on edge-1, as root, from a copy of this repository.
# Does not overwrite an existing installation. Reboots are not required.
#
# After installation, test HTTPS through all three VLANs and the public proxy.
# Only after those checks succeed, cancel the automatic rollback:
#   sudo systemctl stop edge-ingress-routing-rollback.timer
# The printed backup directory contains rollback.sh for manual removal later.
#
# Future edits: copy the five host files to their installed paths, validate
# with nft -c -f, then networkctl reload and systemctl reload
# edge-ingress-routing.service. Protect changes with a rollback timer again.
set -euo pipefail

[[ $EUID == 0 ]] || { echo 'Run as root on edge-1.' >&2; exit 1; }
[[ $(hostname -s) == edge-1 ]] || { echo 'This configuration is for edge-1.' >&2; exit 1; }
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
assets="$repo_root/infrastructure/hosts/edge-1"
unit=/etc/systemd/system/edge-ingress-routing.service
rules=/etc/nftables.d/edge-ingress-routing.nft

# These table IDs, priorities, paths and marks are reserved for this feature.
for path in "$unit" "$rules"; do
    [[ ! -e $path ]] || { echo "Already exists: $path" >&2; exit 1; }
done
if nft list table ip edge_ingress_routing >/dev/null 2>&1; then
    echo 'The nftables table already exists.' >&2; exit 1
fi
if systemctl is-active --quiet edge-ingress-routing-rollback.timer; then
    echo 'A previous rollback timer is still active.' >&2; exit 1
fi
for vlan in 10 20 30; do
    path="/etc/systemd/network/10-netplan-vlan$vlan.network.d/50-ingress-routing.conf"
    [[ ! -e $path ]] || { echo "Already exists: $path" >&2; exit 1; }
    [[ -f /run/systemd/network/10-netplan-vlan$vlan.network ]]
    ip link show "vlan$vlan" >/dev/null
    if ip -4 rule show | grep -q "^$((11000 + vlan)):"; then
        echo "Routing priority already used for VLAN $vlan" >&2; exit 1
    fi
    if [[ -n $(ip -4 route show table "$((10100 + vlan))" 2>/dev/null || true) ]]; then
        echo "Routing table already used for VLAN $vlan" >&2; exit 1
    fi
done
nft -c -f "$assets/edge-ingress-routing.nft"
systemd-analyze verify "$assets/edge-ingress-routing.service"

backup_dir="/var/backups/edge-ingress-routing/$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$backup_dir"
ip -4 rule show > "$backup_dir/ip-rule.before"
ip -4 route show table all > "$backup_dir/ip-route.before"
nft list ruleset > "$backup_dir/nftables.before"
cp -a /etc/netplan "$backup_dir/netplan.before"

cat > "$backup_dir/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
systemctl disable --now edge-ingress-routing.service || true
nft destroy table ip edge_ingress_routing
rm -f /etc/systemd/system/edge-ingress-routing.service
rm -f /etc/nftables.d/edge-ingress-routing.nft
for vlan in 10 20 30; do
    rm -f "/etc/systemd/network/10-netplan-vlan$vlan.network.d/50-ingress-routing.conf"
done
systemctl daemon-reload
networkctl reload
for vlan in 10 20 30; do
    printf -v mark '0x%02x000000' "$vlan"
    while ip -4 rule del priority "$((11000 + vlan))" fwmark "$mark/0xff000000" table "$((10100 + vlan))" 2>/dev/null; do :; done
    ip -4 route flush table "$((10100 + vlan))" 2>/dev/null || true
done
echo 'Edge ingress routing removed; original configuration restored.'
ROLLBACK
chmod 0700 "$backup_dir/rollback.sh"

systemd-run --unit=edge-ingress-routing-rollback --on-active=5m \
    --timer-property=AccuracySec=1s /bin/bash "$backup_dir/rollback.sh"
trap 'bash "$backup_dir/rollback.sh"; systemctl stop edge-ingress-routing-rollback.timer' ERR

install -D -m 0644 "$assets/edge-ingress-routing.nft" "$rules"
install -D -m 0644 "$assets/edge-ingress-routing.service" "$unit"
for vlan in 10 20 30; do
    install -D -m 0644 "$assets/vlan$vlan-routing.conf" \
        "/etc/systemd/network/10-netplan-vlan$vlan.network.d/50-ingress-routing.conf"
done
systemctl daemon-reload
networkctl reload

# Wait for networkd to install the routes/rules before marking any traffic.
for vlan in 10 20 30; do
    ready=false
    for attempt in {1..20}; do
        if ip -4 rule show | grep -q "^$((11000 + vlan)):" && \
            ip -4 route show table "$((10100 + vlan))" | grep -q "^default via 172.26.$vlan.1 dev vlan$vlan"; then
            ready=true
            break
        fi
        sleep 1
    done
    "$ready" || { echo "VLAN $vlan routing did not become ready." >&2; false; }
done
systemctl enable --now edge-ingress-routing.service
echo "Installed. Automatic rollback in five minutes unless timer is stopped."
echo "Backup and manual rollback: $backup_dir/rollback.sh"
ip -4 rule show
