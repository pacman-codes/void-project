#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  echo
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo
  echo "==> $*"
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

make_secret() {
  python3 - "$1" <<'PY'
import secrets, string, sys
n = int(sys.argv[1])
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(n)))
PY
}

PROD_IP="193.233.209.130"
SSH_USER="root"
SSH_PORT="22"
PANEL_PORT="8448"
XUI_VERSION="v3.1.0"
RESULTS_DIR="${HOME}/void-node-bootstrap-results"

SERVER_CODE=""
TARGET_IP=""
DOMAIN=""
HOSTNAME=""
DISPLAY_NAME=""
SECRET_PREFIX=""
OWNER_IP=""
RESET_KNOWN_HOST="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --secret-prefix)
      SECRET_PREFIX="${2:?missing --secret-prefix value}"
      shift 2
      ;;
    --ssh-user)
      SSH_USER="${2:?missing --ssh-user value}"
      shift 2
      ;;
    --ssh-port)
      SSH_PORT="${2:?missing --ssh-port value}"
      shift 2
      ;;
    --owner-ip)
      OWNER_IP="${2:?missing --owner-ip value}"
      shift 2
      ;;
    --reset-known-host)
      RESET_KNOWN_HOST="true"
      shift
      ;;
    *)
      die "Unknown arg: $1"
      ;;
  esac
done

[[ -n "$SERVER_CODE" ]] || die "--server-code is required"
[[ -n "$TARGET_IP" ]] || die "--ip is required"
[[ -n "$DOMAIN" ]] || die "--domain is required"
[[ -n "$HOSTNAME" ]] || die "--hostname is required"

SECRET_PREFIX="${SECRET_PREFIX:-$(echo "$SERVER_CODE" | tr '[:lower:]' '[:upper:]')}"
RESULT_FILE="${RESULTS_DIR}/${SERVER_CODE}_${TARGET_IP}.env"

PANEL_USERNAME="$(make_secret 14)"
PANEL_PASSWORD="$(make_secret 24)"
PANEL_WEB_BASE_PATH="$(make_secret 18)"
PANEL_API_TOKEN="$(make_secret 48)"

log "Local checks"
need ssh
need scp
need sshpass
need curl
need dig
need python3

LOCAL_IP="$(curl -4fsS https://ifconfig.me 2>/dev/null || true)"
echo "local_ip=${LOCAL_IP:-unknown}"
echo "expected_prod_ip=${PROD_IP}"
[[ "$LOCAL_IP" == "$PROD_IP" ]] || die "Run this from PROD only"

RESOLVED="$(dig +short "$DOMAIN" A | tail -1 || true)"
echo "$DOMAIN -> ${RESOLVED:-empty}"
[[ "$RESOLVED" == "$TARGET_IP" ]] || die "DNS A record mismatch"

echo
read -rsp "SSH password for ${SSH_USER}@${TARGET_IP}: " SSH_PASSWORD
echo
[[ -n "$SSH_PASSWORD" ]] || die "SSH password required"

export SSHPASS="$SSH_PASSWORD"

ssh_target() {
  sshpass -e ssh \
    -p "$SSH_PORT" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    "${SSH_USER}@${TARGET_IP}" "$@"
}

scp_from_target() {
  sshpass -e scp \
    -P "$SSH_PORT" \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
    "${SSH_USER}@${TARGET_IP}:$1" "$2"
}

log "Config"
cat <<CFG
server_code=$SERVER_CODE
target=$SSH_USER@$TARGET_IP:$SSH_PORT
domain=$DOMAIN
hostname=$HOSTNAME
panel_port=$PANEL_PORT
secret_prefix=$SECRET_PREFIX
web_base_path=$PANEL_WEB_BASE_PATH
CFG

echo
read -rp "Run bootstrap? Type YES: " CONFIRM
[[ "$CONFIRM" == "YES" ]] || die "Cancelled"

