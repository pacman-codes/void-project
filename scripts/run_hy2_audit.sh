#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/vpn/telegram_bot}"
PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"

cd "${PROJECT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: project Python not found: ${PYTHON_BIN}" >&2
  exit 1
fi

export PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON_BIN}" "${PROJECT_DIR}/scripts/audit_hy2_endpoints.py" "$@"
