# Infographic Recipes (FEAT-324)

Recipe-driven, replayable A2UI infographics: precise construction
instructions — datasets, registered transforms, a catalog layout, a render
profile — persisted once and replayed deterministically with fresh data,
with no LLM in the replay loop.

Design record: `sdd/specs/infographic-builder.spec.md` (spec) and
`sdd/proposals/infographic-builder.brainstorm.md` (brainstorm, all open
questions resolved there).

---

## 1. Concepts

### A recipe is pure data

An `InfographicRecipe` (`parrot.outputs.a2ui.recipes.InfographicRecipe`) is a
Pydantic model, never stored/executed code (spec G1):

- **`params`** — declared parameters (`{param}` substitution + five built-in
  relative-date resolvers: `current_month`, `previous_month`, `today`,
  `yesterday`, `first_of_month`).
- **`data_sources`** — `DatasetManager` dataset names, each bound to an
  alias transforms reference.
- **`transforms`** — an ordered chain of **registered** transformer calls
  (name + params + `output_key`); every value in the layout traces back to
  one of these.
- **`layout`** — a catalog component tree (`Infographic`, `Chart`,
  `KPICard`, `DataTable`, ...) whose data-carrying properties are
  `{"$bind": "/pointer"}` bindings into the assembled `dataModel`.
- **`render`** — the renderer profile (`interactive-html`, `ssr_html`,
  `pdf`, ...) plus optional delivery config.
- **`schedule`** — optional; `principal` is REQUIRED before a recipe can be
  scheduled (spec G8 — see §4).

### Transformers

Registered via `@infographic_transformer` (`parrot.outputs.a2ui.recipes.transformers`):
pure `(inputs: dict[str, DataFrame], params: dict) -> dict` functions. Seven
ship built-in (`parrot.outputs.a2ui.recipes.library`):

| Transformer | Purpose |
|---|---|
| `day_totals` | Per-snapshot revenue/EBITDA totals + variance (dynamic per-snapshot-date keys) |
| `division_breakdown` | Per-division rollup + per-project variances (latest snapshot) |
| `variance_analysis` | First-vs-latest comparison with STABLE keys (`first_totals`/`last_totals`) — the layout-friendly equivalent of `day_totals` |
| `top_movers` | Worst/best N projects by EBITDA variance, with day-over-day trend |
| `groupby_aggregate` | Generic group-by + named aggregation (reshapes multi-day data into flat, chartable rows) |
| `pivot` | Generic pivot table |
| `latest_vs_baseline` | Generic baseline-vs-latest delta join |

Every transformer declares `requires_columns` (checked by the fail-fast gate,
§3) and a `params_schema` (discoverable via `infographic_get_recipe_contract`).

### Stores

`AbstractRecipeStore` (`parrot.outputs.a2ui.recipes.store`) — two backends,
both core:

- **`FileRecipeStore(directory)`** — one YAML file per recipe
  (`<directory>/<name>.yaml`, or `<directory>/<owner>/<name>.yaml` when
  owner-scoped). Atomic writes (write-to-temp + `os.replace`).
- **`DBRecipeStore(redis_url=..., namespace=...)`** — Redis-backed (mirrors
  `parrot.skills.store.SkillRegistry`'s actual persistence mechanism — Redis
  + in-memory fallback, NOT a SQL table), with an in-memory fallback when
  Redis is unset/unreachable.

Both share one contract: `save` (overwrite + `updated_at` bump), `get`,
`list` (lightweight summaries only), `delete`. `RecipeNotFoundError` lists
available names; `RecipeSchemaVersionError` guards `schema_version` drift.

### Triggers — one runner, three doors

`RecipeRunner` (`parrot.tools.infographic_recipes.runner`) executes the
seven-step replay pipeline (params → data → gate → transforms → layout
bind-check → render → best-effort delivery). All three triggers call the
SAME `RecipeRunner.run()`:

