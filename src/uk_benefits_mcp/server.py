"""MCP tool registration and dependency lifecycle."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .models import (
    AdmCatalogue,
    AdmSearch,
    CaseLawSearch,
    CaseTextSearch,
    Evidence,
    GuidanceSearch,
    HmrcManual,
    LegislationProvision,
    LegislationSearch,
)
from .sources import OfficialSources

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
INSTRUCTIONS = """
Retrieve official UK benefits evidence. Distinguish legislation and case law from
DWP/HMRC guidance, preserve the returned source metadata, and verify important
conclusions at the canonical URL. Do not treat these tools as legal, tax, or
benefits advice and do not send claimant-identifying information in queries.
""".strip()


@dataclass(slots=True)
class AppContext:
    sources: OfficialSources


def create_server(injected_sources: OfficialSources | None = None) -> MCPServer[AppContext]:
    """Create an independently testable MCP server."""

    @asynccontextmanager
    async def lifespan(_: MCPServer[AppContext]) -> AsyncGenerator[AppContext]:
        if injected_sources is not None:
            yield AppContext(sources=injected_sources)
            return
        timeout = httpx.Timeout(30.0, connect=10.0)
        headers = {"User-Agent": f"uk-benefits-mcp/{__version__} (+https://github.com/never-software/uk-benefits-mcp)"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            yield AppContext(sources=OfficialSources(client))

    server = MCPServer(
        "uk-benefits-mcp",
        title="UK Benefits Evidence",
        description="Read-only access to official UK benefits, tax, legislation, and case-law evidence",
        instructions=INSTRUCTIONS,
        website_url="https://github.com/never-software/uk-benefits-mcp",
        version=__version__,
        lifespan=lifespan,
    )

    def sources(ctx: Context[AppContext]) -> OfficialSources:
        return ctx.request_context.lifespan_context.sources

    @server.tool(annotations=READ_ONLY)
    async def search_official_guidance(
        query: Annotated[str, Field(min_length=2, max_length=200, description="Non-personal search terms")],
        organisation: Literal["dwp", "hmrc"],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> Evidence[GuidanceSearch]:
        """Search current official GOV.UK guidance restricted to DWP or HMRC."""

        return await sources(ctx).search_guidance(query.strip(), organisation, limit)

    @server.tool(annotations=READ_ONLY)
    async def list_adm_documents(
        ctx: Context[AppContext],
        query: Annotated[str, Field(max_length=200, description="Optional words from an ADM title")] = "",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> Evidence[AdmCatalogue]:
        """List or filter PDFs in DWP's current Advice for Decision Making collection."""

        return await sources(ctx).list_adm(query.strip(), limit)

    @server.tool(annotations=READ_ONLY)
    async def search_adm_document(
        document: Annotated[
            str,
            Field(min_length=2, max_length=300, description="Exact title, or an unambiguous substring"),
        ],
        query: Annotated[str, Field(min_length=2, max_length=200, description="Literal phrase to find in the PDF")],
        ctx: Context[AppContext],
        max_hits: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> Evidence[AdmSearch]:
        """Search one official DWP ADM PDF and return page-numbered excerpts."""

        return await sources(ctx).search_adm(document.strip(), query.strip(), max_hits)

    @server.tool(annotations=READ_ONLY)
    async def get_hmrc_manual(
        manual: Annotated[
            str,
            Field(
                min_length=2,
                max_length=100,
                description="GOV.UK manual slug, for example business-income-manual",
            ),
        ],
        ctx: Context[AppContext],
        section: Annotated[
            str | None, Field(max_length=100, description="Optional section slug, for example bim20205")
        ] = None,
    ) -> Evidence[HmrcManual]:
        """Retrieve one current official HMRC internal-manual page as clean text."""

        return await sources(ctx).get_hmrc_manual(manual, section)

    @server.tool(annotations=READ_ONLY)
    async def search_legislation(
        query: Annotated[str, Field(min_length=2, max_length=200)],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> Evidence[LegislationSearch]:
        """Search legislation.gov.uk for Acts, regulations, orders, and rules."""

        return await sources(ctx).search_legislation(query.strip(), limit)

    @server.tool(annotations=READ_ONLY)
    async def get_legislation_provision(
        document_type: Literal["ukpga", "uksi", "ukla", "asp", "anaw", "mwa", "nia", "nisi", "ssi", "wsi", "nisr"],
        year: Annotated[int, Field(ge=1800, le=2200)],
        number: Annotated[str, Field(pattern=r"^[0-9]+$", max_length=12)],
        ctx: Context[AppContext],
        provision: Annotated[
            str | None,
            Field(
                max_length=160,
                description="Optional path such as regulation/57 or schedule/1/paragraph/3",
            ),
        ] = None,
        as_of: Annotated[str | None, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] = None,
    ) -> Evidence[LegislationProvision]:
        """Retrieve one provision as current text or at an exact point in time."""

        return await sources(ctx).get_legislation(document_type, year, number, provision, as_of)

    @server.tool(annotations=READ_ONLY)
    async def search_benefits_case_law(
        query: Annotated[str, Field(min_length=2, max_length=200)],
        ctx: Context[AppContext],
        court: Literal["ukut/aac", "ewca/civ", "uksc"] = "ukut/aac",
        page: Annotated[int, Field(ge=1, le=50)] = 1,
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> Evidence[CaseLawSearch]:
        """Run a targeted Find Case Law search; this is not a bulk-analysis tool."""

        return await sources(ctx).search_case_law(query.strip(), court, page, limit)

    @server.tool(annotations=READ_ONLY)
    async def search_case_text(
        slug: Annotated[
            str,
            Field(
                min_length=5,
                max_length=100,
                description="Find Case Law identifier returned by search_benefits_case_law",
            ),
        ],
        query: Annotated[str, Field(min_length=2, max_length=200)],
        ctx: Context[AppContext],
        max_hits: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> Evidence[CaseTextSearch]:
        """Search within one Find Case Law judgment and return paragraph excerpts."""

        return await sources(ctx).search_case_text(slug, query.strip(), max_hits)

    return server


mcp = create_server()
