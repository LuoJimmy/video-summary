#!/usr/bin/env bash
# 打包极空间可导入的 docker save tar（单架构，含 manifest.json）
# 用法：
#   ./script/build-docker.sh
#   ./script/build-docker.sh amd64
#   ./script/build-docker.sh arm64
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE_NAME="${IMAGE_NAME:-video-summary:latest}"
NODE_IMAGE="${NODE_IMAGE:-docker.m.daocloud.io/library/node:22-alpine}"
PYTHON_IMAGE="${PYTHON_IMAGE:-docker.m.daocloud.io/library/python:3.12-slim}"
DIST_DIR="${DIST_DIR:-$ROOT/dist}"
BUILDER="${BUILDER:-}"

if [[ -z "$BUILDER" ]] && docker buildx inspect mybuilder >/dev/null 2>&1; then
  BUILDER="mybuilder"
fi

builder_args=()
if [[ -n "$BUILDER" ]]; then
  builder_args=(--builder "$BUILDER")
fi

targets=("$@")
if [[ ${#targets[@]} -eq 0 ]]; then
  targets=(amd64 arm64)
fi

mkdir -p "$DIST_DIR"

build_one() {
  local arch="$1"
  local dest="$DIST_DIR/video-summary-linux-${arch}.tar"
  echo "==> 构建 linux/${arch} -> ${dest}"
  docker buildx build \
    "${builder_args[@]}" \
    --platform "linux/${arch}" \
    --tag "$IMAGE_NAME" \
    --provenance=false \
    --sbom=false \
    --progress=plain \
    --build-arg "NODE_IMAGE=${NODE_IMAGE}" \
    --build-arg "PYTHON_IMAGE=${PYTHON_IMAGE}" \
    --output "type=docker,dest=${dest}" \
    .
  echo "==> 完成 ${dest}"
}

for arch in "${targets[@]}"; do
  case "$arch" in
    amd64|arm64) build_one "$arch" ;;
    *)
      echo "不支持的架构: $arch（仅支持 amd64 / arm64）" >&2
      exit 1
      ;;
  esac
done

echo "==> 全部完成"
ls -lh "$DIST_DIR"/video-summary-linux-*.tar
