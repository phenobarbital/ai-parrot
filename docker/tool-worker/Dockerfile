# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# parrot-tools — worker image for AI-Parrot remote tool executors.
#
# This is the image referenced by DOCKER_TOOL_IMAGE / K8S_TOOL_IMAGE
# (default "parrot-tools:latest"). It ships ai-parrot + ai-parrot-tools
# and the `parrot.cli.tool_worker` entrypoint that DockerToolExecutor
# and K8sToolExecutor drive: the executor delivers a JSON
# ToolExecutionEnvelope (stdin or file), the worker runs the tool
# in-process, and prints the ToolResult between sentinel markers.
#
# Build (from the repository root — the build context must include packages/):
#
#   docker build -f docker/tool-worker/Dockerfile -t parrot-tools:latest .
#
# Build args:
#
#   PARROT_EXTRAS       ai-parrot extras to install (default "llms": the
#                       OpenAI/Google/Groq/Anthropic SDKs, needed when
#                       Agents-as-Tools run in the worker). "" for a
#                       lean tools-only image.
#   TOOLS_EXTRAS        ai-parrot-tools extras (e.g. "pdf,jira,aws").
#   EXTRA_PIP_PACKAGES  Additional PyPI packages baked into the image
#                       (default "qworker" so the image can also serve
#                       as a Qworker runtime). "" to skip.
#
# Proprietary/private wheels (e.g. a qclient build): drop the .whl files
# into docker/tool-worker/wheels/ before building; anything found there
# is installed into the image.
#
# Runtime notes:
#
# * The default CMD reads the envelope from stdin — what the ephemeral
#   Docker mode and the k8s Job use. The warm Docker mode overrides the
#   command with `sleep infinity` and runs each envelope via exec; both
#   work against this image unchanged.
# * navconfig is scaffolded with an EMPTY env file, so all runtime
#   settings (LLM API keys for Agents-as-Tools, QWORKER_*, DB DSNs…)
#   come from environment variables — pass them via the executor's
#   `env` option. Nothing secret is baked into the image.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Toolchain + headers for source builds (lxml/xmlsec/cffi fallbacks when
# a matching wheel is unavailable for the target arch).
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
COPY packages/ai-parrot-tools ./packages/ai-parrot-tools
COPY docker/tool-worker/wheels ./wheels

ARG PARROT_EXTRAS="llms"
ARG TOOLS_EXTRAS=""
ARG EXTRA_PIP_PACKAGES="qworker"

RUN uv pip install --no-cache \
        "./packages/ai-parrot${PARROT_EXTRAS:+[$PARROT_EXTRAS]}" \
        "./packages/ai-parrot-tools${TOOLS_EXTRAS:+[$TOOLS_EXTRAS]}" \
        ${EXTRA_PIP_PACKAGES} \
    && if ls ./wheels/*.whl >/dev/null 2>&1; then \
           uv pip install --no-cache ./wheels/*.whl; \
       fi

# ---------------------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="parrot-tools" \
      org.opencontainers.image.description="AI-Parrot remote tool executor worker (parrot.cli.tool_worker)" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

# Runtime-only shared libraries + tini as PID 1 (clean signal handling
# for both the one-shot worker and the warm `sleep infinity` container).
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

# navconfig scaffold: an empty env file makes Kardex fall through to
# process environment variables for every setting.
ENV ENV=dev
RUN mkdir -p /app/env/dev /app/etc \
    && touch /app/env/dev/.env \
    && printf '[info]\nname = parrot-tool-worker\n' > /app/etc/config.ini \
    && chown -R parrot:parrot /app

COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER parrot

# Build-time smoke check: the worker entrypoint (and its full import
# chain — parrot.tools, navconfig, envelope runner) must be importable.
RUN python -c "from parrot.cli import tool_worker; print('tool_worker import OK')"

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "parrot.cli.tool_worker", "--envelope", "-"]
