#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
REPOSITORY="Starmanfromskies/vtworain-subscription"
RELEASE="v1.1.0"
DOMAIN="" UPSTREAM="" MODE="" TLS_MODE="" EMAIL="" PORT="" CERT="" KEY="" LATENCY=""
DRY_RUN=0 NON_INTERACTIVE=0 ACCEPT_TERMS=0 PANEL_UPDATE=1 PANEL_SELECTOR=""
TMP="" BACKUP="" CHANGED=0
fail() { printf '\nError: %s\n' "$*" >&2; exit 1; }
# Do not let a newly started daemon inherit the installer's exclusive lock.
svc() { systemctl "$@" 9>&-; }
help() {
  cat <<'HELP'
VTWorain subscription page installer — Ubuntu 22.04+/Debian 12+, systemd
  sudo bash install.sh                       Interactive setup
  bash install.sh --dry-run                   Validate/render only; no service changes
  --domain NAME                           Domain used for the subscription prefix
  --panel-container NAME --no-panel-update
  --upstream URL --mode passthrough|pasarguard   Advanced explicit upstream override
  --tls letsencrypt|existing|off --port PORT --email ADDRESS --agree-tos
  --cert-file PATH --key-file PATH --latency-upstream URL --non-interactive
Local PasarGuard is discovered automatically. Its subscription URL prefix is
updated only after endpoint verification. The admin/login domain is preserved.
Default TLS: Let's Encrypt, port 443. No DNS, accounts or VPN nodes are changed.
HELP
}
while (($#)); do
  case "$1" in
    --help|-h) help; exit 0;;
    --dry-run) DRY_RUN=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --agree-tos) ACCEPT_TERMS=1; shift;;
    --no-panel-update) PANEL_UPDATE=0; shift;;
    --domain|--upstream|--mode|--tls|--email|--port|--cert-file|--key-file|--latency-upstream|--panel-container)
      (($#>=2)) || fail "Missing value for $1"
      case "$1" in
        --domain) DOMAIN="$2";; --upstream) UPSTREAM="$2";; --mode) MODE="$2";;
        --tls) TLS_MODE="$2";; --email) EMAIL="$2";; --port) PORT="$2";;
        --cert-file) CERT="$2";; --key-file) KEY="$2";; --latency-upstream) LATENCY="$2";;
        --panel-container) PANEL_SELECTOR="$2";;
      esac; shift 2;;
    *) fail "Unknown option: $1";;
  esac