1. **Chat tool** — `InfographicToolkit.infographic_run_recipe(name, params)` (§2).
2. **REST** — `POST /api/v1/infographic_recipes/{name}/run` (§3).
3. **Scheduler** — `run_infographic_recipe` callback on the existing
   `AgentSchedulerManager` (§4).

---

## 2. The example recipe, annotated

`examples/infographic_recipes/budget-variance-daily.yaml` reproduces the
reference `sdd/artifacts/budget_variance_dashboard_Template.html` dashboard
end-to-end. Load it with:

```python
from parrot.outputs.a2ui.recipes import InfographicRecipe

recipe = InfographicRecipe.from_yaml(open("budget-variance-daily.yaml").read())
```

Key sections, walked through:

```yaml
params:
  - name: month
    default: current_month   # resolves to "YYYY-MM" at replay time
```
Declares one param; `resolve_params()` (`parrot.outputs.a2ui.recipes.params`)
resolves `current_month` to the literal month string unless a caller
supplies an override (e.g. `{"month": "2026-06"}`) — undeclared overrides
are rejected (typo protection).

```yaml
data_sources:
  - dataset: in_month_projections
    alias: snapshots
  - dataset: in_month_projections
    alias: df
```
TWO aliases for the SAME dataset: `snapshots` feeds the finance-domain
transformers (which all expect an input keyed `"snapshots"`), `df` feeds
`groupby_aggregate` (which expects `"df"`) — each built-in transformer
hard-codes its own expected input-alias name, so a recipe re-aliases the
same dataset per transformer that needs it.

```yaml
transforms:
  - transformer: variance_analysis
    inputs: [snapshots]
    params: {snapshot_col: snapshot}
    output_key: variance_analysis
```
The layout's KPICards bind to `variance_analysis`'s STABLE
`first_totals`/`last_totals` keys — NOT `day_totals`'s per-snapshot-date
keys, which change every day and would break a fixed `$bind` pointer.

