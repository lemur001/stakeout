# Deploy a new Stakeout workspace on Railway

The audited branch launched successfully on Railway on November 2, 2026 UTC: the image built, its persistent volume mounted, healthchecks passed, and the public HTTPS page displayed the setup wizard. Anonymous settings requests, invalid setup tokens and cross-origin setup requests were rejected. [CI passed](https://github.com/lemur001/stakeout/actions/runs/41387886236) on deployed commit `63808bd4fb10d8797423a29af71d58311edb2402`. The owner still needs to claim the workspace and connect providers.

The [one-click template specification](RAILWAY_TEMPLATE.md) includes storage, HTTPS and deployment-time secret generation. Saving that template in Railway is still pending dashboard access; there is no working deployment badge yet. Once saved, template users will skip the manual infrastructure and secret-generation steps below. An ordinary GitHub-repository deployment does not provision those resources from this repository alone.

The remaining sections document manual installation and operations. Railway is retiring legacy `railway.json` processing; configure healthchecks, storage and runtime settings on the service or template itself.

## 1. Create the service and durable storage

1. Make the reviewed security changes available on the GitHub branch you will deploy. Create a new Railway project, select **Deploy from GitHub repo**, and select `lemur001/stakeout` and that branch.
2. Use the repository's `Dockerfile` and set `python docker_entrypoint.py` as the service start command. Set healthcheck path `/health`, timeout 120 seconds, an on-failure restart policy with five retries, and disable sleep/serverless. Use **one replica** and the in-process worker. Avoid a separate worker for this first deployment.
3. Attach a volume to this service at **`/app/data`**. Set `DATABASE_PATH=/app/data/civic.sqlite3`. The application refuses to start with ephemeral SQLite storage on Railway.
4. Under Networking, generate a public domain. Railway provides TLS. `RAILWAY_PUBLIC_DOMAIN` supplies the default application origin; set `APP_URL=https://your-domain` explicitly for a custom domain. Use only the origin, without a path, query, or trailing slash.

An initial deployment can fail until the volume, domain and boot variables are in place. Configure them together, then deploy again. The healthcheck is `/health` and the server honors Railway's `PORT`.

Railway volumes are mounted at runtime as root. The image starts a small initialization script that changes ownership only for `/app/data` and the configured SQLite files, sets restrictive permissions, clears supplementary groups, drops to UID/GID 10001, and then starts the server. The application code remains root-owned and read-only to the server user. Do not replace the start command with `python run.py`.

## 2. Generate and protect the boot secrets

On your computer, from the repository folder:

```sh
python scripts/generate_deploy_env.py
```

The script creates `.env.railway` without printing secrets and refuses to overwrite it. This is a **temporary plaintext transfer file**, excluded from both Git and Docker. On Windows it inherits the permissions of your user folder; keep it private. Transfer its values to Railway and your password manager, then delete the file. Do not paste it into chat, commit it, or attach it to support tickets.

| Variable | Purpose |
| --- | --- |
| `APP_MODE=production` | Enforces named authentication and production validation |
| `HOST=0.0.0.0` | Receives Railway proxy traffic inside the container |
| `DATABASE_PATH=/app/data/civic.sqlite3` | Persistent SQLite database |
| `RUN_WORKER=true` | Runs one worker in the application process |
| `ALLOW_LIVE_SEND=false` | Keeps live email disabled during setup |
| `ENCRYPTION_KEY` | Independent random 32-byte key, base64 encoded; encrypts integration credentials and MFA seeds |
| `APP_SECRET` | Independent random application signing secret |
| `SETUP_TOKEN` | Independent random one-time workspace claim token |

Seal `ENCRYPTION_KEY`, `APP_SECRET`, and `SETUP_TOKEN` in Railway after recording them in your password manager. Railway's sealed variables cannot be recovered from its dashboard, CLI, or API. They still reach the running service so it can use them. Protect your Railway and GitHub accounts with MFA and restrict project access.

Do not set `ADMIN_EMAIL` or `ADMIN_PASSWORD` for a new wizard-based deployment. Do not put API keys or mail passwords into the image. You will enter those in the wizard.

## 3. Complete the browser wizard

Open the generated **HTTPS** address:

1. Enter your one-time setup token, name, email, and a unique password of at least 16 characters.
2. Add the displayed setup key to an authenticator app as a time-based account. Enter the current six-digit code. Save the single-use recovery codes in a password manager. Setup-token reuse is disabled transactionally as soon as the account is created.
3. Save the agency and sender identity. Email and postal address may be completed later; outreach requires them.
4. Optionally connect Gemini and Brave Search. The wizard links to their key-management pages. Confirm your own source/storage permissions and provider billing. Model identifiers remain configurable because access and preview versions change.
5. Optionally configure an approved SMTP/IMAP mailbox, preferably a dedicated mailbox using app passwords. SMTP requires STARTTLS or implicit TLS; IMAP requires TLS. Private network mail hosts are rejected.
6. Review the checklist and open the workspace. **Outreach stays paused.** Worker tasks remain inactive until the setup is completed.

Remove `SETUP_TOKEN` from Railway after claiming the workspace. Keep `APP_SECRET` and `ENCRYPTION_KEY` stable across deploys. Restarting with a missing or wrong encryption key fails closed; the application never silently discards encrypted records.

Later, use **Settings → Setup & connections** to edit integrations. A password/MFA confirmation is required if your most recent authentication is older than 15 minutes. Empty password boxes preserve the current saved secret; a separate checkbox removes it. Changes pause outreach. The primary pilot configuration is one application process; multiple web replicas with independently cached configuration are not supported by this setup.

Saving credentials confirms storage, not provider acceptance. Verify one small research run and successful IMAP monitoring before enabling operational use. Optional integrations can be skipped without blocking the local CRM workflows.

## 4. Verify the deployment before live use

- Confirm `/health` returns 200 and the public address uses valid HTTPS.
- Confirm private API routes reject a signed-out browser; the setup token cannot be reused after account creation.
- Confirm password-only login fails for your new MFA-protected account; test a saved recovery code and replace your record of the consumed code.
- Save an integration, redeploy, and verify that it remains configured without exposing the value in Settings or exports.
- Confirm the database, organization records and MFA login survive a restart.
- Configure Railway volume backups and test restoring one into an isolated staging service using the matching encryption key. Keep staging live sending disabled and give it separate provider credentials.
- Keep automatic deploys limited to a reviewed branch with passing CI. Enable repository secret scanning where available.

Only after provider approval, sender authentication, real reply monitoring, and a reviewed initial message should you set `ALLOW_LIVE_SEND=true`. You must then deliberately remove the workspace pause and queue an approved message. The wizard never does this for you.

## Key rotation and recovery

To rotate the encryption key, keep a verified database backup and its matching old key. Generate a new random 32-byte key, set it as `ENCRYPTION_KEY`, and move the previous key into the sealed `ENCRYPTION_KEY_PREVIOUS` variable. Deploy, then run inside the service:

```sh
python scripts/rotate_encryption_key.py
```

The command re-encrypts credential and MFA records in one transaction. Verify a restart, login and configured integrations, then remove `ENCRYPTION_KEY_PREVIOUS`. Retain old keys in your password manager for old backups. Never regenerate the key automatically on startup. Rotating encryption does not rotate the underlying provider API keys or mailbox passwords; revoke and replace those through the provider if exposed.

If you lose your authenticator, sign in using a saved recovery code, then use **Settings → Authenticator & recovery codes** to enroll its replacement and obtain new recovery codes. Keep several unused recovery codes for this flow: sign-in and each fresh security confirmation consume one. Codes are single-use. A server operator can reset an account through an intentional database/CLI recovery procedure if all factors are lost; the public application has no password-reset email flow. Password changes in Settings revoke existing sessions. Existing and secondary accounts should enroll their own MFA in Settings before use; they do not automatically inherit the owner's MFA.

Losing **all copies** of `ENCRYPTION_KEY` makes saved provider credentials and MFA seeds unrecoverable. Restore the correct key; do not delete the database to work around a decryption failure. Workspace JSON exports exclude account and credential records and are not full backups.

## Optional PostgreSQL

The image includes the PostgreSQL driver, but the default deployment above uses SQLite. A production `DATABASE_URL` must use `sslmode=verify-full` and a trusted certificate chain. Plaintext private-network database connections are deliberately rejected. A provider without verifiable PostgreSQL TLS needs a different database setup. Keep the URL in a sealed Railway variable; it cannot live in the application vault because the application needs it to open that vault.

The `civic` schema stays private, and writes use an advisory transaction lock. No SQLite-to-PostgreSQL migration tool is supplied. Run database-specific migration, backup, restore and concurrency tests before switching a populated workspace.

## References

- [Railway variables and sealing](https://docs.railway.com/variables)
- [Railway volume lifecycle and permissions](https://docs.railway.com/volumes)
- [Railway healthchecks and the PORT variable](https://docs.railway.com/deployments/healthchecks)
- [Railway-provided domain variables](https://docs.railway.com/variables/reference)
