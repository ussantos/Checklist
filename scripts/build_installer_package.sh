#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
STAMP="$(date +%Y%m%d_%H%M%S)"
REVISION="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo local)"
if git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
    REVISION="${REVISION}-dirty"
  fi
fi
PACKAGE_NAME="${CHECKLIST_PACKAGE_NAME:-checklist-ubuntu26-installer-${REVISION}-${STAMP}}"
PACKAGE_PATH="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

command -v rsync >/dev/null 2>&1 || {
  echo "rsync nao encontrado. Instale rsync para gerar o pacote." >&2
  exit 1
}

mkdir -p "${DIST_DIR}" "${TMP_DIR}/${PACKAGE_NAME}"

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '*.env' \
  --exclude 'media/' \
  --exclude 'logs/' \
  --exclude 'backups/' \
  --exclude 'rclone/' \
  --exclude 'staticfiles/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  "${ROOT_DIR}/" "${TMP_DIR}/${PACKAGE_NAME}/"

chmod +x "${TMP_DIR}/${PACKAGE_NAME}/install_ubuntu26.sh"
chmod +x "${TMP_DIR}/${PACKAGE_NAME}/scripts/"*.sh

tar -C "${TMP_DIR}" -czf "${PACKAGE_PATH}" "${PACKAGE_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${PACKAGE_PATH}" >"${PACKAGE_PATH}.sha256"
fi

echo "Pacote gerado: ${PACKAGE_PATH}"
