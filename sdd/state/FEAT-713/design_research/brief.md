<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
## Problem Statement

Finance questions that agents receive — "revenue for Pokémon at TROC last quarter", "EBITDA by cost center", "operating expenses YTD" — are not analytical questions over a schema; they are **rollups over a chart of accounts**. Which GL accounts sum into *revenue*, which ones are netted (returns, discounts), what sign convention applies to each account, and which accounts moved between buckets at the last fiscal year change is **internal, closed knowledge** that no LLM has and no `information_schema` exposes.

Today the only places that knowledge could live are:

1. **A skill / system prompt in prose.** Lossy by construction: a list of 40 account codes in a markdown skill will eventually be paraphrased, truncated or partially recalled, and one omitted account silently changes the number. There is no way to *validate* a prose skill against the chart of accounts.
2. **Free-form SQL from the DB Query Toolkit.** The agent writes the aggregation itself. Even with the sqlglot positive allowlist guard planned in the semantic-layer research, the guard validates *tables and columns*, not *which accounts belong in the `IN (...)` list*. The query is syntactically safe and semantically wrong.
3. **A view maintained by DBAs.** Deterministic, but opaque to the agent (no lineage, no explanation), not portable to in-memory DataFrames in `DatasetManager`, and the "why is revenue this number" question cannot be answered.

The generic semantic layer (BSL/Ibis per the research, sidemantic pending legal) solves metric *naming* and *governance*, but its primitives (measures, dimensions, joins) do not express the accounting-specific invariants: completeness of the chart of accounts over the declared buckets, debit/credit sign normalisation, effective-dated account membership, and reconciliation assertions (`revenue − expenses == net_income`).

Who is affected: any agent using `DatabaseToolkit` / `SQLToolkit` or `DatasetManager` over a general ledger; finance users of the client deployments (TROC is the first concrete case); the AuditLedger (a financial figure must be traceable to the exact query and the exact model version that produced it). Why now: the semantic-layer spec is in progress and this layer must be designed as its *specialisation*, not bolted on after; and the first client request for GL-level answers is on the table.

### Constraints and goals
## Constraints & Requirements

- **The LLM never writes the aggregation.** It selects `metric + grain + filters + period`; the compiler produces the query. This is the "probabilistic proposes, deterministic decides" invariant applied to finance. (Owner constraint.)
- **One compiler, two execution targets.** The same compiled SQL text runs against the source database through `DatabaseToolkit` and against in-memory DataFrames through `DatasetManager`. (Owner decision, 2026-10-20.)
- **DuckDB is the in-process engine; Arrow is the bridge.** polars/pandas DataFrames are registered into DuckDB via Arrow (zero-copy), never serialised. No pickle across trust boundaries (security invariant). (Owner decision, 2026-10-20.)
- **A basic, closed parser.** The metric expression grammar covers exactly what the accounting layer needs — sums over account sets, `+ − × ÷`, parentheses, references to other metrics — and nothing more. No conditionals, no free functions, no inline SQL. Growth pressure on the grammar is a signal that an account set is missing, not that the grammar is. (Owner decision, 2026-10-20.)
- **Home and packaging (resolved 2026-10-21).** `parrot.semantic.accounting`, a standalone package inside the `ai-parrot-semantic` satellite — **not** an engine of FEAT-704 (semantic layer), which is approved but paused until its AGPL-3.0 dependency (sidemantic) is migrated away. FEAT-704's satellite does not exist yet, so this feature creates its skeleton (PEP 420, **no sidemantic**) and FEAT-704 builds on it when it resumes.
- **No new heavy dependency.** `sqlglot` (already used by `SQLToolkit`), `duckdb`, `pyarrow`, Pydantic v2. No AGPL code in the tree; the YAML *shape* may borrow from Cube/MetricFlow conventions, adapter code may not.
- **Determinism is a contract.** Same model version + same request ⇒ byte-identical SQL. `IN (...)` lists sorted, CTE/column names derived from the model, no timestamps or random aliases in the output. The SQL hash and the model hash are recorded with every result.
- **Compile-time validation, never runtime surprises.** Chart-of-accounts completeness, metric cycles, empty sets, dangling references and declared reconciliation assertions are checked when the model loads. A model that fails validation does not load.
- **Explainability for finance people.** Every result carries lineage: which account sets contributed, which concrete accounts each set resolved to, and the formula. A controller must be able to accept the number without reading SQL.
- **Multi-tenant, per-model security.** Models are tenant-scoped; metric visibility is filtered by the PBAC context like any other catalog entry in `DatasetManager`. Results caches are never shared across security contexts (research rule).
- **Pydantic at the I/O boundary; `parrot.interfaces.*` contract pattern** with lazy loading of the DuckDB/Arrow implementation behind an optional extra.
- **Language split:** identifiers, YAML keys, module paths and docs in English.
- **Validation-first:** spikes prove Arrow registration, cross-dialect compilation of the `CASE`-column pattern, and completeness checking on a real chart of accounts before `/sdd-spec`.

