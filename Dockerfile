# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

# uv for fast, reproducible installs. Pinned to an immutable digest (the
# multi-arch manifest-list digest for the 0.11.21 tag) so the builder is
# reproducible and not subject to a mutable :latest moving under us.
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /usr/local/bin/

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

# Drop root: the app only reads mounted specs and (optionally) listens on a
# port — it never needs to write to the image or bind a privileged port. Run as
# a non-root system user. /app (incl. the .venv and the mounted /app/specs
# read path) is chowned so the venv binaries and specs stay readable.
RUN useradd --system --uid 10001 appuser && chown -R appuser /app
USER 10001

# Specs are mounted at runtime — not baked into the image
# -----------------------------------------------------------------------
# Usage:
#
# Build:
#   docker build -t catalyst-center-super-mcp .
#
# Credentials: the values below are the PUBLIC DevNet always-on sandbox creds
# and are shown as placeholders only. For real deployments, source secrets from
# a secrets manager (or an --env-file) rather than literal -e flags, which leak
# into shell history, `docker inspect`, and process listings.
#
# Claude Desktop (stdio) — prefer --env-file:
#   docker run -i --rm \
#     --env-file .env \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp
#
#   ...or with explicit env vars (read from your shell, not hard-coded):
#   docker run -i --rm \
#     -e CATALYST_CENTER_USERNAME="$CATALYST_CENTER_USERNAME" \
#     -e CATALYST_CENTER_PASSWORD="$CATALYST_CENTER_PASSWORD" \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp
#
# Network (SSE):
#   docker run -p 8000:8000 \
#     --env-file .env \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp --transport sse --host 0.0.0.0 --port 8000
# -----------------------------------------------------------------------

ENTRYPOINT ["catalyst-center-mcp"]
