#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE="base"
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:?missing --profile value}"
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

case "$PROFILE" in
  base)
    exec "$(dirname "$0")/bootstrap_node_from_prod_v2.sh" "${ARGS[@]}"
    ;;
  reality|xhttp-cdn|hy2)
    echo "ERROR: profile '$PROFILE' is not implemented yet. Run --profile base first." >&2
    exit 1
    ;;
  *)
    echo "ERROR: unknown profile '$PROFILE'. Supported: base, reality, xhttp-cdn, hy2" >&2
    exit 1
    ;;
esac