done
cleanup() {
  local code=$?
  trap - EXIT
  if ((code!=0 && CHANGED==1)) && [[ -n "$BACKUP" && -f "$BACKUP/state.json" ]]; then
    printf '\nInstallation failed; restoring the previous subscription configuration.\n' >&2
    python3 "$BACKUP/rollback.py" restore "$BACKUP" || printf 'Automatic rollback failed. Run: sudo python3 %q restore %q\n' "$BACKUP/rollback.py" "$BACKUP" >&2
  fi
  if [[ -n "$TMP" && "$TMP" == /tmp/vtwsub-install.* && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  exit "$code"
}
trap cleanup EXIT
[[ -f /etc/os-release ]] || fail "Linux /etc/os-release is required"
# shellcheck source=/dev/null
source /etc/os-release
[[ "$ID" == ubuntu || "$ID" == debian ]] || fail "Supported systems: Ubuntu and Debian"
if [[ "$ID" == ubuntu ]]; then [[ "${VERSION_ID%%.*}" -ge 22 ]] || fail "Ubuntu 22.04 or newer is required"; fi
if [[ "$ID" == debian ]]; then [[ "${VERSION_ID%%.*}" -ge 12 ]] || fail "Debian 12 or newer is required"; fi
if ((DRY_RUN==0)); then
  [[ "$EUID" -eq 0 ]] || fail "Run with sudo or as root"
  [[ -d /run/systemd/system ]] || fail "A running systemd installation is required"
  mkdir -p /run/lock
  exec 9>/run/lock/vtworain-subscription.install.lock
  flock -n 9 || fail "Another subscription installation is running"
fi
ask() {
  local variable="$1" prompt="$2" default="${3:-}" answer=""
  [[ -z "${!variable}" ]] || return 0
  ((NON_INTERACTIVE==0)) || { printf -v "$variable" '%s' "$default"; return 0; }
  [[ -r /dev/tty ]] || fail "Interactive setup needs a terminal; use --non-interactive with explicit options"
  read -r -p "$prompt${default:+ [$default]}: " answer </dev/tty
  printf -v "$variable" '%s' "${answer:-$default}"
}
printf 'VTWorain custom subscription page %s\n' "$RELEASE"
ask DOMAIN "New subscription domain (point its DNS to this server)"
ask TLS_MODE "TLS: letsencrypt, existing, or off (HTTP behind your own proxy)" letsencrypt
if [[ "$TLS_MODE" == off ]]; then ask PORT "HTTP listener port" 8080; else ask PORT "HTTPS listener port" 443; fi
if [[ "$TLS_MODE" == letsencrypt ]]; then
  ask EMAIL "Let's Encrypt email"
  [[ "$EMAIL" == *@*.* && "$EMAIL" != *$'\n'* ]] || fail "A valid email is required"
  if ((ACCEPT_TERMS==0)); then
    ((NON_INTERACTIVE==0)) || fail "Use --agree-tos to accept Let's Encrypt terms"
    ANSWER=""; ask ANSWER "Accept the Let's Encrypt terms at https://letsencrypt.org/repository/? (yes/no)" no
    [[ "$ANSWER" == yes ]] || fail "Certificate terms were not accepted"
  fi
  CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"; KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
elif [[ "$TLS_MODE" == existing ]]; then
  ask CERT "Existing full-chain certificate path"; ask KEY "Existing private key path"
fi
[[ -n "$DOMAIN" ]] || fail "A subscription domain is required"
if ! command -v python3 >/dev/null; then
  ((DRY_RUN==0)) || fail "Install Python 3 to use --dry-run"
  apt-get update 9>&-; DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade python3 9>&-
fi
TMP=$(mktemp -d /tmp/vtwsub-install.XXXXXXXX)
SOURCE=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true); fi
if [[ ! -f "$SOURCE/app.py" || ! -f "$SOURCE/web/index.html" || ! -f "$SOURCE/deploy.py" || ! -f "$SOURCE/panel.py" ]]; then
  command -v curl >/dev/null || fail "curl is required for the bootstrap download"
  mkdir "$TMP/source"
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 "https://github.com/$REPOSITORY/archive/refs/tags/$RELEASE.tar.gz" -o "$TMP/source.tar.gz"
  tar -xzf "$TMP/source.tar.gz" --strip-components=1 --no-same-owner -C "$TMP/source"
  SOURCE="$TMP/source"
fi
DISCOVER_ARGS=()
if [[ -z "$UPSTREAM" ]]; then
  [[ "$EUID" -eq 0 ]] || fail "Run with sudo to discover the local PasarGuard panel"
  python3 "$SOURCE/panel.py" discover --selector "$PANEL_SELECTOR" --out "$TMP/discovered"
  UPSTREAM=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["upstream"])' "$TMP/discovered/discovered.json")
  MODE=pasarguard
  DISCOVER_ARGS=(--discovered "$TMP/discovered/discovered.json")
elif ((PANEL_UPDATE==1)); then
  [[ "$EUID" -eq 0 ]] || fail "Run with sudo to update the local panel, or use --no-panel-update"
  python3 "$SOURCE/panel.py" discover --selector "$PANEL_SELECTOR" --out "$TMP/discovered"
  NATIVE_UPSTREAM=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["upstream"])' "$TMP/discovered/discovered.json")
  [[ "${UPSTREAM%/}" == "$NATIVE_UPSTREAM" ]] || fail "Explicit upstream differs from the local panel. Use --no-panel-update for a separate/custom upstream"
  MODE=pasarguard
  DISCOVER_ARGS=(--discovered "$TMP/discovered/discovered.json")
else
  MODE=${MODE:-pasarguard}
