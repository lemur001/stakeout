# Stakeout Civic — standalone application

A working, single-agency, multi-client workspace for city research, civic website sponsorship proposals and website-delivery tracking. **No Twenty, external CRM, Node build step, or cloud account is required for the local dashboard.**

## Secure Railway setup

For a new hosted workspace, follow [the Railway deployment guide](docs/RAILWAY.md). A [reusable template specification](docs/RAILWAY_TEMPLATE.md) and [automatically generated template variables](deploy/railway-template.env) are prepared; saving the template in Railway and adding its actual deployment button are still pending. The wizard creates an administrator with an Argon2id password hash, authenticator-based MFA and recovery codes, then guides you through your agency identity and optional research/mail connections.

Integration credentials and authenticator seeds are encrypted with AES-256-GCM before storage. The encryption key stays in a Railway variable, separately from the database; seal it after saving a separate recovery copy. Saved passwords and API keys are never returned by the settings API or included in workspace exports. The server must decrypt credentials in memory to use them; encryption does not protect against compromise of the running server or the Railway account.

See [the security audit](docs/SECURITY_AUDIT.md) for findings, fixes, verification and remaining deployment checks. The Docker image installs [the hash-verified runtime lock](requirements.lock); CI tests the image and wizard. The audited branch has also launched successfully on Railway with public HTTPS and a persistent volume; initial administrator enrollment and provider setup remain for the owner.

This is an operating first release, not an unattended production service. Gemini and mail adapters are implemented, but were not exercised against live accounts during this build. A funded Gemini API account, licensed source access and an approved sending mailbox still need to be connected. No emails have been sent.

## Start on your computer

Use Python **3.13** for parity with the Railway image. An internet connection is needed for the first dependency installation.

**Windows:** extract the ZIP, open its `stakeout-civic` folder and double-click `START_WINDOWS.cmd`. Keep the command window open.

**macOS or Linux:** open a terminal in that folder and run:

```sh
sh start.sh
```

Open **http://127.0.0.1:8080** in your browser. Local mode needs no login and rejects non-loopback requests. It cannot send live email.

Manual installation, instead of the startup scripts:

```sh
python -m venv .venv
# Windows:
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
# macOS/Linux:
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

If port 8080 is occupied, copy `.env.example` to `.env` and set both `PORT=8787` and `APP_URL=http://127.0.0.1:8787`. The application reads `.env` at startup. Restart after boot configuration changes. OS environment variables take precedence over `.env`; encrypted integration values saved through the wizard take precedence over both for the fields it manages.

The default database is `data/civic.sqlite3`. It is created automatically. Do not delete it to fix an integration error. Closing the server does not delete saved work.

## What is ready to use

| Area | Implemented workflow |
|---|---|
| Overview | Real record counts, review queue, setup checklist, city coverage, audit history |
| Organizations | Search, city/status filters, evidence dossier, public contact entry, reviewer attestations, existing-site exclusion and suppression |
| Cities | Shared canonical city catalog; research is not duplicated for each client |
| Client sponsors | Service cities, approved budget metadata, funded capacity, scope and renewal terms |
| Research | Durable Gemini Interactions jobs, restart-resumable provider IDs, permitted read-only MCP tools, source quotas, structured extraction and report/JSON import |
| Outreach | Single organization/contact reservation, grouped liaison introductions, editable drafts, exact-content approval, EML preview, controlled SMTP dispatch and IMAP reply ingestion |
| Website projects | Authorized agreements, scope, content/build/review stages, ownership gates, launch records, renewal date, handover notes and brief export |
| Directory records | Planned/submitted/confirmed outcomes with separate confirmed URLs |
| Settings | Sender identity, global pause, configuration diagnostics, suppression records and exports |

The Lakeland seed starts with **23 organizations, 17 distinct email endpoints and no approved contacts or messages**. Six organizations share one municipal introduction route. Citrus Center Kiwanis is excluded based on the supplied seed’s earlier existing-website finding; the application has not reverified that finding. Imported text is not a verified factual claim. No residential addresses or telephone numbers are imported.

## First operating workflow

1. **Review an organization.** In Organizations, open its dossier. Record website checks, historical/civic relevance, current activity, source URLs and the public contact’s role. Check permission and contact-verification boxes only after actually checking the evidence. Only `social_only` or `no_site_found_after_checks` can qualify for this campaign.
2. **Add a real sponsor.** In Client sponsors, assign the city, funded slots, approved scope and renewal/handover terms. Budget is an internal record—not a payment or a live cost calculation.
3. **Set the sender identity.** Settings requires the actual sender, email and postal address. These appear in the proposal. The email must match `SMTP_FROM` before live sending.
4. **Reserve the conversation.** Open an eligible organization and choose Assign sponsor. For a shared liaison, select the relevant eligible organizations in the table and reserve one grouped introduction.
5. **Draft and approve.** In Outreach, create the draft. Edit it, inspect the mandatory footer and approve its exact contents. An approval is not a send. Download the `.eml` preview for inspection without sending it.
6. **Record replies and agreements.** Replies pause the sequence. An authorized agreement opens a website project. Track content permissions, domain ownership, launch and maintenance separately.

