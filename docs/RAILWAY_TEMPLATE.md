# Reusable Railway deployment template

This is the release specification for the GitHub deployment button. The template
must be saved in Railway before there is a working template URL. This file and
`railway.json` do not create Railway resources when committed to GitHub.

## Template service

Create a template from scratch so an existing project's actual secrets cannot
accidentally be distributed. Configure one service named **Stakeout**:

| Setting | Value |
| --- | --- |
| Source | `https://github.com/lemur001/stakeout/tree/codex/security-setup` |
| Dockerfile | `Dockerfile` |
| Start command | `python docker_entrypoint.py` |
| Public HTTP networking | Enabled, target port `8080` |
| Healthcheck | `/health`, timeout 120 seconds |
| Replicas | One |
| Restart policy | On failure, maximum 5 retries |
| Serverless/sleep | Disabled |
| Attached volume | `/app/data`, 1 GB initially |

The source branch contains the security changes in PR #1. Switch the template
to `main` only after those changes have merged and that branch passes CI. Do not
ship the original unpatched `main` branch. The Dockerfile supplies the production
runtime; configure these settings in the template itself instead of depending
on legacy `railway.json` processing.

Import [the template variables](../deploy/railway-template.env) into the template
editor. `secret(...)` is Railway's deployment-time generator. Each deployment
must receive three independent fresh values. The base64 expression produces
the 32-byte encryption key required by the application. Do not put a concrete
key, admin password, API key, or an existing project's environment values into
the template. Do not define `APP_URL`: Railway's generated public domain supplies
it automatically. A custom domain can be configured later.

Give the generated secrets these descriptions:

- `APP_SECRET`: Generated for this deployment. Keep it stable across redeploys;
  save a separate recovery copy in your password manager.
- `ENCRYPTION_KEY`: Generated for this deployment. Encrypts saved integration
  credentials and authenticator seeds. Keep it stable and back it up separately
  from the database. Losing it prevents decrypting those records.
- `SETUP_TOKEN`: Generated one-time workspace claim code. After deployment, copy
  it from this service's Variables into the first screen of the setup wizard.
  It stops working when the administrator account is created.

The user needs no terminal, manual secret generator, volume creation, or API/mail
credentials to launch. They need their Railway account and the setup code to
claim the workspace; then they choose a password, enroll MFA, and optionally
connect their own research and email accounts in the wizard. Passwords are
hashed with Argon2id; recoverable integration credentials use AES-256-GCM.

## Release checks

1. Confirm the template has no copied live secrets or fixed public hostname.
2. Deploy it into a fresh project and verify public HTTPS, `/health`, and
   `/api/setup/status` with `needs_setup: true`.
3. Verify private API routes reject anonymous requests and a fabricated setup
   token cannot enroll an administrator.
4. Restart and confirm the database and setup state survive on the volume.
5. Ensure its generated keys differ from the verification instance. Never print
   the values into logs or paste them into an issue.
6. Save the template's actual share URL and add the official Deploy on Railway
   badge to README. Do not add a placeholder or guessed deployment link.

The initial administrator completes the wizard personally. Real credentials
must not be placed in a public test report. Save recovery material before sealing
variables, because Railway cannot display a sealed value again. The consumed
setup token can be removed after account creation. Provider checks, restoration
of a real backup, and sender configuration remain part of commissioning.

References: [template creation and secret functions](https://docs.railway.com/templates/create),
[template best practices](https://docs.railway.com/templates/best-practices),
[Railway's configuration lifecycle](https://docs.railway.com/infrastructure-as-code).
