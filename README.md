# VTWorain custom subscription page

نسخهٔ جدید ساب کاستوم، به همراه تمام فایل‌های صفحه و نصب‌کنندهٔ سادهٔ لینوکس.
نصب‌کننده دامنه و تنظیمات گواهی را می‌پرسد، پاسارگارد محلی را خودکار پیدا می‌کند
و پس از تأیید سرویس، فقط آدرس عمومی اشتراک را در پنل ثبت می‌کند. آدرس ورود
و مدیریت پنل تغییر نمی‌کند. حساب‌ها و
کانفیگ‌های کاربران از پنل موجود دریافت می‌شوند؛ پایگاه دادهٔ مشتریان همراه
این پروژه نیست.

## One-command installation

Ubuntu 22.04 or newer / Debian 12 or newer, with systemd:

```bash
curl -fsSL https://raw.githubusercontent.com/Starmanfromskies/vtworain-subscription/main/install.sh | sudo bash
```

If already logged in as root, omit `sudo`. The bootstrap downloads the pinned
`v1.1.0` release. Alternatively extract the release ZIP and run
`sudo bash install.sh` in its directory.

The installer asks for:

1. A subscription domain whose DNS points to the new server.
2. TLS mode: automatic Let's Encrypt, existing full-chain/key files, or HTTP
   behind an independently managed TLS proxy.
3. Email/Let's Encrypt terms or the certificate paths, and a listener port.

The panel must be installed on the same machine. The installer discovers a
running Docker or native Python PasarGuard runtime, verifies access using an
existing active owner, and chooses the native backend mode automatically.
Administrative tokens are short-lived, remain inside the panel runtime and
are never printed, exported or stored. No new administrator is created.

Only `subscription.url_prefix` is changed, after gateway/HTTPS health checks.
Its value is built from the domain and port you entered; no customer domain is
hard-coded. The panel login address, listener port, DNS records, users, quotas,
credentials and VPN nodes remain unchanged. Other subscription settings are
retained, including announcements and response headers. Explicit per-admin
subscription-domain overrides remain under your control.

If multiple supported panels run locally, select the intended one with
`--panel-container NAME`. The installer refuses to guess. A panel using only
a Unix socket needs an explicit accessible HTTP upstream; it is not silently
reconfigured.

Advanced flags are available for an independently managed/remote upstream:

```bash
sudo bash install.sh --no-panel-update --upstream https://origin.example.com --mode passthrough
```

`pasarguard` handles native panel exports; `passthrough` relays an already
customized subscription gateway. Neither is asked during normal local setup.
The explicit override does not auto-edit a different/remote panel.

Use a reachable upstream with valid HTTPS, or a trusted loopback/private HTTP
backend. Do not point the upstream back at the new public subscription domain:
that would create a proxy loop. On a **different machine**, `127.0.0.1` refers to
that machine, so supply a reachable address for your existing panel.

Let's Encrypt needs the domain's A/AAAA records to reach this server and inbound
TCP 80 for HTTP-01 validation. The chosen HTTPS port also needs to be reachable.
Provider firewall rules must be opened separately. If UFW is already active,
the installer adds only the necessary public port rules. It never changes DNS.

The installer installs nginx, Gunicorn, Python, QR/image packages and Certbot
(only for automatic certificates), creates a dedicated service, checks occupied
ports/domain conflicts and validates nginx before reloading it. Existing
unrelated sites and services are preserved. An unowned conflicting configuration
causes it to stop rather than overwrite it.

## Subscription URLs and the panel

Keep the private path of each subscription, replacing only its origin:

```text
https://subscription.example.com/sub/<existing-signed-id>
```

Existing legacy IDs, raw app imports, format-specific exports, usage/expiry
headers and WireGuard profiles are retained. A failed upstream authentication
never becomes a successful custom browser page. Panel admin/API routes are not
forwarded. No administrative panel credentials are required by this gateway.