```yaml
layout:
  component: Infographic
  properties:
    sections:
      - heading: Snapshot
        components:
          - component: KPICard
            properties:
              value: {$bind: "/variance_analysis/last_totals/rev_actual"}
```
Every data-carrying property is a `$bind` pointer into the assembled
`dataModel` — never a literal value. The runner cross-checks every pointer's
top-level key against the transform chain's `output_key`s BEFORE rendering
(spec §7's documented "`$bind` drift" risk).

```yaml
render:
  profile: interactive-html
```
Self-contained interactive HTML (vendored Chart.js v4 + vanilla-JS day
tabs/metric toggle/column sort — see Module 7). Swap to `ssr_html` or `pdf`
for static delivery channels (email attachments, print).

---

## 3. Replay

### Chat tool

```python
toolkit = InfographicToolkit(
    artifact_store=artifact_store,
    recipe_store=recipe_store,       # FileRecipeStore | DBRecipeStore
    dataset_manager=dataset_manager,  # builds a RecipeRunner internally
)
# infographic_save_recipe / infographic_list_recipes / infographic_run_recipe /
# infographic_get_recipe_contract are now exposed (absent otherwise).
```

`infographic_save_recipe` freezes the CURRENT session's envelope + explicit
dataset/transform provenance into a recipe (dry-run validated before
persisting) — the LLM half of dual authorship (spec G2). Ad-hoc
REPL-computed data (not a registered transformer call) cannot be frozen;
this is a documented boundary, not a bug.

### REST

```
GET    /api/v1/infographic_recipes              # list (owner-scoped)
GET    /api/v1/infographic_recipes/{name}        # full recipe
PUT    /api/v1/infographic_recipes/{name}        # create/overwrite
DELETE /api/v1/infographic_recipes/{name}
POST   /api/v1/infographic_recipes/{name}/run    # {"params": {...}} body
```

Configure the store/runner once at server startup:

```python
from parrot.handlers.infographic_recipes import register_recipe_routes

register_recipe_routes(
    app, recipe_store=recipe_store, dataset_manager=dataset_manager,
)
```

`POST .../run` returns `422` with the structured `RecipeRunError` body on a
schema-drift/gate failure (§5), `404` listing available recipe names when
the target doesn't exist, `200` with `{"artifact_id", "filename",
"mime_type", "size", "storage_ref"}` on success.

### Scheduling

The **existing** APScheduler-based `AgentSchedulerManager` already ships
jobs + post-run callbacks — FEAT-324 registers `run_infographic_recipe` as a
callback (`CALLBACK_REGISTRY`), NOT a new scheduler (spec Non-Goal). Create
any lightweight scheduled job via the existing `SchedulerJobsHandler` REST
CRUD, attaching the recipe callback:

```json
POST /api/v1/parrot/scheduler/schedules
{
  "agent_name": "ops-bot",
  "schedule_type": "daily",
  "schedule_config": {"hour": 6, "minute": 0},
  "prompt": "noop",
  "callbacks": [
    {"type": "run_infographic_recipe", "config": {"recipe_name": "budget-variance-daily"}}
  ]
}
```

The recipe MUST have `schedule.principal` set (uncomment the `schedule:`
block in the YAML and set a real principal) — scheduled replays run under
THAT principal, resolved into a minimal `PermissionContext`, and **never**
fall back to a server identity (spec G8). A missing principal fails the job
outright.

---

## 4. Permissions (spec G8)

| Trigger | `pctx` source |
|---|---|
| Chat tool | Real `PermissionContext` captured by `InfographicToolkit._pre_execute` from the toolkit-dispatch-injected `_permission_context` (falls back to a principal-only context built from the resolved user id when invoked outside the dispatch path — e.g. direct method calls) |
| REST | Built from the authenticated session's user id via `build_principal_context` (`parrot.auth.permission`) |
| Scheduler | Resolved from the recipe's `schedule.principal` (+ optional `schedule.tenant_id`/`schedule.roles`) — REQUIRED, no fallback |

**Every** `RecipeRunner.run()` call site (chat tool, REST, scheduler) ALWAYS
passes a real `pctx` — a falsy `pctx` makes `DatasetManager`'s PBAC/data-plane
guards fail OPEN (no filtering applied) rather than closed, so this is a hard
requirement, not a nicety. `PermissionContext`s built from a bare principal
(REST, chat-tool fallback) default `tenant_id` to the principal itself and
grant no roles — set `schedule.tenant_id`/`schedule.roles` explicitly on a
recipe's `schedule` block for role-gated PBAC policies to apply to its
scheduled replays.

`RecipeRunner.run()` also takes `recipe_owner` — it MUST match the owner a
recipe was saved under (stores key by `(name, owner)`); all three triggers
resolve and pass it automatically (the invoker's user id for chat/REST,
`None`/unscoped for scheduled recipes unless you scope those separately).

`DatasetManager`'s PBAC/data-plane guards apply unchanged in all three paths
— a permission-denied dataset fails the run, it never silently narrows or
widens access.

### `{param}` substitution into `sql` templates

`DataSourceSpec.sql`'s `{param}` substitution is guarded against SQL
injection: a resolved param value containing quotes, semicolons, or comment
markers (`--`, `/*`, `*/`) is rejected with a `stage="data"` error BEFORE any
query executes. `DatasetManager`'s `TableSource` executes `sql` close to
verbatim and documents itself as NOT a security boundary — recipe `params`
overrides are a new, less-trusted input to that path compared to
`TableSource`'s existing (LLM/agent-authored) callers. Prefer
`DataSourceSpec.conditions` (parameterized, escaped at fetch time) over
embedding `{param}` directly inside `sql` wherever possible.

---

## 5. Reading a `RecipeRunError`

Every abort constructs a structured diagnostic — never a raw traceback:

```python
class RecipeRunError(BaseModel):
    recipe: str                # recipe name
    stage: Literal["params", "data", "gate", "transform", "layout", "render"]
    transformer: Optional[str] # offending transformer, if applicable
    dataset: Optional[str]     # offending dataset/alias, if applicable
    missing_columns: list[str] # required columns absent from the input
    detail: str                # human-readable message
