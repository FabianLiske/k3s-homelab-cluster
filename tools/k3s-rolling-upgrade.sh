#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

PROGRAM=${0##*/}
SSH_USER=faba
IDENTITY_FILE=${HOME}/.ssh/id_ed25519
KUBECONFIG_FILE=${KUBECONFIG:-}
KUBE_CONTEXT=
K3S_VERSION=
K3S_CHANNEL=stable
BACKUP_DIR=${XDG_STATE_HOME:-${HOME}/.local/state}/k3s-upgrade/backups
NODES_CSV=
DRY_RUN=false
ASSUME_YES=false
SKIP_OS=false
SKIP_K3S=false
ALLOW_VERSION_SKEW=false
DRAIN_TIMEOUT=900
REBOOT_TIMEOUT=900
READY_TIMEOUT=600

declare -a KUBECTL=()
declare -a SSH_BASE=()
declare -a SELECTED_NODES=()
declare -a SERVER_NODES=()
declare -a AGENT_NODES=()
declare -A SSH_HOST_OVERRIDES=()
declare -A NODE_IPS=()
declare -A NODE_ROLES=()
declare -A NODE_WAS_UNSCHEDULABLE=()
declare -A NODE_LEASE_BEFORE=()
ACTIVE_NODE=
BACKUP_RUN_DIR=

usage() {
  cat <<EOF
Sicheres, serielles OS- und K3s-Upgrade aller Cluster-Nodes per SSH.

Aufruf:
  $PROGRAM [Optionen]

Wichtige Optionen:
  --k3s-version VERSION    Exakte Zielversion, z. B. v1.33.3+k3s1
  --k3s-channel CHANNEL    K3s-Channel (Default: stable); wird nur verwendet,
                           wenn keine exakte Version angegeben wurde
  --nodes N1,N2            Nur diese Nodes aktualisieren
  --ssh-host NODE=HOST     SSH-Ziel fuer eine Node ueberschreiben (wiederholbar)
  --ssh-user USER          SSH-User (Default: faba)
  --identity FILE          SSH-Key (Default: ~/.ssh/id_ed25519)
  --kubeconfig FILE        Abweichende kubeconfig verwenden
  --context NAME           Abweichenden kubectl-Kontext verwenden
  --backup-dir DIR         Lokales Ziel fuer etcd-Snapshot und Server-Token
  --drain-timeout SEC      Drain-Timeout (Default: 900)
  --reboot-timeout SEC     Reboot-/SSH-Timeout (Default: 900)
  --ready-timeout SEC      Kubernetes-Ready-Timeout (Default: 600)
  --skip-os                Keine APT-Pakete aktualisieren
  --skip-k3s               K3s nicht aktualisieren (keine Versionsermittlung)
  --allow-version-skew     Schutz gegen Downgrade/uebersprungene Minor-Version
                           deaktivieren (nur fuer bewusste Sonderfaelle)
  --dry-run                Nur Discovery und Pruefungen, keine Aenderungen
  --yes                    Einmalige Sicherheitsabfrage ueberspringen
  -h, --help               Diese Hilfe anzeigen

Ohne --nodes werden alle von kubectl gemeldeten Nodes bearbeitet. Control-Plane-
Nodes kommen immer zuerst und einzeln, danach Agents. Bereits vorher cordonte
Nodes werden am Ende nicht automatisch uncordoned.
EOF
}

timestamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '[%s] %s\n' "$(timestamp)" "$*"; }
warn() { printf '[%s] WARNUNG: %s\n' "$(timestamp)" "$*" >&2; }
die() { printf '[%s] FEHLER: %s\n' "$(timestamp)" "$*" >&2; exit 1; }

on_exit() {
  local status=$?
  if (( status != 0 )) && [[ -n $ACTIVE_NODE ]]; then
    warn "Abbruch bei Node ${ACTIVE_NODE}. Sie bleibt absichtlich cordoned."
    if [[ ${NODE_WAS_UNSCHEDULABLE[$ACTIVE_NODE]:-false} != true ]]; then
      warn "Nach der Fehlerbehebung: kubectl get node ${ACTIVE_NODE} && kubectl uncordon ${ACTIVE_NODE}"
    fi
  fi
}
trap on_exit EXIT

