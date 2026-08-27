# UK Benefits MCP

<!-- mcp-name: io.github.never-software/uk-benefits-mcp -->

A read-only [Model Context Protocol](https://modelcontextprotocol.io/) server for
official UK benefits evidence. It gives MCP-capable AI clients bounded access to:

- DWP and HMRC guidance on GOV.UK;
- DWP's Advice for Decision Making (ADM) PDFs;
- HMRC internal manuals;
- legislation.gov.uk, including point-in-time provisions; and
- targeted judgments from The National Archives' Find Case Law service.

It is a standalone public package. It does not connect to a private proxy, hosted
account, or the maintainer's infrastructure.

> [!IMPORTANT]
> This server retrieves evidence; it does not give legal, tax, or benefits advice.
> Do not put names, National Insurance numbers, addresses, health details, account
> credentials, or other claimant-identifying information in tool queries.

## Install in an MCP client

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and an AI
client that supports local MCP servers. The client runs the package on your own
machine using `stdio`.

Generic MCP configuration (used by Claude Desktop, Cursor, and many other clients):

```json
{
  "mcpServers": {
    "uk-benefits": {
      "command": "uvx",
      "args": ["uk-benefits-mcp"]
    }
  }
}
```

For Codex CLI:

```bash
codex mcp add uk-benefits -- uvx uk-benefits-mcp
```

An AI subscription by itself is not enough: the app must support custom MCP
servers. No GOV.UK, DWP, HMRC, or project API key is needed.

For an unreleased branch or commit, install directly from GitHub:

```json
{
  "mcpServers": {
    "uk-benefits": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/never-software/uk-benefits-mcp", "uk-benefits-mcp"]
    }
  }
}
```

## Available tools

| Tool | What it does |
| --- | --- |
| `search_official_guidance` | Searches GOV.UK, restricted to DWP or HMRC. |
| `list_adm_documents` | Finds a current DWP ADM chapter by title. |
| `search_adm_document` | Searches one ADM PDF and returns page-numbered excerpts. |
| `get_hmrc_manual` | Reads one HMRC manual page from the GOV.UK Content API. |
| `search_legislation` | Searches legislation.gov.uk. |
| `get_legislation_provision` | Reads a provision now or at an exact `YYYY-MM-DD` date. |
| `search_benefits_case_law` | Searches a supported court in Find Case Law. |
| `search_case_text` | Searches one judgment and returns paragraph-numbered excerpts. |

Every successful response includes the source URL, authority type, retrieval time,
source update time when available, SHA-256 digest, licence, and caveats. Guidance
is labelled separately from legislation and case law.

Example requests an MCP client can make:

- “Find the current ADM chapters about self-employed earnings and capital.”
- “Show regulation 57 of the Universal Credit Regulations 2013 as it stood on
  1 January 2025.”
- “Search Upper Tribunal AAC cases for Universal Credit and self-employment.”
- “Read HMRC Business Income Manual section BIM20205.”

## Self-hosted HTTP

Local Streamable HTTP is available for clients that cannot launch a subprocess:

```bash
uvx uk-benefits-mcp --transport http --port 8000
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. It binds to localhost by default.
If you expose it beyond localhost, put authentication and TLS in a reverse proxy;
the project intentionally does not pretend an unauthenticated public endpoint is
safe.

Docker:

```bash
docker build -t uk-benefits-mcp .
docker run --rm -p 127.0.0.1:8000:8000 uk-benefits-mcp
```

## Source and safety boundaries

The server only makes HTTPS requests to these official public hosts:

- `www.gov.uk`
- `assets.publishing.service.gov.uk`
- `www.legislation.gov.uk`
- `caselaw.nationalarchives.gov.uk`

Every redirect is validated before it is followed. Callers cannot provide an
arbitrary URL. Responses and result counts are bounded, there is no browser
impersonation, and the server has no credentials, telemetry, database, or
persistent cache.

Find Case Law permits ordinary search and reading of individual judgments under
the [Open Justice Licence](https://caselaw.nationalarchives.gov.uk/open-justice-licence/version/2).
Bulk computational analysis is outside this server's design and may require
[separate permission](https://caselaw.nationalarchives.gov.uk/when-you-need-permission).

## Development

```bash
git clone https://github.com/never-software/uk-benefits-mcp.git
cd uk-benefits-mcp
uv sync --all-groups
uv run pytest -m "not live"
uv run pytest -m live
uv run ruff check .
uv run pyright
```

The live suite only calls the public official sources listed above. See
[`docs/design.md`](docs/design.md) for the frozen scope, failure policy, and
verification gates.

## Licence

The server code is MIT licensed. Retrieved public-sector material remains under
the licence named in each response, normally the Open Government Licence v3.0 or
Open Justice Licence v2.0.