```

- **`stage="params"`** — an override references an undeclared param, or a
  declared param has neither a default nor an override.
- **`stage="data"`** — a dataset isn't registered (lists available names via
  `DatasetManager.list_datasets()`), or `fetch_dataset()` itself errored.
- **`stage="gate"`** — an unknown transformer name (lists registered
  names), or a required column is missing from a data-source-backed input —
  BEFORE any transform executes.
- **`stage="transform"`** — a transform raised, or a step references an
  alias that is neither a data-source alias nor a prior step's `output_key`.
- **`stage="layout"`** — a `$bind` pointer's top-level key is absent from
  the assembled `dataModel` (an `output_key` was renamed without updating
  the layout), or the assembled envelope fails catalog validation.
- **`stage="render"`** — the resolved renderer's `render()` call itself
  raised. (An UNKNOWN/uninstalled renderer profile instead raises the
  existing actionable `ImportError` naming the pip extra — it never reaches
  `RecipeRunError`.)

`infographic_get_recipe_contract(name)` (chat tool) exposes exactly which
datasets/columns/params a recipe needs, so an operator can verify
replayability before scheduling it.

---

## 6. Migration from `daily_report.py`

The reference artifacts (`sdd/artifacts/daily_report.py`,
`executive_summary.py`, `budget_variance_dashboard_Template.html` —
gitignored, non-importable; referenced here for the migration story only)
implement this exact pattern as a standalone Windows script. FEAT-324
replaces each piece with a core AI-Parrot mechanism:

| `daily_report.py` concern | FEAT-324 replacement |
|---|---|
| Windows Task Scheduler | `AgentSchedulerManager` (existing) + `run_infographic_recipe` callback |
| Outlook COM delivery | `deliver_artifact()` (existing `NotificationMixin.send_notification` bridge) |
| `parse_csv` + hardcoded row indices | `DatasetManager` dataset registration (any source: table, query, in-memory) |
| `day_totals`/`division_breakdown`/`analyze` (inline functions) | Registered `@infographic_transformer`s (`day_totals`, `division_breakdown`, `variance_analysis`, `top_movers`) — same math, ported verbatim where the semantics carry over |
| String-splicing into an HTML template (`splice_into_template`) | `interactive-html` renderer — Chart.js + vanilla-JS day-tabs/metric-toggle/sort, driven by the embedded `dataModel` JSON, zero string templating |
| Hardcoded file paths / one-off script | A persisted, versioned `InfographicRecipe` — replayable by name, from chat, REST, or a schedule |
| No structured failure mode (silent wrong numbers) | Fail-fast `RecipeRunError` — the gate aborts BEFORE any transform runs on drifted data |

The `budget-variance-daily.yaml` example (§2) is the concrete migration
target: same construction instructions the legacy script encoded in Python,
now declarative, replayable, and schema-drift-safe.

---

## 7. Testing

`packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py`
exercises the full pipeline against synthetic fixture CSVs (derived from
`daily_report.py`'s compact-row format, never the real reference data):

- `test_e2e_budget_variance_recipe` — fixtures → `DatasetManager` → recipe →
  interactive-HTML `RenderedArtifact`.
- `test_rerun_updates_values_keeps_structure` — re-running with changed
  fixture data yields updated numbers, identical `dataModel` structure.
- `test_e2e_freeze_then_replay` — a simulated session envelope → freeze →
  replay produces an equivalent envelope, deterministically, with no LLM.
- `test_e2e_static_profile_delivery` — the same recipe rendered via
  `ssr_html` → `deliver_artifact` (mocked notification provider).

No pixel/screenshot assertions (no browser in CI) — structure is asserted
via the embedded `dataModel` JSON's key set and static HTML markers; value
changes are asserted on the actual numbers.
