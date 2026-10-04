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
MySQL, etc.) when no alias is given. If you have two Postgres databases, the second must have
its own alias:

```bash
# First Postgres database: alias defaults to the dialect ("postgres")
wikitoolkit schema add-source --dialect postgres --dsn-env DATABASE_URL

# Second Postgres database: pass an explicit alias
wikitoolkit schema add-source datalake-prod --dialect postgres --dsn-env DATALAKE_URL
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
wikitoolkit schema add-source [ALIAS] --dialect <name> --dsn-env <ENV_VAR_NAME> [OPTIONS]
```

**Options:**
- `--dialect <name>` — SQL dialect (`postgres`, `bigquery`, `mysql`, `duckdb`, …). Required.
- `--dsn-env <name>` — Environment variable **name** holding the DSN (never the value). Required.
- `--schemas <csv>` — Comma-separated allowed schemas. Defaults to `public`.
- `--tables <csv>` — Comma-separated `schema.table` allowlist. Optional.

`ALIAS` is an optional positional argument; when omitted it defaults to `--dialect`'s value.

**Example:**

```bash
export DATABASE_URL="postgresql://prod.internal:5432/main"
wikitoolkit schema add-source --dialect postgres --dsn-env DATABASE_URL --schemas public,analytics
```

Sources are stored as `source:<origin>` pages in the schema plane. The DSN is **never** stored
directly; only the environment variable **name** is kept (FEAT-600 Goal G7).

---

## 4. Sync — Live Introspection

Live introspection reads the database using the SQL dialect hooks (the same machinery that powers
`SQLToolkit.describe_table`):

```bash
wikitoolkit schema sync <origin> [OPTIONS]
```

**Options:**
- `--tables <csv>` — Comma-separated `schema.table` subset to sync (defaults to the source's
  declared `tables` allowlist, or every table discovered in the allowed schemas).
- `--changed` — Only re-introspect tables where the stored content hash has drifted (e.g., after
  a migration). Saves time on large databases.
- `--json` — Machine-readable report output.

Row-level sample data is controlled per source via the `include_samples` allowlist in
`.parrot/wiki.json` (`schema.sources.<alias>.include_samples`), not a CLI flag — empty (off) by
default (FEAT-600 Goal G7).

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

# Sync an explicit table subset
wikitoolkit schema sync postgres --tables public.orders,public.customers
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
- `--changed` — With no `<paths>` given, ingest only the `.sql` files that changed in the most
  recent commit (used by the post-merge hook). Ignored when explicit paths are passed.
- `--json` — Machine-readable report output.
- `--quiet` — Suppress the summary line (used by the git hook, which redirects output).

**What happens:**
1. Parse each `.sql` file (or every `.sql` file under a given directory, recursively) with
   sqlglot, isolating parse errors per statement so one bad statement never aborts the whole file.
2. Extract every `CREATE TABLE` statement.
3. Write each as a `table:<origin>/<schema>.<table>` page with `source="ddl"` — unless a live
   page already exists for that table, in which case only a `defined_in` edge is added (see the
   merge rule below).
4. Record `defined_in` edges linking each table to the `.sql` file that defined it.

**Merge rule** (FEAT-600 Goal G3): If a table already exists (from live sync), the live version
wins. DDL only creates new pages and always contributes `defined_in` edges.

**Example:**

```bash
# Ingest all DDL from a repo
wikitoolkit schema ingest-ddl migrations/ --origin bigquery --dialect bigquery

# Ingest a single archived schema file
wikitoolkit schema ingest-ddl archive/schemas.sql --origin postgres --dialect postgres
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

There is no CLI `neighbors` verb — join-path traversal is exposed as the MCP tool
`wiki_schema_neighbors(table_id, depth=1)` (see MCP Tools above), used by agents when planning a
text-to-SQL join:

```python
hops = await wiki_schema_neighbors("table:bigquery/epson.sales", depth=1)
```

Each hop reports the neighboring `concept_id`, the join direction, and the FK column pairs —
covering both tables that reference `sales` (incoming) and tables `sales` itself references
(outgoing). This is the single most useful piece of information for text-to-SQL agents.

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
wikitoolkit schema diff <origin> [--ledger]
```

**Options:**
- `--ledger` — File each divergence as a `tech_debt` SDD ledger issue (refuses to run in a
  linked worktree, like the other write verbs).

**What it reports:** per-table, per-field divergences between the live and DDL-derived values
already stored in the plane (columns, types, constraints — whatever the two sources disagree on).

```bash
wikitoolkit schema diff postgres
wikitoolkit schema diff postgres --ledger   # also files each divergence to the SDD ledger
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
  export DATABASE_URL="postgresql://user:pass@host/db"
  wikitoolkit schema add-source --dialect postgres --dsn-env DATABASE_URL
  # the source page stores dsn_env="DATABASE_URL" — never the resolved value
  ```

- **Sample data is off by default**: Row counts and column statistics are only fetched for tables
  listed in a source's `include_samples` allowlist (`.parrot/wiki.json`); empty by default.
  Avoids sending large result sets over the wire.

- **Write verbs refuse to run in linked worktrees**: `schema add-source`, `schema sync`, `schema
  ingest-ddl` refuse to execute in a git-linked worktree (e.g., inside `/sdd-done`). This prevents
  accidental shared-database mutations.

---

## 11. Runtime: DatabaseAgent with Schema Plane

A `DatabaseAgent` can be configured to warm its table cache from the schema plane by passing a
plane directory (or an already-open `SchemaPlaneService`):

```python
from parrot.bots.database.agent import DatabaseAgent

agent = DatabaseAgent(
    ...,
    schema_plane=".parrot/schema",   # str/Path -> opened via SchemaPlaneService.from_dir(read_only=False)
)

# Each toolkit's CachePartition then gets `plane`, `plane_write=True`, and `origin` set from the
# toolkit's own `origin` (defaults to its `database_type`).
```

`CachePartition.get()`'s resolution order is **LRU → schema cache → Redis → schema plane →
vector store** — the plane is a durable, never-introspecting tier that sits *after* Redis, not
before it.

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
tables with schema drift, or `wikitoolkit schema sync <origin>` (no flags) to re-introspect
everything.

**Annotations disappeared after sync** → This should not happen. Annotations are preserved by
design (FEAT-600 Goal G6). If they vanish, open an issue.