if [[ "$RESET_KNOWN_HOST" == "true" ]]; then
  log "Reset known_hosts entries"
  mkdir -p "${HOME}/.ssh"
  touch "${HOME}/.ssh/known_hosts"
  ssh-keygen -f "${HOME}/.ssh/known_hosts" -R "$TARGET_IP" || true
  ssh-keygen -f "${HOME}/.ssh/known_hosts" -R "$DOMAIN" || true
fi

log "Remote bootstrap"
ssh_target bash -s <<REMOTE
set -Eeuo pipefail

SERVER_CODE='$SERVER_CODE'
TARGET_IP='$TARGET_IP'
DOMAIN='$DOMAIN'
HOSTNAME='$HOSTNAME'
PROD_IP='$PROD_IP'
PANEL_PORT='$PANEL_PORT'
PANEL_USERNAME='$PANEL_USERNAME'
PANEL_PASSWORD='$PANEL_PASSWORD'
PANEL_WEB_BASE_PATH='$PANEL_WEB_BASE_PATH'
PANEL_API_TOKEN='$PANEL_API_TOKEN'
XUI_VERSION='$XUI_VERSION'

log() { echo; echo "==> \$*"; }
die() { echo "ERROR: \$*" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive

log "Install packages"
apt-get update
apt-get install -y \
  ca-certificates curl wget gnupg lsb-release jq ufw fail2ban htop nano vim unzip \
  tar gzip socat net-tools dnsutils iproute2 iptables cron rsync expect postgresql \
  python3 python3-bcrypt

log "Set hostname"
hostnamectl set-hostname "\$HOSTNAME"

log "Firewall"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP/ACME'
ufw allow 443/tcp comment 'VLESS/Reality'
ufw allow from "\$PROD_IP" to any port "\$PANEL_PORT" proto tcp comment 'Panel API from PROD'
ufw --force enable
ufw status numbered

log "Install or pin 3x-ui \${XUI_VERSION} without official installer"

TMP="/tmp/x-ui-linux-amd64.tar.gz"
WORKDIR="/tmp/x-ui-release-\${XUI_VERSION}"

curl -LfsS "https://github.com/MHSanaei/3x-ui/releases/download/\${XUI_VERSION}/x-ui-linux-amd64.tar.gz" -o "\${TMP}"

rm -rf "\${WORKDIR}"
mkdir -p "\${WORKDIR}"
tar -xzf "\${TMP}" -C "\${WORKDIR}"

REAL_DIR="\$(find "\${WORKDIR}" -type f -name x-ui -printf '%h\n' | head -1)"
[[ -n "\${REAL_DIR}" ]] || die "x-ui binary not found in release archive"
[[ -f "\${REAL_DIR}/x-ui" ]] || die "x-ui binary missing after extract"

systemctl stop x-ui || true

if [[ -e /usr/local/x-ui ]]; then
  mv /usr/local/x-ui "/usr/local/x-ui.bak_\$(date +%Y%m%d_%H%M%S)"
fi

mkdir -p /usr/local/x-ui
cp -a "\${REAL_DIR}"/. /usr/local/x-ui/
chmod +x /usr/local/x-ui/x-ui
chmod +x /usr/local/x-ui/bin/xray-linux-amd64 || true

if [[ -f /usr/local/x-ui/x-ui.service.debian ]]; then
  cp /usr/local/x-ui/x-ui.service.debian /etc/systemd/system/x-ui.service
fi

systemctl daemon-reload

[[ -f /usr/local/x-ui/x-ui ]] || die "/usr/local/x-ui/x-ui is not a file"
[[ -x /usr/local/x-ui/x-ui ]] || die "/usr/local/x-ui/x-ui is not executable"
/usr/local/x-ui/x-ui -v || die "x-ui binary does not run"

log "Ensure PostgreSQL xui database"
systemctl enable --now postgresql
sudo -u postgres psql -tc "select 1 from pg_database where datname='xui'" | grep -q 1 || \
  sudo -u postgres createdb xui

log "Start x-ui once and migrate"
systemctl enable --now x-ui
sleep 3
/usr/local/x-ui/x-ui migrate-db || true
sleep 1

log "Ensure PostgreSQL schema"
sudo -u postgres psql -d xui -v ON_ERROR_STOP=1 <<SQL
create table if not exists settings (
  id bigserial primary key,
  key text unique,
  value text
);

create table if not exists users (
  id bigserial primary key,
  username text,
  password text,
  login_epoch bigint default 0
);
SQL

log "Force real settings in PostgreSQL"
sudo -u postgres psql -d xui -v ON_ERROR_STOP=1 <<SQL
insert into settings(key,value)
select 'webPort','\$PANEL_PORT'
where not exists(select 1 from settings where key='webPort');

insert into settings(key,value)
select 'webBasePath','/\$PANEL_WEB_BASE_PATH/'
where not exists(select 1 from settings where key='webBasePath');

insert into settings(key,value)
select 'secret','\$PANEL_API_TOKEN'
where not exists(select 1 from settings where key='secret');

update settings set value='\$PANEL_PORT' where key='webPort';
update settings set value='/\$PANEL_WEB_BASE_PATH/' where key='webBasePath';
update settings set value='\$PANEL_API_TOKEN' where key='secret';

delete from settings
where key in ('webCertFile','webKeyFile','subCertFile','subKeyFile');
SQL

log "Force panel user in PostgreSQL"
HASH="\$(NEW_PASS="\$PANEL_PASSWORD" python3 - <<'PY'
import bcrypt, os
password = os.environ["NEW_PASS"].encode()
h = bcrypt.hashpw(password, bcrypt.gensalt(rounds=10)).decode()
if h.startswith("\$2b\$"):
    h = "\$2a\$" + h[4:]
print(h)
PY
)"

