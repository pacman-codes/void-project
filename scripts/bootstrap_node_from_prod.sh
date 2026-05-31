#!/usr/bin/env bash
set -Eeuo pipefail

PROD_IP_DEFAULT="193.233.209.130"
PANEL_PORT_DEFAULT="8448"
SSH_PORT_DEFAULT="22"
XUI_VERSION_DEFAULT="v3.1.0"
RESULTS_DIR="${HOME}/void-node-bootstrap-results"

TMP_REMOTE_SCRIPT=""

die() {
  echo
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo
  echo "==> $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

make_secret() {
  python3 - "$1" <<'PY_SECRET'
import secrets
import string
import sys

n = int(sys.argv[1])
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(n)))
PY_SECRET
}

cleanup_local() {
  unset SSH_PASSWORD SSHPASS || true
  [[ -n "${TMP_REMOTE_SCRIPT:-}" && -f "${TMP_REMOTE_SCRIPT}" ]] && rm -f "${TMP_REMOTE_SCRIPT}" || true
}

trap cleanup_local EXIT

install_local_deps() {
  log "Check local dependencies"

  if need_cmd sshpass && need_cmd ssh && need_cmd scp && need_cmd dig && need_cmd curl; then
    echo "local deps OK"
    return 0
  fi

  sudo apt-get update
  sudo apt-get install -y sshpass openssh-client curl dnsutils
}

confirm_running_on_prod() {
  log "Check local PROD host"

  local local_ip
  local_ip="$(curl -4fsS https://ifconfig.me 2>/dev/null || true)"

  echo "local hostname: $(hostname)"
  echo "local public ip: ${local_ip:-unknown}"
  echo "expected PROD ip: ${PROD_IP}"

  if [[ "${local_ip}" != "${PROD_IP}" ]]; then
    read -rp "Current host does not look like PROD. Continue? Type YES: " confirm
    [[ "${confirm}" == "YES" ]] || die "Cancelled."
  fi
}

ask_inputs() {
  echo
  read -rp "New server IP: " TARGET_IP
  [[ -n "${TARGET_IP}" ]] || die "New server IP is required."
  [[ "${TARGET_IP}" != "${PROD_IP}" ]] || die "Target IP equals PROD IP. Refusing."

  read -rp "Panel/domain host, example swpg.voidmod.space: " NODE_DOMAIN
  [[ -n "${NODE_DOMAIN}" ]] || die "Domain is required."
  [[ "${NODE_DOMAIN}" != *"/"* ]] || die "Domain must not contain slash."

  read -rp "SSH user [root]: " SSH_USER
  SSH_USER="${SSH_USER:-root}"

  read -rp "SSH port [${SSH_PORT_DEFAULT}]: " SSH_PORT
  SSH_PORT="${SSH_PORT:-${SSH_PORT_DEFAULT}}"

  read -rp "Node code [swpg_1]: " NODE_CODE
  NODE_CODE="${NODE_CODE:-swpg_1}"

  read -rp "Node hostname [swpg1]: " NODE_HOSTNAME
  NODE_HOSTNAME="${NODE_HOSTNAME:-swpg1}"

  read -rp "Panel port [${PANEL_PORT_DEFAULT}]: " PANEL_PORT
  PANEL_PORT="${PANEL_PORT:-${PANEL_PORT_DEFAULT}}"

  read -rp "Secret prefix [SWPG_1]: " SECRET_PREFIX
  SECRET_PREFIX="${SECRET_PREFIX:-SWPG_1}"

  read -rp "Owner public IP for panel access, empty = skip: " OWNER_IP
  OWNER_IP="${OWNER_IP:-}"

  echo
  echo "DNS check:"
  local resolved
  resolved="$(dig +short "${NODE_DOMAIN}" A | tail -1 || true)"
  echo "${NODE_DOMAIN} -> ${resolved:-empty}"

  [[ "${resolved}" == "${TARGET_IP}" ]] || die "DNS A record mismatch. Fix DNS first."

  echo
  read -rsp "SSH password for ${SSH_USER}@${TARGET_IP}: " SSH_PASSWORD
  echo
  [[ -n "${SSH_PASSWORD}" ]] || die "SSH password is required."

  PANEL_USERNAME_GENERATED="$(make_secret 14)"
  PANEL_PASSWORD_GENERATED="$(make_secret 24)"
  PANEL_WEB_BASE_PATH_GENERATED="$(make_secret 24)"

  echo
  echo "Config:"
  echo "  target: ${SSH_USER}@${TARGET_IP}:${SSH_PORT}"
  echo "  node_code: ${NODE_CODE}"
  echo "  hostname: ${NODE_HOSTNAME}"
  echo "  domain: ${NODE_DOMAIN}"
  echo "  panel_port: ${PANEL_PORT}"
  echo "  secret_prefix: ${SECRET_PREFIX}"
  echo "  prod_ip: ${PROD_IP}"
  echo "  owner_ip: ${OWNER_IP:-not set}"
  echo
  read -rp "Run bootstrap on target? Type YES: " confirm
  [[ "${confirm}" == "YES" ]] || die "Cancelled."
}