require_value() {
  [[ $# -ge 2 && -n ${2:-} ]] || die "Option $1 benoetigt einen Wert."
}

while (( $# > 0 )); do
  case $1 in
    --k3s-version) require_value "$@"; K3S_VERSION=$2; shift 2 ;;
    --k3s-channel) require_value "$@"; K3S_CHANNEL=$2; shift 2 ;;
    --nodes) require_value "$@"; NODES_CSV=$2; shift 2 ;;
    --ssh-host)
      require_value "$@"
      [[ $2 == *=* ]] || die "--ssh-host erwartet NODE=HOST."
      SSH_HOST_OVERRIDES[${2%%=*}]=${2#*=}
      shift 2
      ;;
    --ssh-user) require_value "$@"; SSH_USER=$2; shift 2 ;;
    --identity) require_value "$@"; IDENTITY_FILE=$2; shift 2 ;;
    --kubeconfig) require_value "$@"; KUBECONFIG_FILE=$2; shift 2 ;;
    --context) require_value "$@"; KUBE_CONTEXT=$2; shift 2 ;;
    --backup-dir) require_value "$@"; BACKUP_DIR=$2; shift 2 ;;
    --drain-timeout) require_value "$@"; DRAIN_TIMEOUT=$2; shift 2 ;;
    --reboot-timeout) require_value "$@"; REBOOT_TIMEOUT=$2; shift 2 ;;
    --ready-timeout) require_value "$@"; READY_TIMEOUT=$2; shift 2 ;;
    --skip-os) SKIP_OS=true; shift ;;
    --skip-k3s) SKIP_K3S=true; shift ;;
    --allow-version-skew) ALLOW_VERSION_SKEW=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --yes) ASSUME_YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
done

for timeout in "$DRAIN_TIMEOUT" "$REBOOT_TIMEOUT" "$READY_TIMEOUT"; do
  [[ $timeout =~ ^[1-9][0-9]*$ ]] || die "Timeouts muessen positive Ganzzahlen sein."
