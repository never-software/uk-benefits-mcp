import httpx
import pytest

from uk_benefits_mcp.sources import OfficialHttpClient, SourceError


@pytest.mark.asyncio
async def test_rejects_non_official_initial_url_without_requesting_it() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=b"should not be reached")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="Refused non-official"):
            await OfficialHttpClient(client).get("https://example.com/private")

    assert called is False


@pytest.mark.asyncio
async def test_validates_redirect_target_before_following_it() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/internal"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="Refused non-official"):
            await OfficialHttpClient(client).get("https://www.gov.uk/start")

    assert requested_hosts == ["www.gov.uk"]


@pytest.mark.asyncio
async def test_enforces_streamed_response_limit() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"12345")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="exceeds the 4 byte limit"):
            await OfficialHttpClient(client).get("https://www.gov.uk/small", max_bytes=4)
