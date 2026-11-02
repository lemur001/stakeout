# Security update verification — November 1, 2026

The security update was tested with Python **3.13.18** on Windows: **83 tests passed**. The expanded suite includes setup-token replay/races, MFA and recovery-code replay, encrypted persistence, key rotation, secret redaction, role/CSRF checks, fresh authentication for credential changes, HTTPS requirements, and private-network mail destination rejection. The original 57 tests remain in the suite.

The runtime dependency audit of the hash-verified lock returned **no known vulnerabilities**. Every browser ES module passed the Node syntax check. The HTTPS browser wizard was tested with synthetic credentials at desktop and mobile widths; no live provider credentials or email sends were used. Container and Railway commissioning are separate checks; see [SECURITY_AUDIT.md](SECURITY_AUDIT.md) and [RAILWAY.md](RAILWAY.md).

[Linux CI](https://github.com/lemur001/stakeout/actions/runs/41387886236) also passed all 83 tests, the locked dependency audit, static scan gate, and real HTTPS browser workflow. It built the Docker image, booted it with a persistent volume, verified PID 1 runs as UID 10001, confirmed setup and health endpoints, and successfully restarted the container.

## Railway launch verification — November 2, 2026 UTC

Deployed commit: `63808bd4fb10d8797423a29af71d58311edb2402`.
Railway deployment: `deb430b1-cd8c-4d1b-979b-0dc794d005ff` (SUCCESS).

- Docker image built, 1 GB persistent volume mounted at `/app/data`, healthcheck passed.
- Public HTTPS certificate verified by the HTTP client; browser rendered the first setup screen.
- `/health`, `/`, and `/api/setup/status` returned 200; status reported `needs_setup: true`.
- Anonymous integration settings and setup checklist requests returned 401.
- A fabricated setup token and a cross-origin setup enrollment request each returned 403.
- No-store, HSTS, nosniff and CSP framing protections were present on checked responses.
- No owner account was claimed, no real provider credentials were supplied, and live email remained disabled.

Restart persistence was tested in Linux CI. Production owner enrollment, live provider tests,
encryption-key recovery backups and a real volume restoration remain unverified. The reusable
Railway template specification is prepared, but its share URL and GitHub deployment badge
remain pending template creation in the Railway dashboard.

The historical record below describes the original build and its original verification environment.

# Original verification record — October 2, 2026

## Automated suite

Verified using Python 3.13.5 with the versions pinned in `requirements.txt` and `requirements-dev.txt`.

```sh
python -m compileall -q app scripts run.py worker.py
python -m pytest -q
```

Result: **57 tests passed**. The suite uses real SQLite transactions and application routes. External Gemini and mail behavior is tested using controlled transport doubles, not live accounts.

Covered behavior includes:

- Idempotent import of 23 organizations and 17 unique contact endpoints; no approved contacts, messages or live sending after import.
- Existing-site exclusions, missing/stale evidence, current contact-role checks and source-rights attestations.
- Distinct organization and contact records, six shared municipal liaison relationships, grouped introductions and conflicting sponsor reservations.
- Frozen approval content, expiry, edits and sponsor-term changes invalidating approval.
- Replies pausing conversations; opt-outs, permanent bounces and complaints suppressing subsequent outreach; queued message cancellation.
- Stable outbound message identifiers, uncertain SMTP outcomes and interrupted dispatch being held rather than blindly retried.
- Research run deduplication, recorded Gemini interaction IDs, worker restart recovery and ambiguous submission handling.
- Explicit read-only MCP tools, scoped tokens, private-network URL rejection, extraction schema validation and candidate provenance checks.
- Website-project authorization/ownership gates and submitted-versus-confirmed directory updates.
- Authentication, roles, CSRF, local/production host checks, body-size limits, unsubscribe confirmation and signed event deduplication.

JavaScript syntax was also checked for every ES module using:

```sh
for f in web/assets/*.js; do node --input-type=module --check < "$f" || exit 1; done
```

Node is a verification aid only; the application does not require Node to run.

## Browser interaction verification

Browser: **Chromium 144.0.7559.96**. Desktop viewport: **1440 × 1080**. Mobile viewport: **390 × 844**.

The managed browser in this environment blocks URL navigation. Its policy was not modified. Playwright loaded the application's actual HTML, stylesheet and ES modules into an `about:blank` document; browser requests were bridged to real HTTP calls against the running FastAPI service. This used the real database-backed application, not mocked workflow results. Cookie/CSRF and authenticated HTTP behavior were tested separately with the API test suite.

This harness verifies rendered controls, JavaScript behavior and backend changes, but **does not establish that a public HTTPS deployment, normal-origin browser authentication or the Docker image works end to end**. Those remain deployment acceptance checks.

The following interaction paths passed:

1. Create a client sponsor and its funded capacity/terms.
2. Configure sender identity.
3. Search and filter organizations.
4. Save evidence and public-contact reviews.
5. Reserve a sponsor conversation.
6. Generate and edit a draft.
7. Approve exact message content.
8. Confirm live sending remains unavailable in local mode.
9. Edit an approved draft and confirm approval is revoked.
10. Record a reply and confirm the sequence pauses.
11. Record an authorized agreement and create a project.
12. Record a directory submission.
13. Create a research job that correctly reports missing live setup.
14. Add an approved-source registry record.
15. Add a city.
16. Navigate all main screens at mobile width without page-level horizontal overflow.

Result: **zero page JavaScript errors** in the completed workflow. Test sponsor/review records were synthetic and stored in a separate temporary database. They are not included in this distribution. No emails were sent.

The supplied preview is an actual rendered dashboard with the untouched Lakeland seed. Visual inspection covered navigation, typography, tables and status labels, review/draft dialogs, spacing, controls, and mobile layout. It is not a screenshot-based substitute for the application.

## Defects found and corrected during verification

- Imported introduction-route relationships were initially misclassified as direct contacts; the mapping and shared-liaison regression test were corrected.
- An ES-module syntax error prevented client-page rendering; browser loading and ES-module syntax checks now pass.
- Navigation prematurely closed the newly created project dialog; agreement creation now navigates to the project board.
- Off-screen accessible table content caused mobile page overflow; its positioning is constrained to the table container.
- Manual-event ID generation depended on a secure-context-only helper; it now uses cryptographic random bytes supported by the test browser context.

## Not verified against live infrastructure

- Gemini, Brave Search, real remote MCP invocation, billing and source-plan permissions.
- SMTP acceptance/delivery or real IMAP mailbox behavior, sender authentication, bounce/complaint provider formats and mailbox reputation.
- PostgreSQL/Supabase execution, grants, pooler behavior or SQLite-to-PostgreSQL migration.
- Docker image build, Railway deployment, public TLS, persistent-volume ownership or reverse-proxy behavior.
- A clean-machine dependency installation or Windows/macOS double-click startup. The application ran with the pinned dependencies already installed in this environment.
- Production load, multiple worker replicas, large-catalog pagination or operational backup restoration drills.

The PostgreSQL path and live provider adapters are implementations awaiting account-level integration tests. Passing local tests is not a claim of production readiness at agency-wide scale.

## Backup smoke check

The SQLite backup helper was run against the temporary browser-test database. The backup opened successfully and `PRAGMA integrity_check` returned `ok`. This does not replace a production restoration drill.
