# QuerysourceToolkit

Tenant-scoped QuerySource tools for agents (`parrot_tools.querysource.QuerysourceToolkit`, tool prefix `qs`).
It replaces `QSourceTool` (FEAT-558, hard cut — see [Migrating from QSourceTool](#migrating-from-qsourcetool)
below) with a typed, tenant-aware surface over QuerySource query-slugs (`public.queries`) and MultiQuery
pipelines. All access is in-process, through the installed `querysource` package — there are no HTTP calls to
the QuerySource REST API.

## Configuration

| Argument | Default | Meaning |
|---|---|---|
| `programs` | `None` | allowlist of `program_slug` values; `None` = unrestricted |
| `allow_write` | `False` | enables `qs_save_multiquery` and destination (`Output`) steps |
| `allow_raw_sql` | `False` | inline `{"query": …}` pipeline nodes (ignored — always forbidden — when restricted) |
| `allow_external_sources` | `True` | `files` / `sources` sections |
| `include_sql` | `True` | `qs_describe_slug` returns the SQL / pipeline JSON |
| `max_rows` | `200` | row cap pushed into QuerySource as `querylimit` |
| `forced_conditions` | `{}` | conditions merged last on every execution (`permanent_filter` precedence) |
| `dsn` | querysource `asyncpg_url` | catalog connection used to read `public.queries` |
| `multiquery_timeout` | `600` | seconds `qs_run_multiquery` waits before raising a timeout error |

```python
from parrot_tools.querysource import QuerysourceToolkit

# Unrestricted, read-only (default)
toolkit = QuerysourceToolkit()

# Tenant-restricted to the "pokemon" program, allowed to persist pipelines it composes
toolkit = QuerysourceToolkit(programs=["pokemon"], allow_write=True)
```

## Tools

Generated tool names use the `qs` prefix (`tool_prefix="qs"`). Eight tools are always present; the ninth
(`qs_save_multiquery`) appears only when the toolkit is constructed with `allow_write=True`, and is marked
`requires_confirmation` (HITL) via `confirming_tools`.

- **`qs_get_dialect_reference`** — Returns the QuerySource conditions dialect: which keys are options, which
  become placeholders, which become WHERE filters, the WHERE value grammar with examples, and the
  `@variables` this deployment accepts as values (e.g. `@today`). Call this before building conditions.
- **`qs_list_slugs`** — Lists query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug
  or description. Optional `tenant` argument selects a QuerySource tenant store schema.
- **`qs_describe_slug`** — Explains a slug: placeholders and types, stored defaults,
  filtering/fields/ordering/grouping, provider, program, and — when the toolkit is configured with
  `include_sql` — the SQL or pipeline JSON. `dry_run=True` also returns the rendered query via `QS.dry_run()`
  (this performs provider setup, not a pure catalog read). Optional `tenant` argument selects a QuerySource tenant store schema.
- **`qs_execute_slug`** — Runs a query-slug. `placeholders` fill the slug's declared conditions (see
  `qs_describe_slug`); `filter` adds WHERE clauses in the dialect grammar (see `qs_get_dialect_reference`);
  `fields`, `ordering`, `grouping` override the stored projection; `limit` is capped at the toolkit's
  `max_rows`; `refresh` bypasses the QuerySource cache. Returns bounded rows plus
  `returned_rows`/`total_rows`/`truncated`. Optional `tenant` argument selects a QuerySource tenant store schema.
- **`qs_list_components`** — Lists MultiQuery pipeline components (Operators, Transformations, Sources,
  Destinations) with their JSON schema and a usage example — the same catalog as
  `GET /api/v3/qs/components`. Optional `category` filter.
- **`qs_validate_pipeline`** — Validates a MultiQuery pipeline without running it: structural rules (known
  step names, ≥1 source, Join/Merge arity) plus this toolkit's policy — every `queries[*]` slug must be one
  this instance may execute; raw SQL nodes, external sources and destination (write) steps are reported when
  the configuration forbids them.
- **`qs_run_multiquery`** — Runs a MultiQuery pipeline inline (`pipeline`, the JSON with
  queries/Join/Concat/…/Output) or a saved multi-query slug (`slug`). Every referenced slug must be
  executable by this toolkit; raw SQL nodes, external sources and destination steps follow the instance
  configuration (see `qs_validate_pipeline`). Results are bounded per frame.
- **`qs_build_linked_surface`** — (FEAT-598) Emits a linked A2UI surface for a query-slug: checks the slug
  (and `tenant`) against the allowlist, derives `params` from `qs_describe_slug`, builds `conditions` (forced
  keys become `locked`; `@variables` are rejected), **executes the slug once** to validate the component's
  axes/columns against the real columns, and embeds ≤ 500 rows only when `snapshot=True`. Returns
  `{a2ui_envelope, artifacts}`. See [A2UI linked surfaces](../outputs/a2ui-linked-surfaces.md).
- **`qs_save_multiquery`** *(only when `allow_write=True`)* — Persists a validated MultiQuery pipeline as a
  query-slug owned by `program` (forced to the single allowed program when this toolkit is tenant-restricted).
  Requires operator opt-in (`allow_write`) and user confirmation. Refuses to overwrite a slug owned by another
  program; set `overwrite=True` to update your own.

## Tenancy semantics

Tenancy is a static `program_slug` allowlist passed at construction time (`programs=[...]`), re-checked on
**every** call against `public.queries` — there is no positive authorization cache, so a `program_slug`
change takes effect immediately. `None` means unrestricted.

