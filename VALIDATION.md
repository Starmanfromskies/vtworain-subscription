# Validation — 12 October 2026

The newly active custom browser template and all eight referenced assets were
downloaded from the deployed service. The HTML is 27,147 bytes, SHA-256
`46039ed428fbea6d228f4546c8f1a44af4dc425ff46f7fdc65d697c36d28236c`.
All asset hashes are recorded in `source-manifest.json`; the exported frontend
was left byte-for-byte unchanged.

- 29 backend/configuration tests passed with synthetic infrastructure.
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

The GitHub workflow additionally tests real systemd installation/upgrade/rollback
on disposable Ubuntu 22.04 and 24.04 runners and runs the browser checks.
No installation or configuration change was made to the live customer services.
Let's Encrypt issuance requires the actual destination domain/DNS and is not
claimed to have been issued for an unspecified new server.
