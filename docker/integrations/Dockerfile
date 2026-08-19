# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# parrot-integrations — standalone image for AI-Parrot messaging-bot
# integrations (Telegram, Slack, MS Teams, WhatsApp, Matrix, MS Agent SDK).
#
# This image does NOT run the full company webserver (app.py/run.py at the
# repo root), which additionally pulls in QuerySource, navigator_auth, PBAC,
# Jira OAuth and FormDesigner. It runs docker/integrations/server.py — the
# minimal entrypoint documented in docs/telegram-integration.md's Quick
# Start: a bare aiohttp app wrapping `parrot.manager.BotManager`, which
# wires `IntegrationBotManager` on startup and reads
# {SITE_ROOT}/env/integrations_bots.yaml.
#
# Build (from the repository root — the build context must include packages/):
#
#   docker build -f docker/integrations/Dockerfile -t parrot-integrations:latest .
#
# Build args:
#
#   PARROT_EXTRAS        ai-parrot extras (default "llms,mcp,db,integrations").
#                         `BotManager`'s import chain (AbstractBot,
#                         NotificationMixin, crew/flow handlers,
#                         parent-searcher factory, ai-parrot-tools) is NOT
#                         gated behind feature flags at import time, so it
#                         unconditionally needs sqlalchemy (db), aioquic
#                         (mcp) and async-notify (integrations) — see
#                         "Known coupling" below before trimming this down.
#                         (Plain "all" doesn't resolve standalone: ai-parrot's
#                         `flowtask` extra pins a pillow-heif version that
#                         conflicts with `images`'s; both are only reconciled
#                         by the monorepo workspace's dependency overrides.)
#   SERVER_EXTRAS         ai-parrot-server extras (default "all": scheduler,
#                         mcp, a2a, autonomous — same reasoning as above).
#   INTEGRATIONS_EXTRAS  ai-parrot-integrations channel extras (default
#                         "all": every channel SDK — Telegram, Slack,
#                         MS Teams, WhatsApp, Matrix, voice; msagentsdk is
#                         intentionally excluded from "all" upstream).
#                         Narrow to just the channels you use, comma
#                         separated (e.g. "telegram,slack"), once you've
#                         confirmed the trimmed import chain still resolves.
#   TOOLS_EXTRAS          ai-parrot-tools extras (e.g. "pdf,jira,aws").
#                         Empty by default — the package itself is required
#                         (see below), but its per-tool extras are opt-in.
#
# Known coupling (as of this writing): `from parrot.manager import
# BotManager` is documented as the minimal integrations entrypoint
# (docs/telegram-integration.md), but its module import graph reaches
# several optional-extra-only packages — and a whole separate satellite,
# ai-parrot-tools — unconditionally. Anything short of the extras above
# currently fails at import time, not at runtime, and none of it is gated
# by ENABLE_DATABASE_BOTS/ENABLE_CREWS/etc. Worth raising upstream if a
# leaner bots-only footprint is wanted.
#
# Runtime notes:
#
# * Nothing secret is baked into the image. Provide the real config at
#   container start by mounting it over /app/env:
#     - /app/env/integrations_bots.yaml   bot/channel definitions
#     - /app/env/<ENV>/.env               tokens, API keys (ENV defaults to
#                                          "dev"; override with -e ENV=prod)
#   e.g. `docker run -v $(pwd)/env:/app/env -e ENV=prod ...`
# * Feature flags that would pull in extra infrastructure default OFF
#   (ENABLE_DATABASE_BOTS / ENABLE_CREWS / ENABLE_DASHBOARDS /
#   ENABLE_SWAGGER = false) so the bots-only footprint needs no Postgres.
#   Set REDIS_URL if a channel/feature you enable needs it.
# * PORT (default 5000) controls the aiohttp listen port; /healthz is a
#   liveness check.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Toolchain + headers for source builds (lxml/xmlsec/cffi fallbacks when a
# matching wheel is unavailable for the target arch — needed by several
# channel SDKs, e.g. azure-teambots/mautrix).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        pkg-config \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libxmlsec1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY packages/ai-parrot ./packages/ai-parrot
COPY packages/ai-parrot-server ./packages/ai-parrot-server
COPY packages/ai-parrot-integrations ./packages/ai-parrot-integrations
COPY packages/ai-parrot-tools ./packages/ai-parrot-tools