ssh_target() {
  SSHPASS="${SSH_PASSWORD}" sshpass -e ssh \
    -p "${SSH_PORT}" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    "${SSH_USER}@${TARGET_IP}" "$@"
}

scp_to_target() {
  SSHPASS="${SSH_PASSWORD}" sshpass -e scp \
    -P "${SSH_PORT}" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    "$1" "${SSH_USER}@${TARGET_IP}:$2"
}

scp_from_target() {
  SSHPASS="${SSH_PASSWORD}" sshpass -e scp \
    -P "${SSH_PORT}" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    "${SSH_USER}@${TARGET_IP}:$1" "$2"
}

make_remote_script() {
  TMP_REMOTE_SCRIPT="$(mktemp /tmp/void-remote-bootstrap.XXXXXX.sh)"

  cat > "${TMP_REMOTE_SCRIPT}" <<'REMOTE_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

NODE_CODE="${NODE_CODE:?}"
NODE_HOSTNAME="${NODE_HOSTNAME:?}"
NODE_DOMAIN="${NODE_DOMAIN:?}"
TARGET_IP="${TARGET_IP:?}"
PROD_IP="${PROD_IP:?}"
PANEL_PORT="${PANEL_PORT:?}"
SSH_PORT="${SSH_PORT:-22}"
OWNER_IP="${OWNER_IP:-}"
PANEL_USERNAME_GENERATED="${PANEL_USERNAME_GENERATED:?}"
PANEL_PASSWORD_GENERATED="${PANEL_PASSWORD_GENERATED:?}"
PANEL_WEB_BASE_PATH_GENERATED="${PANEL_WEB_BASE_PATH_GENERATED:?}"
XUI_VERSION="${XUI_VERSION:-v3.1.0}"

STATE_DIR="/root/void-node-bootstrap-state"
INSTALL_LOG="${STATE_DIR}/3xui-install.log"
RESULT_FILE="/root/void-node-result.env"

log() {
  echo
  echo "==> $*"
}

die() {
  echo
  echo "ERROR: $*" >&2
  exit 1
}

public_ip() {
  curl -4fsS https://ifconfig.me 2>/dev/null || true
}

check_target() {
  log "Target host check"

  local ip
  ip="$(public_ip)"

  echo "hostname: $(hostname)"
  echo "public_ip: ${ip:-unknown}"
  echo "target_ip: ${TARGET_IP}"
  echo "domain: ${NODE_DOMAIN}"
  echo "prod_ip: ${PROD_IP}"

  [[ "${ip}" == "${TARGET_IP}" ]] || die "Public IP mismatch."
  [[ "${ip}" != "${PROD_IP}" ]] || die "This is PROD. Refusing."
}

install_base() {
  log "Install base packages"

  export DEBIAN_FRONTEND=noninteractive

  command -v apt-get >/dev/null 2>&1 || die "Only Debian/Ubuntu supported in v4."

  apt-get update
  apt-get install -y \
    ca-certificates curl wget gnupg lsb-release jq \
    ufw fail2ban htop nano vim unzip tar gzip socat \
    net-tools dnsutils iproute2 iptables cron rsync expect
}

set_hostname_safe() {
  log "Set hostname"

  hostnamectl set-hostname "${NODE_HOSTNAME}"
  grep -q "127.0.1.1 ${NODE_HOSTNAME}" /etc/hosts || echo "127.0.1.1 ${NODE_HOSTNAME}" >> /etc/hosts
}

apply_sysctl() {
  log "Apply sysctl basics"

  cat > /etc/sysctl.d/99-void-node.conf <<'SYSCTL'
fs.file-max = 1048576
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 250000
net.ipv4.ip_forward = 1
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5
SYSCTL

  modprobe tcp_bbr 2>/dev/null || true

  if sysctl net.ipv4.tcp_available_congestion_control 2>/dev/null | grep -qw bbr; then
    cat >> /etc/sysctl.d/99-void-node.conf <<'SYSCTL'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
SYSCTL
  fi

  sysctl --system >/dev/null || true
}

configure_fail2ban() {
  log "Configure fail2ban"

  mkdir -p /etc/fail2ban/jail.d

  cat > /etc/fail2ban/jail.d/void-sshd.conf <<EOF_F2B
[sshd]
enabled = true
port = ${SSH_PORT}
filter = sshd
logpath = %(sshd_log)s
maxretry = 5
findtime = 10m
bantime = 2h
EOF_F2B

  systemctl enable fail2ban
  systemctl restart fail2ban
}

cleanup_amnezia_docker() {
  log "Cleanup Amnezia Docker if present"

  mkdir -p "${STATE_DIR}"

  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not installed"
    return 0
  fi

  docker ps -a > "${STATE_DIR}/docker-ps-a-before.txt" 2>&1 || true

  if docker ps -a --format '{{.Names}}' | grep -qx 'amnezia-xray'; then
    echo "Found amnezia-xray. Saving inspect/logs and removing it."
    docker inspect amnezia-xray > "${STATE_DIR}/amnezia-xray.inspect.json" 2>&1 || true
    docker logs amnezia-xray > "${STATE_DIR}/amnezia-xray.logs.txt" 2>&1 || true
    docker stop amnezia-xray || true
    docker rm amnezia-xray || true
  fi

  local running
  running="$(docker ps -q 2>/dev/null | wc -l | tr -d ' ' || echo 0)"

  if [[ "${running}" == "0" ]]; then
    systemctl disable --now docker docker.socket containerd 2>/dev/null || true
  fi
}

cleanup_partial_xui() {
  log "Cleanup partial x-ui install if needed"

  if [[ -d /usr/local/x-ui && ! -f /etc/systemd/system/x-ui.service ]]; then
    echo "Partial x-ui detected. Removing /usr/local/x-ui and /etc/x-ui"
    rm -rf /usr/local/x-ui /etc/x-ui
  fi
}

install_3xui_skip_ssl() {
  log "Install 3x-ui with PostgreSQL, panel port and SKIP SSL"

  if [[ -x /usr/local/x-ui/x-ui && -f /etc/systemd/system/x-ui.service ]]; then
    echo "x-ui already installed, skipping installer"
    return 0
  fi

  mkdir -p "${STATE_DIR}"
  rm -f "${INSTALL_LOG}"

  cat > /root/void-install-3xui.expect <<EOF_EXPECT
set timeout 900
log_user 0
log_file -noappend "${INSTALL_LOG}"
set choose_count 0

spawn bash -c {bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)}

expect {
  eof {
    exit 0
  }
  timeout {
    exit 124
  }
  -re {Choose \\[1\\]:} {
    incr choose_count
    if { \$choose_count == 1 } {
      send "2\r"
    } else {
      send "\r"
    }
    exp_continue
  }
  -re {Would you like to customize the Panel Port settings.*\\[y/n\\]:} {
    send "y\r"
    exp_continue
  }
  -re {Please set up the panel port:|Please enter the panel port:|Panel port:} {
    send "${PANEL_PORT}\r"
    exp_continue
  }
  -re {Choose an option \\(default 2 for IP\\):|Choose SSL certificate setup method:|Choose an option.*:} {
    send "4\r"
    exp_continue
  }
  -re {Bind the panel to 127\\.0\\.0\\.1 only\\?.*\\[y/N\\]:} {
    send "n\r"
    exp_continue
  }
}
EOF_EXPECT

  echo "3x-ui installer is running. Output is stored in ${INSTALL_LOG}"
  expect /root/void-install-3xui.expect
}


