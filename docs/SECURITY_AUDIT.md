# Security audit and remediation

Audit date: November 1, 2026 (America/Chicago). Baseline: `eabfbfa`. Scope: Python/FastAPI API, authentication, SQLite/PostgreSQL adapter, background worker, Gemini/source gateway, SMTP/IMAP, browser rendering, Docker/Railway configuration and dependency manifests. This is a source review with local and Linux CI regression checks, not an independent penetration-test certification or a guarantee against compromise.

## Findings and disposition

| Finding | Risk / impact | Remediation |
| --- | --- | --- |
| Known advisories in Starlette 0.50.0 | The initial dependency audit returned ten entries representing five distinct advisory IDs: PYSEC-2026-161, -2281, -2280, -249 and -248. Applicability varies by route, but carrying a known vulnerable framework into production was unacceptable. | Upgraded FastAPI to 0.162.0 and Starlette to 1.10.0. Added hash-verified transitive runtime lock, dependency audit CI, and update configuration. Re-audit returned no known vulnerabilities. |
| No Docker/Git exclusions for deployment secrets and runtime data | A local `.env`, database, backup or virtual environment could enter a build context or commit. | Added explicit `.dockerignore` and `.gitignore` rules. The image installs only the locked runtime. |
| No encrypted settings storage or first-run ownership flow | Operators had to place all credentials in environment configuration; there was no safe browser onboarding. Existing environment values were not found exposed in the API, but the requested hosted setup was absent. | Added an admin-only encrypted vault and one-time, token-protected wizard. A transaction creates the first owner, stores encrypted MFA, and closes bootstrap permanently. No first-visitor ownership race. |
| Original scrypt work factor below current recommended settings; no MFA | Password compromise or a stolen password gave full account access. | New passwords use Argon2id with 64 MiB, three iterations and one lane. Existing scrypt hashes upgrade on successful login. New wizard owners must enroll TOTP. Codes are replay-protected; random recovery codes are hashed and consumed once. Password/MFA changes revoke old sessions. |
| Login throttle was process-local and keyed to proxy peer | Restarting cleared counters; reverse-proxy traffic could share one bucket. Unbounded peer-key tracking was also undesirable. | Added expiring database-backed per-account and global throttles. Forwarded IP headers cannot bypass them. Concurrent expensive hashes are capped at two to bound memory. Edge-level flood protection remains an infrastructure concern. |
| Loose substring-based role checks and viewer logout blocked | Authorization intent was difficult to verify; read-only users could not log out through the API. | Replaced substring checks with anchored method/path rules; protected setup/integration reads and writes with admin checks. Viewers can log out and manage their own password/MFA. Added regression tests. |
| Long-lived session could change integration destinations | A stolen session could redirect mail connections while reusing saved credentials. | Credential changes require password/MFA authentication within 15 minutes. Config changes pause outreach; secret values never have a read-back endpoint. |
| Security headers absent on early rejections; exception trace risk | Some denied requests skipped security headers; raw provider exceptions could reach server logs. | Added outer ASGI security headers and sanitized error handling. Disabled URL access logging to avoid recording unsubscribe tokens and query strings. Added JSON content-type checks and cross-origin restrictions. |
| Container/volume startup was incompatible with root-owned Railway volumes | UID 10001 could fail to create the database; ephemeral storage could lose accounts and keys. | Added a constrained volume initializer that drops privileges before serving. Startup requires persistent SQLite storage on Railway; healthchecks read the database. Added Linux container smoke checks to CI. |
| Mail endpoints were unchecked network destinations | Browser-configured mail hosts would otherwise allow connections to private networks or metadata services. | Added public-IP validation and address pinning before SMTP/IMAP connections, preserving TLS hostname verification. Production PostgreSQL now requires `sslmode=verify-full`. |

## Security properties verified locally

- Production startup rejects absent/malformed encryption keys, invalid origins, ephemeral Railway SQLite, and unverified PostgreSQL TLS configuration.
- Unauthenticated callers cannot read workspace data or configuration. The public bootstrap status reveals only whether initial setup is open.
- Setup token failure, replay, simultaneous claims, invalid TOTP, and short passwords are rejected. The token is sent in JSON over HTTPS, never in a URL.
- Sessions are high-entropy, server-side, SHA-256-indexed tokens, expire after 12 hours, and use a `__Host-` cookie with Secure, HttpOnly, SameSite=Strict, Path=/ and no Domain in production. CSRF tokens are separate from session tokens.
- TOTP seeds and integration settings are encrypted using AES-256-GCM, random 96-bit nonces, and version/purpose-bound associated data. Database-only theft cannot decrypt them without the separately stored key. Wrong keys and tampered ciphertext fail closed.
- Saved integration values survive reopening the store. Blank secret inputs preserve existing values; removal is explicit. No secret value is returned by settings, state, checklist or JSON exports; credential updates write no secrets to audit logs.
- Password hashes and recovery-code hashes are one-way. Raw account passwords are never persisted. MFA setup keys and recovery codes are shown only during enrollment, with no-store responses.
- Key rotation re-encrypts vault and MFA records transactionally; a previous key can be retained temporarily for reads.
- Private IPv4/IPv6 mail destinations are rejected; connection uses the validated address rather than repeating DNS resolution. Existing source fetches also pin public addresses and validate each redirect.
- The real browser wizard runs over local HTTPS with Secure cookies. Synthetic account creation, MFA, encrypted settings, reload, recovery login, and responsive desktop/mobile layouts are exercised without contacting external providers.