fi
APP_PORT=$(python3 - <<'PY'
import socket
from pathlib import Path
import json
file=Path('/etc/vtworain-subscription/config.json')
if file.exists():
 try:
  import re
  unit=Path('/etc/systemd/system/vtworain-subscription.service').read_text()
  match=re.search(r'--bind 127\.0\.0\.1:(\d+)',unit)
  if match:print(match[1]);raise SystemExit
 except (ValueError,OSError):pass
for port in range(19839,19939):
 with socket.socket() as s:
  try:s.bind(('127.0.0.1',port))
  except OSError:continue
  print(port);break
else:raise SystemExit('No free loopback application port')
PY
)
python3 "$SOURCE/deploy.py" --domain "$DOMAIN" --upstream "$UPSTREAM" --mode "$MODE" --tls "$TLS_MODE" --port "$PORT" --app-port "$APP_PORT" --certificate "$CERT" --key "$KEY" --latency "$LATENCY" --out "$TMP/rendered" "${DISCOVER_ARGS[@]}"
if ((DRY_RUN==1)); then
  printf '\nDry run passed. Dedicated nginx site and systemd service rendered successfully.\n'
  printf 'Domain: %s\nMode: %s\nTLS: %s\nPublic port: %s\nLoopback port: %s\n' "$DOMAIN" "$MODE" "$TLS_MODE" "$PORT" "$APP_PORT"
  exit 0
fi
if [[ -e /opt/vtworain-subscription ]]; then
  [[ -f /opt/vtworain-subscription/.managed-by-installer && ! -L /opt/vtworain-subscription ]] || fail "The runtime directory is owned by another installation"
fi
if [[ -e /etc/vtworain-subscription/config.json && ! -f /opt/vtworain-subscription/.managed-by-installer ]]; then fail "An unowned subscription configuration already exists"; fi
for file in /etc/nginx/conf.d/vtworain-subscription.conf /etc/nginx/conf.d/vtworain-subscription-rate.conf /etc/systemd/system/vtworain-subscription.service /etc/letsencrypt/renewal-hooks/deploy/vtworain-subscription.sh; do
  if [[ -e "$file" ]]; then grep -q '^# Managed by vtworain-subscription installer$' "$file" || fail "Refusing to overwrite unowned file: $file"; fi
done
python3 - "$DOMAIN" "$PORT" "$TLS_MODE" <<'PY'
import re,subprocess,sys,shutil
domain,port,tls=sys.argv[1:]
ports=[port]+(['80'] if tls!='off' else [])
if not shutil.which('nginx'):ports.append('80')
if shutil.which('ss'):
 for p in set(ports):
  data=subprocess.check_output(['ss','-Hlntp','sport','=',':'+p],text=True)
  if data.strip() and 'nginx' not in data:raise SystemExit('Port '+p+' is used by another service; choose another port/TLS mode')
