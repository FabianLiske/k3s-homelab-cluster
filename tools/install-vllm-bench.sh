#!/usr/bin/env bash

set -Eeuo pipefail

PROGRAM=${0##*/}
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BIN_DIR="${REPO_ROOT}/tools/.bin"
BIN_PATH="${BIN_DIR}/vllm-bench"
VERSION=${VLLM_BENCH_VERSION:-latest}

usage() {
  cat <<EOF
Laedt das vllm-bench-Release-Binary (Rust-CLI des vLLM-Projekts) nach
${BIN_PATH}. Kein Python/Torch/GPU noetig, nur ein einzelnes statisches
Binary fuer die lokale Plattform.

Usage: ${PROGRAM} [--version vX.Y.Z]

  --version   vllm-bench-Release (Default: latest). Das Standalone-Repo
              vllm-project/vllm-bench ist archiviert; falls das gepinnte
              Release fehlschlaegt, aktueller Stand ist jetzt
              vllm-project/vllm unter rust/src/bench (per cargo bauen).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

ARCH=$(uname -m)
case "${ARCH}" in
  x86_64|aarch64) ;;
  *)
    echo "Nicht unterstuetzte Architektur: ${ARCH}" >&2
    exit 1
    ;;
esac

mkdir -p "${BIN_DIR}"

if [[ "${VERSION}" == "latest" ]]; then
  URL="https://github.com/vllm-project/vllm-bench/releases/latest/download/vllm-bench-${ARCH}-linux-musl"
else
  URL="https://github.com/vllm-project/vllm-bench/releases/download/${VERSION}/vllm-bench-${ARCH}-linux-musl"
fi

echo "Lade ${URL} nach ${BIN_PATH} ..."
curl -fsSL "${URL}" -o "${BIN_PATH}"
chmod +x "${BIN_PATH}"

"${BIN_PATH}" --version