pin_3xui_version() {
  log "Pin 3x-ui version ${XUI_VERSION}"

  [[ -x /usr/local/x-ui/x-ui ]] || die "x-ui binary not found before pin"

  local current_version
  current_version="$(
    /usr/local/x-ui/x-ui version 2>/dev/null \
      | grep -Eo 'v?[0-9]+\.[0-9]+\.[0-9]+' \
      | head -1 || true
  )"

  echo "Current x-ui version: ${current_version:-unknown}"
  echo "Target x-ui version: ${XUI_VERSION}"

  if [[ "${current_version}" == "${XUI_VERSION#v}" || "${current_version}" == "${XUI_VERSION}" ]]; then
    echo "x-ui already pinned to ${XUI_VERSION}"
    return 0
  fi

  local arch="amd64"
  local workdir="/root/void-xui-pin-${XUI_VERSION}"
  local asset="x-ui-linux-${arch}.tar.gz"

  rm -rf "${workdir}"
  mkdir -p "${workdir}"
  cd "${workdir}"

  curl -fL -o "${asset}" \
    "https://github.com/MHSanaei/3x-ui/releases/download/${XUI_VERSION}/${asset}" \
    || die "Failed to download 3x-ui ${XUI_VERSION}"

  tar -xzf "${asset}" || die "Failed to unpack 3x-ui ${XUI_VERSION}"

  mkdir -p "${STATE_DIR}"
  tar -czf "${STATE_DIR}/x-ui-before-pin-$(date +%Y%m%d_%H%M%S).tar.gz" \
    /usr/local/x-ui /etc/systemd/system/x-ui.service 2>/dev/null || true

  systemctl stop x-ui || true

  rm -rf /usr/local/x-ui
  mkdir -p /usr/local/x-ui

  if [[ -d "./x-ui" ]]; then
    cp -a ./x-ui/* /usr/local/x-ui/
  else
    cp -a ./* /usr/local/x-ui/
  fi

  chmod +x /usr/local/x-ui/x-ui || true
  chmod +x /usr/local/x-ui/bin/xray-linux-amd64 || true

  if [[ ! -f /etc/systemd/system/x-ui.service ]]; then
    cat > /etc/systemd/system/x-ui.service <<'EOF_SERVICE'
[Unit]
Description=x-ui Service
After=network.target nss-lookup.target

[Service]
User=root
WorkingDirectory=/usr/local/x-ui
ExecStart=/usr/local/x-ui/x-ui
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF_SERVICE
  fi

  systemctl daemon-reload
  systemctl enable x-ui
  systemctl restart x-ui
  sleep 3
  systemctl is-active x-ui || die "x-ui is not active after version pin"

  echo "Pinned x-ui version:"
  /usr/local/x-ui/x-ui version || true
}

force_panel_settings() {
  log "Force panel credentials, webBasePath and port"

  [[ -x /usr/local/x-ui/x-ui ]] || die "x-ui binary not found"

  local normalized_web_base_path
  normalized_web_base_path="/${PANEL_WEB_BASE_PATH_GENERATED#/}"
  normalized_web_base_path="${normalized_web_base_path%/}/"

  /usr/local/x-ui/x-ui setting \
    -username "${PANEL_USERNAME_GENERATED}" \
    -password "${PANEL_PASSWORD_GENERATED}" \
    -port "${PANEL_PORT}" \
    -webBasePath "${normalized_web_base_path}" \
    || die "Failed to set panel credentials/path/port"

  /usr/local/x-ui/x-ui migrate || true

  systemctl enable x-ui
  systemctl restart x-ui
  sleep 3
  systemctl is-active x-ui || die "x-ui is not active after forced settings"

  echo "Forced webBasePath: ${normalized_web_base_path}"
  echo "Current x-ui settings after force:"
  /usr/local/x-ui/x-ui setting -show true || true
}

configure_firewall() {
  log "Configure UFW firewall"

  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing

  ufw allow "${SSH_PORT}/tcp" comment "SSH"
  ufw allow 80/tcp comment "HTTP/ACME"
  ufw allow 443/tcp comment "VLESS/Reality"
  ufw allow from "${PROD_IP}" to any port "${PANEL_PORT}" proto tcp comment "Panel API from PROD"

  if [[ -n "${OWNER_IP}" ]]; then
    ufw allow from "${OWNER_IP}" to any port "${PANEL_PORT}" proto tcp comment "Panel owner access"
  fi

  ufw --force enable
  ufw status numbered
}

issue_domain_cert_non_blocking() {
  log "Issue domain certificate with acme.sh, non-blocking for panel API"

  mkdir -p "/root/cert/${NODE_DOMAIN}"

  if [[ ! -x /root/.acme.sh/acme.sh ]]; then
    curl -fsSL https://get.acme.sh | sh -s email="admin@${NODE_DOMAIN}" || true
  fi

  if [[ -x /root/.acme.sh/acme.sh ]]; then
    /root/.acme.sh/acme.sh --set-default-ca --server letsencrypt || true

    if [[ ! -f "/root/cert/${NODE_DOMAIN}/fullchain.pem" || ! -f "/root/cert/${NODE_DOMAIN}/privkey.pem" ]]; then
      systemctl stop x-ui || true

      /root/.acme.sh/acme.sh --issue \
        -d "${NODE_DOMAIN}" \
        --standalone \
        --httpport 80 \
        --keylength ec-256 || true

      /root/.acme.sh/acme.sh --install-cert \
        -d "${NODE_DOMAIN}" \
        --ecc \
        --fullchain-file "/root/cert/${NODE_DOMAIN}/fullchain.pem" \
        --key-file "/root/cert/${NODE_DOMAIN}/privkey.pem" \
        --reloadcmd "systemctl restart x-ui || true" || true
    fi
  fi

  if [[ -f "/root/cert/${NODE_DOMAIN}/fullchain.pem" && -f "/root/cert/${NODE_DOMAIN}/privkey.pem" ]]; then
    /usr/local/x-ui/x-ui cert \
      -webCert "/root/cert/${NODE_DOMAIN}/fullchain.pem" \
      -webCertKey "/root/cert/${NODE_DOMAIN}/privkey.pem" || true
  fi

  systemctl enable x-ui
  systemctl restart x-ui
  sleep 3
  systemctl is-active x-ui || die "x-ui not active after cert step"
}

parse_panel_credentials() {
  PANEL_USERNAME_PARSED="${PANEL_USERNAME_GENERATED}"
  PANEL_PASSWORD_PARSED="${PANEL_PASSWORD_GENERATED}"
  PANEL_WEB_BASE_PATH_PARSED="$(
    printf '%s\n' "${PANEL_WEB_BASE_PATH_GENERATED}" \
      | sed 's#^/##; s#/$##'
  )"

  local token_raw
  token_raw="$(/usr/local/x-ui/x-ui setting -getApiToken true 2>/dev/null || true)"

  PANEL_API_TOKEN_PARSED="$(
    printf '%s\n' "${token_raw}" \
      | sed -r 's/\x1B\[[0-9;]*[mK]//g; s/\r//g' \
      | awk -F':' '
          BEGIN {IGNORECASE=1}
          /api.*token/ {
            v=$2
            sub(/^[ \t]+/, "", v)
            sub(/[ \t]+$/, "", v)
            print v
          }
        ' \
      | tail -1
  )"

  if [[ -z "${PANEL_API_TOKEN_PARSED}" ]]; then
    PANEL_API_TOKEN_PARSED="$(
      printf '%s\n' "${token_raw}" \
        | grep -Eo '[A-Za-z0-9_-]{32,}' \
        | tail -1
    )"
  fi

  if [[ -z "${PANEL_WEB_BASE_PATH_PARSED}" ]]; then
    echo "ERROR: generated webBasePath is empty" >&2
    exit 1
  fi

  if [[ -z "${PANEL_API_TOKEN_PARSED}" ]]; then
    echo "ERROR: failed to get panel API token" >&2
    echo "== x-ui setting -getApiToken true ==" >&2
    printf '%s\n' "${token_raw}" >&2
    exit 1
  fi

  echo "Forced webBasePath for result: /${PANEL_WEB_BASE_PATH_PARSED}/"
}

detect_panel_scheme_and_origin() {
  local base_path tmp_headers tmp_body code scheme api_path url label
  base_path="/${PANEL_WEB_BASE_PATH_PARSED#/}"
  base_path="${base_path%/}"

  PANEL_SCHEME_PARSED=""
  PANEL_ORIGIN_PARSED=""
  PANEL_ACCESS_URL_PARSED=""
  PANEL_API_BASE_PATH_PARSED=""

  for scheme in https http; do
    for api_path in "${base_path}" ""; do
      if [[ -n "${api_path}" ]]; then
        label="webBasePath"
      else
        label="root"
      fi

      tmp_headers="${STATE_DIR}/scheme-check-${scheme}-${label}.headers"
      tmp_body="${STATE_DIR}/scheme-check-${scheme}-${label}.body"
      : > "${tmp_headers}"
      : > "${tmp_body}"

      url="${scheme}://127.0.0.1:${PANEL_PORT}${api_path}/panel/api/inbounds/list"

      code="$(
        curl -skS \
          -D "${tmp_headers}" \
          -o "${tmp_body}" \
          -w "%{http_code}" \
          -H "Authorization: Bearer ${PANEL_API_TOKEN_PARSED}" \
          -H "X-Requested-With: XMLHttpRequest" \
          --max-time 10 \
          "${url}" || true
      )"

      echo "scheme probe: ${url} -> HTTP_CODE=${code}"
      cat "${tmp_body}" || true
      echo

      if grep -q '"success":true' "${tmp_body}" 2>/dev/null; then
        PANEL_SCHEME_PARSED="${scheme}"
        PANEL_API_BASE_PATH_PARSED="${api_path}"

        if [[ "${scheme}" == "https" ]]; then
          PANEL_ORIGIN_PARSED="https://${NODE_DOMAIN}:${PANEL_PORT}"
          PANEL_ACCESS_URL_PARSED="https://${NODE_DOMAIN}:${PANEL_PORT}/${PANEL_WEB_BASE_PATH_PARSED}"
        else
          PANEL_ORIGIN_PARSED="http://${TARGET_IP}:${PANEL_PORT}"
          PANEL_ACCESS_URL_PARSED="http://${NODE_DOMAIN}:${PANEL_PORT}/${PANEL_WEB_BASE_PATH_PARSED}"
        fi

        echo "Working API base path: ${PANEL_API_BASE_PATH_PARSED:-/}"
        return 0
      fi
    done
  done

  echo "WARNING: panel API did not work through https/http with webBasePath/root paths" >&2
  echo "== x-ui settings ==" >&2
  /usr/local/x-ui/x-ui setting -show true >&2 || true
  echo "== api token ==" >&2
  /usr/local/x-ui/x-ui setting -getApiToken true >&2 || true

  PANEL_SCHEME_PARSED="http"
  PANEL_ORIGIN_PARSED="http://${TARGET_IP}:${PANEL_PORT}"
  PANEL_API_BASE_PATH_PARSED="/${PANEL_WEB_BASE_PATH_PARSED}"
  PANEL_API_BASE_PATH_PARSED="${PANEL_API_BASE_PATH_PARSED%/}"
  PANEL_ACCESS_URL_PARSED="http://${NODE_DOMAIN}:${PANEL_PORT}/${PANEL_WEB_BASE_PATH_PARSED}"

  echo "Fallback PANEL_ORIGIN=${PANEL_ORIGIN_PARSED}"
  echo "Fallback PANEL_API_BASE_PATH=${PANEL_API_BASE_PATH_PARSED}"
  return 0
}

collect_result() {
  log "Collect panel result"

  parse_panel_credentials
  detect_panel_scheme_and_origin

  umask 077
  cat > "${RESULT_FILE}" <<EOF_RESULT
NODE_CODE=${NODE_CODE}
NODE_HOSTNAME=${NODE_HOSTNAME}
NODE_DOMAIN=${NODE_DOMAIN}
PUBLIC_IP=${TARGET_IP}
PANEL_ORIGIN=${PANEL_ORIGIN_PARSED}
PANEL_SCHEME=${PANEL_SCHEME_PARSED}
PANEL_PORT=${PANEL_PORT}
PANEL_USERNAME=${PANEL_USERNAME_PARSED}
PANEL_PASSWORD=${PANEL_PASSWORD_PARSED}
PANEL_WEB_BASE_PATH=${PANEL_WEB_BASE_PATH_PARSED}
PANEL_API_BASE_PATH=${PANEL_API_BASE_PATH_PARSED}
PANEL_API_TOKEN=${PANEL_API_TOKEN_PARSED}
PANEL_ACCESS_URL=${PANEL_ACCESS_URL_PARSED}
PROD_IP=${PROD_IP}
OWNER_IP=${OWNER_IP}
EOF_RESULT

  chmod 600 "${RESULT_FILE}"

  sed -E 's/(PANEL_PASSWORD=).+/\1***hidden***/; s/(PANEL_API_TOKEN=).+/\1***hidden***/' "${RESULT_FILE}"
}