## Static review notes

SQL values use parameters. Bandit flags `Service.required()` because a table name is interpolated; the method first checks a fixed internal allowlist and the identifier is never supplied by a request. The flag is not an exploitable SQL injection in the reviewed code. Bandit also flags `0.0.0.0` in the deployment-variable generator; that bind is intentional behind Railway's proxy, with production authentication and canonical-host checks. These findings remain visible for review rather than being silently suppressed. The CI gates high-severity results; medium/low results need human triage.

The frontend escapes untrusted text/attributes and only renders http(s) external links. CSP disallows inline scripts, external script origins, framing, objects and arbitrary connection destinations. Generated research does not get send/approval/deployment tools, and imported contacts remain unverified. Review and mail-dispatch business gates were retained and exercised by the original suite.

All eleven low-severity Bandit findings were also reviewed: the fixed interpreter `execv` after privilege dropping, cleanup/rollback exception handling, malformed-mail parsing that cannot authorize a send, and assertions/synthetic passwords in the browser test harness. They are not untrusted shell execution or production hardcoded credentials. There were no high-severity Bandit findings.

## Deployment acceptance and residual risks

1. **Railway launch verified on November 2, 2026 UTC.** Commit `63808bd4fb10d8797423a29af71d58311edb2402` built and started with a 1 GB volume at `/app/data`. Public TLS certificate verification, health/setup endpoints and rendered wizard passed. Anonymous private endpoints returned 401; invalid claim tokens and cross-origin setup calls returned 403; security headers were present. [Linux CI passed](https://github.com/lemur001/stakeout/actions/runs/41387886236) all 83 tests, HTTPS wizard, dependency audit, static scan gate, image build, UID 10001 and container restart checks. Owner enrollment, real credentials and a live backup restore were not performed. The reusable template has not yet been created in Railway.
2. Real Gemini/Brave access, SMTP/IMAP behavior, external MCP calls, provider spend controls and deliverability were not tested with real accounts. Configuration checks do not verify provider acceptance. Keep live sending off during commissioning.
3. The PostgreSQL adapter and full backup restoration require staging tests. Schema version 2 adds tables without deleting existing records; a pre-upgrade backup is still necessary. The supported pilot topology is one web/worker process, not multiple active replicas.
4. Encryption protects stored credential material, not a compromised running process, an XSS-capable code change, or an attacker controlling Railway/GitHub. Runtime memory and environment must contain usable key material. Seal boot variables, restrict collaborator access, enable MFA, and keep database and encryption-key backups separate.
5. Organization/contact records, notes, messages, user email addresses and ordinary application settings remain in the database in their normal format. They are not covered by the application credential vault. Protect volume/backups and exports accordingly. No claim of full-database application encryption is made.
6. A source-registry `fetch_allowed` entry grants host-level retrieval in this release. Do not approve a host if your permission only covers a path. Robots checks are not licenses, and model-derived records still require human review.
7. Legacy or CLI-created secondary accounts do not automatically have MFA. They can enroll via Settings → Authenticator & recovery codes. There is no SSO, WebAuthn/passkey authentication, email password-reset workflow, client-tenant isolation, or independent external key-management service. All agency roles share one workspace.
8. Application throttling and a concurrency limit reduce common abuse but do not replace edge rate limiting or volumetric DDoS protection. A global throttle can deny legitimate login during a sustained attack; it deliberately favors limiting password-hash resource usage.
9. Linux base-image OS packages must be scanned and regularly rebuilt separately from the Python dependency audit. A clean package audit is time-specific, not a claim that vulnerabilities cannot exist.

## Reproduce verification

```sh
python -m pip install --require-hashes -r requirements.lock
python -m pip install -r requirements-dev.txt -r requirements-security.txt
python -m pytest -q
python -m pip_audit -r requirements.lock --progress-spinner off
python -m bandit -r app scripts run.py worker.py docker_entrypoint.py -ll -q
python -m playwright install chromium
python scripts/test_browser_setup.py
```

The browser harness generates temporary synthetic credentials and a short-lived local TLS certificate, removes its temporary database afterward, and saves screenshots without credential values under `.local/`. Tests do not send email, publish sites or use paid research services. See [RAILWAY.md](RAILWAY.md) for production commissioning and key rotation.

References: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [OWASP cryptographic storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html), [cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/), [Railway variables](https://docs.railway.com/variables), [Railway volumes](https://docs.railway.com/volumes).
