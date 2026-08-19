# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# parrot-dev — isolated sandbox for building AI-Parrot agents, crews/flows
# ("workflows"), and running the dev_loop.
#
# Unlike docker/tool-worker and docker/integrations (which COPY packages/
# and build from THIS monorepo's local source), this image installs
# ai-parrot the normal way — `uv pip install ai-parrot[...]`, per
# INSTALL.md — so it has no build-context dependency on the repo checkout
# and can be built from anywhere:
#
#   docker build -f docker/dev/Dockerfile -t parrot-dev:latest docker/dev
#
# Build args:
#
#   PYTHON_VERSION   Python version (default "3.11").
#   PARROT_EXTRAS    ai-parrot extras to install, comma separated (default
#                     "agents,llms": ReAct tool-using agents plus the
#                     OpenAI/Google/Groq/Anthropic client SDKs). "" for a
#                     bare install (note: plain `import parrot` works with
#                     "", but building an actual Agent needs at least the
#                     packages below).
#   EXTRA_PACKAGES   Additional PyPI packages/extras, space separated.
#                     Defaults to "ai-parrot-server[mcp] async-notify[all]"
#                     — see "Known coupling" below for why these are
#                     required, not optional, to use `parrot.bots.agent`.
#                     Add more here (e.g. "ai-parrot-tools[all]
#                     ai-parrot-embeddings[pgvector]") as your agents need
#                     tools/vector stores.
#
# Known coupling (as of this writing): ai-parrot core's `bots.agent.Agent`
# unconditionally imports MCPEnabledMixin (which needs the transports
# submodule shipped by the ai-parrot-server satellite, not ai-parrot core)
# and NotificationMixin (which needs the `notify` package — declared only
# behind ai-parrot's `integrations` extra, not `agents`). Neither is gated
# by a feature flag, so a plain `ai-parrot[agents]` install fails at import
# time when you actually build an Agent. Worth raising upstream.
#
# Runtime notes:
#
# * WORKDIR /workspace is where your agent/workflow/dev_loop code lives —
#   mount your project into it:
#     docker run -it -v $(pwd):/workspace parrot-dev:latest
# * navconfig is scaffolded under /app (SITE_ROOT=/app, ENV=dev) with an
#   EMPTY env file, kept separate from /workspace so mounting your own
#   project there never shadows it. All runtime settings (LLM API keys, DB
#   DSNs...) come from environment variables — pass them via `-e` /
#   `--env-file`. Nothing secret is baked into the image.
# * Default CMD drops into an interactive bash shell with the venv already
#   active (PATH points at /opt/venv/bin) — ready to `python your_agent.py`
#   or run dev_loop / crew / flow scripts directly.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="parrot-dev" \
      org.opencontainers.image.description="Isolated AI-Parrot sandbox for agent/workflow/dev_loop development" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        pkg-config \
        libffi-dev \
        libssl-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 parrot

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

ARG PARROT_EXTRAS="agents,llms"
ARG EXTRA_PACKAGES="ai-parrot-server[mcp] async-notify[all]"

RUN uv pip install --no-cache \
        "ai-parrot${PARROT_EXTRAS:+[$PARROT_EXTRAS]}" \
        ${EXTRA_PACKAGES}

# navconfig scaffold: SITE_ROOT/BASE_DIR are pinned explicitly (rather than
# left to navconfig's virtualenv-parent heuristic, which resolves to /opt
# here since VIRTUAL_ENV=/opt/venv) and kept out of /workspace so a project
# bind-mount there never shadows it. /app/templates is scaffolded too:
# NotificationMixin (async-notify) resolves {SITE_ROOT}/templates at import
# time and raises if it's missing, even when no templates are rendered.
ENV SITE_ROOT=/app \
    BASE_DIR=/app \
    ENV=dev
RUN mkdir -p /app/env/dev /app/etc /app/templates /workspace \
    && touch /app/env/dev/.env \
    && printf '[info]\nname = parrot-dev\n' > /app/etc/config.ini \
    && chown -R parrot:parrot /app /workspace

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace
USER parrot

RUN python -c "from parrot.bots.agent import Agent; print('ai-parrot Agent import OK')"

CMD ["bash"]
