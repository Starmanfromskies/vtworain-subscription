#!/usr/bin/env bash
# Real native panel integration, exclusively on an isolated CI VM.
set -Eeuo pipefail
[[ "${CI:-}" == true ]] || { echo 'Isolated CI runner required'; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
NAME=vtwsub-pasarguard-ci
docker run -d --name "$NAME" --network host \
  -e UVICORN_HOST=127.0.0.1 -e UVICORN_PORT=18080 \
  -e SUDO_USERNAME=ciowner -e SUDO_PASSWORD=SYNTHETIC-CI-ONLY \
  "${PASARGUARD_TEST_IMAGE:-pasarguard/panel:latest}" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
for attempt in {1..90}; do
  code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/api/settings || true)
  [[ "$code" == 401 || "$code" == 403 ]] && break
  sleep 2
done
# Initialize the native token path using only the synthetic CI environment owner.
docker exec -i "$NAME" python - <<'PY'
from urllib.request import Request,urlopen
from urllib.parse import urlencode
data=urlencode({'username':'ciowner','password':'SYNTHETIC-CI-ONLY'}).encode()
with urlopen(Request('http://127.0.0.1:18080/api/admin/token',data=data),timeout=15) as r:
 assert r.status==200
PY
sudo python3 panel.py discover --selector "$NAME" --out /tmp/vtwsub-ci-native
sudo python3 panel.py snapshot --integration /tmp/vtwsub-ci-native/panel.json --backup /tmp/vtwsub-ci-native
sudo bash install.sh --non-interactive --domain native.example.test --panel-container "$NAME" --tls off --port 8080
sudo python3 - <<'PY'
import json,panel
from pathlib import Path
integration=json.loads(Path('/etc/vtworain-subscription/panel.json').read_text())
current=panel.run_bridge(integration['locator'],'snapshot',{'fingerprint':integration['fingerprint']})
before=json.loads(Path('/tmp/vtwsub-ci-native/panel-before.json').read_text())
assert current['old_url']=='http://native.example.test:8080'
a=current['subscription'];b=before['subscription'];a.pop('url_prefix',None);b.pop('url_prefix',None)
assert a==b,'Unrelated native subscription fields changed'
PY
# Rerun under a different public domain: no fixed domain and no upstream prompt.
sudo bash install.sh --non-interactive --domain another.example.test --panel-container "$NAME" --tls off --port 8080
sudo python3 - <<'PY'
import json,panel
from pathlib import Path
integration=json.loads(Path('/etc/vtworain-subscription/panel.json').read_text())
assert panel.run_bridge(integration['locator'],'describe')['old_url']=='http://another.example.test:8080'
assert json.loads(Path('/etc/vtworain-subscription/config.json').read_text())['upstream']=='http://127.0.0.1:18080'
PY
LATEST=$(sudo find /var/backups/vtworain-subscription -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
sudo python3 "$LATEST/rollback.py" restore "$LATEST"
sudo python3 - <<'PY'
import json,panel
from pathlib import Path
integration=json.loads(Path('/etc/vtworain-subscription/panel.json').read_text())
assert panel.run_bridge(integration['locator'],'describe')['old_url']=='http://native.example.test:8080'
PY
echo 'Real native autodetection, dynamic prefix, unrelated settings and panel rollback PASS'
