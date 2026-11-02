# Public-source pilot — November 2, 2026

The combined discovery pipeline completed a local, unpaid hunt against public IRS, Census, filing, website, RDAP and Wayback sources. This tested source integration and useful website evidence. It did not measure backlink value or compare search recall across the two original apps.

## Scope

- Des Plaines, Illinois; 15-mile radius using ZIP centroids.
- Default rebuild campaign, service/history/civic/veterans/arts types, maximum reported revenue $500,000, recent filings required.
- IRS inventory matched **1,823 records** after those filters. These are inventory candidates, not qualified prospects or backlinks.
- Enrichment was capped at **five organizations** in the inventory's distance/name order, not a random sample.
- Paid search and backlink APIs were disabled. No uploaded credentials were loaded, no messages were sent, and no production records were changed.
- Public dataset downloads were reused from the local cache. This is not a cold-start performance benchmark.

## Results after fixes

| Organization | Result | Interpretation |
| --- | --- | --- |
| American Legion, EIN 366108432 | [Website candidate](https://americanlegion36.org/) | Name and filing/website evidence supported the match. Independent review and current activity confirmation remain required. |
| Art Reach Educational Theatre | [Website candidate](https://artreachspotlite.com/) | Filed website plus the site's compact “ArtReach” branding supported the match. The earlier matcher missed this candidate. |
| American Legion, EIN 362499318 | Unresolved | Guessed domains did not resolve. This is not proof of website absence; the separate EIN remains a separate record. |
| All Equal Foundation | Retry needed | A filed domain did not resolve and other checks were unavailable. The app retained the failed checks instead of inventing a result. |
| Arirang Lions Community Services NFP | Unresolved | Guessed domains did not resolve. Additional search or manual evidence is needed. |

All five candidates retained **Unknown** backlink opportunity because no backlink provider was called. None became automatically verified or eligible for outreach. The rerun completed with four completed checks and one retryable candidate; its total elapsed worker time was approximately 44 seconds with cached datasets.

The pilot exposed and fixed two practical issues: compact branding could fail a filed-website match, and ordinary nonexistent guesses were displayed as operational failures. The matcher now requires supporting name evidence and a same-domain filing match; a manual URL or redirect to an unrelated domain cannot gain that support.

## Additional verification

The local regression suite passed **122 tests**. The real HTTPS browser flow passed account setup, MFA/recovery login, encrypted connections, discovery, evidence review, CSV export and pagination. An unauthenticated browser could not download a hunt CSV. Desktop and mobile views were checked. Static scanning found no high-severity findings and the same two reviewed medium findings documented in the CI workflow.

Paid adapters and cost reservations are tested with deterministic provider responses. A live paid-account benchmark remains outstanding. The five-record pilot is too small and deliberately limited to establish recall, precision, backlink quality, or superiority over either original app.
