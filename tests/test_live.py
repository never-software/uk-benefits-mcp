import httpx
import pytest

from uk_benefits_mcp.sources import OfficialSources


@pytest.fixture
async def live_sources():  # type: ignore[no-untyped-def]
    headers = {"User-Agent": "uk-benefits-mcp-live-test/0.1 (+https://github.com/never-software/uk-benefits-mcp)"}
    async with httpx.AsyncClient(timeout=45, headers=headers) as client:
        yield OfficialSources(client)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_govuk_adm_and_hmrc(live_sources: OfficialSources) -> None:
    guidance = await live_sources.search_guidance("self-employed Universal Credit", "dwp", 3)
    assert guidance.data.count > 0

    catalogue = await live_sources.list_adm("Chapter H4", 5)
    assert catalogue.data.count == 1
    pdf = await live_sources.search_adm(catalogue.data.documents[0].title, "self-employed", 2)
    assert pdf.data.count > 0
    assert pdf.data.pages > 0

    manual = await live_sources.get_hmrc_manual("business-income-manual", "bim20205")
    assert "trade" in manual.data.title.lower()
    assert manual.data.text


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_legislation_point_in_time(live_sources: OfficialSources) -> None:
    search = await live_sources.search_legislation("universal credit", 3)
    assert search.data.count > 0
    provision = await live_sources.get_legislation("uksi", 2013, "376", "regulation/57", "2025-01-01")
    assert "earned income" in provision.data.text.lower()
    assert provision.data.as_of == "2025-01-01"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_targeted_case_law(live_sources: OfficialSources) -> None:
    search = await live_sources.search_case_law("universal credit", "ukut/aac", 1, 3)
    assert search.data.count > 0
    judgment = await live_sources.search_case_text(search.data.results[0].slug, "universal credit", 3)
    assert judgment.data.count > 0