verify_panel_api_token_local() {
  log "Verify panel API token locally"

  source "${RESULT_FILE}"

  local base_path local_origin url tmp_headers tmp_body http_code
  if [[ -n "${PANEL_API_BASE_PATH:-}" ]]; then
    base_path="${PANEL_API_BASE_PATH}"
  else
    base_path="/${PANEL_WEB_BASE_PATH#/}"
    base_path="${base_path%/}"
  fi

  if [[ "${PANEL_SCHEME}" == "https" ]]; then
    local_origin="https://127.0.0.1:${PANEL_PORT}"
  else
    local_origin="http://127.0.0.1:${PANEL_PORT}"
  fi

  url="${local_origin}${base_path}/panel/api/inbounds/list"

  echo "API URL: ${url}"

  tmp_headers="${STATE_DIR}/api-check.headers"
  tmp_body="${STATE_DIR}/api-check.body"

  http_code="$(
    curl -skS \
      -D "${tmp_headers}" \
      -o "${tmp_body}" \
      -w "%{http_code}" \
      -H "Authorization: Bearer ${PANEL_API_TOKEN}" \
      -H "X-Requested-With: XMLHttpRequest" \
      --max-time 10 \
      "${url}" || true
  )"

  echo "HTTP_CODE=${http_code}"
  cat "${tmp_headers}" || true
  cat "${tmp_body}" || true

  if ! grep -q '"success":true' "${tmp_body}"; then
    echo "WARNING: local panel API token check failed; bootstrap will continue."
    echo "This is a 3x-ui API compatibility check, not a base node setup failure."
  fi
}