done
[[ $SSH_USER =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || die "Ungueltiger SSH-User: $SSH_USER"
[[ $K3S_CHANNEL =~ ^[a-zA-Z0-9._-]+$ ]] || die "Ungueltiger K3s-Channel: $K3S_CHANNEL"
if $SKIP_OS && $SKIP_K3S; then
  die "--skip-os und --skip-k3s zusammen ergeben kein Upgrade."
fi

for command in kubectl ssh curl sha256sum sort awk sed; do
  command -v "$command" >/dev/null 2>&1 || die "Lokales Kommando fehlt: $command"
done
[[ -r $IDENTITY_FILE ]] || die "SSH-Key ist nicht lesbar: $IDENTITY_FILE"

KUBECTL=(kubectl)
[[ -n $KUBECONFIG_FILE ]] && KUBECTL+=(--kubeconfig "$KUBECONFIG_FILE")
[[ -n $KUBE_CONTEXT ]] && KUBECTL+=(--context "$KUBE_CONTEXT")

SSH_BASE=(
  ssh -i "$IDENTITY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes
  -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
)
kube() { "${KUBECTL[@]}" "$@"; }

ssh_host_for() {
  local node=$1
  printf '%s' "${SSH_HOST_OVERRIDES[$node]:-${NODE_IPS[$node]}}"
}

ssh_node() {
  local node=$1
  shift
  "${SSH_BASE[@]}" "${SSH_USER}@$(ssh_host_for "$node")" "$@"
}

resolve_channel_version() {
  local effective
  log "Ermittle Zielversion aus K3s-Channel '${K3S_CHANNEL}' ..."
  effective=$(curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
    -o /dev/null -w '%{url_effective}' \
    "https://update.k3s.io/v1-release/channels/${K3S_CHANNEL}") \
    || die "K3s-Channel '${K3S_CHANNEL}' konnte nicht aufgeloest werden."
  K3S_VERSION=${effective##*/}
  K3S_VERSION=${K3S_VERSION//%2B/+}
  K3S_VERSION=${K3S_VERSION//%2b/+}
}

validate_k3s_version() {
  [[ $K3S_VERSION =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)\+k3s([0-9]+)$ ]] \
    || die "Ungueltige K3s-Version '$K3S_VERSION' (erwartet: vX.Y.Z+k3sN)."
}

version_lt() {
  local first
  first=$(printf '%s\n%s\n' "$1" "$2" | sort -V | sed -n '1p')
  [[ $first == "$1" && $1 != "$2" ]]
}

discover_nodes() {
  local node labels ip ready unsched version
  local -a all_nodes requested
  local -A requested_set=() discovered_set=()

  kube get --raw=/readyz >/dev/null || die "Kubernetes API ist nicht Ready."
  mapfile -t all_nodes < <(kube get nodes -o name | sed 's#^node/##')
  (( ${#all_nodes[@]} > 0 )) || die "kubectl meldet keine Nodes."

  if [[ -n $NODES_CSV ]]; then
    IFS=',' read -r -a requested <<<"$NODES_CSV"
    for node in "${requested[@]}"; do
      [[ $node =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || die "Ungueltiger Node-Name: $node"
      requested_set[$node]=1
    done
  fi

  for node in "${all_nodes[@]}"; do
    discovered_set[$node]=1
    if [[ -n $NODES_CSV && -z ${requested_set[$node]:-} ]]; then
      continue
    fi

    ip=$(kube get node "$node" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
    ready=$(kube get node "$node" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
    unsched=$(kube get node "$node" -o jsonpath='{.spec.unschedulable}')
    version=$(kube get node "$node" -o jsonpath='{.status.nodeInfo.kubeletVersion}')
    labels=$(kube get node "$node" -o jsonpath='{.metadata.labels}')

    [[ -n $ip ]] || die "Node $node hat keine InternalIP."
    [[ $ready == True ]] || die "Node $node ist vor dem Upgrade nicht Ready."
    [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+\+k3s[0-9]+$ ]] \
      || die "Node $node meldet eine unerwartete Version: $version"

    NODE_IPS[$node]=$ip
    NODE_WAS_UNSCHEDULABLE[$node]=${unsched:-false}
    if [[ $labels == *node-role.kubernetes.io/control-plane* \
       || $labels == *node-role.kubernetes.io/master* \
       || $labels == *node-role.kubernetes.io/etcd* ]]; then
      NODE_ROLES[$node]=server
      SERVER_NODES+=("$node")
    else
      NODE_ROLES[$node]=agent
      AGENT_NODES+=("$node")
    fi
    NODE_VERSIONS[$node]=$version
  done

  if [[ -n $NODES_CSV ]]; then
    for node in "${requested[@]}"; do
      [[ -n ${discovered_set[$node]:-} ]] || die "Ausgewaehlte Node existiert nicht im Cluster: $node"
    done
  fi

  SELECTED_NODES=("${SERVER_NODES[@]}" "${AGENT_NODES[@]}")
  (( ${#SELECTED_NODES[@]} > 0 )) || die "Keine Nodes ausgewaehlt."
}

declare -A NODE_VERSIONS=()

validate_version_plan() {
  local node current current_minor target_minor
  $SKIP_K3S && return 0
  [[ -n $K3S_VERSION ]] || resolve_channel_version
  validate_k3s_version
  target_minor=${BASH_REMATCH[2]}

  $ALLOW_VERSION_SKEW && return 0
  for node in "${SELECTED_NODES[@]}"; do
    current=${NODE_VERSIONS[$node]}
    [[ $current =~ ^v[0-9]+\.([0-9]+)\. ]] || die "Version von $node kann nicht gelesen werden."
    current_minor=${BASH_REMATCH[1]}
    if version_lt "$K3S_VERSION" "$current"; then
      die "Downgrade abgelehnt: $node laeuft auf $current, Ziel ist $K3S_VERSION."
    fi
    if (( target_minor > current_minor + 1 )); then
      die "Minor-Version wuerde auf $node uebersprungen ($current -> $K3S_VERSION). Erst eine Zwischenversion installieren."
    fi
  done
}

remote_preflight() {
  local node=$1 expected_role=${NODE_ROLES[$1]} output remote_role remote_version
  log "SSH-/sudo-Preflight auf ${node} ($(ssh_host_for "$node")) ..."
  output=$(ssh_node "$node" 'bash -s' <<'REMOTE'
set -Eeuo pipefail
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || { echo "Nur Ubuntu wird unterstuetzt (gefunden: ${ID:-unbekannt})." >&2; exit 1; }
for command in curl sha256sum systemctl apt-get find awk install; do
  command -v "$command" >/dev/null || { echo "Kommando fehlt: $command" >&2; exit 1; }
done
sudo -n true
if systemctl is-active --quiet k3s; then
  role=server
elif systemctl is-active --quiet k3s-agent; then
  role=agent
else
  echo "Weder k3s noch k3s-agent ist aktiv." >&2
  exit 1
fi
available_kb=$(df -Pk / | awk 'NR==2 {print $4}')
(( available_kb >= 1048576 )) || { echo "Weniger als 1 GiB frei auf /." >&2; exit 1; }
version=$(k3s --version | awk 'NR==1 {print $3}')
printf '%s\t%s\n' "$role" "$version"
REMOTE
  ) || die "Remote-Preflight auf $node fehlgeschlagen."
  IFS=$'\t' read -r remote_role remote_version <<<"$output"
  [[ $remote_role == "$expected_role" ]] \
    || die "Rollen-Konflikt fuer $node: Kubernetes=$expected_role, systemd=$remote_role."
  [[ $remote_version == "${NODE_VERSIONS[$node]}" ]] \
    || die "Versions-Konflikt fuer $node: Kubernetes=${NODE_VERSIONS[$node]}, Host=$remote_version."
}

show_plan() {
  local node target
  target=$K3S_VERSION
  $SKIP_K3S && target='uebersprungen'
  printf '\nUpgrade-Plan\n'
  printf '  K3s-Ziel:   %s\n' "$target"
  printf '  OS-Upgrade: %s\n' "$([[ $SKIP_OS == true ]] && echo nein || echo ja)"
  printf '  Backup:     %s\n' "$BACKUP_DIR"
  printf '  Reihenfolge:\n'
  for node in "${SELECTED_NODES[@]}"; do
    printf '    - %-16s %-6s SSH=%-15s aktuell=%s%s\n' \
      "$node" "${NODE_ROLES[$node]}" "$(ssh_host_for "$node")" "${NODE_VERSIONS[$node]}" \
      "$([[ ${NODE_WAS_UNSCHEDULABLE[$node]} == true ]] && echo ' (bleibt cordoned)' || true)"
  done
  printf '\n'
}

confirm_plan() {
  $DRY_RUN && return 0
  $ASSUME_YES && return 0
  local answer
  warn "Drain mit --delete-emptydir-data entfernt temporaere emptyDir-Daten. PodDisruptionBudgets werden respektiert; --force wird nicht benutzt."
  read -r -p "Diesen Plan jetzt ausfuehren? [j/N] " answer
  [[ $answer == j || $answer == J || $answer == ja || $answer == JA \
     || $answer == y || $answer == Y || $answer == yes || $answer == YES ]] \
    || die "Vom Benutzer abgebrochen."
}

download_remote_file() {
  local node=$1 remote_path=$2 local_path=$3 partial=${3}.partial
  [[ $remote_path =~ ^/[a-zA-Z0-9_./+:-]+$ ]] || die "Unsicherer Remote-Pfad abgelehnt: $remote_path"
  ssh_node "$node" "sudo -n cat -- '$remote_path'" >"$partial" \
    || { rm -f -- "$partial"; die "Download von $remote_path auf $node fehlgeschlagen."; }
  [[ -s $partial ]] || { rm -f -- "$partial"; die "Heruntergeladene Datei ist leer: $remote_path"; }
  chmod 600 "$partial"
  mv -f -- "$partial" "$local_path"
}

backup_datastore() {
  local node=$1 run_id snapshot_name remote_snapshot local_snapshot remote_sha local_sha
  run_id=$(date -u +%Y%m%dT%H%M%SZ)
  BACKUP_RUN_DIR=${BACKUP_DIR%/}/${run_id}-${K3S_VERSION//+/_}
  mkdir -p -m 700 "$BACKUP_RUN_DIR"
  snapshot_name=pre-upgrade-${run_id}

  log "Erzeuge etcd-Snapshot auf $node ..."
  remote_snapshot=$(ssh_node "$node" 'bash -s' -- "$snapshot_name" <<'REMOTE'
set -Eeuo pipefail
name=$1
snapshot_dir=/var/lib/rancher/k3s/server/db/snapshots
sudo -n k3s etcd-snapshot save --name "$name" >/dev/null
snapshot=$(sudo -n find "$snapshot_dir" -maxdepth 1 -type f -name "${name}*" -printf '%T@ %p\n' \
  | sort -nr | awk 'NR==1 {$1=""; sub(/^ /, ""); print}')
[[ -n $snapshot ]] || { echo "Snapshot-Datei wurde nicht gefunden." >&2; exit 1; }
printf '%s\n' "$snapshot"
REMOTE
  ) || die "etcd-Snapshot auf $node fehlgeschlagen. Ist embedded etcd aktiv?"

  local_snapshot=${BACKUP_RUN_DIR}/$(basename "$remote_snapshot")
  log "Lade etcd-Snapshot nach $local_snapshot ..."
  download_remote_file "$node" "$remote_snapshot" "$local_snapshot"
  remote_sha=$(ssh_node "$node" "sudo -n sha256sum -- '$remote_snapshot'" | awk '{print $1}')
  local_sha=$(sha256sum "$local_snapshot" | awk '{print $1}')
  [[ -n $remote_sha && $remote_sha == "$local_sha" ]] || die "Checksumme des etcd-Snapshots stimmt nicht."

  log "Sichere den fuer eine Wiederherstellung notwendigen K3s-Server-Token ..."
  download_remote_file "$node" /var/lib/rancher/k3s/server/token "${BACKUP_RUN_DIR}/server-token"
  printf '%s  %s\n' "$local_sha" "$(basename "$local_snapshot")" >"${BACKUP_RUN_DIR}/SHA256SUMS"
  chmod 600 "${BACKUP_RUN_DIR}/SHA256SUMS"
  log "Backup verifiziert: $BACKUP_RUN_DIR"
}

cordon_and_drain() {
  local node=$1
  log "Cordon $node ..."
  kube cordon "$node"
  log "Drain $node (PDBs werden respektiert, kein --force) ..."
  kube drain "$node" \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --timeout="${DRAIN_TIMEOUT}s"
}

upgrade_os() {
  local node=$1
  $SKIP_OS && { log "APT-Upgrade auf $node uebersprungen."; return 0; }
  log "APT update/full-upgrade auf $node ..."
  ssh_node "$node" 'bash -s' <<'REMOTE'
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=l
sudo -n --preserve-env=DEBIAN_FRONTEND,NEEDRESTART_MODE \
  apt-get -o DPkg::Lock::Timeout=300 update
sudo -n --preserve-env=DEBIAN_FRONTEND,NEEDRESTART_MODE \
  apt-get -y -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confold full-upgrade
REMOTE
}

upgrade_k3s() {
  local node=$1 current=${NODE_VERSIONS[$1]}
  $SKIP_K3S && { log "K3s-Upgrade auf $node uebersprungen."; return 0; }
  if [[ $current == "$K3S_VERSION" ]]; then
    log "$node laeuft bereits auf $K3S_VERSION; Binary-Download uebersprungen."
    return 0
  fi

  log "Lade und verifiziere K3s $K3S_VERSION auf $node ..."
  ssh_node "$node" 'bash -s' -- "$K3S_VERSION" <<'REMOTE'
set -Eeuo pipefail
version=$1
case $(uname -m) in
  x86_64) asset=k3s; checksum_file=sha256sum-amd64.txt ;;
  aarch64|arm64) asset=k3s-arm64; checksum_file=sha256sum-arm64.txt ;;
  armv7l|armv7) asset=k3s-armhf; checksum_file=sha256sum-arm.txt ;;
  s390x) asset=k3s-s390x; checksum_file=sha256sum-s390x.txt ;;
  *) echo "Nicht unterstuetzte Architektur: $(uname -m)" >&2; exit 1 ;;
esac

workdir=$(mktemp -d /tmp/k3s-upgrade.XXXXXX)
trap 'rm -rf -- "$workdir"' EXIT
version_urlsafe=${version//+/%2B}
base_url="https://github.com/k3s-io/k3s/releases/download/${version_urlsafe}"
curl --proto '=https' --tlsv1.2 -fL --retry 5 --retry-delay 2 --retry-connrefused \
  -o "$workdir/$asset" "$base_url/$asset"
curl --proto '=https' --tlsv1.2 -fL --retry 5 --retry-delay 2 --retry-connrefused \
  -o "$workdir/$checksum_file" "$base_url/$checksum_file"
expected=$(awk -v wanted="$asset" '$2 == wanted || $2 == "*" wanted {print $1; exit}' \
  "$workdir/$checksum_file")
actual=$(sha256sum "$workdir/$asset" | awk '{print $1}')
[[ -n $expected && $actual == "$expected" ]] \
  || { echo "K3s-SHA256-Pruefung fehlgeschlagen." >&2; exit 1; }
chmod 0755 "$workdir/$asset"
downloaded_version=$("$workdir/$asset" --version | awk 'NR==1 {print $3}')
[[ $downloaded_version == "$version" ]] \
  || { echo "Download meldet $downloaded_version statt $version." >&2; exit 1; }

binary=$(readlink -f "$(command -v k3s)")
binary_dir=$(dirname "$binary")
backup="${binary}.pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ)"
sudo -n cp -a -- "$binary" "$backup"
sudo -n install -o root -g root -m 0755 "$workdir/$asset" "$binary_dir/.k3s.upgrade-new"
sudo -n mv -f -- "$binary_dir/.k3s.upgrade-new" "$binary"
[[ "$(k3s --version | awk 'NR==1 {print $3}')" == "$version" ]]
printf 'Altes Binary: %s\n' "$backup"
REMOTE
}

reboot_node() {
  local node=$1 old_boot_id deadline boot_id last_notice=0
  NODE_LEASE_BEFORE[$node]=$(kube get lease -n kube-node-lease "$node" -o jsonpath='{.spec.renewTime}')
  [[ -n ${NODE_LEASE_BEFORE[$node]} ]] || die "Kubelet-Lease von $node konnte nicht gelesen werden."
  old_boot_id=$(ssh_node "$node" 'cat /proc/sys/kernel/random/boot_id')
  log "Reboot $node ..."
  ssh_node "$node" 'sudo -n systemctl reboot' >/dev/null 2>&1 || true

  deadline=$(( SECONDS + REBOOT_TIMEOUT ))
  while (( SECONDS < deadline )); do
    boot_id=$(ssh_node "$node" 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || true)
    if [[ -n $boot_id && $boot_id != "$old_boot_id" ]]; then
      log "$node ist per SSH wieder erreichbar (neue Boot-ID)."
      return 0
    fi
    if (( SECONDS - last_notice >= 15 )); then
      log "Warte auf Reboot von $node ..."
      last_notice=$SECONDS
    fi
    sleep 5
  done
  die "$node kam nach ${REBOOT_TIMEOUT}s nicht mit neuer Boot-ID zurueck."
}

wait_until_ready() {
  local node=$1 service expected_version deadline actual_version lease_now last_notice=0
  [[ ${NODE_ROLES[$node]} == server ]] && service=k3s || service=k3s-agent
  log "Warte auf systemd-Service $service auf $node ..."
  deadline=$(( SECONDS + READY_TIMEOUT ))
  while (( SECONDS < deadline )); do
    if ssh_node "$node" "sudo -n systemctl is-active --quiet '$service'" 2>/dev/null; then
      break
    fi
    sleep 5
  done
  ssh_node "$node" "sudo -n systemctl is-active --quiet '$service'" \
    || die "$service ist auf $node nicht aktiv."

  log "Warte auf ein neues Kubelet-Lease von $node ..."
  deadline=$(( SECONDS + READY_TIMEOUT ))
  while (( SECONDS < deadline )); do
    lease_now=$(kube get lease -n kube-node-lease "$node" -o jsonpath='{.spec.renewTime}' 2>/dev/null || true)
    [[ -n $lease_now && $lease_now != "${NODE_LEASE_BEFORE[$node]}" ]] && break
    sleep 5
  done
  [[ -n $lease_now && $lease_now != "${NODE_LEASE_BEFORE[$node]}" ]] \
    || die "Kubelet-Lease von $node wurde nach dem Reboot nicht erneuert."

  log "Warte auf Kubernetes-Condition Ready fuer $node ..."
  kube wait --for=condition=Ready "node/$node" --timeout="${READY_TIMEOUT}s"

  if ! $SKIP_K3S; then
    expected_version=$K3S_VERSION
    deadline=$(( SECONDS + READY_TIMEOUT ))
    while (( SECONDS < deadline )); do
      actual_version=$(kube get node "$node" -o jsonpath='{.status.nodeInfo.kubeletVersion}' 2>/dev/null || true)
      [[ $actual_version == "$expected_version" ]] && break
      if (( SECONDS - last_notice >= 15 )); then
        log "Warte auf Versionsmeldung $expected_version von $node (aktuell: ${actual_version:-unbekannt}) ..."
        last_notice=$SECONDS
      fi
      sleep 5
    done
    [[ $actual_version == "$expected_version" ]] \
      || die "$node meldet $actual_version statt $expected_version."
  fi
}

uncordon_if_needed() {
  local node=$1
  if [[ ${NODE_WAS_UNSCHEDULABLE[$node]} == true ]]; then
    log "$node war schon vor dem Lauf cordoned und bleibt es."
  else
    log "Uncordon $node ..."
    kube uncordon "$node"
  fi
}

verify_cluster_ready() {
  local not_ready
  kube get --raw=/readyz >/dev/null || die "Kubernetes API ist nach dem Node-Upgrade nicht Ready."
  not_ready=$(kube get nodes --no-headers | awk '$2 !~ /^Ready/ {print $1 ":" $2}')
  [[ -z $not_ready ]] || die "Nicht alle Cluster-Nodes sind Ready: $not_ready"
}

main() {
  local node backup_server
  log "Pruefe Cluster und ermittle Nodes ..."
  discover_nodes
  validate_version_plan
  for node in "${SELECTED_NODES[@]}"; do
    remote_preflight "$node"
  done
  show_plan

  if $DRY_RUN; then
    log "Dry-Run erfolgreich. Es wurden keine Cluster- oder Node-Aenderungen vorgenommen."
    return 0
  fi
  confirm_plan

  if (( ${#SERVER_NODES[@]} > 0 )); then
    backup_server=${SERVER_NODES[0]}
  else
    mapfile -t SERVER_NODES < <(kube get nodes -o name | sed 's#^node/##' | while read -r node; do
      labels=$(kube get node "$node" -o jsonpath='{.metadata.labels}')
      [[ $labels == *node-role.kubernetes.io/control-plane* || $labels == *node-role.kubernetes.io/etcd* ]] && printf '%s\n' "$node"
    done)
    (( ${#SERVER_NODES[@]} > 0 )) || die "Kein Control-Plane-Node fuer das etcd-Backup gefunden."
    backup_server=${SERVER_NODES[0]}
    NODE_IPS[$backup_server]=$(kube get node "$backup_server" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
  fi
  backup_datastore "$backup_server"

  for node in "${SELECTED_NODES[@]}"; do
    ACTIVE_NODE=$node
    log "===== Beginne ${node} (${NODE_ROLES[$node]}) ====="
    verify_cluster_ready
    cordon_and_drain "$node"
    upgrade_os "$node"
    upgrade_k3s "$node"
    reboot_node "$node"
    wait_until_ready "$node"
    uncordon_if_needed "$node"
    verify_cluster_ready
    log "===== ${node} erfolgreich abgeschlossen ====="
    ACTIVE_NODE=
  done

  log "Alle ausgewaehlten Nodes wurden erfolgreich aktualisiert."
  log "Etcd-Snapshot und Server-Token: $BACKUP_RUN_DIR"
  kube get nodes -o wide
}

main