The normal installer automatically sets the panel's **subscription URL prefix**
to the verified new endpoint. The advanced `--no-panel-update` mode leaves that
setting under your control. Neither mode edits the panel login domain, bots,
customer accounts, Xray configuration or existing DNS records.
It installs the subscription frontend/gateway, not a complete VPN control panel.

## Files and operation

- `web/index.html`: the exact newly deployed browser template; inline styles.
- `web/live-wireguard-v2.js`: subscription parser, status, import/copy/search/QR,
  and WireGuard `.conf` download/share support.
- `web/server-labels.js` and `web/assets/`: all eight deployed font/script/icon
  dependencies, served at the existing versioned asset base.
- `app.py`: configurable, subscription-only gateway; verified upstream TLS,
  no external redirects, no subscription request logging or customer cache.
- `deploy.py`, `install.sh`, `backup.py`: installer/configuration/rollback.
- `panel.py`, `panel_bridge.py`: local panel discovery and a conditional,
  field-only subscription prefix update with native API cache refresh.
- `source-manifest.json`: source/asset hashes verified against the current page.
- `tests/`: synthetic backend/browser and isolated Linux installation tests.

Installed configuration: `/etc/vtworain-subscription/config.json`.
Runtime: `/opt/vtworain-subscription`.
Service: `vtworain-subscription.service`.

```bash
sudo systemctl status vtworain-subscription
sudo systemctl restart vtworain-subscription
curl -fsS https://subscription.example.com/healthz
```

Configuration changes take effect after restarting the dedicated service.
The app binds only to loopback, behind nginx. Authentication, quotas and
expiration remain controlled by the authoritative upstream panel. Signed
subscription tokens are private bearer links: keep real ones out of public
issues, logs, sample configurations and screenshots.

`latency_upstream` is optional and defaults to disabled. To preserve an existing
customer-scoped `/tg3xbot-latency/<id>` service, configure its base URL locally.
No reports or customer mappings are copied into this public repository. The
current deployed frontend contains no separate latency companion script.

## Backups and rollback

Before managed changes, the installer backs up its own runtime/config/site,
service state and relevant previous subscription settings under
`/var/backups/vtworain-subscription/<timestamp>`.
Failures restore those files automatically. The exact manual rollback command
is printed on successful installation:

```bash
sudo python3 /var/backups/vtworain-subscription/<timestamp>/rollback.py restore /var/backups/vtworain-subscription/<timestamp>
```

Backups may contain your upstream address/configuration; they are root-only.
Rollback restores only the prefix it changed, and preserves unrelated panel
settings and nginx sites. An independent later prefix edit is not overwritten.
Installed OS packages, certificates
issued by Certbot and additive firewall rules remain installed; no customer
database is restored or overwritten.

For input/config validation without installation:

```bash
bash install.sh --dry-run
```

## Local preview and tests

```bash
python3 tests/mock_upstream.py 18080
```

In another terminal, copy `config.example.json` to `preview-config.json`, use
`mode: "passthrough"` and `public_url: "http://127.0.0.1:8789"`, then run:

```bash
python3 app.py --config preview-config.json --port 8789
```

Open `/sub/synthetic.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/` at that
localhost address. The mock's profiles are synthetic and cannot connect to a
real VPN. Production runs Gunicorn rather than the development server.

```bash
python3 -B -m unittest discover -s tests -v
npm install --no-save playwright
npx playwright install --with-deps chrome
node tests/browser.cjs
```

Panel database regression tests additionally need SQLAlchemy and aiosqlite:
`python3 -m pip install 'SQLAlchemy>=2.0,<2.1' aiosqlite` in your test environment.
Production uses the packages already installed inside your panel runtime.

The Linux installation tests run only on disposable CI runners and explicitly
refuse a regular production machine. They check a fresh HTTP installation,
an HTTPS update, WireGuard/legacy QR exports, unrelated-site preservation and
rollback. Live Let's Encrypt issuance still depends on the target domain/DNS.

References: [nginx proxy module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[Certbot usage](https://eff-certbot.readthedocs.io/en/stable/using.html).
See `THIRD_PARTY_NOTICES.md` for retained third-party libraries and branding.