post_checks() {
  log "Post checks"

  systemctl enable x-ui
  systemctl restart x-ui
  sleep 3

  echo
  echo "== services =="
  systemctl is-active x-ui || true
  systemctl is-active fail2ban || true
  systemctl is-active ufw || true
  systemctl is-active docker || true

  echo
  echo "== listening ports =="
  ss -tulpn | grep -E ":(${SSH_PORT}|80|443|${PANEL_PORT})\\b" || true

  echo
  echo "== firewall =="
  ufw status numbered || true

  echo
  echo "== local panel check =="
  curl -kI --max-time 5 "https://127.0.0.1:${PANEL_PORT}/" || true
  curl -I --max-time 5 "http://127.0.0.1:${PANEL_PORT}/" || true
}

main() {
  [[ "${EUID}" -eq 0 ]] || die "Run as root"

  mkdir -p "${STATE_DIR}"

  check_target
  install_base
  set_hostname_safe
  apply_sysctl
  configure_fail2ban
  cleanup_amnezia_docker
  cleanup_partial_xui
  install_3xui_skip_ssl
  pin_3xui_version
  force_panel_settings
  configure_firewall
  issue_domain_cert_non_blocking
  force_panel_settings
  collect_result
  verify_panel_api_token_local
  post_checks

  echo
  echo "DONE: remote bootstrap completed"
}

