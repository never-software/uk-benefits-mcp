FROM python:3.13-slim

LABEL io.modelcontextprotocol.server.name="io.github.never-software/uk-benefits-mcp"

RUN useradd --create-home --uid 10001 mcp
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

USER mcp
EXPOSE 8000

ENTRYPOINT ["uk-benefits-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
