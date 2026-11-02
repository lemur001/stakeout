# API and integration contracts

## Authentication
The browser calls `GET /api/session` first. Production returns an anonymous result until `POST /api/login` succeeds with an email and password. The login sets an HttpOnly Secure session cookie and returns a CSRF token. Send `X-CSRF-Token` and the same-origin cookie on every authenticated mutation. Secrets are never returned in `/api/state`.

Most API validation errors return `{ "error": "...", "details": ["..."] }`. Domain errors use a 4xx status. Network/provider calls are made by the worker rather than a long-running browser request.

## Principal routes

| Route | Purpose |
|---|---|
| GET `/health` | Process HTTP health only; not provider or database readiness |
| GET `/api/state` | Agency-wide state snapshot; not paginated for large catalogs |
| POST `/api/cities` | Add one canonical US city |
| POST `/api/clients`; PUT `/api/clients/{id}` | Funded sponsor metadata, cities and terms |
| POST `/api/entities/{id}/contacts` | Add one sourced public contact; not verified automatically |
| POST `/api/entities/{id}/review` | Store the human review contract in `app/models.py` |
| POST `/api/conversations` | Reserve entity IDs, one sponsor and a shared contact ID |
| POST `/api/conversations/{id}/draft` | Create/reuse the initial draft |
| GET/PATCH `/api/messages/{id}` | Inspect or edit; editing invalidates approval |
| POST `/api/messages/{id}/approve` | Freeze and hash the exact current context/content |
| POST `/api/messages/{id}/queue` | Queue approved email only after live transport gates |
| GET `/api/messages/{id}/preview.eml` | MIME preview; no send side effect |
| POST `/api/events` | Record an operator-verified normalized incoming event |
| POST `/api/suppressions` | Program-wide contact or entity exclusion from outreach |
| POST `/api/research` | Deduplicated city/category/window job |
| POST `/api/research/import` | Store a permitted report for extraction |
| POST `/api/research/{id}/retry` | Resume an existing interaction; unknown submissions need actual provider ID |
| POST `/api/research/{id}/import-candidates` | Validate a CandidateBatch against the report; never approves contacts |
| POST `/api/projects`; PUT `/api/projects/{id}` | Authorized agreement and delivery record |
| POST `/api/projects/{id}/directories` | Separate planned/submitted/confirmed directory outcomes |
| GET `/api/export/prospects.csv` | Spreadsheet-safe CSV cells |
| GET `/api/export/workspace.json` | Private record export; not a database restore format |

Full request types and size limits are defined in `app/models.py`. All routes require a logged-in agency account except process health, login/session, token-based unsubscribe and authenticated MCP/webhook entry points.

## CandidateBatch for a permitted stored report

Every organization name, email address, website URL and evidence URL must literally occur in the stored report. This is a provenance gate, not a factual verification. Missing fields should remain empty or unknown.

```json
{
  "candidates": [
    {
      "name": "EXAMPLE ONLY Heritage Association",
      "category": "historical_preservation",
      "website_status": "unknown",
      "website_url": "",
      "history_note": "Reported historical scope, not independently verified.",
      "activity_note": "",
      "evidence": [{"url": "https://example.org/history", "note": "EXAMPLE ONLY source paraphrase."}],
      "contacts": [{"email": "board@example.org", "source_url": "https://example.org/history", "role_note": "Reported organizational contact", "route": "direct"}]
    }
  ],
  "coverage_gaps": ["Current activity and contact role need review."]
}
```

The example does not represent a real prospect. A real input must match the actual stored report. Unknown extraction fields are rejected.

## Read-only MCP

`POST /mcp` uses `Authorization: Bearer <run-scoped-HMAC-token>`. Only the Gemini adapter creates these run tokens; keep `APP_SECRET` private. Supported JSON-RPC methods: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Tools: `get_city_source_registry`, `search_permitted_sources`, `fetch_permitted_page`. No write/approval/send tool is exposed.

The server is stateless request/response HTTP and does not implement an SSE event stream. This limited MCP implementation has unit-level and request-contract coverage; live Gemini compatibility must be tested before rollout. Token expiry is two hours; exceptionally long-running research may need operator review rather than a new duplicate job.

## Normalized inbound webhook

`POST /webhooks/email` is optional. Configure `INBOUND_WEBHOOK_SECRET` only on the server. Send the exact UTF-8 JSON body with:

- `X-Civic-Timestamp`: Unix seconds; accepted within five minutes.
- `X-Civic-Signature`: lowercase hex HMAC-SHA256 of `timestamp + "." + raw_body`, keyed by the secret.

```json
{
  "event_id": "YOUR-PROVIDER-UNIQUE-EVENT-ID",
  "message_id": "EXISTING-APPLICATION-MESSAGE-UUID",
  "event_type": "reply",
  "body": "Actual normalized reply text."
}
```

Supply an existing application `message_id`, or an `email` matching a stored contact. When both are supplied they must match. Allowed events: `reply`, `optout`, `bounce`, `complaint`, `delivered`. `bounce` is for a permanent failure, not a transient soft bounce. Duplicate event IDs are ignored. Provider-specific webhook verification and mapping must happen in an adapter; arbitrary vendor payloads do not match this schema. IMAP still must be healthy before dispatch.

GET unsubscribe requests do not change records. POST `/unsubscribe/{opaque-token}` records the opt-out and is idempotent. There is no public recipient-directory lookup API.
