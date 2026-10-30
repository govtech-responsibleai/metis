# syntax=docker/dockerfile:1

# Build from the repository ROOT, not from apps/api:
#
#   docker build -f apps/api/Dockerfile -t metis-api .
#
# METIS is a single uv workspace with one lockfile, so the image needs the workspace root and the
# path-dependency members to resolve metis-api -> metis-wizard -> metis-library -> metis-core.

FROM python:3.12-slim AS runtime

# A corporate proxy intercepts TLS, so `uv sync` and every later model call fail with
# CERTIFICATE_VERIFY_FAILED unless the CA bundle is installed early and every client points at it.
# (See the root AGENTS.md note.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# uv, taken as a pinned static binary from its published image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The lockfile, the workspace root, and the Python members. `apps/web` is a React demo with no
# pyproject, so it is not a workspace member and is left out of the service image.
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/api/ apps/api/

# Install only metis-api and its workspace path-deps, from the frozen lockfile, without the dev or
# test groups. No frontend, no gateway credentials baked in — those arrive from the environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package metis-api

# The container binds all interfaces; the host maps the port. Both are overridable at run time.
ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# `metis-api` runs Uvicorn on metis.api.main:app (see apps/api/src/metis/api/cli.py).
CMD ["metis-api"]
