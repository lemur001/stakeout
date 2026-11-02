# Stakeout Civic setup

For a new Railway deployment, follow `docs/RAILWAY.md` in the source repository. Use one replica, a persistent volume mounted at `/app/data`, the supplied Docker entrypoint, and an HTTPS public domain.

The server needs three independent boot secrets: `ENCRYPTION_KEY`, `APP_SECRET`, and the one-time `SETUP_TOKEN`. Generate them with `python scripts/generate_deploy_env.py`, transfer them privately to sealed Railway variables and your password manager, and delete the temporary transfer file. Never enter boot encryption keys into ordinary profile fields or commit them to Git.

On first visit, the guided setup asks for your setup token and creates your administrator account. Choose a unique password of at least 16 characters, enroll a time-based authenticator, and save your recovery codes securely. The first account claim permanently closes public setup; you can remove `SETUP_TOKEN` afterward. Keep the encryption key and application secret stable across deploys.

The wizard walks through:

1. Administrator password, authenticator, and recovery codes.
2. Agency identity and sender details.
3. Optional Gemini/Brave research credentials and source permissions.
4. Optional SMTP/IMAP credentials for a dedicated approved sending mailbox.
5. Configuration checks and a paused workspace.

Use **Settings → Setup & connections** to return to the connection forms. After 15 minutes, confirm your password and authenticator again before changing credentials. Secret fields are write-only: leave a box empty to retain its saved value, or use the explicit removal checkbox. Integration credentials and authenticator seeds are encrypted in the database; the key stays in Railway. Account passwords are stored as Argon2id hashes.

Configuration checks do not prove that a provider accepted the credentials. Test your real research and reply-monitoring integrations before using them operationally. Saving connection settings pauses outreach; the wizard never enables live sending. Live email additionally requires `ALLOW_LIVE_SEND=true` on the server and all existing approval, provider, sender and reply-monitoring gates.

Use **Settings → Authenticator & recovery codes** to enroll or replace your authenticator. You will need the current password and a fresh authenticator or unused recovery code at each security confirmation. Replacement issues new recovery codes and revokes the old ones and other sessions. Password changes also revoke existing sessions.

Back up the persistent database and keep a separate secure copy of the matching encryption key. Workspace JSON exports omit credentials and user accounts and are not complete backups. See `docs/RAILWAY.md` for key rotation and restore procedures. Losing every copy of the encryption key makes saved credentials and authenticator seeds unrecoverable.
