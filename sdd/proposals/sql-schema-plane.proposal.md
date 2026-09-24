---
id: FEAT-600
title: SQL Schema Plane — data-model knowledge (sources/schemas/tables) as a wikitoolkit overlay plane
slug: sql-schema-plane
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-24
  summary_oneline: Schema Plane — SQL data-model knowledge as a wikitoolkit overlay plane, ids origin:object (brainstorm Option B)
overall_confidence: medium
base_branch: dev
projects: [ai-parrot]
tags: [wiki, schema-plane, database-agent, sqlglot, mcp, dev-loop]
research_state: sdd/state/FEAT-600/
created: 2026-09-24
updated: 2026-09-24
---

# FEAT-600 — SQL Schema Plane

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/schema-plane.brainstorm.md` (Option B recommended)
> **Audit**: [`sdd/state/FEAT-600/`](../state/FEAT-600/)

---

## 0. Origin

The source is the brainstorm `sdd/proposals/schema-plane.brainstorm.md` (2026-09-24, Option B
recommended). Full copy at `sdd/state/FEAT-600/source.md`.

> Every agent that touches a relational source re-discovers the data model at run time.
> `SQLToolkit.describe_table` / `search_schema` go to `information_schema` … whenever the
> `CachePartition` misses, and the partition is a **TTL cache** … empty on every cold start.
> […] Coding agents have no data model at all. […] Relations are not a graph. […] No place
> for meaning. […] **Ids are `origin`-first, dialect-ordered**: a table is addressed as
> *origin:object* — `bigquery:epson.sales`.

**Initial signals** (extracted, not interpreted):
- Verbs: "re-discovers", "empty on every cold start", "have no data model" → capability gap, not a bug
- Named entities: `SQLToolkit`, `CachePartition`, `TableMetadata`, `information_schema`, `wikitoolkit`, `NamespaceHandle`, `sqlglot`, BigQuery/Epson
- Components: `knowledge/wiki/*`, `bots/database/*`, `flows/dev_loop/wiki_search.py`, Claude Code hooks
- Acceptance criteria provided: no formal ACs; a 4-item **Spike Gate** and 9 **Open Questions**

---

## 1. Synthesis Summary

The brainstorm asks for a durable, shared, graph-shaped record of SQL data models that both a
running `DatabaseAgent` and a repo-bound coding agent can read, addressed as *origin:object*.
Research confirms the recommended shape (Option B) is a near-verbatim copy of the ledger plane:
`mcp_server.py` mounts an already-open store as a read-only overlay `NamespaceHandle` with
`overlay_prefixes`, and `FederatedWikiStore` routes bare ids by kind prefix and hydrates cross-kind
neighbors for *any* overlay, not just the ledger. The record already exists as
`bots/database/models.py::TableMetadata`, and every live producer hook (`SQLToolkit.describe_table`,
`PostgresToolkit`, `BigQueryToolkit`) and the stale-error classifier (`retries.py`) are in place.
Two things the brainstorm missed change the plan: a duplicate legacy `TableMetadata` lives in
`parrot_tools/database/models.py`, and FEAT-569 (rootless/remote wikitoolkit, 17 tasks in progress)
is concurrently refactoring the exact mount, CLI and tool-bundle seams the plane needs. A direct
sqlglot probe over the 32 in-repo `.sql` files replaces spike 1 with numbers: 26 files parse, 20
tables and 329 columns are recovered, 6 files fail whole-file. Recommendation: proceed to
`/sdd-spec` with Option B, sequencing the tool/mount lane behind FEAT-569's M2d/M6a tasks.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-600/findings/`. Paths are repo-relative;
> `W` = `packages/ai-parrot/src/parrot`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `W/knowledge/wiki/mcp_server.py` | `create_wiki_mcp_server` (ledger block) | 154-225 | template for the `schema` overlay mount + tool registration | F001 |
| 2 | `W/knowledge/wiki/federation.py` | `FederatedWikiStore._route` / `_route_bare_overlay_id` / `neighbors` | 885-930, 976-1059, 1133-1197 | bare-id kind routing; cross-kind hydration the plane inherits | F002 |
| 3 | `W/knowledge/wiki/store.py` | edges DDL / `add_edges` / `symbols` / `replace_source_slice` / `page_hashes` / `compare_and_swap_page` | 112-131, 550-837, 1593-1614 | store primitives; **no edge attribute slot**; side-table precedent | F003 |
| 4 | `W/knowledge/wiki/project.py` | `WikiNamespaceConfig`, `WikiProjectConfig.backend`, `decisions`, `ledger_path`, `find_shared_root`, `is_linked_worktree` | 183-260, 419, 478-485, 520-532, 1185-1197 | config surface to extend (`schema: SchemaPlaneConfig`, `schema_path`) | F004 |
| 5 | `W/knowledge/wiki/ledger/store.py` | `LedgerStore` | 24-123 | `SQLiteWikiStore` specialisation to mirror as `SchemaStore` | F005 |
| 6 | `W/knowledge/wiki/ledger/service.py` | `LedgerService.from_root` | 116-143 | constructor to mirror (`from_root` + `from_dir`, see F023) | F005, F023 |
| 7 | `W/bots/database/models.py` | `TableMetadata`, `MetadataSource`, `Completeness` | 97-155 | canonical record; needs `"ddl"` source | F006 |
| 8 | `W/bots/database/cache.py` | `CachePartition.get` / `store_table_metadata` | 33-40, 54-92, 104, 112-185, 321 | plane tier + write-through; Redis keys already `table:…` | F007 |
| 9 | `W/bots/database/toolkits/sql.py` | `SQLToolkit.describe_table` / `validate_query` / `_warm_table_cache` / `_SQLGLOT_DIALECT_MAP` | 45, 80-214, 509-576, 636-714 | live producer, repair hook, warm-from-plane | F008 |
| 10 | `W/bots/database/toolkits/postgres.py` | `PostgresToolkit` | 28-123 | `pg_catalog` producer (also overrides `_get_information_schema_query`) | F008 |
| 11 | `W/bots/database/toolkits/bigquery.py` | `BigQueryToolkit` | 19-60 | BigQuery producer | F008 |
| 12 | `W/bots/database/agent.py` | toolkit start loop (`tk_id`) | 206-224 | `tk_id → origin` mapping, `schema_plane` wiring | F009 |
| 13 | `W/bots/database/retries.py` | `SQLRetryHandler` | 56-57, 123-135 | proven-stale signal for read-repair | F010 |
| 14 | `W/knowledge/wiki/claude_code/assets.py` | `git_hook_block` | 166-190 | add `schema ingest-ddl --changed` inside the existing guard | F012 |
| 15 | `W/knowledge/wiki/structural/service.py` | `StructuralService._ensure_fresh` | 431-479 | read-repair shape (non-blocking lock, stale flag) | F014 |
| 16 | `W/knowledge/wiki/cli.py` | `symbols` / `ns` / `ledger` / `sync` groups | 2277, 2479, 2765, 3958 | add `wikitoolkit schema` group | F021 |
| 17 | `W/knowledge/wiki/file_suffixes.py` | — | 38 | `.sql` already yields `file:` pages for `defined_in` | F017 |
| 18 | `W/flows/dev_loop/wiki_search.py` | `DevLoopWikiSearch.build_research_context` | — | include `table:` hits | F020 |
| 19 | `packages/ai-parrot-tools/src/parrot_tools/database/models.py` | `TableMetadata` (**legacy duplicate**) | 12-45 | must NOT be the plane's input | F022 |
| 20 | `W/tools/databasequery/toolkit.py` | `DatabaseQueryToolkit.get_table_metadata` | 298-312 | second live introspection surface (`dq_get_table_metadata`); out of v1 | F022 |
| 21 | `W/tools/dataset_manager/sources/sql.py` | `SQLQuerySource.prefetch_schema` | 105-108 | returns `{}` today; follow-up consumer | F011 |

### 2.2 Constraints Discovered

- **Edges carry no attributes.** `edges(src, dst, rel, provenance)` with `PRIMARY KEY (src, dst, rel)`.
  *Implication*: an FK column pair needs a `rel` encoding or an `attrs` column bump on every backend. *Evidence*: F003
- **Bare-id routing is by kind prefix.** `_route_bare_overlay_id` returns the first overlay whose `overlay_prefixes` contain the id's kind.
  *Implication*: kind must be the first segment (`table:`, `schema:`, `source:`); *origin:object* lives in the second. *Evidence*: F002, F019
- **`WikiProjectConfig.backend` Literal stops at `arangodb`** although `create_wiki_store` knows `postgres`.
  *Implication*: a Postgres-hosted production plane needs a plane-specific backend field or a widened Literal. *Evidence*: F004
- **Mount guard + rootless mode.** The ledger mounts only when `find_shared_root(root)` is not `None`; FEAT-569 is adding `LedgerService.from_dir()` and `StructuralService(read_repair=False)`.
  *Implication*: `SchemaPlaneService` ships `from_root` **and** `from_dir`, tools get a `read_repair` switch; coordinate with FEAT-569 on `mcp_server.py`, `cli.py` and the tool bundle; the tool-surface golden test changes. *Evidence*: F001, F023
- **Two `TableMetadata` dataclasses.** `bots/database` (with `completeness`/`source`) vs `parrot_tools/database` (legacy, without).
  *Implication*: import `parrot.bots.database.models.TableMetadata` explicitly; adapter if `databasequery` ever feeds the plane. *Evidence*: F006, F022
- **`DatabaseAgent` keys by `tk_id = f"{database_type}_{primary_schema}"`.**
  *Implication*: map `tk_id → origin` or declare `origin` on the toolkit config; never rename `tk_id` (router registration). *Evidence*: F009
- **Redis keys already use `table:{schema}:{table}`.**
  *Implication*: no functional clash (Redis vs wiki) but grep/log ambiguity — document it. *Evidence*: F007, F019
- **One managed hook block for post-commit and post-merge**, guarded by `[ ! -f .git ]`.
  *Implication*: DDL ingest is one more line inside the same guard; no new hook. *Evidence*: F012
- **`sqlglot.parse` aborts a whole file on one `ParseError`; inline `PRIMARY KEY` is a column constraint, not `exp.PrimaryKey`.**
  *Implication*: `ingest-ddl` must split statements, isolate errors per statement, and fold column-level constraints. *Evidence*: F025, F018
- **`knowledge/wiki` is hot (201 commits / 30 days); `bots/database` is quiet (6 / 60 days).**
  *Implication*: wiki-side lanes in small, frequently rebased PRs; database-side lane is low-conflict. *Evidence*: F024
- **`_internal.generate_create_table_statement` takes YAML text**, not `TableMetadata`.
  *Implication*: the sqlglot DDL renderer is new code; `_internal.py` stays untouched. *Evidence*: F008

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched area |
|--------|------|--------|---------|--------------|
| `553a96217` | 2026-09-24 | Jesus Lara | fix over bookstore mcp plugin for wiki | `knowledge/wiki` |
| `3196ec57c` | 2026-09-23 | Jesus | feat(wiki): dedicated light wikitoolkit console entry for claude-hook (TASK-3673, FEAT-595) | `knowledge/wiki/claude_code` |
| `ea6becdec` | 2026-09-23 | Jesus | feat(wiki): stdlib prefilter and lazy imports for the claude-hook runtime (TASK-3672, FEAT-595) | `knowledge/wiki` |
| `72a4eb7fc` | 2026-09-21 | Jesus Lara | feat(sdd-execution-optimization): TASK-3569 — lazy ADR registration for wiki CLI hook startup | `knowledge/wiki/cli.py` |
| `705f6a56f` | 2026-09-20 | phenobarbital | Merge PR #1442 feat-FEAT-578-sdd-spec-wiki-adr | `knowledge/wiki/decisions` |
| `668e2521a4` | 2026-09-04 | Jesus | feat(conversation-history-ownership): TASK-2816 — bot callers render history | `bots/database` |

`knowledge/wiki`: 201 commits in 30 days (FEAT-578, 584, 587, 595). `bots/database`: 6 commits in 60
days, none touching cache/schema logic since FEAT-178. *Evidence*: F024. FEAT-569 (`wikitoolkit-http-mcp`)
has 17 tasks in progress on the same wiki files. *Evidence*: F023.

---

## 3. Probable Scope

### What's New

- **`knowledge/wiki/schema/`** — `models.py` (`SchemaSourceConfig`, `TableRecord` wrapping `TableMetadata` + `origin`/`dialect`, `ColumnRecord`), `ids.py` (`table_concept_id`, `parse_table_id`, `normalize_ref("bigquery:epson.sales")`), `render.py` (sqlglot `exp.Create` DDL + page body + `content_hash`), `store.py` (`SchemaStore(SQLiteWikiStore)` + `columns` side table), `producers/live.py`, `producers/ddl.py`, `service.py` (`SchemaPlaneService.from_root` / `from_dir`; `sync`, `ingest_ddl`, `diff`, `lookup`, `neighbors`, `search`), `tools.py` (`wiki_schema_lookup`, `wiki_schema_search`, `wiki_schema_neighbors`, `wiki_schema_sources`), `toolkit.py` (`SchemaPlaneToolkit`).
- **`WikiProjectConfig.schema: SchemaPlaneConfig`** + `schema_path(root) → <shared>/.parrot/schema/`.
- **`schema` overlay `NamespaceHandle`** in `mcp_server.py` with `overlay_prefixes=["source", "schema", "table"]`.
- **`wikitoolkit schema {sources, add-source, sync, ingest-ddl, diff, lookup}`**; write verbs refuse linked worktrees.
- **`MetadataSource += "ddl"`**; origin/dialect carried by `TableRecord`, not by `TableMetadata`.
- **`CachePartition` plane tier** (after Redis) + write-through; `DatabaseAgent(schema_plane=…)` with `tk_id → origin`.
- **Error-driven read-repair** in `SQLToolkit` on `column/relation does not exist`.

### What Changes

- **`W/knowledge/wiki/mcp_server.py`** — second overlay handle + `create_schema_tools`. *Evidence*: F001
- **`W/knowledge/wiki/project.py`** — `SchemaPlaneConfig`, `schema_path`. *Evidence*: F004
- **`W/knowledge/wiki/cli.py`** — `schema` group. *Evidence*: F021
- **`W/knowledge/wiki/claude_code/assets.py`** — `ingest-ddl --changed` line inside `git_hook_block`'s guard. *Evidence*: F012
- **`W/bots/database/models.py`** — `MetadataSource` gains `"ddl"`. *Evidence*: F006
- **`W/bots/database/cache.py`** — plane tier; behaviour-identical when unset. *Evidence*: F007
- **`W/bots/database/toolkits/sql.py`** — repair hook, `validate_query` wording, plane-aware `generate_query` context. *Evidence*: F008, F010
- **`W/bots/database/agent.py`** — `schema_plane` argument, `tk_id → origin`. *Evidence*: F009
- **`W/flows/dev_loop/wiki_search.py`** — include `table:` pages. *Evidence*: F020

### What's Untouched (Non-Goals)

- Columns as pages (side table only; `col:` pages can come later without changing table ids).
- `maps_to` (Python model → table) extraction — v2.
- Schema history / archive of previous pages — v2 or Option D territory.
- `SQLQuerySource.prefetch_schema` plane implementation — follow-up (F011).
- `databasequery` / `dq_get_table_metadata` as producer or consumer — follow-up (F022).
- Retiring the legacy `parrot_tools.database.TableMetadata` — avoided, not removed.
- Write tools over MCP — CLI-only in v1 (the MCP holds no credentials).
- `sample_data` ingestion — off by default, per-table allowlist only.

### Patterns to Follow

- Ledger plane: own SQLite file, `LedgerStore(SQLiteWikiStore)`, `Service.from_root` via `find_shared_root` + `load_effective_config`, read-only `NamespaceHandle` with `overlay_prefixes`. *Evidence*: F001, F005
- `symbols` side table and `sym:` id helpers → `columns` table and table-id helpers. *Evidence*: F003, F013
- `StructuralService._ensure_fresh`: non-blocking lock, `stale=True` flag, partial repair. *Evidence*: F014
- `DecisionConfig` sub-model on `WikiProjectConfig` → `SchemaPlaneConfig`. *Evidence*: F004
- Single guarded `git_hook_block` for both hooks. *Evidence*: F012
- `DevLoopWikiSearch` ledger-context integration that degrades gracefully. *Evidence*: F020
- Rootless constructors and `read_repair` switch being introduced by FEAT-569. *Evidence*: F023

### Integration Risks

- **FEAT-569 overlap**: 17 in-progress tasks refactor tool bundling (`build_wiki_tools`, TASK-3358), CLI proxies (TASK-3362) and add `from_dir()` (TASK-3354). Sequence the tools/mount lane after those land, or plan the rebase explicitly. *Evidence*: F023, F024
- **Tool-surface golden test** (FEAT-569 TASK-3367) must gain the four `wiki_schema_*` tools. *Evidence*: F023
- **sqlglot whole-file failures**: 6 of 32 in-repo files yield nothing without per-statement isolation. *Evidence*: F025
- **Duplicate `TableMetadata`**: an accidental `parrot_tools.database` import silently drops `completeness`/`source`. *Evidence*: F022
- **Edge attribute decision** (U2) touches every `BaseWikiStore` backend if an `attrs` column is chosen. *Evidence*: F003
- **`CachePartition` regression**: the existing `bots/database` suite is the gate for plane-off parity. *Evidence*: F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The ledger overlay mount in `mcp_server.py` is a copyable template for a `schema` overlay | F001 | high | block read directly; test fixture mounts it the same way |
| C2 | `FederatedWikiStore` already supports a second overlay with its own prefixes and hydrates cross-kind neighbors | F002 | high | `_route` iterates all handles; M13 tests exist; two-overlay test not yet present |
| C3 | Edges cannot carry an FK column pair without `rel` encoding or a schema bump | F003 | high | edges DDL read directly |
| C4 | `bots/database.TableMetadata` is the canonical record and lacks only `"ddl"` + origin | F006, F022 | high | fields read; legacy duplicate identified |
| C5 | `CachePartition` has no durable tier; a plane tier after Redis is additive | F007 | high | `get()` docstring + code anchors read |
| C6 | `SQLToolkit`/`PostgresToolkit`/`BigQueryToolkit` expose the hooks for a live producer and error-driven repair | F008, F010 | high | method anchors and retry strings read |
| C7 | The offline DDL path is feasible on Postgres with sqlglot 30.x but needs per-statement isolation and column-constraint folding | F025, F018 | medium | probe: 26/32 parse, 6 fail whole-file; PK undercount observed; BigQuery/T-SQL untested |
| C8 | FEAT-569 is in flight and overlaps the plane's mount/CLI/tool seams | F023, F024 | high | index read: 17 tasks in progress; hot-file history |
| C9 | No schema plane, `table:`/`schema:`/`source:` kinds or `wiki_schema_*` tools exist today | F019 | high | grep over `packages/*/src` empty |
| C10 | The DDL-ingest hook is one line inside the existing guarded `git_hook_block` | F012 | high | block read |
| C11 | Option B (own `schema.db` overlay) is the right architecture over A/C/D | F001, F005, F016, F023 | medium | precedents confirmed; production placement and FEAT-569 remote mode may shift the backend choice |
| C12 | Annotations via `wiki_remember` survive `schema sync` slice replacement | F015, F003 | medium | inferred from `origin="memory"` + `replace_source_slice` semantics; not executed |
| C13 | BigQuery `INFORMATION_SCHEMA` cost savings justify the feature for the Epson client | — | low | asserted by the brainstorm; no measurement in repo (spike 3) |

Distribution: **9** high, **3** medium, **1** low. Overall **medium**, bounded by C7/C11 (the offline
path and the architecture call both depend on owner decisions U1–U4) and the unmeasured C13.

---

## 5. Open Questions

### Resolved (during proposal phase — by codebase evidence)

- [x] **Does a second overlay namespace work?** — *Resolved*: yes; `_route` / `_route_bare_overlay_id` / `_overlay_incoming_edges` iterate every handle (F002). Brainstorm spike 2 reduces to adding a two-overlay regression test.
- [x] **Is sqlglot DDL parsing viable on the in-repo corpus?** — *Resolved*: sqlglot 30.18.0 parses 26/32 files; 20 tables / 329 columns / 3 FKs / 15 ALTERs recovered; 6 whole-file `ParseError`s; PL/pgSQL and `DO $$` fall back to `Command` harmlessly (F025). Per-statement isolation is required. BigQuery/T-SQL still need external samples.
- [x] **Do edges have an attribute slot?** — *Resolved*: no — `(src, dst, rel, provenance)` only (F003). The *choice* remains U2.
- [x] **Is `schema` free as a CLI group and are `table:`/`schema:`/`source:` free as kinds?** — *Resolved*: yes (F019, F021).
- [x] **Columns as pages?** — *Resolved by default*: side table in v1 (mirrors `symbols`, F003); `col:` pages can be added later without changing table ids. Owner may override.
- [x] **`maps_to`, schema history, DatasetManager exposure?** — *Resolved by default*: v2 / follow-ups (§3 Non-Goals).

### Unresolved (defer to spec)

- [ ] **U1 — Final id grammar**: kind-first `table:<origin>/<schema>.<table>` (routing-safe, *recommended*, with `normalize_ref()` accepting bare `bigquery:epson.sales` on input) vs bare `<origin>:<schema>.<table>` as concept id (every alias in `overlay_prefixes`) vs one namespace per origin. — *Owner*: Jesus
  *Blocks claims*: C2, C9
- [ ] **U2 — FK edge payload**: a) `attrs` JSON column on `edges` (schema v3, all backends) · b) `rel` encoding `references:store_id->id` · c) keep the pair only in the `columns` side table / page body, edge stays plain `references`. — *Owner*: Jesus
  *Blocks claims*: C3
- [ ] **U3 — Live vs DDL merge rule** for one origin: a) newest `introspected_at` wins per table, `defined_in` always kept, conflicts reported by `schema diff` (*recommended*) · b) live always authoritative · c) separate origins, never merged. — *Owner*: Jesus
  *Blocks claims*: C11
- [ ] **U4 — Production placement and FEAT-569 dependency**: a) v1 = SQLite `schema.db` with `from_root` + `from_dir`, backend swap later (*recommended*) · b) v1 ships `create_wiki_store(backend=…)` with a widened Literal · c) v1 waits for FEAT-569 and mounts only in the remote server. — *Owner*: Jesus
  *Blocks claims*: C11, C8
- [ ] **U5 — Origin key**: a) explicit `origin` on `DatabaseToolkitConfig` defaulting to `database_type`, passed to the partition (*recommended*) · b) derive from `tk_id` by convention · c) rename `tk_id`. — *Owner*: Jesus
  *Blocks claims*: C5, C6

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-600`** — *Rationale*: localization is high-confidence (C1–C6, C9, C10) and the
brainstorm already selected Option B; U1–U5 are owner decisions the spec's Open Questions capture,
and the DDL probe (C7) replaces spike 1 with measured numbers. The spec should sequence the
tools/mount module after FEAT-569 M2d (`build_wiki_tools`) and M6a (`remote_cli`) or state the rebase
plan explicitly, and keep spikes 3 (BigQuery cost baseline) and 4 (plane-tier regression) as tasks.

### Alternatives

- **`/sdd-brainstorm FEAT-600`** — not recommended; the options analysis already exists in the source brainstorm.
- **`/sdd-task FEAT-600`** — not applicable; this is a multi-lane feature, not a single-file fix.
- **Manual review** — run spike 3 (BigQuery bytes billed for `describe_table` FULL over the Epson dataset) before the spec if C13 must justify prioritisation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-600/state.json` |
| Source (raw) | `sdd/state/FEAT-600/source.md` |
| Research plan | `sdd/state/FEAT-600/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-600/findings/F001-*.md` … `F025-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-600/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read (targeted anchors): 16 / 40
- Grep calls: 21 / 25
- Git calls: 2 / 10
- Wiki queries: 19 (free) + 6 page reads (free)
- DDL probe: 1 (`sqlglot.parse` over 32 files, read-only)
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (source is a design brainstorm with a recommended option;
no defect signal).

**Gates**: the session ran unattended, so the plan gate, review gate and Q&A were auto-skipped and
recorded in `state.json`; unknowns are carried unresolved into §5 with recommended answers.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (Claude Fable 5.1, unattended) |
