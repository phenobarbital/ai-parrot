# Schema Plane — Operator Guide (FEAT-600)

The schema plane is a durable, shared overlay of SQL data models on the LLM wiki. Tables live in
a separate database (`.parrot/schema/schema.db`) as read-only pages, enriched with annotations,
join paths, and freshness metadata. Before writing SQL or a `DatabaseToolkit` subclass, operators
and agents consult the schema plane instead of re-discovering models at runtime.

> **Complete guides**: `docs/guides/schema-plane-setup.md`, `docs/runbooks/schema-plane-troubleshooting.md`.
> This guide covers CLI operations and the id grammar. For MCP/agent integration, see the
> embedded tool help (`wiki_schema_lookup --help`, etc.).

---

## 1. Why the Schema Plane

Every SQL agent re-introspects the same tables:
- **Expensive**: BigQuery `INFORMATION_SCHEMA` reads are billed and rate-limited.
- **Stale**: Introspection is cached per process (TTL 30 min) or per Redis instance (TTL 1 h).
- **Isolated**: Coding agents (`sdd-coder`) have no database connection and no schema pages to read.
- **Unlinked**: "What tables join to `epson.sales`?" cannot be asked — foreign keys are stored as a
  list inside one table row.
- **Meaningless**: `information_schema` has no column for domain knowledge (`store_id` ← T-ROC store
  ID) or deprecation notices. `wiki_remember` exists but has no table page to annotate.

The schema plane solves this: a shared, durable cache of table definitions enriched with relations,
freshness hints, and annotations.

---

## 2. Ids & Grammar

The schema plane uses a **kind-first, origin-second** naming convention:

```
source:<origin>              — e.g., source:bigquery
schema:<origin>/<schema>     — e.g., schema:bigquery/epson
table:<origin>/<schema>.<table>   — e.g., table:bigquery/epson.sales
```

An **origin** is a declared source alias that defaults to the SQL dialect (Postgres, BigQuery,
MySQL, etc.). If you have two Postgres databases, the second must have its own origin name:

```bash
# First Postgres database: origin is "postgres" (the dialect)
wikitoolkit schema add-source postgres "postgresql://prod.internal/main"

# Second Postgres database: must have a custom origin name
wikitoolkit schema add-source datalake-prod "postgresql://datalake.internal/analytics" --origin datalake
```

**Normalization**: All lookups and tools accept the provider's native reference format and normalize
it. Provide any of these; all resolve to `table:bigquery/epson.sales`:

```
bigquery:epson.sales              (provider:schema.table)
epson.sales                        (schema.table, assumes origin "bigquery" is the only active source)
table:bigquery/epson.sales         (explicit page id)
```

---

## 3. Declare a Source

Every source that gets ingested (either live or from DDL) must be declared:

```bash
wikitoolkit schema add-source <origin> <dsn_or_connection_string> [OPTIONS]
```

**Options:**
- `--dialect <name>` — SQL dialect (`postgres`, `bigquery`, `mysql`, `duckdb`, …).
  Defaults to the origin if the origin is a valid dialect name.
- `--description <text>` — Human-readable label (e.g., "Production Postgres, US region").
- `--origin <name>` — Custom alias (only needed if dialect is used by multiple sources).

**Example:**

```bash
wikitoolkit schema add-source postgres "postgresql://prod.internal:5432/main" \
  --dialect postgres \
  --description "Production database, US"
```

Sources are stored as `source:<origin>` pages in the schema plane. The DSN is **never** stored
directly; only the environment variable **name** is kept (FEAT-600 Goal G7):

```bash
# Pass the DSN via an environment variable
export DATABASE_URL="postgresql://prod.internal:5432/main"
wikitoolkit schema add-source postgres ENV:DATABASE_URL
```

---

## 4. Sync — Live Introspection

Live introspection reads the database using the SQL dialect hooks (the same machinery that powers
`SQLToolkit.describe_table`):

```bash
wikitoolkit schema sync <origin> [OPTIONS]
```

**Options:**
- `--changed` — Only re-introspect tables where the stored DDL hash has drifted (e.g., after a
  migration). Saves time on large databases.
