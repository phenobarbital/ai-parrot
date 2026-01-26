# =============================================================================
# Jira MCP Server - Dockerfile específico
# =============================================================================
# Build:
#   docker build -f Dockerfile.jira -t jira-mcp-server .
#
# Run:
#   docker run -p 8080:8080 \
#     -e JIRA_INSTANCE=https://your-instance.atlassian.net \
#     -e JIRA_USERNAME=your@email.com \
#     -e JIRA_API_TOKEN=your-token \
#     -e JIRA_PROJECT=PROJ \
#     jira-mcp-server
# =============================================================================

FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libffi-dev libssl-dev libpq-dev git curl \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# Builder
# =============================================================================
FROM base AS builder

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build
COPY . .

RUN uv venv /opt/venv --python 3.12
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Jira solo necesita el extra "agents"
RUN uv pip install -e ".[agents]"

# =============================================================================
# Runtime
# =============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    PORT=8080 \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8080 \
    # Defaults para Jira (sobrescribir en runtime)
    MCP_TRANSPORT=http

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash parrot

WORKDIR /app
RUN mkdir -p /app/env /app/etc && chown -R parrot:parrot /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build /app
RUN chown -R parrot:parrot /app

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    BASE_DIR=/app \
    NAVCONFIG_ENV=/app/env

USER parrot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

# Entrypoint específico para Jira
COPY --chown=parrot:parrot <<'EOF' /app/server.yaml
MCPServer:
  name: JiraMCP
  host: 0.0.0.0
  port: 8080
  transport: http
  enable_ssl: false
  auth_method: none
  tools:
    - JiraToolkit:
        server_url: 
        username: 
        token: 
        default_project: 
        auth_type: basic_auth
EOF

CMD ["parrot", "mcp", "--config", "server.yaml"]