main "$@"
REMOTE_EOF

  chmod +x "${TMP_REMOTE_SCRIPT}"
}

run_remote_bootstrap() {
  log "Upload and run remote bootstrap"

  make_remote_script
  scp_to_target "${TMP_REMOTE_SCRIPT}" "/root/void_remote_node_bootstrap.sh"

  ssh_target "
    NODE_CODE='${NODE_CODE}' \
    NODE_HOSTNAME='${NODE_HOSTNAME}' \
    NODE_DOMAIN='${NODE_DOMAIN}' \
    TARGET_IP='${TARGET_IP}' \
    PROD_IP='${PROD_IP}' \
    PANEL_PORT='${PANEL_PORT}' \
    SSH_PORT='${SSH_PORT}' \
    OWNER_IP='${OWNER_IP}' \
    PANEL_USERNAME_GENERATED='${PANEL_USERNAME_GENERATED}' \
    PANEL_PASSWORD_GENERATED='${PANEL_PASSWORD_GENERATED}' \
    PANEL_WEB_BASE_PATH_GENERATED='${PANEL_WEB_BASE_PATH_GENERATED}' \
    XUI_VERSION='${XUI_VERSION:-v3.1.0}' \
    bash /root/void_remote_node_bootstrap.sh
  "
}

copy_result_back() {
  log "Copy result back to PROD"

  mkdir -p "${RESULTS_DIR}"
  chmod 700 "${RESULTS_DIR}"

  LOCAL_RESULT="${RESULTS_DIR}/${NODE_CODE}_${TARGET_IP}.env"

  scp_from_target "/root/void-node-result.env" "${LOCAL_RESULT}"
  chmod 600 "${LOCAL_RESULT}"

  echo
  echo "Saved:"
  echo "${LOCAL_RESULT}"
  sed -E 's/(PANEL_PASSWORD=).+/\1***hidden***/; s/(PANEL_API_TOKEN=).+/\1***hidden***/' "${LOCAL_RESULT}"
}

