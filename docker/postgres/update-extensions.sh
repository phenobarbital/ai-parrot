#!/bin/bash
# Upgrade every installed extension to the version shipped in the image.
# Run after rebuilding the image against an existing data volume:
#   docker exec -u postgres parrot-postgres update-extensions.sh [extra_db ...]
set -o errexit -o nounset -o pipefail

export PGUSER="${POSTGRES_USER:-postgres}"

for db in postgres "${PARROT_DB_NAME:-navigator}" "$@"; do
    echo "Updating extensions in '$db'"
    psql -v ON_ERROR_STOP=1 --dbname "$db" -Atc \
        "SELECT format('ALTER EXTENSION %I UPDATE;', extname) FROM pg_extension" \
        | psql -v ON_ERROR_STOP=1 --dbname "$db"
    # PostGIS sub-extensions (raster/topology/tiger) follow postgis_extensions_upgrade().
    psql --dbname "$db" -Atc \
        "SELECT postgis_extensions_upgrade() WHERE EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')" \
        || true
done