COUNT="\$(sudo -u postgres psql -d xui -Atc "select count(*) from users;")"
if [[ "\$COUNT" == "0" ]]; then
  sudo -u postgres psql -d xui -v ON_ERROR_STOP=1 <<SQL
insert into users(username,password,login_epoch)
values ('\$PANEL_USERNAME','\$HASH',0);
SQL
else
  sudo -u postgres psql -d xui -v ON_ERROR_STOP=1 <<SQL
update users
set username='\$PANEL_USERNAME',
    password='\$HASH',
    login_epoch=0
where id=(select id from users order by id limit 1);
SQL
fi

log "Force x-ui CLI settings too"
/usr/local/x-ui/x-ui setting -port "$PANEL_PORT" || true
/usr/local/x-ui/x-ui setting -webBasePath "/$PANEL_WEB_BASE_PATH/" || true
/usr/local/x-ui/x-ui setting -username "$PANEL_USERNAME" -password "$PANEL_PASSWORD" || true

log "Restart x-ui"
systemctl restart x-ui
sleep 3

log "Verify PostgreSQL state"
sudo -u postgres psql -d xui -P pager=off -c "select id,key,value from settings order by id;"
sudo -u postgres psql -d xui -P pager=off -c "select id,username,login_epoch from users order by id;"

REAL_BASE="\$(sudo -u postgres psql -d xui -Atc "select value from settings where key='webBasePath';" | sed 's#^/##; s#/\$##')"

log "Verify panel base"
rm -f /tmp/xui_cookie.txt /tmp/xui_login.html
curl -fsS \
  -c /tmp/xui_cookie.txt \
  "http://127.0.0.1:\${PANEL_PORT}/\${REAL_BASE}/" >/tmp/xui_login.html

CSRF="\$(grep -oE 'name="csrf-token" content="[^"]+"' /tmp/xui_login.html | sed -E 's/.*content="([^"]+)".*/\1/')"
[[ -n "\$CSRF" ]] || die "CSRF not found"