## Research setup

Manual report storage and candidate JSON validation work locally. Extraction of a stored report needs `GEMINI_API_KEY`. Fully automated Deep Research also needs your public authenticated HTTPS application, because Gemini must reach its `/mcp` endpoint.

For hosted operation, use **Settings → Setup & connections** to save credentials encrypted. Server-side environment variables remain available for local use and legacy operation; the wizard's saved values override them:

```dotenv
GEMINI_API_KEY=
GEMINI_RESEARCH_AGENT=deep-research-preview-04-2026
GEMINI_EXTRACTION_MODEL=gemini-3.8-flash
SOURCE_RIGHTS_APPROVED=false
BRAVE_SEARCH_API_KEY=
BRAVE_STORAGE_RIGHTS_APPROVED=false
DAILY_RESEARCH_LIMIT=5
MAX_RESEARCH_CONCURRENT=1
```

Leave keys empty until supplying your real credentials. Set the rights flags to true **only after confirming the applicable source and search-plan permissions**. These are attestations, not licenses created by the application. Search-result storage rights and publisher-content rights are separate.

Register permitted source URLs in Research → Approved source registry. A source record does not authorize scraping an entire domain unless its documented permission actually covers that use. Page retrieval is HTTPS-only, exact-host allowlisted, robots-checked and limited to public IPs, text content, size caps and redirect caps. PDFs, screenshots and JavaScript-rendered pages are not parsed by this first release.

The Gemini agent has exactly three tools: city source registry, licensed search and permitted page fetch. It has no send, approval or publishing tool. Default Google Search grounding is not used for CRM ingestion. Model-generated candidates are always unverified, even if the report sounds confident.

Gemini preview IDs and account access can change. They are configurable. Before a live launch, test one city and verify the actual provider interaction, MCP calls, final report and extracted records. Review your provider’s billing: source-call and job caps do not implement a guaranteed dollar-spend cap.

## Live email setup

This application does not provide sending accounts, reputation, consent or legal approval. Use a provider whose terms permit the intended outreach. Confirm relevant legal requirements for your recipients. The first release supports US cities and does not implement international outreach rules.

Live sending requires all of the following:

- `APP_MODE=production`, public HTTPS, named operator authentication;
- `ALLOW_LIVE_SEND=true`, `OUTREACH_PROVIDER_APPROVED=true`, `SENDER_AUTH_CONFIRMED=true`;
- complete `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`;
- working `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_MAILBOX`;
- the workspace pause turned off, a queued exact-content approval and a successful recent IMAP poll.

SMTP uses STARTTLS by default on port 587. For implicit TLS, use `SMTP_SSL=true` and your provider’s implicit-TLS port. IMAP uses TLS on port 993 by default. This version uses provider-supported username/password or app-password authentication, not OAuth authorization-code flows.

A successful SMTP handoff means **accepted by the mail server**, not delivered to the inbox. Transport timeouts or interrupted sends become `delivery_unknown` and are never automatically resent. Reconcile them with the provider log before changing their state. A stable Message-ID assists investigation; SMTP does not guarantee exactly-once delivery.

Defaults: five attempts per UTC day, recipient-city weekdays from 09:00 to 17:00, one initial message and one newly reviewed follow-up after seven business days. The limit counts uncertain attempts too. Follow-ups are drafted, not auto-approved. Reviews expire after seven days; approval expires after 48 hours. Worker checks take place immediately before dispatch, but an opt-out arriving after SMTP handoff cannot recall a message already transmitted.

Replies pause the conversation. Opt-outs, complaints and permanent bounces suppress the contact and linked organizations. No subsequent sponsor can bypass the conversation lock. A GET unsubscribe link shows a confirmation; POST performs the opt-out, including RFC8058 one-click requests. Quote-stripping prevents your own “no thanks” footer from being interpreted as a recipient opt-out.

For multiple mailbox folders, or providers using nonstandard bounce/complaint formats, add and test a provider-specific adapter. The included signed webhook endpoint accepts the documented normalized event format, not arbitrary provider payloads. It does not remove the IMAP freshness requirement.

## Deploy as one service

