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

# start-period generoso: /health devuelve 503 durante TODA la carga del
# modelo, y un MoE de 22 GB (Qwen3.6-35B-A3B Q4_K_M) tarda varios minutos
# en cargar desde cache de disco. Con los 120s originales el contenedor se
# marcaba `unhealthy` mientras cargaba correctamente.
# docker-compose.llama.yml sobreescribe este valor vía LLAMA_HEALTH_START;
# súbelo a 30m la primera vez que descargues un modelo grande con -hf.
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=5 \
    CMD curl -fsS http://localhost:8080/health || exit 1

# ENTRYPOINT heredado: /app/llama-server
# Los argumentos (modelo, contexto, etc.) los define docker-compose.llama.yml
