# syntax=docker/dockerfile:1.7
###############################################################################
# PostgreSQL 19 (Debian trixie) for AI-Parrot local development.
#
# Based on navigator-dataintegrator/bin/docker/postgres, moved from Alpine +
# source builds to the official Debian image + PGDG packages (the official
# image already ships the apt.postgresql.org repository):
#   - PostGIS 3 (raster, topology, tiger geocoder, address standardizer)
#   - pgvector               -> parrot.stores.pgvector (vector store)
#   - pg_cron, pg_partman    -> scheduled jobs / partitioned tables
#   - pg_similarity          -> compiled from source (not packaged for PG 19)
#   - contrib: earthdistance, cube, tsm_system_rows, hstore, btree_gin/gist...
#
# PL/Rust (tcdi/plrust) is NOT included: its latest release (v1.2.8) only
# supports PostgreSQL 13-16.
###############################################################################
ARG PG_MAJOR=19
ARG PG_IMAGE_TAG=19.0-trixie

###############################################################################
# Builder: pg_similarity
###############################################################################
FROM postgres:${PG_IMAGE_TAG} AS builder
ARG PG_MAJOR
# Pinned commit of https://github.com/eulerto/pg_similarity (master, 2026-11-23)
ARG PG_SIMILARITY_REF=3a3ac5f5aaadce22d0dc303475f73ba90dfcd7a6

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl \
        "postgresql-server-dev-${PG_MAJOR}"; \
    mkdir -p /usr/src/pg_similarity; \
    curl -fsSL "https://github.com/eulerto/pg_similarity/archive/${PG_SIMILARITY_REF}.tar.gz" \
        | tar -xz -C /usr/src/pg_similarity --strip-components=1; \
    cd /usr/src/pg_similarity; \
    make USE_PGXS=1; \
    make USE_PGXS=1 install DESTDIR=/out

###############################################################################
# Runtime
###############################################################################
FROM postgres:${PG_IMAGE_TAG}
ARG PG_MAJOR

LABEL org.opencontainers.image.title="ai-parrot-postgres" \
      org.opencontainers.image.description="PostgreSQL ${PG_MAJOR} + PostGIS, pgvector, pg_cron, pg_partman, pg_similarity for AI-Parrot development" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "postgresql-${PG_MAJOR}-postgis-3" \
        "postgresql-${PG_MAJOR}-postgis-3-scripts" \
        "postgresql-${PG_MAJOR}-postgis-tiger-geocoder" \
        "postgresql-${PG_MAJOR}-pgvector" \
        "postgresql-${PG_MAJOR}-cron" \
        "postgresql-${PG_MAJOR}-partman"; \
    rm -rf /var/lib/apt/lists/*

# pg_similarity (.so, .control, .sql) built in the first stage.
COPY --from=builder /out/ /

RUN mkdir -p /var/log/postgresql && chown -R postgres:postgres /var/log/postgresql

COPY --chmod=0755 initdb/ /docker-entrypoint-initdb.d/
COPY --chmod=0755 update-extensions.sh /usr/local/bin/update-extensions.sh

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD pg_isready -U "${POSTGRES_USER:-postgres}" -h 127.0.0.1 || exit 1

CMD ["postgres", \
     "-c", "shared_preload_libraries=pg_cron,pg_partman_bgw", \
     "-c", "cron.database_name=postgres"]