The included Dockerfile serves both dashboard and API; the worker runs in the same process for the pilot. Follow [docs/RAILWAY.md](docs/RAILWAY.md) for deployment and acceptance checks. Linux CI verified the image's unprivileged server UID and persistence across a restart. A real Railway launch passed health, HTTPS, setup-page, anonymous-access and invalid-token checks. Provider connections and backup restoration still need commissioning.

Before exposing the application, configure:

```dotenv
APP_MODE=production
HOST=0.0.0.0
APP_URL=https://YOUR-ACTUAL-APPLICATION-HOST
APP_SECRET=
ENCRYPTION_KEY=
SETUP_TOKEN=
RUN_WORKER=true
ALLOW_LIVE_SEND=false
```

Run `python scripts/generate_deploy_env.py` to generate independent boot secrets into a private, Git-ignored transfer file. Copy them into Railway variables and your password manager, then remove the transfer file. Create your password and MFA in the browser wizard. Remove `SETUP_TOKEN` after the workspace is claimed. Keep `APP_SECRET` and `ENCRYPTION_KEY` stable and backed up. Legacy `ADMIN_EMAIL`/`ADMIN_PASSWORD` provisioning remains available only for an empty workspace; existing accounts are never reset by changing environment variables.

Use **one web/worker instance** for the pilot. Attach a persistent volume at `/app/data` for SQLite. Railway startup refuses an ephemeral SQLite path. The container entrypoint initializes the volume permissions, then drops permanently to UID/GID 10001 before starting the application. Keep the configured `python docker_entrypoint.py` start command.

For PostgreSQL or Supabase, install `requirements-postgres.txt` and set a server-only `DATABASE_URL` with `sslmode=verify-full` and a trusted server certificate. The adapter creates tables in a private `civic` schema and does not expose it through Supabase’s Data API. Use a dedicated database role, not credentials shipped to the browser. For a persistent worker, use a direct connection or an appropriate session-pooler connection. Keep `civic` out of exposed schemas and review role grants before launch.

**The PostgreSQL adapter was not exercised against a live database in this build.** Test migrations, permissions, TLS, restart recovery, concurrency and backup restoration in staging before choosing it for client work. Changing `DATABASE_URL` does not automatically migrate existing SQLite records. A migration tool is not included.

For a later separate-worker topology, run the web process with `RUN_WORKER=false` and run `python worker.py` against the same database and configuration. Do not scale replicas merely by increasing a count: test leases, mailbox cursors and provider behavior first. The shared-state snapshot endpoint and serialized write transactions have not been load-tested for very large catalogs.

## Operator accounts

Production uses opaque HttpOnly Secure SameSite cookies, CSRF tokens and named roles. There is no public signup or email-confirmation loop.

```sh
python scripts/user.py reviewer@example.org --name "Agency Reviewer" --role reviewer
python scripts/user.py viewer@example.org --name "Reporting User" --role viewer
```

The command prompts for a password, avoiding shell-history exposure. Reusing an email updates its password/role and revokes its sessions. Admins manage research, clients, dispatch, events and projects; reviewers can review contacts and evidence and edit/approve drafts; viewers cannot mutate records. All accounts operate inside **one agency workspace**, not isolated customer accounts.

## Backups, recovery and verification

```sh
python scripts/check_setup.py
python scripts/backup.py backups/civic-YYYY-MM-DD.sqlite3
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The SQLite backup script uses the backup API to include live WAL contents. Keep backups and workspace JSON exports private. Stop the server before restoring a SQLite backup, and clear old sidecar WAL/SHM files only as part of an intentional tested restore. For PostgreSQL use managed backups or `pg_dump` and verify restores.

`docs/TEST_RESULTS.md` records the actual test scope and limitations. Source references are in `docs/SOURCES.md`; API integration contracts are in `docs/API.md`.

## Deliberate boundaries of this version

This is a complete local workspace and integration implementation, not a claim that all external systems have been commissioned. It does not automatically register domains, build or publish the sponsored websites, collect payments, establish email deliverability, verify board authority, guarantee backlinks, or guarantee rankings. Website production is tracked through projects and exported briefs. Sponsorship acknowledgements should be visible and qualified with `rel="sponsored"` or `rel="nofollow"`; organizations retain their domain and content.

There is no mailbox OAuth setup UI, SSO/passkey authentication, per-client login isolation, automatic SQLite-to-Postgres migration, provider spend reconciliation or complete large-catalog pagination. TOTP MFA and recovery codes are included. Schema version 2 adds the credential and authentication-security tables without deleting existing records. Production configuration still requires staged live provider/database acceptance tests before client rollout.
