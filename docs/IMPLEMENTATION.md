# Implemented architecture and scope

## Approved direction
Replace Twenty CRM with an internal dashboard while retaining shared city research, organization/contact deduplication, sponsor assignments, outreach approvals, suppression and website-delivery tracking. The supplied blueprint provides the business workflow; this implementation changes the application architecture, not the requirement for supported evidence and deliberate sending.

## Final stack
- Python 3.13 / FastAPI serves the same-origin UI, authenticated API and static native ES modules.
- HTML/CSS and browser ES modules implement the dashboard. No npm dependency, frontend compile step, image-rendered UI or external CDN is needed.
- SQLite is the verified default. An optional psycopg PostgreSQL adapter uses a private schema and transaction advisory locks; this adapter still needs live acceptance testing.
- A durable Python worker advances stored Gemini provider interactions, retries read/extraction failures, monitors IMAP, and dispatches exact-approved SMTP messages.
- Database uniqueness and transactions enforce contact and organization reservations. Every meaningful mutation is audited.

## Execution rulings
The earlier planning draft named Node and React. Those are superseded by the final stack above. Package-registry access was unavailable in the build environment, while Python and Chromium were installed. Native ES modules preserve a real interactive interface without an unavailable frontend build dependency. The actual browser-rendered UI, rather than an image-generated mockup, is the delivered surface.

All implementation remained in a new local folder. No external repositories, accounts, shared databases or deployments were changed. Seed data was processed through the existing attached JSON. Claims stayed unverified. UI tests used a separate temporary database and clearly labeled synthetic sponsor/verification records; those records are not part of the package or default seed.

## Runtime boundaries
The agency workspace can hold many clients and cities, but there is no per-client login tenancy. A research agent can access permitted public sources for its own run, not private client financial/contact notes or write operations. Source text is treated as untrusted data. Authenticated reviewers, not model output, determine qualification and approval.

Sending is a two-phase operation: commit intent plus a stable message ID, then hand off to SMTP. Unknown outcomes require operator reconciliation. This prevents automatic duplicate resends but does not make SMTP exactly-once. A reply arriving after handoff cannot recall the message. Production rollout must measure provider behavior and capacity rather than assume the application has been load-certified.

## Functional design
Light workspace shell, fixed desktop navigation, table-oriented organization review, side-sheet evidence and email editors, concise sponsor forms, seven-stage project board, and an off-canvas mobile menu. The color system is white/soft gray with restrained green controls; no fabricated metrics or sample client outcomes appear on first launch. All 23 Lakeland rows are actual supplied candidates, not a painted dashboard image.

Browser inspection covered navigation, typography, table alignment and scrolling, semantic status colors, form widths, approval controls, dialog focus/visibility and responsive layout. The prior syntax, grouped-route import, dialog-navigation race and visually hidden header overflow defects were fixed and re-tested.
