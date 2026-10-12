# Validation — 12 October 2026

## v1.1.0 — automatic local PasarGuard integration

The [v1.1 verification run](https://github.com/Starmanfromskies/vtworain-subscription/actions/runs/38206574876)
passed all five jobs: Ubuntu 22.04, Ubuntu 24.04, Chrome browser, native
PasarGuard/SQLite and native PasarGuard/PostgreSQL 16.

- 46 backend/configuration/database/TLS tests passed. The database tests verify
  conditional field-only updates, concurrent edit preservation, identity checks,
  empty/absent prefix rollback and compensation when native cache refresh fails.
- 13 browser scenarios passed with the original, unchanged frontend.
- Real native panels in disposable CI containers were discovered without asking
  for an upstream URL or backend mode. Existing production database owner
  authentication was used. No installer-created administrator or stored auth
  token was needed.
- Two different subscription domains were installed in sequence. Both databases
  recorded the entered domain/port correctly, retained other subscription fields,
  and restored the previous prefix during rollback. The panel API listener and
  login address were not changed.
- Real upstream TLS tests verified the configured hostname and certificate;
  the wrong hostname was rejected. Automatic integration keeps TLS verification
  enabled for a panel that terminates TLS itself.
- A read-only compatibility probe recognized the existing deployed PasarGuard
  runtime and verified its owner/settings API. No live customer settings were
  modified during this probe.
- Expected initial connection retries are quiet; readiness still must pass
  before the installer can report success or register the public prefix.

The live installation at a customer's machine is upgraded by rerunning the
published installer there. Merely publishing this release does not change that
machine's panel or subscription configuration.

## Original v1.0 verification

The newly active custom browser template and all eight referenced assets were
downloaded from the deployed service. The HTML is 27,147 bytes, SHA-256
`46039ed428fbea6d228f4546c8f1a44af4dc425ff46f7fdc65d697c36d28236c`.
All asset hashes are recorded in `source-manifest.json`; the exported frontend
was left byte-for-byte unchanged.

- 30 backend/configuration tests passed with synthetic infrastructure, including
  waiting for restored worker readiness before rollback completes.
- 13 Chrome browser scenarios passed, including signed/legacy, plain/base64,
  mixed protocols, expiry/unlimited/error states, WireGuard downloads, QR,
  clipboard, search, dual-stack profiles and invalid-profile rejection.
- Bash syntax checks passed for the installer and isolated Linux test script.
- On an isolated Ubuntu 24.04 container, the installer installed the actual OS
  dependencies, served the exact HTML and raw profile data through nginx and
  Gunicorn, produced a legacy WireGuard subscription QR, updated to HTTPS,
  preserved a separate nginx site and successfully restored the prior version.
  The container used a service lifecycle shim because it does not boot systemd;
  nginx/Gunicorn/TLS/QR processing were real. HTTPS used a test certificate/CA.
- Protected credentials, GitHub authentication and token/private-key patterns
  were checked against public files: zero matches. Test profiles and keys are
  explicitly synthetic. Customer IDs, real configurations, databases, API
  credentials, production nginx snapshots and original backend secrets are not
  included in the public repository.

The [GitHub verification run](https://github.com/Starmanfromskies/vtworain-subscription/actions/runs/38203254367)
passed all three jobs: real systemd installation/HTTPS upgrade/rollback on
disposable Ubuntu 22.04 and 24.04 runners, and the 13 browser scenarios.
No installation or configuration change was made to the live customer services.
Let's Encrypt issuance requires the actual destination domain/DNS and is not
claimed to have been issued for an unspecified new server.
