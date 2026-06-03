"""THROWAWAY: Ibis connection spike for FEAT-219 Module 2.

Decision gate: can TableSource._get_connection_args() map cleanly onto
ibis.postgres.connect() / ibis.bigquery.connect() without a translation shim?

Run: python -m parrot.tools.dataset_manager.spatial._ibis_probe
(requires ibis-framework[postgres,bigquery] to be installed first)

OUTCOME: NO-GO — see TASK-1437 Completion Note.

Mapping analysis (code inspection, NOT runtime execution — ibis not installed):
---------------------------------------------------------------------------

pg credentials dict (from _resolve_credentials / _get_connection_args):
    {'host': ..., 'port': ..., 'database': ..., 'user': ..., 'password': ...}

ibis.postgres.connect() signature (ibis >= 9):
    ibis.postgres.connect(host=, port=, database=, user=, password=)
    -> DIRECT MATCH: no shim needed for pg.

bigquery credentials dict:
    {'credentials': Path('/path/to/service_account.json'), 'project_id': ...}

ibis.bigquery.connect() signature:
    ibis.bigquery.connect(project_id=, credentials=<google.oauth2.Credentials | None>)
    -> credentials key matches, BUT ibis expects a google.oauth2.Credentials object.
       navconfig stores a Path. Conversion requires:
           creds = google.oauth2.service_account.Credentials.from_service_account_file(path)
       This is a one-liner shim, but it introduces an implicit google-auth dependency and
       diverges from the asyncdb pattern where AsyncDB handles auth internally.

Also: DSN form (when _get_connection_args returns (None, dsn)):
    ibis.postgres.connect() accepts a connection_string kwarg in some versions, but
    navconfig DSNs are asyncpg-format (asyncpg://user:pass@host/db) while ibis expects
    a psycopg-format DSN (host=... port=... dbname=...) or URL (postgresql://...).
    This is a non-trivial translation gap.

Decision: NO-GO
Rationale:
  - ibis-framework is not yet a project dependency; adding it introduces risk.
  - DSN translation for pg (asyncpg → psycopg format) is non-trivial.
  - BigQuery credentials require an extra shim (Path → google.oauth2.Credentials).
  - The fallback (~2 hand-written SQL dialect templates) is pre-approved (spec §8,
    brainstorm Option C) and keeps the SpatialCompiler free of a new heavy dependency.
  - compile() stays pure (I/O-free, syrupy-snapshotable) either way.
  - TASK-1438 will use hand-written ST_DWITHIN dialect templates.

This file may be deleted before or after TASK-1438 — it exists only to document
the decision for TASK-1438 to inherit.
"""

# This probe is intentionally NOT executed (ibis not installed).
# The decision is documented above from code inspection alone.

OUTCOME = "NO-GO"
"""str: The spike outcome.  TASK-1438 uses hand-written dialect templates."""

PG_MAPPING = {
    "host": "host",           # direct match
    "port": "port",           # direct match
    "database": "database",   # direct match
    "user": "user",           # direct match
    "password": "password",   # direct match
    "dsn_gap": (
        "asyncpg DSN format ≠ psycopg/ibis DSN format; requires translation"
    ),
}
"""dict: navconfig pg key → ibis pg key mapping (all direct, but DSN needs conversion)."""

BIGQUERY_MAPPING = {
    "project_id": "project_id",   # direct match
    "credentials": (
        "navconfig: Path  →  ibis: google.oauth2.service_account.Credentials  "
        "(requires from_service_account_file() shim + google-auth dependency)"
    ),
}
"""dict: navconfig bigquery key → ibis bigquery key mapping."""
