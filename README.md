# VTWorain custom subscription page

نسخهٔ جدید ساب کاستوم، به همراه تمام فایل‌های صفحه و نصب‌کنندهٔ سادهٔ لینوکس.
نصب‌کننده دامنه، آدرس پنل/ساب مبدأ و تنظیمات گواهی را می‌پرسد. حساب‌ها و
کانفیگ‌های کاربران از پنل موجود دریافت می‌شوند؛ پایگاه دادهٔ مشتریان همراه
این پروژه نیست.

## One-command installation

Ubuntu 22.04 or newer / Debian 12 or newer, with systemd:

```bash
curl -fsSL https://raw.githubusercontent.com/Starmanfromskies/vtworain-subscription/main/install.sh | sudo bash
```

If already logged in as root, omit `sudo`. The bootstrap downloads the pinned
`v1.0.0` release. Alternatively extract the release ZIP and run
`sudo bash install.sh` in its directory.

The installer asks for:

1. A subscription domain whose DNS points to the new server.
2. The base URL of the existing subscription backend/panel, **without a customer
   subscription token**, username, password or URL query.
3. `passthrough` for an existing custom subscription service, or `pasarguard` for
   the native PasarGuard panel. Native `?raw=1` requests use `links_base64`.
4. TLS mode: automatic Let's Encrypt, existing full-chain/key files, or HTTP
   behind an independently managed TLS proxy.
5. Email/Let's Encrypt terms or the certificate paths, and a listener port.

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

To make newly issued panel/bot links use this domain, set the **subscription URL
prefix** in your panel to the new endpoint. This installer does not edit the
panel, bots, customer accounts, Xray configuration or existing DNS records.
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

Before managed changes, the installer backs up only its own runtime/config/site
and service state under `/var/backups/vtworain-subscription/<timestamp>`.
Failures restore those files automatically. The exact manual rollback command
is printed on successful installation:

```bash
sudo python3 /var/backups/vtworain-subscription/<timestamp>/rollback.py restore /var/backups/vtworain-subscription/<timestamp>
```

Backups may contain your upstream address/configuration; they are root-only.
Rollback preserves unrelated nginx sites. Installed OS packages, certificates
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

The Linux installation tests run only on disposable CI runners and explicitly
refuse a regular production machine. They check a fresh HTTP installation,
an HTTPS update, WireGuard/legacy QR exports, unrelated-site preservation and
rollback. Live Let's Encrypt issuance still depends on the target domain/DNS.

References: [nginx proxy module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[Certbot usage](https://eff-certbot.readthedocs.io/en/stable/using.html).
See `THIRD_PARTY_NOTICES.md` for retained third-party libraries and branding.
