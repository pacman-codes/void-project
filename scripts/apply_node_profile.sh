#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo
  echo "==> $*"
}

PROFILE=""
SERVER_CODE=""
TARGET_IP=""
DOMAIN=""
HOSTNAME=""
DISPLAY_NAME=""
RESULTS_DIR="${HOME}/void-node-bootstrap-results"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:?missing --profile value}"
      shift 2
      ;;
    --server-code)
      SERVER_CODE="${2:?missing --server-code value}"
      shift 2
      ;;
    --ip)
      TARGET_IP="${2:?missing --ip value}"
      shift 2
      ;;
    --domain)
      DOMAIN="${2:?missing --domain value}"
      shift 2
      ;;
    --hostname)
      HOSTNAME="${2:?missing --hostname value}"
      shift 2
      ;;
    --display-name)
      DISPLAY_NAME="${2:?missing --display-name value}"
      shift 2
      ;;
    --reset-known-host)
      # consumed by base deploy, irrelevant for profile apply
      shift
      ;;
    *)
      die "Unknown arg: $1"
      ;;
  esac
done

[[ -n "$PROFILE" ]] || die "--profile is required"
[[ -n "$SERVER_CODE" ]] || die "--server-code is required"
[[ -n "$TARGET_IP" ]] || die "--ip is required"

RESULT_FILE="${RESULTS_DIR}/${SERVER_CODE}_${TARGET_IP}.env"

[[ -f "$RESULT_FILE" ]] || die "Result file not found: $RESULT_FILE. Run --profile base first."

source "$RESULT_FILE"

log "Profile apply"
echo "profile=$PROFILE"
echo "server_code=$SERVER_CODE"
echo "ip=$TARGET_IP"
echo "domain=${DOMAIN:-$NODE_DOMAIN}"
echo "panel_origin=$PANEL_ORIGIN"
echo "panel_path=$PANEL_API_BASE_PATH"

case "$PROFILE" in
  base)
    echo "Base profile already applied. Nothing to do."
    ;;
  reality)
    die "profile 'reality' is not implemented yet"
    ;;
  xhttp-cdn)
    die "profile 'xhttp-cdn' is not implemented yet"
    ;;
  hy2)
    die "profile 'hy2' is not implemented yet"
    ;;
  *)
    die "unknown profile '$PROFILE'. Supported: base, reality, xhttp-cdn, hy2"
    ;;
esac