result_get() {
  local key="$1"
  grep "^${key}=" "${LOCAL_RESULT}" | head -1 | cut -d= -f2-
}

verify_panel_api_token_from_prod() {
  log "Verify panel API token from PROD"

  local panel_origin panel_path panel_api_path panel_token
  panel_origin="$(result_get PANEL_ORIGIN)"
  panel_path="$(result_get PANEL_WEB_BASE_PATH)"
  panel_api_path="$(result_get PANEL_API_BASE_PATH || true)"
  panel_token="$(result_get PANEL_API_TOKEN)"

  [[ -n "${panel_origin}" ]] || die "PANEL_ORIGIN empty"
  [[ -n "${panel_token}" ]] || die "PANEL_API_TOKEN empty"

  local base_path
  if [[ -n "${panel_api_path}" ]]; then
    base_path="${panel_api_path}"
  else
    base_path="/${panel_path#/}"
    base_path="${base_path%/}"
  fi

  local url="${panel_origin}${base_path}/panel/api/inbounds/list"

  echo "API URL: ${url}"

  local body
  body="$(curl -sS \
    -H "Authorization: Bearer ${panel_token}" \
    -H "X-Requested-With: XMLHttpRequest" \
    --max-time 10 \
    "${url}" || true)"

  echo "${body}"

  if ! echo "${body}" | grep -q '"success":true'; then
    echo "WARNING: PROD -> panel API token check failed; bootstrap will continue."
    echo "This node may still be usable after PanelClient/API compatibility patch."
  fi
}

