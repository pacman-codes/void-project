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
  base|reality|xhttp-cdn|hy2)
    ;;
  *)
    echo "ERROR: unknown profile '$PROFILE'. Supported: base, reality, xhttp-cdn, hy2" >&2
    exit 1
    ;;
esac

"$(dirname "$0")/bootstrap_node_from_prod_v2.sh" "${ARGS[@]}"

if [[ "$PROFILE" != "base" ]]; then
  "$(dirname "$0")/apply_node_profile.sh" "${ARGS[@]}" --profile "$PROFILE"
fi
