---
id: F008
query_id: Q010
type: read
intent: "How navauth declares and orders migration files (catalog discovery, naming, checksum, templating)."
executed_at: 2026-11-12T20:41:18Z
duration_ms: 300
parent_id: null
depth: 1
merged_from: [FC-008]
---

# F008 — navauth catalog: filesystem-registered sets, NNN_ names, sha256 of raw bytes, {schema} templating

## Summary

A migration is registered by dropping a file named `^\d{3}_[a-z0-9_]+\.sql$` into `sql/<set>/`; `MIGRATION_SETS` is a
hard-coded ordered tuple, unknown set directories and duplicate numeric prefixes raise `MigrationCatalogError`. Order is
set order, then filename. Checksum = sha256 of the raw file bytes (so any edit flips the file to CHANGED).
`render_sql()` substitutes `{schema}` and `{users_table}` from config, so the schema name is not hard-coded in SQL.

## Citations

- path: `../navigator-auth/navigator_auth/migrations/catalog.py`
  lines: 19-21
  symbol: `MIGRATION_SETS`
  excerpt: |
    SQL_ROOT: Path = Path(__file__).parent / "sql"
    MIGRATION_SETS: tuple[str, ...] = ("vault", "identity", "passkey", "mfa", "oauth2")
    FILENAME_PATTERN: re.Pattern[str] = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")

- path: `../navigator-auth/navigator_auth/migrations/catalog.py`
  lines: 28-43
  symbol: `MigrationFile`
  excerpt: |
    class MigrationFile(BaseModel):
        model_config = ConfigDict(frozen=True)
        migration_set: str
        filename: str
        path: Path
        checksum: str

- path: `../navigator-auth/navigator_auth/migrations/catalog.py`
  lines: 62-113
  symbol: `discover`
  excerpt: |
    def discover(sets: Iterable[str] | None = None) -> tuple[MigrationFile, ...]:
        ...
            if prefix in prefixes:
                raise MigrationCatalogError(f"Duplicate migration prefix in {migration_set!r}: {prefix}")
            files.append(MigrationFile(..., checksum=hashlib.sha256(path.read_bytes()).hexdigest()))

- path: `../navigator-auth/navigator_auth/migrations/catalog.py`
  lines: 116-118
  symbol: `render_sql`
  excerpt: |
    def render_sql(sql: str) -> str:
        """Replace ``{schema}`` and ``{users_table}``; other text is returned unchanged."""
        return sql.replace("{schema}", AUTH_DB_SCHEMA).replace("{users_table}", AUTH_USERS_TABLE)

## Notes

Path-based (`Path(__file__).parent`) — fine for a wheel-installed package. For parrot the equivalent placeholders
would be PARROT_SCHEMA / PARROT_BOTS_TABLE (F014), since ai_bots' table name is configurable.
Sets map naturally to parrot distributions/subsystems (e.g. `bots`, `studio`, `formdesigner`), but a hard-coded tuple
cannot see sets contributed by satellite packages — parrot would need entry-point or namespace discovery.
