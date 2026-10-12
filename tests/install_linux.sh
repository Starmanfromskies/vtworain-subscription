#!/usr/bin/env bash
# Runs only on a disposable Ubuntu/Debian CI machine, never a production server.
set -Eeuo pipefail
[[ "${CI:-}" == true ]] || { echo 'This installation test requires an isolated CI runner'; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
python3 tests/mock_upstream.py 18080 &
UPSTREAM_PID=$!
trap 'kill "$UPSTREAM_PID" 2>/dev/null || true' EXIT
sleep 1
bash install.sh --dry-run --no-panel-update --non-interactive --domain subscription.example.test --upstream http://127.0.0.1:18080 --mode passthrough --tls off --port 8080
if bash install.sh --dry-run --no-panel-update --non-interactive --domain 'bad;domain' --upstream http://127.0.0.1:18080 --mode passthrough --tls off --port 8080; then exit 1; fi
sudo bash install.sh --no-panel-update --non-interactive --domain subscription.example.test --upstream http://127.0.0.1:18080 --mode passthrough --tls off --port 8080
TOKEN="synthetic.$(printf 'A%.0s' {1..43})"
curl --noproxy '*' --resolve subscription.example.test:8080:127.0.0.1 -fsS -H 'Accept: text/html' "http://subscription.example.test:8080/sub/$TOKEN/" -o /tmp/vtwsub-page.html
cmp web/index.html /tmp/vtwsub-page.html
curl --noproxy '*' --resolve subscription.example.test:8080:127.0.0.1 -fsS "http://subscription.example.test:8080/sub/$TOKEN/?raw=1" -o /tmp/vtwsub-raw.txt
python3 - <<'PY'
import base64
from pathlib import Path
assert b'wireguard://' in base64.b64decode(Path('/tmp/vtwsub-raw.txt').read_bytes())
PY
curl --noproxy '*' --resolve subscription.example.test:8080:127.0.0.1 -fsS 'http://subscription.example.test:8080/tg3xbot-sub-qr/synthetic123.png' -o /tmp/vtwsub-qr.png
python3 - <<'PY'
from pathlib import Path
assert Path('/tmp/vtwsub-qr.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
PY
cat >/tmp/vtwsub-unrelated.conf <<'NGINX'
server { listen 127.0.0.1:18081; server_name unrelated.example.test; location / { return 200 'unrelated-preserved'; } }
NGINX
sudo cp /tmp/vtwsub-unrelated.conf /etc/nginx/conf.d/vtwsub-unrelated-ci.conf
sudo nginx -t
sudo systemctl reload nginx
CERT_DIR=$(mktemp -d /tmp/vtwsub-ci-cert.XXXXXXXX)
chmod 755 "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" -days 1 -subj '/CN=subscription.example.test' -addext 'subjectAltName=DNS:subscription.example.test' 2>/dev/null
sudo env CURL_CA_BUNDLE="$CERT_DIR/cert.pem" bash install.sh --no-panel-update --non-interactive --domain subscription.example.test --upstream http://127.0.0.1:18080 --mode pasarguard --tls existing --port 443 --cert-file "$CERT_DIR/cert.pem" --key-file "$CERT_DIR/key.pem"
curl --noproxy '*' --cacert "$CERT_DIR/cert.pem" --resolve subscription.example.test:443:127.0.0.1 -fsS "https://subscription.example.test/sub/$TOKEN/?raw=1" -o /tmp/vtwsub-tls-raw.txt
cmp /tmp/vtwsub-raw.txt /tmp/vtwsub-tls-raw.txt
cmp /tmp/vtwsub-unrelated.conf /etc/nginx/conf.d/vtwsub-unrelated-ci.conf
LATEST=$(sudo find /var/backups/vtworain-subscription -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
sudo python3 "$LATEST/rollback.py" restore "$LATEST"
curl --noproxy '*' --resolve subscription.example.test:8080:127.0.0.1 -fsS 'http://subscription.example.test:8080/healthz'
cmp /tmp/vtwsub-unrelated.conf /etc/nginx/conf.d/vtwsub-unrelated-ci.conf
printf '\nFresh install, HTTPS update, raw/QR compatibility, unrelated site preservation and rollback PASS\n'
