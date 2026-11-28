#!/bin/bash
# Creates the AI-Parrot application role + database and loads the extensions.
# Runs once, on the first start against an empty data volume.
set -o errexit -o nounset -o pipefail

: "${PARROT_DB_USER:?PARROT_DB_USER must be set}"
: "${PARROT_DB_PASSWORD:?PARROT_DB_PASSWORD must be set}"
: "${PARROT_DB_NAME:?PARROT_DB_NAME must be set}"

psql=(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --no-password)

echo "Creating role '$PARROT_DB_USER' and database '$PARROT_DB_NAME'"
"${psql[@]}" --dbname postgres \
    -v user="$PARROT_DB_USER" -v password="$PARROT_DB_PASSWORD" -v dbname="$PARROT_DB_NAME" <<-'EOSQL'
	SELECT format('CREATE ROLE %I WITH LOGIN SUPERUSER CREATEDB CREATEROLE PASSWORD %L', :'user', :'password')
	WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec
	SELECT format('CREATE DATABASE %I WITH OWNER = %I ENCODING = ''UTF8'' TEMPLATE = template0 LC_COLLATE = ''en_US.UTF-8'' LC_CTYPE = ''en_US.UTF-8''', :'dbname', :'user')
	WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname') \gexec
EOSQL

echo "Loading extensions into '$PARROT_DB_NAME'"
"${psql[@]}" --dbname "$PARROT_DB_NAME" <<-'EOSQL'
	CREATE EXTENSION IF NOT EXISTS btree_gin;
	CREATE EXTENSION IF NOT EXISTS btree_gist;
	CREATE EXTENSION IF NOT EXISTS hstore;
	CREATE EXTENSION IF NOT EXISTS tablefunc;
	CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
	CREATE EXTENSION IF NOT EXISTS pg_trgm;
	CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
	CREATE EXTENSION IF NOT EXISTS tsm_system_rows;
	CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;
	CREATE EXTENSION IF NOT EXISTS vector;
	CREATE EXTENSION IF NOT EXISTS postgis;
	CREATE EXTENSION IF NOT EXISTS postgis_raster;
	CREATE EXTENSION IF NOT EXISTS postgis_topology;
	CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder CASCADE;
	CREATE EXTENSION IF NOT EXISTS address_standardizer;
	CREATE EXTENSION IF NOT EXISTS pg_similarity;
	CREATE SCHEMA IF NOT EXISTS partman;
	CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;
EOSQL

# pg_cron can only live in cron.database_name (the "postgres" maintenance DB);
# schedule jobs for other databases with cron.schedule_in_database().
echo "Loading pg_cron into 'postgres'"
"${psql[@]}" --dbname postgres -c "CREATE EXTENSION IF NOT EXISTS pg_cron;"
