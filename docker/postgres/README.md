# PostgreSQL local para AI-Parrot

PostgreSQL **19** (imagen oficial Debian trixie) con:

| Extensión | Origen | Uso en AI-Parrot |
|---|---|---|
| `vector` (pgvector) | PGDG | `parrot.stores.pgvector` |
| PostGIS 3 (`postgis`, `postgis_raster`, `postgis_topology`, `postgis_tiger_geocoder`, `address_standardizer`) | PGDG | datos geoespaciales |
| `pg_cron` | PGDG | jobs programados (vive en la BD `postgres`) |
| `pg_partman` (esquema `partman`) | PGDG | tablas particionadas |
| `pg_similarity` | compilado desde fuente (commit fijado) | funciones de similitud de texto |
| contrib: `btree_gin`, `btree_gist`, `hstore`, `tablefunc`, `uuid-ossp`, `pg_trgm`, `fuzzystrmatch`, `tsm_system_rows`, `cube`, `earthdistance` | PostgreSQL | — |

Derivado de `navigator-dataintegrator/bin/docker/postgres`, pero pasando de
Alpine + compilación desde fuente a paquetes PGDG (la imagen oficial ya trae el
repositorio `apt.postgresql.org`), que tienen builds para PG 19.

**PL/Rust no está incluido**: la última versión de `tcdi/plrust` (v1.2.8)
sólo soporta PostgreSQL 13–16. (El Dockerfile original instalaba la toolchain
de Rust pero nunca compilaba plrust.)

## Arranque

```bash
cd docker/postgres
docker compose up -d --build
docker compose ps
```

Variables (todas opcionales):

| Variable | Default | Descripción |
|---|---|---|
| `PG_PORT` | `5432` | puerto publicado en `127.0.0.1` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | `postgres` / `postgres` | superusuario |
| `DBUSER` / `DBPWD` / `DBNAME` | `navigator` / `navigator` / `navigator` | rol y BD de la aplicación |

`DBUSER`/`DBPWD`/`DBNAME` son las mismas variables que lee
`packages/ai-parrot/src/parrot/conf.py`, así que exportando esos valores (y
`DBHOST=localhost`, `DBPORT=5432`) AI-Parrot conecta sin más configuración.

El script `initdb/01-parrot-db.sh` sólo se ejecuta la primera vez, con el
volumen `parrot-postgres-data` vacío.

## Comprobar

```bash
docker exec parrot-postgres psql -U postgres -d navigator -c '\dx'
```

## Actualizar extensiones tras reconstruir la imagen

```bash
docker compose up -d --build
docker exec -u postgres parrot-postgres update-extensions.sh
```

Cambiar de versión mayor de PostgreSQL (p. ej. 18 → 19) requiere
`pg_upgrade` o dump/restore: el volumen de datos no es compatible entre
versiones mayores.

## Detener

```bash
docker compose down          # conserva los datos
docker compose down -v       # borra el volumen
```
