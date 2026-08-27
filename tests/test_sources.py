import httpx
import pytest
from conftest import fixture_bytes

from uk_benefits_mcp.sources import OfficialSources, SourceError


def fixture_handler(request: httpx.Request) -> httpx.Response:
    fixtures = {
        "/api/search.json": ("govuk_search.json", "application/json"),
        "/api/content/government/publications/advice-for-decision-making-staff-guide": (
            "adm_collection.json",
            "application/json",
        ),
        "/api/content/hmrc-internal-manuals/business-income-manual/bim20205": (
            "hmrc_manual.json",
            "application/json",
        ),
        "/all/data.feed": ("legislation_feed.xml", "application/atom+xml"),
        "/uksi/2013/376/regulation/57/2025-01-01/data.xml": ("legislation.xml", "application/xml"),
        "/atom.xml": ("caselaw_feed.xml", "application/atom+xml"),
        "/ukut/aac/2026/312/data.xml": ("judgment.xml", "application/akn+xml"),
    }
    fixture = fixtures.get(request.url.path)
    if fixture is None:
        return httpx.Response(404)
    name, content_type = fixture
    return httpx.Response(200, content=fixture_bytes(name), headers={"content-type": content_type})


@pytest.mark.asyncio
async def test_parses_guidance_adm_and_hmrc_results_with_provenance() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_handler)) as client:
        sources = OfficialSources(client)

        guidance = await sources.search_guidance("self employed", "dwp", 10)
        assert guidance.source.authority == "dwp_guidance"
        assert len(guidance.source.content_sha256) == 64
        assert guidance.data.results[0].url == "https://www.gov.uk/self-employment-and-universal-credit"

        adm = await sources.list_adm("self-employed", 20)
        assert adm.data.count == 1
        assert adm.data.documents[0].title.startswith("Chapter H4")
        assert all("example.invalid" not in item.url for item in adm.data.documents)

        manual = await sources.get_hmrc_manual("business-income-manual", "bim20205")
        assert manual.source.authority == "hmrc_guidance"
        assert "No single badge is decisive" in manual.data.text
        assert "Frequency of transactions" in manual.data.text
        assert manual.data.truncated is False


@pytest.mark.asyncio
async def test_parses_legislation_search_and_point_in_time_provision() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_handler)) as client:
        sources = OfficialSources(client)

        search = await sources.search_legislation("universal credit", 5)
        result = search.data.results[0]
        assert result.url == "https://www.legislation.gov.uk/uksi/2013/376"
        assert result.year == 2013
        assert result.number == "376"
        assert search.source.authority == "legislation"

        provision = await sources.get_legislation("uksi", 2013, "376", "regulation/57", "2025-01-01")
        assert provision.data.as_of == "2025-01-01"
        assert "earned income" in provision.data.text
        assert provision.data.truncated is False


@pytest.mark.asyncio
async def test_rejects_invalid_historical_date_instead_of_falling_back() -> None:
    requested = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="real date"):
            await OfficialSources(client).get_legislation("uksi", 2013, "376", "regulation/57", "2025-02-31")
    assert requested is False


@pytest.mark.asyncio
async def test_parses_targeted_case_search_and_paragraph_hits() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_handler)) as client:
        sources = OfficialSources(client)

        search = await sources.search_case_law("universal credit", "ukut/aac", 1, 5)
        result = search.data.results[0]
        assert result.slug == "ukut/aac/2026/312"
        assert result.citation == "[2026] UKUT 312 (AAC)"
        assert search.source.licence == "Open Justice Licence v2.0"

        text = await sources.search_case_text(result.slug, "self-employment", 5)
        assert text.data.count == 1
        assert text.data.hits[0].locator == "para_2"
        assert "Self-employment" in text.data.hits[0].excerpt