log "Verify login"

rm -f /tmp/xui_login_resp.txt

LOGIN_PAYLOAD="\$(jq -nc \
  --arg username "\$PANEL_USERNAME" \
  --arg password "\$PANEL_PASSWORD" \
  '{username:\$username,password:\$password,twoFactorCode:""}')"

LOGIN_CODE="\$(curl -sS \
  -o /tmp/xui_login_resp.txt \
  -w "%{http_code}" \
  -b /tmp/xui_cookie.txt \
  -c /tmp/xui_cookie.txt \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: \$CSRF" \
  -d "\$LOGIN_PAYLOAD" \
  "http://127.0.0.1:\${PANEL_PORT}/\${REAL_BASE}/login" || true)"

LOGIN_RESP="\$(cat /tmp/xui_login_resp.txt 2>/dev/null || true)"

echo "LOGIN_CODE=\$LOGIN_CODE"
echo "LOGIN_RESP=\$LOGIN_RESP"

echo "\$LOGIN_RESP" | grep -q '"success":true' || die "Panel login failed"

log "Result"
mkdir -p /root/void-node-bootstrap-results
cat > "/root/void-node-bootstrap-results/\${SERVER_CODE}_\${TARGET_IP}.env" <<EOF_RESULT
NODE_CODE=\${SERVER_CODE}
NODE_HOSTNAME=\${HOSTNAME}
NODE_DOMAIN=\${DOMAIN}
PUBLIC_IP=\${TARGET_IP}
PANEL_ORIGIN=http://\${TARGET_IP}:\${PANEL_PORT}
PANEL_SCHEME=http
PANEL_PORT=\${PANEL_PORT}
PANEL_USERNAME=\${PANEL_USERNAME}
PANEL_PASSWORD=\${PANEL_PASSWORD}
PANEL_WEB_BASE_PATH=\${REAL_BASE}
PANEL_API_BASE_PATH=/\${REAL_BASE}
PANEL_API_TOKEN=\${PANEL_API_TOKEN}
PANEL_ACCESS_URL=http://\${DOMAIN}:\${PANEL_PORT}/\${REAL_BASE}/
PROD_IP=\${PROD_IP}
OWNER_IP=
EOF_RESULT

cat "/root/void-node-bootstrap-results/\${SERVER_CODE}_\${TARGET_IP}.env" | sed -E 's/(PASSWORD|TOKEN)=.*/\1=***hidden***/'

log "DONE remote"
REMOTE

log "Copy result"
mkdir -p "$RESULTS_DIR"
scp_from_target "/root/void-node-bootstrap-results/${SERVER_CODE}_${TARGET_IP}.env" "$RESULT_FILE"

log "Update PROD secrets"
source "$RESULT_FILE"

sudo cp /etc/void/server_secrets.env "/etc/void/server_secrets.env.bak_before_${SERVER_CODE}_$(date +%Y%m%d_%H%M%S)"

sudo sed -i "/^${SECRET_PREFIX}_PANEL_USERNAME=/d" /etc/void/server_secrets.env
sudo sed -i "/^${SECRET_PREFIX}_PANEL_PASSWORD=/d" /etc/void/server_secrets.env
sudo sed -i "/^${SECRET_PREFIX}_PANEL_API_TOKEN=/d" /etc/void/server_secrets.env

{
  echo "${SECRET_PREFIX}_PANEL_USERNAME=${PANEL_USERNAME}"
  echo "${SECRET_PREFIX}_PANEL_PASSWORD=${PANEL_PASSWORD}"
  echo "${SECRET_PREFIX}_PANEL_API_TOKEN=${PANEL_API_TOKEN}"
} | sudo tee -a /etc/void/server_secrets.env >/dev/null

log "Final result"
cat "$RESULT_FILE" | sed -E 's/(PASSWORD|TOKEN)=.*/\1=***hidden***/'

echo
echo "DONE."