- `--include-views` — Include views. Default is tables only.
- `--sample-data` — Fetch row counts and column statistics. Off by default (FEAT-600 Goal G7).
- `--force` — Re-introspect every table, even if unchanged.

**What happens:**
1. Connect to the source using the DSN from the `source:` page.
2. Call `DESCRIBE <table>` (or the dialect's equivalent) for every table in every schema.
3. Write (or update) a `table:<origin>/<schema>.<table>` page per table with:
   - Canonical `CREATE TABLE` (rendered via sqlglot)
   - Column list (name, type, constraints)
   - Foreign keys and join targets
   - Metadata: row count, completeness (full/partial/ddl-only), when last introspected
4. Preserve all existing annotations (`wiki_remember` links to this table).

**Example:**

```bash
# Full sync of Postgres
wikitoolkit schema sync postgres

# Incremental sync — only tables with schema drift
wikitoolkit schema sync postgres --changed

# Sync live but also fetch row counts (slower)
wikitoolkit schema sync postgres --sample-data
```

---

## 5. Offline DDL Ingest

For sources without a live connection (e.g., archived databases, SQL files under version control),
parse and ingest DDL directly:

```bash
wikitoolkit schema ingest-ddl <paths> [OPTIONS]
```

**Options:**
- `--origin <name>` — Source alias. Required.
- `--dialect <name>` — SQL dialect. Required.
- `--upsert-only` — Do not create new tables; only update existing ones. Use this to merge DDL
  into a schema already populated by live sync.

**What happens:**
1. Parse each `.sql` file (or directory of `.sql` files) with sqlglot.
2. Extract every `CREATE TABLE` / `CREATE VIEW` statement.
3. Write each as a `table:<origin>/<schema>.<table>` page with `source="ddl"`.
4. Record `defined_in` edges linking each table to the `.sql` file that defined it.

**Merge rule** (FEAT-600 Goal G3): If a table already exists (from live sync), the live version
wins. DDL only creates new pages and always contributes `defined_in` edges.

**Example:**

```bash
# Ingest all DDL from a repo
wikitoolkit schema ingest-ddl migrations/ \
  --origin bigquery \
  --dialect bigquery

# Merge DDL into an existing source (only update, no new tables)
wikitoolkit schema ingest-ddl archive/schemas.sql \
  --origin postgres \
  --dialect postgres \
  --upsert-only
```

---

## 6. Lookup & Join Paths

### CLI Lookup

```bash
wikitoolkit schema lookup <table_id>
```

Returns the stored page: DDL, columns, foreign keys, row count, age, and staleness estimate.

```bash
wikitoolkit schema lookup "table:bigquery/epson.sales"
wikitoolkit schema lookup "bigquery:epson.sales"      # normalized
wikitoolkit schema lookup epson.sales                 # if origin is unambiguous
```

### MCP Tools (Agents & Claude Code)

Four tools are exposed via the MCP server:

- **`wiki_schema_lookup(origin_schema_table)`** — Return the DDL, columns, and metadata for a table.
- **`wiki_schema_search(query)`** — Full-text search over table and column names, descriptions, and
  annotations. Useful for "find all tables with 'customer'" without knowing the origin.
- **`wiki_schema_neighbors(table_id)`** — Discover join paths: tables that reference this table, and
  tables this table references. Essential for text-to-SQL query planning.
- **`wiki_schema_sources()`** — List all declared sources, their dialects, and status.

### Join Paths

```bash
wikitoolkit schema lookup "table:bigquery/epson.sales" --neighbors
```

Shows all tables joined to `epson.sales` via foreign keys:
- **Incoming** (tables that reference `sales`): `store`, `region`, `salesperson`
- **Outgoing** (tables that `sales` references): `customer`, `product`

This is the single most useful piece of information for text-to-SQL agents.

---

## 7. Annotate Tables

Use `wiki_remember` to attach domain knowledge to a table page:

```bash
wikitoolkit remember "store_id here is the T-ROC store identifier" \
  --link "table:postgres/datalake.stores" \
  --rel "contains_meaning"
```

Annotations survive schema syncs (FEAT-600 Goal G6): `schema sync` never rewrites existing
`wiki_remember` links.

---

## 8. Drift (`schema diff`)

Compare the stored schema against the live database:

```bash
wikitoolkit schema diff <origin> [OPTIONS]
```

**What it reports:**
- **New tables**: tables in the database not in the schema plane.
- **Dropped tables**: tables in the schema plane not in the database.
- **Columns added/removed**: per table.
- **Type changes**: column type mismatches.
- **Constraint changes**: PRIMARY KEY, FOREIGN KEY, NOT NULL differences.

```bash
wikitoolkit schema diff postgres
wikitoolkit schema diff postgres --json   # machine-readable output
```

Use this after a migration to understand what changed before deciding to re-sync.

---

## 9. Freshness & Repair

### Staleness

The read path never introspects; instead, it returns age and a staleness estimate.

```python
lookup_result = wiki_schema_lookup("table:postgres/public.users")
# Returns:
# {
#   "age_days": 3,
#   "stale": False,
#   "stale_after_days": 7,
#   "ddl": "CREATE TABLE ...",
#   ...
# }
```

A table is considered **stale** when `age_days > stale_after_days`.

### Repair Triggers

1. **Manual**: `wikitoolkit schema sync <origin> --changed` (run in a cron job or post-merge hook).
2. **Error-driven**: When `SQLToolkit.execute_query` hits a schema error (e.g., "column does not exist"),
   it re-runs introspection for the affected table and write-through upserts the schema plane
   (non-blocking; uses a lock when multiple processes race).

---

## 10. Security (FEAT-600 Goal G7)

- **No credentials on pages**: Sources store only the **environment variable name**, not the DSN itself.
  ```bash
  # Correct: source page contains "ENV:DATABASE_URL"
  export DATABASE_URL="postgresql://user:pass@host/db"
  wikitoolkit schema add-source postgres ENV:DATABASE_URL
  ```

- **Sample data is off by default**: Row counts and column statistics are only fetched with
  `--sample-data`. Avoids sending large result sets over the wire.

- **Write verbs refuse to run in linked worktrees**: `schema add-source`, `schema sync`, `schema
  ingest-ddl` refuse to execute in a git-linked worktree (e.g., inside `/sdd-done`). This prevents
  accidental shared-database mutations.

---

## 11. Runtime: DatabaseAgent with Schema Plane

A `DatabaseAgent` can be configured to warm its table cache from the schema plane:

```python
from parrot.bots import DatabaseAgent

agent = DatabaseAgent(
    schema_plane=SchemaPlaneConfig(
        root=".parrot",
        origin="postgres"  # which source to warm from
    )
)

# The agent now:
# 1. Checks the schema plane first (read-only).
# 2. Falls back to Redis cache (if configured).
# 3. Falls back to live introspection only if neither has a hit.
```

Behavior is **byte-identical** when no plane is configured (FEAT-600 Goal G5).

---

## 12. The Six Verbs (Quick Reference)

| Verb | Purpose |
|---|---|
| `wikitoolkit schema sources` | List all declared sources and their status. |
| `wikitoolkit schema add-source` | Declare a new SQL source (live or DDL archive). |
| `wikitoolkit schema sync` | Live introspection: read the database and populate the plane. |
| `wikitoolkit schema ingest-ddl` | Parse SQL files and populate the plane offline. |
| `wikitoolkit schema diff` | Compare stored schema against live database; report drift. |
| `wikitoolkit schema lookup` | Query a table page: DDL, columns, relations, freshness. |

---

## Troubleshooting

**"Could not determine the origin"** → Multiple sources declared; use the full id format:
`table:bigquery/epson.sales` instead of `epson.sales`.

**"Table not found in schema plane"** → Run `wikitoolkit schema sync <origin>` to populate it
first, or use `wikitoolkit schema ingest-ddl` if you have DDL files.

**"Stale schema (3 days old)"** → Run `wikitoolkit schema sync <origin> --changed` to refresh only
tables with schema drift, or `--force` to re-introspect everything.

**Annotations disappeared after sync** → This should not happen. Annotations are preserved by
design (FEAT-600 Goal G6). If they vanish, open an issue.