if shutil.which('nginx'):
 subprocess.run(['nginx','-t'],check=True)
 data=subprocess.run(['nginx','-T'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,check=True).stdout
 for section in re.split(r'^# configuration file ',data,flags=re.M):
  if section.startswith('/etc/nginx/conf.d/vtworain-subscription.conf:'):continue
  for names in re.findall(r'\bserver_name\s+([^;]+);',section):
   if domain in names.split():raise SystemExit('This domain already belongs to another nginx site')
PY
if [[ "$TLS_MODE" == existing ]]; then [[ -r "$CERT" && -r "$KEY" ]] || fail "Certificate/key files cannot be read"; fi
BACKUP="/var/backups/vtworain-subscription/$(date -u +%Y%m%dT%H%M%SZ)-$$"
python3 "$SOURCE/backup.py" capture "$BACKUP"
if ((PANEL_UPDATE==1)); then
  python3 "$SOURCE/panel.py" snapshot --integration "$TMP/discovered/panel.json" --backup "$BACKUP"
fi
CHANGED=1
apt-get update 9>&-
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade nginx python3 gunicorn python3-qrcode python3-pil ca-certificates curl 9>&-
if [[ "$TLS_MODE" == letsencrypt ]]; then DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade certbot 9>&-; fi
getent passwd vtwsub >/dev/null || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin vtwsub
mkdir -p /opt/vtworain-subscription /etc/vtworain-subscription /etc/nginx/conf.d /var/lib/vtworain-subscription/acme
chmod 755 /var/lib/vtworain-subscription /var/lib/vtworain-subscription/acme
touch /opt/vtworain-subscription/.managed-by-installer
cp -a "$SOURCE/web" /opt/vtworain-subscription/
install -m 644 "$SOURCE/app.py" /opt/vtworain-subscription/app.py
install -m 644 "$SOURCE/panel.py" /opt/vtworain-subscription/panel.py
install -m 644 "$SOURCE/panel_bridge.py" /opt/vtworain-subscription/panel_bridge.py
install -m 644 "$SOURCE/source-manifest.json" /opt/vtworain-subscription/source-manifest.json
chown -R root:root /opt/vtworain-subscription
find /opt/vtworain-subscription -type d -exec chmod 755 {} +
find /opt/vtworain-subscription -type f -exec chmod 644 {} +
install -o root -g vtwsub -m 640 "$TMP/rendered/config.json" /etc/vtworain-subscription/config.json
chmod 750 /etc/vtworain-subscription; chown root:vtwsub /etc/vtworain-subscription
if [[ -f "$TMP/discovered/panel.json" ]]; then install -m 600 "$TMP/discovered/panel.json" /etc/vtworain-subscription/panel.json; fi
if [[ -f "$TMP/discovered/panel-ca.pem" ]]; then install -o root -g vtwsub -m 640 "$TMP/discovered/panel-ca.pem" /etc/vtworain-subscription/panel-ca.pem; fi
install -m 644 "$TMP/rendered/vtworain-subscription.service" /etc/systemd/system/vtworain-subscription.service
install -m 644 "$TMP/rendered/rate-limit.conf" /etc/nginx/conf.d/vtworain-subscription-rate.conf
if [[ "$TLS_MODE" == letsencrypt ]]; then
  install -m 644 "$TMP/rendered/acme.conf" /etc/nginx/conf.d/vtworain-subscription.conf
  nginx -t
  if svc is-active --quiet nginx; then svc reload nginx; else svc start nginx; fi
  printf '\nDNS for %s must point to this server; inbound TCP 80 and %s must be open.\n' "$DOMAIN" "$PORT"
  if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then ufw allow 80/tcp; ufw allow "$PORT/tcp"; fi
  certbot certonly --webroot -w /var/lib/vtworain-subscription/acme --cert-name "$DOMAIN" -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --keep-until-expiring
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  printf '#!/bin/sh\n# Managed by vtworain-subscription installer\nnginx -t && systemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/vtworain-subscription.sh
  chmod 755 /etc/letsencrypt/renewal-hooks/deploy/vtworain-subscription.sh
  svc enable --now certbot.timer
fi
install -m 644 "$TMP/rendered/nginx.conf" /etc/nginx/conf.d/vtworain-subscription.conf
nginx -t
svc daemon-reload
svc enable --now vtworain-subscription
svc restart vtworain-subscription
for attempt in {1..15}; do
  if curl --noproxy '*' -fsS "http://127.0.0.1:$APP_PORT/healthz" > "$TMP/health.json" 2>"$TMP/startup-check.log"; then break; fi
  sleep 1
done
python3 - "$TMP/health.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))=={'status':'ok','version':'1.1.0'},'Subscription service did not become ready'
PY
if svc is-active --quiet nginx; then svc reload nginx; else svc start nginx; fi
svc enable nginx
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then ufw allow "$PORT/tcp"; fi
SCHEME=https; [[ "$TLS_MODE" != off ]] || SCHEME=http
curl --noproxy '*' --resolve "$DOMAIN:$PORT:127.0.0.1" -fsS "$SCHEME://$DOMAIN:$PORT/healthz" > "$TMP/public-health.json"
python3 - "$TMP/public-health.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))=={'status':'ok','version':'1.1.0'}
PY
if ((PANEL_UPDATE==1)); then
  PUBLIC_URL=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["public_url"])' "$TMP/rendered/config.json")
  python3 "$SOURCE/panel.py" update --integration "$TMP/discovered/panel.json" --backup "$BACKUP" --url "$PUBLIC_URL"
fi
CHANGED=0
printf '\nInstallation verified. New endpoint: %s://%s:%s\n' "$SCHEME" "$DOMAIN" "$PORT"
printf 'Use the same private subscription path under the new domain.\n'
if ((PANEL_UPDATE==1)); then printf 'PasarGuard Subscription URL Prefix was updated automatically.\n'; fi
printf 'The panel admin/login address, accounts, DNS and VPN services were preserved.\n'
printf 'Rollback: sudo python3 %q restore %q\n' "$BACKUP/rollback.py" "$BACKUP"
printf 'Configuration: /etc/vtworain-subscription/config.json\n'