---

### Recommended option / probable scope
## Recommendation

**Option B.** The accounting layer is small enough to own and specific enough that no generic engine will enforce its invariants. Owning the compiler gives three things the alternatives cannot:

1. **Completeness as a load-time error.** The one failure mode finance cares about — an account silently missing from a bucket — becomes impossible to ship: the model does not load.
2. **Determinism as a contract, not a hope.** We control the AST and pin sqlglot; the SQL hash is reproducible across machines and months, which is what the AuditLedger needs.
3. **Independence from the engine decision.** Legal's answer on AGPL and BSL's Ibis pin stop being blockers (FEAT-704 is in fact paused on the AGPL migration as of 2026-10-21); when the generic layer lands, this model lowers into it as filtered + derived metrics, so finance metrics appear in the same catalog without rewriting them.

What we trade: a second (tiny) compiler and no joins in v1. Option D stays available as a materialisation mode; Option A becomes the lowering path.

---

### Option B: Dedicated accounting compiler — YAML → Pydantic IR → sqlglot AST → single-scan SQL; DuckDB over Arrow for DataFrames — *recommended*

A small package (`parrot.semantic.accounting` → `packages/ai-parrot-semantic/src/parrot/semantic/accounting/`; this feature creates the satellite skeleton — see Open Questions) with four parts:

1. **Model** (`model.py`) — Pydantic v2, frozen, hashable:
   - `ChartOfAccounts`: source (`table` or `dataframe`), `account_key`, **`amount_sign: by_nature | signed`** (required, no default — resolved 2026-10-21), `nature` column or per-account map (`debit | credit`, required only with `by_nature`), optional `parent_key` for hierarchy, `amount`, `posting_date`, `entity`/`dimension` columns.
   - `AccountSet`: explicit `accounts: [...]`, or selector (`prefix`, `range`, `tag`, `parent`) plus `except`; optional `valid_from` / `valid_to`. Selectors are **resolved at compile time** against the loaded chart of accounts and materialised to an explicit sorted list; the SQL always carries a literal `IN (...)`. The model hash therefore changes when the chart of accounts changes, which is the desired behaviour.
   - `Metric`: `expr` string over sets and other metrics, `description`, `dimensions` allowed, optional `unit`.
   - `Assertion`: `expr == expr` pairs evaluated as validation queries (e.g. `revenue - total_expenses == net_income`).
   - `Model`: `name`, `version`, `tenant`, `chart_of_accounts`, `sets`, `metrics`, `assertions`, `excluded` (accounts deliberately outside every set, with a `reason`).

2. **Parser** (`grammar.py`) — a Pratt parser (~100 lines) for the metric expression language:
   ```
   expr   := term (("+" | "-") term)*
   term   := factor (("*" | "/") factor)*
   factor := "sum" "(" SET ")" | METRIC | NUMBER | "(" expr ")" | "-" factor
   ```
   Produces a typed AST (`Sum(set)`, `Ref(metric)`, `Num`, `BinOp`). No other node kinds exist.

3. **Compiler** (`compiler.py`) — three passes:
   - *Resolve*: selectors → explicit account lists (with `valid_from/valid_to` filtered by the requested period); detect empty sets, dangling refs, metric cycles (topological sort), **completeness** (every account in the chart is in ≥ 1 set or in `excluded`).
   - *Inline*: each requested metric is expanded to a tree over `Sum(set)` leaves; shared sets are deduplicated.
   - *Emit*: one `SELECT` over the journal table with one column per distinct set — `SUM(CASE WHEN account_id IN (...) THEN amount * sign END) AS set_<name>` — grouped by the requested grain, wrapped in an outer `SELECT` that computes the metric arithmetic over the set columns. Built with `sqlglot.exp` nodes, rendered with `sql(dialect=...)`. A composite metric is **N `CASE` columns and one expression**, never N subqueries; this is fast in DuckDB and readable by finance.
   - Output: `CompiledMetricQuery(sql: str, dialect: str, sql_hash: str, model_hash: str, lineage: Lineage, assertions: list[CompiledMetricQuery])`.

