# Source and integration references

Implementation research was checked against primary sources on 2026-10-02. Live provider requests were not made.

- Gemini Deep Research: https://ai.google.dev/gemini-api/docs/deep-research
  The implementation uses the documented Interactions background job and explicit MCP tool shape. The current configured preview is `deep-research-preview-04-2026`; account availability must be checked.
- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
  A separate extraction request uses a validated JSON schema; configured model `gemini-3.8-flash` is editable.
- Gemini API terms: https://ai.google.dev/gemini-api/terms
  The application avoids default Google Search-grounded database ingestion. Obtain applicable permissions for all chosen sources and providers.
- Brave search interface: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
- Brave storage/use FAQ: https://brave.com/search/api/
- MCP server development: https://modelcontextprotocol.io/docs/develop/build-server
  The app implements a limited stateless JSON-RPC subset over HTTP. A live Gemini compatibility check is still required.
- Supabase PostgreSQL connections: https://supabase.com/docs/guides/database/connecting-to-postgres
- Psycopg package: https://pypi.org/project/psycopg/
- Google link spam policies: https://developers.google.com/search/docs/essentials/spam-policies
- FTC commercial email guidance: https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- Gmail sender guidance: https://support.google.com/a/answer/81126

## User-supplied source handling
`seed/lakeland.json` is copied from the supplied `Lakeland_Civic_Prospects_Unverified.json`. Its provenance points to `Lakeland Entities Without Websites.md`. Entity and email spelling is retained; no contact spelling is inferred or corrected. All contacts remain unverified. One existing-site exclusion is retained as a prior seed observation, not independently rechecked by this app.

The original report includes strong ranking, inherited-authority, activity and leadership claims that this implementation does not silently convert into established facts. Source notes and a separate human evidence review remain attached to the organization. A historical document or a municipal award is not automatically a current-role verification.
