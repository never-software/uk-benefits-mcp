import httpx
import pytest
from conftest import fixture_bytes
from mcp.client import Client

from uk_benefits_mcp.server import create_server
from uk_benefits_mcp.sources import OfficialSources


@pytest.mark.asyncio
async def test_mcp_lists_only_the_bounded_read_only_tools_and_returns_structured_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search.json":
            return httpx.Response(
                200,
                content=fixture_bytes("govuk_search.json"),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        server = create_server(OfficialSources(http_client))
        async with Client(server) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            assert names == {
                "search_official_guidance",
                "list_adm_documents",
                "search_adm_document",
                "get_hmrc_manual",
                "search_legislation",
                "get_legislation_provision",
                "search_benefits_case_law",
                "search_case_text",
            }
            assert all(tool.annotations and tool.annotations.read_only_hint for tool in listing.tools)
            assert all("ctx" not in tool.input_schema.get("properties", {}) for tool in listing.tools)

            result = await client.call_tool(
                "search_official_guidance",
                {"query": "self employed", "organisation": "dwp", "limit": 1},
            )
            assert result.is_error is not True
            assert result.structured_content is not None
            assert result.structured_content["source"]["authority"] == "dwp_guidance"
            assert result.structured_content["data"]["count"] == 1


@pytest.mark.asyncio
async def test_mcp_input_schema_rejects_out_of_bounds_result_count() -> None:
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as http_client,
        Client(create_server(OfficialSources(http_client))) as client,
    ):
        result = await client.call_tool(
            "search_official_guidance",
            {"query": "self employed", "organisation": "dwp", "limit": 1000},
        )
        assert result.is_error is True