4. **Execution** (`runtime.py`, behind the optional extra):
   - `DatabaseToolkit` path: `compile(..., dialect=toolkit.dialect)` → existing execution (`asyncpg` etc.), result + `CompiledMetricQuery` metadata to the accounting audit ledger (`AccountingAuditEntry`).
   - `DatasetManager` path: `DuckDBRunner` registers the DataFrame via `con.register(name, arrow_table)` (polars `to_arrow()`, pandas via `pyarrow.Table.from_pandas`) and executes the same `sql` compiled with `dialect="duckdb"`. One `DuckDBPyConnection` per worker thread (`root.cursor()`), `asyncio.to_thread` for execution — the connection is not thread-safe (research note).

Tool surface (separate named tools, per the "multi-purpose tools fail" principle): `finance_list_metrics`, `finance_explain_metric` (formula + resolved accounts + assertions touching it), `finance_query_metric(metric, grain, filters, period)` returning rows **and** lineage, `finance_validate_model` (CLI/MCP, runs completeness + assertions against live data).

✅ **Pros:**
- All accounting invariants live in one place and are enforced at load time; the SQL shape is fully under our control, so byte-level determinism is a real contract.
- Independent of the generic engine decision; can later be *lowered* into BSL/sidemantic (Option A becomes an export, not a dependency).
- Single scan + `CASE` columns: trivial to read, trivial to explain, fast in DuckDB and Postgres alike.
- Lineage is a by-product of the resolve pass — no extra work to answer "which accounts made this number".
- Tiny grammar ⇒ tiny attack surface; no SQL from the model author either (sets are data, not expressions).

❌ **Cons:**
- A second compiler next to the generic one; both emit SQL through sqlglot but the models are different objects. Mitigated by keeping this one deliberately small and by the planned lowering.
- No joins in v1: the journal must already carry the dimensions (entity, product line, cost center) or a pre-joined view must be pointed at. Acceptable for GL fact tables; a `dimension_source` join is a v2 item.
- Natural calendar only in v1. Cumulative YTD/QTD/MTD over that calendar **is** in v1 (client requirement, 2026-10-21); fiscal calendars, consolidation and multi-currency are non-goals.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlglot` | AST construction + dialect rendering | core declares `sqlglot>=20.0`; the satellite pins `>=30.1,<31` (FEAT-704's pin) and the per-dialect golden tests guard rendering changes — they would break the byte-level contract |
| `duckdb` | in-process engine for DataFrames | MIT; not a dependency anywhere today (verified 2026-10-21); optional extra `duckdb` (`duckdb>=1.0`) of `ai-parrot-semantic`, the same extra FEAT-704 declares |
| `pyarrow` | zero-copy registration | already a core dependency (`pyarrow>=25.0`, `packages/ai-parrot/pyproject.toml`) |
| `pydantic` v2 | model + IR | in stack |

🔗 **Existing Code to Reuse:**
- `bots/database/toolkits/sql.py::SQLToolkit` — `_SQLGLOT_DIALECT_MAP`, `validate_query`, execution; the compiled SQL goes through the same positive allowlist guard as free SQL (defence in depth).
- `bots/database/models.py::TableMetadata` — to validate that `account_key`, `amount`, `posting_date` columns exist before compiling (schema plane later).
- `parrot.security.audit_ledger` — reuse the signers (`AbstractKMSSigner`, `LocalHMACSigner`) and the async `storage(json_str)` contract for a new signed `AccountingAuditEntry`. `AuditLedgerEntry` itself is credential-shaped (`user_id`, `channel`, `tool`, `provider`, `key_fingerprint`) and is **not** extended (same decision FEAT-704 took for its own ledger).
- `DatasetManager` catalog + PBAC filtering (`parrot/tools/dataset_manager/`; catalog shape ⚠️ VERIFY in spec) — metrics registered as catalog entries with `kind="accounting_metric"`.
- `parrot.interfaces.*` lazy-loading pattern (`faiss _try_create_faiss_store`) for the DuckDB runner.

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
packages/ai-parrot/src/parrot/bots/database/models.py
packages/ai-parrot/src/parrot/security/audit_ledger.py
packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
packages/ai-parrot/src/parrot/tools/dataset_manager/config.py
packages/ai-parrot-embeddings/pyproject.toml
sdd/specs/semantic-layer.spec.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
