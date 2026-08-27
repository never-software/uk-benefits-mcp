"""Console entry point for stdio and Streamable HTTP transports."""

import argparse
from collections.abc import Sequence

from . import __version__
from .server import mcp


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Official UK benefits evidence over MCP")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    result.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    result.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: 127.0.0.1)")
    result.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser().error("--port must be between 1 and 65535")
    if args.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            json_response=True,
            stateless_http=True,
        )
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