append_secrets_to_prod() {
  log "Append panel credentials to /etc/void/server_secrets.env"

  [[ -f "${LOCAL_RESULT}" ]] || die "Local result not found"

  local username password api_token

  username="$(result_get PANEL_USERNAME)"
  password="$(result_get PANEL_PASSWORD)"
  api_token="$(result_get PANEL_API_TOKEN)"

  [[ -n "${username}" ]] || die "PANEL_USERNAME is empty"
  [[ -n "${password}" ]] || die "PANEL_PASSWORD is empty"
  [[ -n "${api_token}" ]] || die "PANEL_API_TOKEN is empty"

  sudo mkdir -p /etc/void
  sudo touch /etc/void/server_secrets.env
  sudo chown root:vpn /etc/void/server_secrets.env
  sudo chmod 640 /etc/void/server_secrets.env
  sudo cp /etc/void/server_secrets.env "/etc/void/server_secrets.env.bak_$(date +%Y%m%d_%H%M%S)"

  sudo sed -i "/^${SECRET_PREFIX}_PANEL_USERNAME=/d" /etc/void/server_secrets.env
  sudo sed -i "/^${SECRET_PREFIX}_PANEL_PASSWORD=/d" /etc/void/server_secrets.env
  sudo sed -i "/^${SECRET_PREFIX}_PANEL_API_TOKEN=/d" /etc/void/server_secrets.env

  {
    echo "${SECRET_PREFIX}_PANEL_USERNAME=${username}"
    echo "${SECRET_PREFIX}_PANEL_PASSWORD=${password}"
    echo "${SECRET_PREFIX}_PANEL_API_TOKEN=${api_token}"
  } | sudo tee -a /etc/void/server_secrets.env >/dev/null

  sudo chown root:vpn /etc/void/server_secrets.env
  sudo chmod 640 /etc/void/server_secrets.env

  sudo grep "^${SECRET_PREFIX}_PANEL_" /etc/void/server_secrets.env \
    | sed -E 's/(PASSWORD=).+/\1***hidden***/; s/(API_TOKEN=).+/\1***hidden***/'
}

final_notes() {
  echo
  echo "DONE."
  echo
  echo "Panel result:"
  sed -E 's/(PANEL_PASSWORD=).+/\1***hidden***/; s/(PANEL_API_TOKEN=).+/\1***hidden***/' "${LOCAL_RESULT}"
  echo
  echo "Next:"
  echo "1. add node to /etc/void/servers.json"
  echo "2. patch PanelClient for API token auth if needed"
  echo "3. create VLESS Reality inbound on 443"
  echo "4. then SSH key hardening"
}

main() {
  PROD_IP="${PROD_IP:-${PROD_IP_DEFAULT}}"
  XUI_VERSION="${XUI_VERSION:-${XUI_VERSION_DEFAULT}}"

  install_local_deps
  confirm_running_on_prod
  ask_inputs
  run_remote_bootstrap
  copy_result_back
  verify_panel_api_token_from_prod
  append_secrets_to_prod
  final_notes

  unset SSH_PASSWORD
}

main "$@"
