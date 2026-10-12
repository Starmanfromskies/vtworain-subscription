#!/usr/bin/env bash
# Real native panel integration, exclusively on an isolated CI VM.
set -Eeuo pipefail
[[ "${CI:-}" == true ]] || { echo 'Isolated CI runner required'; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
NAME=vtwsub-pasarguard-ci
DATABASE_ARGS=()
if [[ "${PASARGUARD_TEST_DATABASE:-sqlite}" == postgres ]]; then
  docker run -d --name vtwsub-postgres-ci -e POSTGRES_USER=vtwci -e POSTGRES_PASSWORD=SYNTHETIC-CI-ONLY -e POSTGRES_DB=vtwci -p 127.0.0.1:15432:5432 postgres:16 >/dev/null
  for attempt in {1..40}; do docker exec vtwsub-postgres-ci pg_isready -U vtwci >/dev/null 2>&1 && break; sleep 1; done
  DATABASE_ARGS=(-e SQLALCHEMY_DATABASE_URL=postgresql+asyncpg://vtwci:SYNTHETIC-CI-ONLY@127.0.0.1:15432/vtwci)
fi
docker run -d --name "$NAME" --network host \
  -e UVICORN_HOST=127.0.0.1 -e UVICORN_PORT=18080 \
  -e SUDO_USERNAME=ciowner -e SUDO_PASSWORD=SYNTHETIC-CI-ONLY \
  "${DATABASE_ARGS[@]}" "${PASARGUARD_TEST_IMAGE:-pasarguard/panel:latest}" >/dev/null
trap 'docker rm -f "$NAME" vtwsub-postgres-ci >/dev/null 2>&1 || true' EXIT
for attempt in {1..90}; do
  code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/api/settings || true)
  [[ "$code" == 401 || "$code" == 403 ]] && break
  sleep 2
done
# Provision an existing owner fixture in this disposable panel's database.
docker exec -i "$NAME" python - <<'PY'
import asyncio,inspect
from sqlalchemy import select
from app.db import GetDB,models
from app.models.admin import hash_password
async def setup():
 async with GetDB() as db:
  role=(await db.execute(select(models.AdminRole).where(models.AdminRole.is_owner.is_(True)))).scalars().first()
  if not role:
   role=models.AdminRole(name='CI Owner',is_owner=True);db.add(role);await db.commit();await db.refresh(role)
  password=hash_password('SYNTHETIC-CI-ONLY')
  if inspect.isawaitable(password):password=await password
  db.add(models.Admin(username='ciowner',hashed_password=password,role_id=role.id));await db.commit()
asyncio.run(setup())
PY
# Initialize the native token path with an ordinary production owner login.
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
