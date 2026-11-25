# Redis local para AI-Parrot

Este stack levanta Redis 8 en `127.0.0.1:6379`, que coincide con los valores
por defecto de AI-Parrot (`packages/ai-parrot/src/parrot/conf.py`):

```text
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=1            # store por defecto (crews, checkpoints, credenciales…)
CACHE_HOST=localhost
CACHE_PORT=6379
CACHEDB=2             # caché
REDIS_HISTORY_DB=3    # historial de conversación
REDIS_DATASET_DB=3    # datasets
                      # DB 4: servicios (REDIS_SERVICES_URL)
```

## Por qué Redis 8

AI-Parrot necesita:

- **Redis ≥ 6.2** — usa `GETDEL` (channel links, deep links A2UI, passkeys).
- **Streams y Pub/Sub** — jobs autónomos, transporte de salidas estructuradas, A2A.
- **RediSearch** (`FT.CREATE` / `FT.SEARCH` con campos `VECTOR`) — la memoria
  episódica vectorial (`parrot.memory.episodic.backends.redis_vector`).

Redis 8 Open Source trae el Query Engine (RediSearch), JSON, TimeSeries y
Bloom integrados, así que no hace falta `redis-stack`.

## Arranque

Desde este directorio:

```bash
docker compose up -d --build
docker compose ps
```

Comprobar que el motor de búsqueda está cargado:

```bash
docker exec parrot-redis redis-cli MODULE LIST   # debe aparecer "search"
```

## Configuración

`redis.conf` activa persistencia AOF + RDB y `maxmemory-policy noeviction`:
AI-Parrot guarda estado durable en Redis (checkpoints de flows, definiciones y
resultados de crews, credenciales OAuth/BYOK) y esas claves no deben
desalojarse. Las entradas de caché ya llevan su propio TTL.

Los datos se guardan en el volumen Docker `parrot-redis-data`. Para detener el
servicio conservando los datos:

```bash
docker compose down
```

## Activar contraseña

```bash
export REDIS_PASSWORD=change-me
docker compose up -d --build
```

Los `*_URL` que AI-Parrot construye a partir de `REDIS_HOST`/`REDIS_PORT` no
incluyen contraseña, así que en ese caso define las URL completas:

```bash
export REDIS_URL=redis://:change-me@localhost:6379/1
export REDIS_HISTORY_URL=redis://:change-me@localhost:6379/3
export CREW_RESULT_STORAGE_REDIS_URL=redis://:change-me@localhost:6379/1
```