The `qs_list_slugs`, `qs_describe_slug`, `qs_execute_slug`, and `qs_build_linked_surface` tools accept an optional `tenant` argument for selecting a QuerySource tenant store schema. Omit it for public/legacy slugs. Routing, not security.

| Capability | Restricted (`programs=[...]`) | Unrestricted (`programs=None`) |
|---|---|---|
| Query-slug access | Only rows whose `program_slug` is in the allowlist; a foreign slug raises `TenantDeniedError` from `describe_slug`, `execute_slug`, `run_multiquery` and `save_multiquery` **before** any `QS`/`MultiQS` object is constructed | Any program |
| `list_slugs` | Filtered server-side to allowed programs | All programs (or one, via the `program` argument) |
| Inline raw SQL nodes (`{"query": …}` / `{"raw_query": …}`) | Always rejected, regardless of `allow_raw_sql` | Rejected unless `allow_raw_sql=True` |
| `files` / `sources` pipeline sections | Accepted (not program-scoped) unless `allow_external_sources=False` | Same — accepted unless `allow_external_sources=False` |
| Destination steps (`Output` writes, e.g. `tableOutput`, `dwh`, `s3`, `sharepoint`) | Rejected unless `allow_write=True` | Same — rejected unless `allow_write=True` |
| `save_multiquery` | Forces `program_slug` to the single allowed program (or the explicit `program` argument, if it is in the allowlist) | Requires an explicit `program` argument |

## Conditions dialect quick reference

`qs_get_dialect_reference` returns a `DialectReference` verified against querysource **4.5.11**. Summary:

**Option keys** — these become QuerySource options, not placeholders or WHERE filters: `fields`, `querylimit`
(alias `_limit`), `_offset` (`paged`/`page` for page-based pagination), `ordering` (alias `order_by`),
`grouping` (alias `group_by`), `filter` (alias `where_cond`), `refresh`, `filter_options`, `qry_options`,
`hierarchy`, `distinct`, `add_fields`, `tablename`, `schema`, `database`, `slug`, `conditions`.

**Placeholder rules:**
- A slug's stored `conditions` are default values for the placeholders in its SQL (e.g. `{firstdate}`);
  `cond_definition` declares their types.
- Merge order: stored defaults < your flat keys < your nested `conditions`. Your values win.
- Any key that is not an option key and not a declared placeholder becomes a WHERE filter — put ad-hoc column
  filters in `filter`, and only declared names in `placeholders`.
- Values starting with `@` call a deployment variable function (see `variables`), e.g. `@today`.

**WHERE grammar** (`filter` argument):
| Form | Meaning |
|---|---|
| `col: 'v'` | `col = 'v'` |
| `col: '!v'` or `'col!': 'v'` | `col != 'v'` |
| `col: ['a', 'b']` | `col IN ('a', 'b')`; `'col!': [...]` → `NOT IN` |
| `col: ['>=', 10]` | `col >= 10` (first item must be one of `operators_list_form`: `<`, `>`, `>=`, `<=`, `<>`, `!=`, `IS NOT`, `IS`) |
| `col: {'>': 10}` | `col > 10` (single key from `operators_dict_form`: `>=`, `<=`, `<>`, `!=`, `<`, `>`) |
| `col: 'BETWEEN 1 AND 5'` | `(col BETWEEN 1 AND 5)` — must not contain `;`, `--`, `/*`, `UNION`, `SELECT` |
| `col: 'null'` / `'!null'` | `IS NULL` / `IS NOT NULL` |
| `col: true` | `col = True` |

Keys must be identifier-safe (`[A-Za-z0-9_.]` after stripping suffix characters `|!~#@:`); the parser
silently drops unsafe keys/operators, so this toolkit rejects them up front instead (`InvalidConditionsError`).

**Example** (from `qs_get_dialect_reference`): filtering `epson_field_activity` by date range —
```json
{"slug": "epson_field_activity", "placeholders": {"firstdate": "2026-08-09", "lastdate": "2026-08-15"}}
```

## Migrating from QSourceTool

`QSourceTool` (deleted in FEAT-558) exposed a single free-form `conditions` dict with no grammar. Map its
usage to the new typed tools:

| `QSourceTool` (removed) | `QuerysourceToolkit` replacement |
|---|---|
| `query_slug` argument | `slug` argument (same value, e.g. `epson_field_activity`) on `qs_execute_slug` / `qs_describe_slug` |
| `conditions` dict — declared placeholders (e.g. `{"firstdate": ..., "lastdate": ...}`) | `qs_execute_slug(placeholders={...})` — validated against the slug's `cond_definition` first |
| `conditions` dict — ad-hoc WHERE clauses (fields not declared by the slug) | `qs_execute_slug(filter={...})` in the dialect grammar (see above); validated up front instead of being silently dropped by the SQL parser |
| `conditions["fields"]` / `["group_by"]` / `["order_by"]` | `fields=[...]`, `grouping=[...]`, `ordering=[...]` typed arguments |
| `conditions["querylimit"]` / free row limit | `limit=...`, capped by the toolkit's `max_rows` — never unbounded |
| No tenancy — any slug was accessible | `programs=[...]` allowlist enforced on every call, before any query executes |
| No discovery — the LLM had to already know a slug existed | `qs_list_slugs` / `qs_describe_slug` — browse and inspect what is available |
| No MultiQuery support | `qs_list_components`, `qs_validate_pipeline`, `qs_run_multiquery`, `qs_save_multiquery` |
| Raw SQL was never exposed either | Still never exposed as a tool argument; `allow_raw_sql` only affects inline MultiQuery pipeline nodes for **unrestricted** instances, and is always forbidden when tenant-restricted |
