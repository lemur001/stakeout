# Unified prospect discovery

This combines the uploaded Backlink Hunter's nonprofit classification and bulk-discovery approach with Stakeout's persistent catalog, secure connections, human review and delivery workflow. Only selected source definitions were adapted; uploaded credentials, caches, contacts and hunt results were not imported.

## Run a hunt

1. Finish the secure setup wizard. In **Settings → Setup & connections**, confirm source permissions. Public inventory and website checks need no provider credentials.
2. Open **Prospect discovery → New hunt** and type any US city, then choose its state. There is no separate city setup step. Starting the hunt automatically saves or reuses the location. AI research and report imports work the same way.
3. Choose **Build a first website** or **Improve an existing website**. Set a radius, revenue ceiling, organization types and candidate limit. A center ZIP overrides the Census city location for unincorporated or ambiguous places.
4. Choose IRS inventory, existing city records, or manually sourced organizations. To find groups outside IRS coverage, use **Investigate a city with AI** and include its imported candidates in a later hunt. AI research retains its separate provider configuration and job limits.
5. Start with unpaid checks. Optionally enter fresh DataForSEO API credentials in Connections, select search/backlink checks and approve an estimate envelope. Old uploaded secrets are never used.
6. Rank results by project fit, link opportunity or evidence confidence. Filter and page through every candidate, or download **Export hunt CSV**. Open an organization to inspect findings and sources. **Review** is the only route to verified website, contact and outreach eligibility.

Existing organizations retain their campaign until a reviewer changes it. A campaign change invalidates pending message approvals. Rebuild campaigns accept reviewed existing websites; first-website campaigns keep their original eligibility rules. No discovery action approves or sends outreach. SendGrid remains deferred.

## Discovery and evidence

| Stage | Current implementation |
| --- | --- |
| Geography | Cached Census 2025 place and ZIP centroid files; optional explicit center ZIP. No geocoding API account. |
| Inventory | IRS state BMF files; type, tax-status and reported-revenue filters; streaming latest 990-N website/filing enrichment. EIN identity prevents duplicate organizations and separates same-name chapters. |
| Filing enrichment | ProPublica organization API and the GivingTuesday public IRS XML mirror, when a filing ID exists. Retains website, mission and filing year. |
| Website discovery | Filed/manual/existing website, up to six domain guesses, then up to two optional DataForSEO searches for unresolved organizations. |
| Inspection | Public HTTPS pages, robots rules, bounded redirects, pinned public DNS, HTML text inspection, name plus locality/EIN or same-domain IRS website evidence, platform/member portal/store/designer/parked/spam signals. Compact branding such as ArtReach can match Art Reach. Up to two relevant internal pages and one sitemap are inspected. Visible ISO and English/US dates retain context; future events remain separate from recent past activity. |
| Domain context | RDAP registration events, Wayback year coverage, optional Open PageRank. These are context, not proof of backlink value. |
| Backlinks | Optional DataForSEO referring-domain summary and up to 20 backlinks. Up to three source pages are fetched to check the destination, anchor, follow/nofollow/sponsored/ugc attributes, robots meta tags, and organization/locality context. Provider-reported attributes remain separate from observed HTML. |
| Persistence | Candidate-level progress, run leases, pause/resume, timestamped observations, source URLs, refresh deadlines and a paid-call ledger. |

Successful observations can be reused for 21 days. Unavailable observations remain visible but are not reused as successful results. Refreshing a completed hunt reruns checks that lack fresh evidence; already completed paid calls are reused within that hunt. Start a new approved hunt for new paid data after successful evidence expires. Uncertain paid calls require provider billing review and are never retried automatically in the same hunt.

## Understand the scores

These are versioned screening heuristics, not calibrated probabilities or ranking guarantees.

