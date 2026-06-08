-- ClickHouse bootstrap for the OpenLIT observability stack.
-- Mounted into /docker-entrypoint-initdb.d/ so it runs on first container init.
--
-- OpenLIT runs its own table migrations against this database on startup, but
-- it does NOT create the database itself — it expects INIT_DB_DATABASE to
-- already exist. Without this, OpenLIT loops on "Database openlit does not exist".
CREATE DATABASE IF NOT EXISTS openlit;
