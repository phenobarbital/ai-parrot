# =============================================================================
# AI-Parrot MCP Server - Dockerfile para AWS App Runner / Fargate
# =============================================================================
# Este Dockerfile crea un entorno completo para ejecutar SimpleMCPServer
# con cualquier toolkit (Jira, O365, etc.)
#
# Build:
#   docker build -t parrot-mcp-server .
#   docker build --build-arg INSTALL_EXTRAS="agents,loaders" -t parrot-mcp-server .
#
# Run locally:
#   docker run -p 8080:8080 --env-file .env parrot-mcp-server
# =============================================================================

FROM python:3.12-slim AS base

# Evitar prompts interactivos y establecer locale
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalar dependencias del sistema necesarias para compilar extensiones
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# Stage: Builder - Instalar uv y dependencias
# =============================================================================
FROM base AS builder

# Instalar uv (gestor de paquetes rápido)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build

# Copiar archivos de configuración del proyecto
COPY pyproject.toml setup.py ./
COPY parrot/version.py parrot/__init__.py parrot/

# Crear virtualenv con uv
RUN uv venv /opt/venv --python 3.12

# Activar virtualenv para las instalaciones
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Argumento para extras opcionales (agents, loaders, vectors, etc.)
ARG INSTALL_EXTRAS="agents"

# Copiar todo el código fuente
COPY . .

# Instalar AI-Parrot con los extras especificados
RUN uv pip install -e ".[$INSTALL_EXTRAS]"

# =============================================================================
# Stage: Runtime - Imagen final optimizada
# =============================================================================
FROM python:3.12-slim AS runtime

# Variables de entorno para producción
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    # Puerto estándar para App Runner / Fargate
    PORT=8080 \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8080

# Instalar solo runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root para seguridad
RUN useradd --create-home --shell /bin/bash parrot

# Crear estructura de directorios que navconfig espera
WORKDIR /app

# Directorios para navconfig (env/ para .env, etc/ para configs)
RUN mkdir -p /app/env /app/etc /app/static /app/plugins /app/agents \
    && chown -R parrot:parrot /app

# Copiar virtualenv desde builder
COPY --from=builder /opt/venv /opt/venv

# Copiar código fuente instalado
COPY --from=builder /build /app

# Asegurar permisos
RUN chown -R parrot:parrot /app

# Activar virtualenv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Variables para navconfig
ENV BASE_DIR=/app \
    NAVCONFIG_ENV=/app/env

# Cambiar a usuario no-root
USER parrot

# Puerto expuesto (App Runner y Fargate usan 8080 por defecto)
EXPOSE 8080

# Healthcheck para ALB/App Runner
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/mcp/info || curl -f http://localhost:${PORT}/ || exit 1

# =============================================================================
# Entrypoint configurable
# =============================================================================
# Por defecto arranca un servidor MCP HTTP genérico
# Puede ser sobrescrito con CMD en docker run o task definition

# Script de entrada que permite flexibilidad
COPY --chown=parrot:parrot <<'EOF' /app/entrypoint.sh
#!/bin/bash
set -e

# Si existe un .env en /app/env, copiarlo
if [ -f "/app/env/.env" ]; then
    echo "Loading environment from /app/env/.env"
    export $(grep -v '^#' /app/env/.env | xargs)
fi

# Ejecutar el comando pasado o el default
exec "$@"
EOF

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

# Comando por defecto - puede ser sobrescrito
CMD ["python", "-m", "parrot.mcp.server", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]