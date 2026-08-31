# llama-server (llama.cpp) con soporte CUDA.
#
# Se parte de la imagen oficial del proyecto ggml (ya compilada con CUDA)
# en lugar de compilar desde fuente: el build de llama.cpp + CUDA tarda
# >20 min y la imagen oficial se actualiza casi a diario.
#
# Solo añadimos `curl` (la imagen runtime no lo trae) para poder usar el
# HEALTHCHECK contra /health.
FROM ghcr.io/ggml-org/llama.cpp:server-cuda

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

# ENTRYPOINT heredado: /app/llama-server
# Los argumentos (modelo, contexto, etc.) los define docker-compose.llama.yml
