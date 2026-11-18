# syntax=docker/dockerfile:1

# One image serves the web app and the API on one address. Build it from the repository root:
#
#   docker build -t metis .
#
# METIS is a single uv workspace with one lockfile, so the image needs the workspace root and the
# path-dependency members. See docs/guide/docker.md.

# ---- The web app: a static build that the API serves from its package. ----
# The output is the same on every CPU, so this stage runs on the platform of the build machine. A
# build for another platform then emulates only the runtime stage, and esbuild, which can crash
# under emulation, runs natively.
FROM --platform=$BUILDPLATFORM node:22-slim AS web

# A corporate proxy intercepts TLS, so `npm ci` fails with a certificate error unless the CA bundle
# is installed early and Node points at it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /web

# apps/web has its own lockfile and is not part of an npm workspace.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

# ---- The runtime: the API, the `metis` CLI, and the built web app. ----
FROM python:3.11-slim AS runtime

# A corporate proxy intercepts TLS, so `uv sync` and every later model call fail with
# CERTIFICATE_VERIFY_FAILED unless the CA bundle is installed early and every client points at it.
# See "Certificates" in docs/guide/docker.md.
#
# tini is PID 1. It sends each stop signal on to the API and reaps child processes that end.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tini \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# uv, taken as a static binary from its published image, pinned to one release.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The workspace root project ships the `metis` CLI and depends on every Python member, so the
# image has the API, the engine, the wizard, and insights. `apps/web` is not a Python member.
COPY pyproject.toml uv.lock metis_cli.py metis_dev.py ./
COPY packages/ packages/
COPY apps/api/ apps/api/

# Install from the frozen lockfile, without the dev group. No key and no .env go into the image.
# They come from the environment or from /data/.env at run time.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY --from=web /web/dist /app/apps/api/src/metis/api/web_dist

# An API that cannot find the web app serves the API alone and reports no error, so fail here.
RUN python -c "from metis.api.web import WEB_DIR; assert (WEB_DIR / 'index.html').is_file(), WEB_DIR"

# The container listens on all interfaces, and the host maps the port. Both can change at run time.
ENV HOST=0.0.0.0 \
    PORT=8000

# Everything that must persist is under /data: the database, the Target files, and the
# experiments. The API and the CLI both use /data as the project folder.
RUN groupadd --system --gid 10001 metis \
 && useradd --system --uid 10001 --gid metis --home-dir /data --shell /usr/sbin/nologin metis \
 && mkdir -p /data \
 && chown metis:metis /data

USER metis
VOLUME /data
WORKDIR /data
EXPOSE 8000

# The slim image has no curl, so the check uses Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)"

# The API runs each experiment on a thread of its own, up to METIS_API_ENGINE_MAX_RUNS at once,
# and queues the rest. tini as PID 1 and the exec form of CMD let the stop signal reach the API,
# which then stops its runs. Run one API process in one container only. The store, the
# experiment folders, the live runs, and the queue are not shared between processes. See "Run
# one container" in docs/guide/docker.md.
ENTRYPOINT ["tini", "--"]
CMD ["metis-api", "--project-dir", "/data"]
