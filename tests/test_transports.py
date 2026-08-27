import asyncio
import socket
import subprocess
import sys

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


@pytest.mark.asyncio
async def test_real_stdio_subprocess_lists_tools() -> None:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "uk_benefits_mcp"])
    async with Client(parameters, read_timeout_seconds=10) as client:
        listing = await client.list_tools()
    assert "get_legislation_provision" in {tool.name for tool in listing.tools}


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait_for_port(port: int) -> None:
    for _ in range(100):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.05)
            continue
        writer.close()
        await writer.wait_closed()
        del reader
        return
    raise AssertionError("Streamable HTTP server did not start")


@pytest.mark.asyncio
async def test_real_local_streamable_http_lists_tools() -> None:
    port = _unused_local_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uk_benefits_mcp",
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        await _wait_for_port(port)
        async with Client(f"http://127.0.0.1:{port}/mcp", read_timeout_seconds=10) as client:
            listing = await client.list_tools()
        assert "search_adm_document" in {tool.name for tool in listing.tools}
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
