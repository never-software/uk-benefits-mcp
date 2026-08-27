# UK Benefits MCP — implementation contract

## Outcome

Publish a standalone, read-only MCP server that any MCP-compatible AI client can
install locally or self-host. It must retrieve authoritative UK benefits, tax,
legislation, and social-security case-law evidence without sending claimant data
to this project's operator and without depending on any private Control, LiteLLM,
or fleet service.

## Completion criteria

1. The package exposes a small benefits-specific tool set over MCP `stdio` and
   Streamable HTTP.
2. Network access is restricted to named official public sources. There is no
   arbitrary-URL fetch, credential input, browser impersonation, telemetry, or
   persistent claimant-data storage.
3. Every successful result identifies its authority level, source URL, retrieval
   time, source update time when available, content digest, licence, and material
   caveats.
4. Inputs and result sizes are bounded. Case-law access is limited to targeted
   searches and individual judgments, not bulk corpus analysis.
5. Unit, mocked HTTP, in-memory MCP, package-install, real `stdio`, and local
   Streamable HTTP checks pass. A small opt-in live-source suite confirms the
   official integrations.
6. The README gives client-neutral installation plus working configuration
   examples, while making clear that the server supplies evidence rather than
   legal, tax, or benefits advice.

Risk level: medium. The server is read-only, but its output may inform decisions
about benefits and tax. Exact provenance, point-in-time law, authority labels,
and visible limitations are therefore part of correctness.

## Deliberate scope

The MCP is an evidence retriever, not a benefits calculator or automated adviser.
Version one exposes:

- GOV.UK guidance search, restricted to DWP or HMRC;
- DWP Advice for Decision Making (ADM) document discovery and page-level search;
- HMRC manual section retrieval;
- legislation.gov.uk search and provision retrieval, including an optional
  point-in-time date;
- Find Case Law search and paragraph-level search within one judgment.

It does not accept claimant records, determine entitlement, calculate awards or
tax, submit declarations, contact government systems, access authenticated HMRC
services, scrape BAILII, or analyse the Find Case Law corpus in bulk.

## Official-source boundary

Outbound HTTPS is allowlisted to:

- `www.gov.uk` — GOV.UK Search and Content APIs;
- `assets.publishing.service.gov.uk` — ADM PDFs linked by the official collection;
- `www.legislation.gov.uk` — legislation search and CLML XML;
- `caselaw.nationalarchives.gov.uk` — Find Case Law Atom and judgment XML.

Redirect targets are checked against the same allowlist. ADM PDF URLs are never
accepted from the caller; they are resolved from the current GOV.UK collection.
No API key, user account, cookie, proxy, or private infrastructure is required.

## Tool contract

| Tool | Bounded behaviour |
| --- | --- |
| `search_official_guidance` | Search DWP or HMRC GOV.UK results, max 20. |
| `list_adm_documents` | Filter the current ADM attachment catalogue, max 50. |
| `search_adm_document` | Search one resolved ADM PDF, max 20 hits and 25 MiB. |
| `get_hmrc_manual` | Retrieve one validated HMRC manual or section slug. |
| `search_legislation` | Search legislation.gov.uk, max 20 results. |
| `get_legislation_provision` | Retrieve one validated document/provision, optionally as at `YYYY-MM-DD`. |
| `search_benefits_case_law` | Targeted Find Case Law search, max 20 results. |
| `search_case_text` | Search one validated judgment slug, max 20 paragraph hits. |

Tool results are typed JSON. Text excerpts are deliberately short; callers get
the canonical URL for verification and fuller reading.

## Implementation shape

- Python 3.11+ package, built with Hatchling.
- Official `mcp` Python SDK v2 and `MCPServer` API.
- One lifespan-scoped `httpx.AsyncClient`; no global mutable cache.
- Pydantic result models provide stable MCP structured output.
- `defusedxml` parses XML, Beautiful Soup converts sanctioned HTML, and `pypdf`
  extracts text from ADM PDFs.
- The command defaults to `stdio`. `--transport http` starts Streamable HTTP on
  `127.0.0.1` unless the installer deliberately chooses another bind address.
- Docker runs as a non-root user and keeps the same localhost-first posture.

## Likely failure modes

- An official page or feed changes schema: fail with a source-specific error;
  never guess fields or return sample data.
- A query resolves multiple ADM documents: return the candidates and require a
  more specific title rather than selecting silently.
- An unsupported legislation type or malformed provision path is supplied:
  reject it before any network request.
- A PDF is oversized, non-PDF, encrypted, or has no extractable text: report the
  exact limitation.
- A historical provision is unavailable: preserve the official 404 as a clear
  not-found error; do not fall back to current law.
- Find Case Law coverage is incomplete or a judgment lacks a neutral citation:
  expose the available identifier and the coverage caveat.

## Verification ledger

Evidence is recorded against the final Git tree and is invalidated only by a
relevant source or code change.

| Gate | Distinct risk covered | Planned evidence |
| --- | --- | --- |
| Parser/unit | Schema parsing, validation, snippets, provenance | `pytest` fixture tests |
| Mocked HTTP | Host allowlist, redirects, error handling, response bounds | `pytest` with HTTP mocks |
| MCP in-memory | Tool discovery, input schema, typed structured output | official SDK `Client(server)` |
| Live source | Current official schemas and one real result per source family | opt-in `pytest -m live` |
| Packaging | Wheel metadata, console command, dependency completeness | build and clean virtualenv install |
| `stdio` acceptance | Real subprocess MCP framing and tool call | official SDK stdio client |
| HTTP acceptance | Real local Streamable HTTP startup and tool call | official SDK URL client |
| Final suite | Stable complete tree | one successful full test/lint/type/build run |