- **Project fit:** identity, dated-site signals, recent visible activity, filing recency, reported size and a published contact. The campaign adjusts fit. Member portals, stores, existing designers, parked sites and suspected spam flag added complexity. An existing owned-site candidate scores zero for a first-website campaign.
- **Link opportunity (v2):** only available when the provider returns a referring-domain count. Count contributes up to 45 points (`round(log10(1 + count) × 17)`); observed distinct linking domains add up to 25; observed follow links without a noindex meta tag add up to 15; sources mentioning both name and locality add up to 15. Provider spam score subtracts up to 40. The total is clamped to 0–100 and every component is shown in the profile. A three-page sample is limited evidence; HTML attributes do not establish indexing, relevance of the whole site or ranking benefit.
- **Evidence confidence:** 40 points for a name supported by locality, EIN or the same website domain recorded in an IRS filing; 10 for an EIN; 10 for a recent filing; 15 for a recent visible activity date; 10 for a backlink summary; and 10 for an observed inbound link. Without a website identity match, it is capped at 40. Automated confidence never constitutes approval.

Unknown authority stays **Unknown**; a confirmed provider count of zero is distinct. A nonexistent guessed domain is recorded as **not_found**, leaving website identity unresolved. A timeout or unavailable source remains an operational failure that can be retried. A date, copyright year, domain age or filing does not prove that an organization is active. A page mentioning the name and city is a website candidate, not independently verified ownership. CSV exports preserve zero separately from unknown and neutralize spreadsheet formulas in source-derived values.

## Spending and credentials

DataForSEO calls reserve planning estimates before submission: 5 cents per search, 10 cents per summary, 10 cents per backlink sample. These are conservative application estimates, not quoted provider prices. Returned charges are rounded upward to whole cents per call. Reservations plus recorded charges stop further calls when the approved estimate envelope is exhausted. A provider may charge more than an estimate; use provider-side account limits for a billing ceiling.

If a call times out or its response cannot be interpreted, its reservation remains held. Do not start another paid hunt until you have reconciled that outcome in the provider console. There is no in-app billing reconciliation editor in this release. AI city research remains a separate paid workflow and is not charged against the discovery estimate envelope.

DataForSEO login/password and Open PageRank keys use the existing AES-256-GCM vault. The API returns only whether a secret is configured. Missing or failed credentials never become a zero-authority score. Root encryption keys remain outside the database. Review raw source observations before exporting them; they are research data, not vault secrets.

## Deployment and limits

The existing Railway Docker service starts both workers with `RUN_WORKER=true`. Keep one web/worker replica and the persistent `/app/data` volume. Migrations are additive and preserve existing records, defaulting their campaign to `first_website`. Dataset cache files live beside the SQLite database and are capped at approximately 220 MB by evicting older disposable files. They need not be backed up; the database and root encryption key do.

`python worker.py` also runs both workers for an explicitly configured separate-worker topology. PostgreSQL uses the existing transaction lock, but this release has not been load-tested with multiple replicas. A crashed discovery lease can delay resumption for up to 30 minutes. Pausing lets an in-flight check finish; it prevents new paid calls. The daily run ceiling is shared with AI research.

IRS coverage excludes many informal neighborhood groups and organizations outside its filing coverage. Locations are filing addresses and ZIP centroids, not precise service areas. The geographic state lookup supports the 50 states and DC. Filtering by recent filings can omit active groups; a missing or malformed upstream dataset fails visibly rather than fabricating an empty result. Websites requiring JavaScript, PDFs, HTTP-only access, robots exceptions or manual ownership confirmation need human review. Sitemap counts are listed URLs, not verified live page counts.

Public APIs can rate-limit or change. Paid adapters are covered by mocked-provider tests, but have not been exercised with live paid accounts. No paid benchmark establishes that this combined implementation finds more valuable backlinks than either original tool yet.

## Verification and source references

Regression tests cover migration, campaigns, source ingestion, EIN identity, filing-domain identity, visible dates, link attributes, suppression, expired evidence, restart leases, public-network restrictions, unknown-versus-zero authority, encrypted credentials, CSV safety, CSRF and spending reservations. The browser test exercises the HTTPS wizard, creating a hunt, deterministic worker results, evidence inspection, review, protected CSV downloads, pagination and mobile layout without paid calls. An unpaid five-organization public-source pilot found two supported website candidates; see [pilot results](PILOT_VALIDATION.md) for its scope and limits.

Upstream references: [Census Gazetteer files](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2025.html), [IRS BMF scope and fields](https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf), [DataForSEO backlink summary](https://docs.dataforseo.com/v3/backlinks-summary-live/), [DataForSEO backlink records](https://docs.dataforseo.com/v3/backlinks-backlinks-live/).
