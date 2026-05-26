# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY catalyst_center_mcp ./catalyst_center_mcp

# Install into /app/.venv
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# --- runtime ---
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app /app
COPY catalyst-center-mcp.yaml ./

ENV PATH="/app/.venv/bin:$PATH"

# Specs are mounted at runtime — not baked into the image
# -----------------------------------------------------------------------
# Usage:
#
# Build:
#   docker build -t catalyst-center-super-mcp .
#
# Claude Desktop (stdio):
#   docker run -i --rm \
#     -e CATALYST_CENTER_USERNAME=devnetuser \
#     -e CATALYST_CENTER_PASSWORD=Cisco123! \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp
#
# Network (SSE):
#   docker run -p 8000:8000 \
#     -e CATALYST_CENTER_USERNAME=devnetuser \
#     -e CATALYST_CENTER_PASSWORD=Cisco123! \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp --transport sse --host 0.0.0.0 --port 8000
# -----------------------------------------------------------------------

ENTRYPOINT ["catalyst-center-mcp"]