# `parrot.manager.BotManager` (imported by server.py) pulls in AbstractBot,
# NotificationMixin, the crew/flow handlers, the parent-searcher factory,
# and handlers.agents.data (which imports ai-parrot-tools) at *module
# import time*, unconditionally — not gated by ENABLE_CREWS /
# ENABLE_DATABASE_BOTS / etc. Those hard imports reach sqlalchemy (db
# extra), aioquic (mcp extra), async-notify (integrations extra), and the
# whole ai-parrot-tools package, so anything short of what's listed here
# fails at import, not at runtime. Trim at your own risk, once you've
# confirmed your BotManager import path doesn't need a given extra.
ARG PARROT_EXTRAS="llms,mcp,db,integrations"
ARG SERVER_EXTRAS="all"
ARG INTEGRATIONS_EXTRAS="all"
ARG TOOLS_EXTRAS=""

# --no-sources: the satellite packages declare `ai-parrot = { workspace =
# true }` in their own [tool.uv.sources], which only resolves inside the
# full monorepo uv workspace (root pyproject.toml + lockfile, not copied
# into this build context). Ignoring that table falls back to the local
# path already given explicitly on this command line for `ai-parrot`.
RUN uv pip install --no-cache --no-sources \
        "./packages/ai-parrot${PARROT_EXTRAS:+[$PARROT_EXTRAS]}" \
        "./packages/ai-parrot-server${SERVER_EXTRAS:+[$SERVER_EXTRAS]}" \
        "./packages/ai-parrot-integrations${INTEGRATIONS_EXTRAS:+[$INTEGRATIONS_EXTRAS]}" \
        "./packages/ai-parrot-tools${TOOLS_EXTRAS:+[$TOOLS_EXTRAS]}"

# ---------------------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="parrot-integrations" \
      org.opencontainers.image.description="AI-Parrot messaging-bot integrations server (Telegram/Slack/MSTeams/WhatsApp/...) driven by integrations_bots.yaml" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

# Runtime-only shared libraries + tini as PID 1 (clean signal handling).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
        libxml2 \
        libxslt1.1 \
        libxmlsec1-openssl \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 parrot

WORKDIR /app

# navconfig scaffold: SITE_ROOT/BASE_DIR are pinned explicitly (rather than
# left to navconfig's virtualenv-parent heuristic, which resolves to /opt
# here since VIRTUAL_ENV=/opt/venv) so the env directory Kardex looks for
# is always /app/env, not /opt/env. An empty env file makes every runtime
# setting fall through to process environment variables. /app/templates is
# scaffolded too: NotificationMixin (async-notify) resolves
# {SITE_ROOT}/templates at import time and raises if it's missing, even
# when no notification templates are actually rendered.
ENV SITE_ROOT=/app \
    BASE_DIR=/app \
    ENV=dev
RUN mkdir -p /app/env/dev /app/etc /app/templates \
    && touch /app/env/dev/.env \
    && printf '[info]\nname = parrot-integrations\n' > /app/etc/config.ini \
    && chown -R parrot:parrot /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=parrot:parrot docker/integrations/server.py /app/server.py

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    ENABLE_DATABASE_BOTS=false \
    ENABLE_CREWS=false \
    ENABLE_DASHBOARDS=false \
    ENABLE_SWAGGER=false

USER parrot

# Build-time smoke check: the manager and its full handler import chain
# must be importable.
RUN python -c "from parrot.manager import BotManager; print('BotManager import OK')"

EXPOSE 5000

ENTRYPOINT ["tini", "--"]
CMD ["python", "/app/server.py"]
