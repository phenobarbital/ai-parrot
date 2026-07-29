---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: DataAgent Infographic — Infographic Authoring for Data Agents

**Date**: 2026-07-24
**Author**: jesuslara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Today the "Budget Variance" infographic (`sdd/artifacts/budget_variance_dashboard_Template.html`)
is produced OUTSIDE ai-parrot by two standalone Windows scripts
(`sdd/artifacts/daily_report.py` + `sdd/artifacts/executive_summary.py`): they read CSVs from a
OneDrive-synced folder, splice a JSON payload into the template's
`<script type="application/json" id="report-data">` tag, write the HTML to disk, and email it via
Outlook COM. Every new infographic of this style would require another hand-written script.

We want this workflow to live inside ai-parrot as an **agent capability**: an agent that
extends `PandasAgent` (which already carries a `DatasetManager` and a pandas REPL) so it can

1. take an infographic **template** (sections, hero cards, charts, summary),
2. follow a **descriptor** that declares which data fills each section (e.g. hero cards ←
   revenue projection + revenue variance + EBITDA),
3. **execute pandas transformation code** against the datasets in `DatasetManager` to build the
   per-section datasets,
4. hand those datasets to `InfographicToolkit`, which emits the final **HTML**, and
5. **persist** the artifact through `ArtifactStore` (disk first, S3-capable later), together with a
   **deterministic descriptor** that allows re-generating the infographic with fresh data.

Affected users: finance/ops report consumers (end users), and developers who today must write
one-off report scripts per dashboard.

**Key discovery during research**: FEAT-324 (`parrot/tools/infographic_recipes/` +
`parrot/outputs/a2ui/recipes/`) already implements the *deterministic replay* half of this
(recipe descriptor → DatasetManager fetch → registered transform chain → render → deliver), and
`InfographicToolkit` already accepts `recipe_store`/`recipe_runner`/`dataset_manager` and exposes
recipe tools. What is **missing** is the *authoring* half (an agent that explores data, writes the
transformations, builds the descriptor) and the **data-splice template mode** (JSON payload into a
`<script id="report-data">` tag — the budget_variance template is NOT Jinja).

## Constraints & Requirements

- **FEAT-324 spec G1 is inviolable**: recipes reference transformations by *registered name only* —
  never stored/executed code (`parrot/outputs/a2ui/recipes/transformers.py:3-6`). The agent's
  ad-hoc REPL code may produce one-shot artifacts, but anything replayable must compile down to
  registered `@infographic_transformer` functions. (User decision: **two-tier model**.)
- **Security/pctx**: every replay path MUST pass a real `PermissionContext` — a falsy `pctx` makes
  `DatasetManager` PBAC guards fail OPEN (`runner.py` security note). Scheduled refreshes need a
  resolved service principal (`parrot.auth.permission.build_principal_context`).
- **Persistence milestone 1 = local disk**: reuse the existing `ArtifactStore`
  (`ConversationSQLiteBackend` + `OverflowStore` over the local `FileManagerInterface`, already
  selectable via `PARROT_OVERFLOW_STORE` / `PARROT_OVERFLOW_LOCAL_PATH`). S3 later is a
  configuration change, not an interface change. (User decision.)
- **Both template styles**: the new **data-splice** mode (self-contained HTML + JSON payload in a
  script tag, template untouched) AND the existing HTML+Jinja `render_template` path must be
  drivable by the same section descriptor. (User decision: "Ambos".)
- **Descriptor is machine-enforced**: Pydantic model, fail-fast validation of required
  datasets/columns per section BEFORE rendering (mirrors FEAT-324's `$bind` cross-check).
  (User decision.)
- **All three invocation modes**: conversational (chat), programmatic API, and scheduled runs.
  (User decision.)
- Async-first, Pydantic models, `self.logger`, no new blocking I/O; `uv` for any new dependency
  (none anticipated — this feature is pure composition of existing subsystems).
- The reference template is 259,581 bytes — over `OverflowStore.INLINE_THRESHOLD` (200 KB), so
  rendered artifacts will offload to the file manager. On the local backend that IS the
  "HTML on disk" requirement, for free.

---

## Options Explored

### Option A: `InfographicAuthoringMixin` — reusable authoring layer over FEAT-324 (two-tier)

A new mixin in `parrot/bots/mixins/` (same cooperative pattern as `ModelSwitchingMixin` /
`IntentRouterMixin`) that any `DatasetManager`-bearing agent — primarily `PandasAgent` — composes:
`class MyAgent(InfographicAuthoringMixin, PandasAgent)`. The mixin:

- wires a pre-configured `InfographicToolkit` (with `artifact_store`, `recipe_store`,
  `dataset_manager`) into the agent's tool set and system prompt;
- introduces the **`SectionDescriptor`** Pydantic contract: template ref + mode
  (`jinja` | `data-splice`) + per-section entries (section name, payload key / bind pointer,
  required dataset aliases + columns, semantic hint for the LLM);
- exposes authoring methods: `generate_infographic(...)` (tier 1: one-shot — the agent uses its
  REPL to build the section datasets ad hoc, descriptor validated fail-fast, HTML rendered and
  persisted, provenance descriptor returned) and `publish_recipe(...)` (tier 2: map the authored
  logic onto **registered transformers**; if a step has no matching transformer, report the gap
  with a suggested implementation for a developer to register — G1 stays intact);
- extends `InfographicToolkit` with a **data-splice render mode** (new tool, e.g.
  `infographic_render_data_template`): inject a JSON payload into a configurable
  `<script type="application/json" id="...">` marker, generalizing `splice_into_template()` from
  `daily_report.py`.

Replay/refresh is NOT reimplemented: tier-2 recipes run through the existing `RecipeRunner`
(chat tool / REST / scheduler triggers already exist per FEAT-324 G6).

✅ **Pros:**
- Reuses the entire FEAT-324 replay pipeline — the feature is mostly *authoring UX + one new
  render mode*, not new infrastructure.
- Mixin composes onto `PandasAgent` today and onto future data agents tomorrow (user-requested
  shape); no inheritance lock-in.
- G1 security posture preserved; the ad-hoc/replayable boundary is explicit in the API.
- Disk→S3 persistence is pure configuration (`build_overflow_store`).

❌ **Cons:**
- Two-tier model means a one-shot infographic is NOT automatically refreshable — publishing
  requires transformer coverage, which may need developer involvement for novel transforms.
- Data-splice templates are opaque to the catalog validator (client-side JS renders the payload),
  so validation is limited to the descriptor's payload-schema check, weaker than the `$bind`
  cross-check of catalog layouts.
- Cooperative-mixin MRO wiring needs care (must not fight `IntentRouterMixin`).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Pure composition: pandas, pydantic, jinja2 already in the dependency tree |

🔗 **Existing Code to Reuse:**
- `parrot/bots/mixins/model_switching.py` — cooperative mixin pattern to mirror
- `parrot/tools/infographic_toolkit.py` — toolkit to extend with data-splice mode (constructor already takes `recipe_store`/`recipe_runner`/`dataset_manager`)
- `parrot/tools/infographic_recipes/runner.py` — `RecipeRunner.run()` for all replay
- `parrot/outputs/a2ui/recipes/{models,transformers,store}.py` — `InfographicRecipe`, `TransformStep`, `@infographic_transformer`, `FileRecipeStore`
- `parrot/storage/artifacts.py` + `parrot/storage/overflow.py` — persistence
- `sdd/artifacts/daily_report.py::splice_into_template` — reference logic for the data-splice renderer

---

### Option B: Standalone `DataInfographicAgent(PandasAgent)` subclass

A dedicated agent class in `parrot/bots/` that hard-wires DatasetManager + InfographicToolkit +
ArtifactStore + recipe store, with its own backstory/system prompt tuned for report building, and
registered via `@register_agent("data-infographic")`.

✅ **Pros:**
- Simplest mental model: "the infographic agent"; zero MRO subtleties.
- One obvious place for report-authoring prompts and defaults.

❌ **Cons:**
- Locks the capability to one class — a future SQL/finance agent wanting infographics would have
  to inherit from it or duplicate wiring (user explicitly preferred reusability).
- Encourages divergence from `PandasAgent` improvements over time.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | same reuse as Option A |

🔗 **Existing Code to Reuse:**
- Same list as Option A, plus `parrot/bots/data.py` (`PandasAgent`) as base class.

---

### Option C: No new agent surface — toolkit wiring + prompts only

Do everything inside `InfographicToolkit`: add the data-splice mode and the descriptor model
there, document a recommended `PandasAgent + InfographicToolkit` configuration, and rely on the
existing recipe tools for persistence/replay. No mixin, no subclass.

✅ **Pros:**
- Smallest diff; no new bot-layer concepts.
- Toolkit improvements benefit every consumer immediately.

❌ **Cons:**
- No programmatic authoring API on the agent (`generate_infographic()` / `publish_recipe()`);
  scheduled and handler-driven use must reconstruct wiring each time.
- The descriptor-driven authoring loop (validate sections → build datasets → render) would live
  only in prompts — fragile, not machine-enforced end to end.
- Doesn't satisfy the "new type of agent" intent of the request.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/tools/infographic_toolkit.py`, FEAT-324 recipe subsystem (as in Option A).

---

### Option D (unconventional): Retire data-splice — compile the dashboard into an A2UI catalog recipe

Instead of supporting self-contained JS templates, convert `budget_variance_dashboard_Template.html`
into catalog components (`LayoutSpec` + `$bind` pointers) and author ONLY FEAT-324 recipes. The
"template + descriptor" pair becomes a single recipe; hero cards/charts/summary become catalog
components; replay, validation, and delivery are 100% the existing pipeline.

✅ **Pros:**
- One representation for everything; strongest validation (`$bind` cross-check catches every
  missing data key); no second render mode to maintain.
- The infographic becomes theme-able and component-reusable across reports.

❌ **Cons:**
- Requires porting a large hand-crafted JS dashboard (259 KB, custom charts/interactions) into
  catalog components — high effort, and any visual gap versus the approved dashboard is a
  regression for stakeholders.
- Doesn't help the general case the user described: teams WILL keep handing us finished HTML
  templates; "convert it first" is a heavy on-ramp.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | catalog/renderers already exist in `parrot/outputs/a2ui/` |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/`, `parrot/outputs/a2ui/renderers/`, recipes subsystem.

---

## Recommendation

**Option A** is recommended (and matches the user's Round-2 decisions):

- The user explicitly chose a **reusable mixin** over a dedicated subclass, and chose to have the
  agent **author FEAT-324 recipes** rather than build a parallel replay path — Option A is the
  only option that does both.
- It trades away automatic replayability of ad-hoc work (tier 1 one-shots are not refreshable
  until their logic is mapped to registered transformers) in exchange for keeping G1's
  no-stored-code security boundary intact. That trade is acceptable: the high-value recurring
  reports (daily budget variance) justify one-time transformer registration, while exploratory
  one-shots don't need replay.
- It accepts weaker validation for data-splice templates (payload-schema only) as the cost of
  supporting stakeholder-approved, hand-crafted HTML dashboards as-is. Option D shows the
  stronger-validation path exists later if a template is ever worth porting.
- Persistence rides entirely on existing, configurable infrastructure (SQLite backend + local
  overflow now, S3 by env change later) — no new storage abstraction to maintain.

---

## Feature Description

### User-Facing Behavior

**Conversational**: a user chats with a `PandasAgent`-based agent composed with the mixin:
*"Genera la infografía de budget variance con los datos de hoy"*. The agent inspects the
template's `SectionDescriptor`, uses its pandas REPL to build each declared section dataset from
`DatasetManager` (e.g. hero cards ← revenue projection, revenue variance %, EBITDA variance;
divisions table ← per-division breakdown; trend chart ← first-of-month vs yesterday vs today),
renders the HTML via the toolkit, and replies with the artifact reference (path/URL) plus a
summary of what was built. If the user then says *"publícala como reporte diario"*, the agent
attempts tier-2 publication: it maps each section build onto registered transformers and saves an
`InfographicRecipe`; from then on the existing FEAT-324 tools (`infographic_run_recipe`, REST,
scheduler) refresh it deterministically with fresh data.

**Programmatic**: `await agent.generate_infographic(template="budget_variance", descriptor=...,
params={...})` returns the render result + provenance descriptor; `await agent.publish_recipe(...)`
returns the saved recipe (or a structured "transformer gap" report). Scheduled refresh is NOT new
code: it is FEAT-324's scheduler trigger running the published recipe under a service principal.

**Descriptor round-trip**: every generated artifact carries its descriptor (template ref, mode,
section→data mapping, dataset sources, params). For tier-2 artifacts the descriptor IS the recipe
name + params — deterministic re-generation guaranteed by `RecipeRunner`.

### Internal Behavior

1. **Descriptor contract** (`SectionDescriptor`, Pydantic, `extra="forbid"`): template name +
   mode (`jinja` | `data-splice`) + splice marker id (default `report-data`) + `sections[]`, each
   declaring: name, target (payload JSON-pointer for data-splice / context key for Jinja),
   required dataset aliases and columns, expected shape (records/scalar/mapping), and a semantic
   hint. Registered alongside the template (mirrors `get_template_contract`).
2. **Fail-fast validation gate**: before any render, the mixin checks every section's required
   datasets/columns against `DatasetManager` (via `get_dataset_entry`) and the assembled payload
   against the descriptor's shape declarations — unmet sections abort with a structured error
   listing exactly what is missing (same philosophy as FEAT-324's `$bind` cross-check and
   `InfographicValidationError`).
3. **Data-splice render mode** (new in `InfographicToolkit`): takes the registered self-contained
   HTML template + the validated payload dict, injects `json.dumps(payload)` into the
   `<script type="application/json" id="...">` element (generalized `splice_into_template`),
   wraps the result in the standard `InfographicRenderResult`, and persists via `ArtifactStore`
   exactly like the existing render paths.
4. **Tier 1 (one-shot)**: the LLM builds section datasets with ad-hoc REPL pandas code
   (`PythonPandasTool`, `build_block`-style flow). The provenance descriptor records datasets,
   params, and section mapping; the ad-hoc code is captured as *audit metadata only* — never
   executed on replay (G1).
5. **Tier 2 (publish)**: the mixin resolves each section build to a `TransformStep`
   (registered transformer name + inputs + params). Full coverage → save `InfographicRecipe`
   via the recipe store (`(name, owner)`-scoped). Partial coverage → return a gap report with
   suggested transformer source for human registration (promotion flow — see Open Questions).
6. **Persistence**: `ArtifactStore.save_artifact(user_id, agent_id, session_id, artifact)` with
   the backend/overflow resolved by the existing factories; the 259 KB-class HTML payloads exceed
   the 200 KB inline threshold and land on the overflow file manager → local disk in milestone 1,
   S3 when `PARROT_OVERFLOW_STORE=s3`.

### Edge Cases & Error Handling

- **Missing dataset/columns**: validation gate aborts pre-render with the per-section deficit
  list; the agent can then ask the user or call `add_query`/`refresh_data` to fill the gap.
- **Template missing the splice marker**: structured error (like `splice_into_template`'s
  "template edited/corrupted" ValueError) naming the expected script-tag id.
- **Payload not JSON-serializable / NaN handling**: serializer must coerce numpy/pandas scalars
  and reject silently-lossy values with a clear error.
- **`pctx` absent on replay/scheduled runs**: refuse to run (fail closed) — never invoke
  `RecipeRunner.run()` with falsy `pctx`; scheduled jobs must resolve a service principal first.
- **Publish with unregistered transforms**: never silently degrade — return the explicit gap
  report; the recipe is NOT saved partially.
- **Recipe name collisions**: store keys by `(name, owner)`; publishing over an existing name
  requires explicit overwrite intent.
- **Oversized payloads**: overflow offload is automatic; if the file manager write fails,
  `OverflowStore` falls back inline with a warning (existing behavior — surface it in the result).
- **Stale data**: `DataSourceSpec.force_refresh=True` default (spec G3) keeps replays fresh;
  tier-1 one-shots use whatever is loaded, and the descriptor records the snapshot timestamps.

---

## Capabilities

### New Capabilities
- `infographic-authoring-mixin`: `InfographicAuthoringMixin` in `parrot/bots/mixins/` — authoring
  API (`generate_infographic`, `publish_recipe`), toolkit wiring, two-tier model.
- `infographic-data-splice`: data-splice render mode in `InfographicToolkit` (JSON payload into a
  script-tag marker of a self-contained HTML template) + its tool exposure.
- `infographic-section-descriptor`: machine-enforced `SectionDescriptor` contract + fail-fast
  validation gate shared by both render modes.

### Modified Capabilities
- `infographictoolkit` (FEAT-197 spec): gains the data-splice mode and descriptor-aware
  validation; existing tools/behavior unchanged.
- (No changes expected to FEAT-324 recipe models; if descriptor storage needs a field on
  `InfographicRecipe`, that is an additive, versioned change — flagged in Open Questions.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/mixins/` | extends (new module) | `InfographicAuthoringMixin`, mirrors `model_switching.py` cooperative pattern |
| `parrot/tools/infographic_toolkit.py` | modifies | new data-splice render tool + descriptor validation; constructor untouched |
| `parrot/bots/data.py` (`PandasAgent`) | depends on | composition target; no changes anticipated (mixin uses existing hooks/`attach_dm`) |
| `parrot/tools/dataset_manager/tool.py` | depends on | `get_dataset_entry`/`fetch_dataset` used by validation gate; read-only |
| `parrot/tools/infographic_recipes/runner.py` | depends on | all replay; no changes |
| `parrot/outputs/a2ui/recipes/` | depends on | `InfographicRecipe`, `TransformStep`, transformer registry, stores; new domain transformers (e.g. `day_totals`, `division_breakdown`) get REGISTERED here or in a domain module |
| `parrot/storage/` | depends on | `ArtifactStore` + `build_overflow_store` (local now, S3 later); no changes |
| `parrot/auth/` | extends | new **system account** principal for scheduled refreshes (resolved via `build_principal_context`) — see resolved Open Question 3 |
| `sdd/artifacts/budget_variance_dashboard_Template.html` | reference asset | first data-splice template; ships as test fixture/registered template |

No new external dependencies. No breaking changes. Deployment: two env vars already govern the
disk milestone (`PARROT_OVERFLOW_STORE`, `PARROT_OVERFLOW_LOCAL_PATH`).

---

## Code Context

### User-Provided Code

```python
# Source: sdd/artifacts/daily_report.py:185-200 — the logic the data-splice mode generalizes
def splice_into_template(template_html: str, report_data: dict) -> str:
    """Replace the contents of the <script id="report-data"> tag with fresh JSON."""
    start_marker = '<script type="application/json" id="report-data">'
    end_marker = "</script>"

    start_idx = template_html.find(start_marker)
    if start_idx == -1:
        raise ValueError("Could not find the report-data script tag in the template. "
                          "Has the template file been edited/corrupted?")
    content_start = start_idx + len(start_marker)
    content_end = template_html.find(end_marker, content_start)
    if content_end == -1:
        raise ValueError("Could not find the closing </script> tag after report-data.")

    new_json = json.dumps(report_data)
    return template_html[:content_start] + "\n" + new_json + "\n" + template_html[content_end:]
```

```python
# Source: sdd/artifacts/executive_summary.py:40-51 — example transformation to become a
# registered @infographic_transformer for tier-2 publication (payload row format:
# [division, project, revActual, revBudget, ebitdaActual, ebitdaBudget])
def day_totals(rows: list) -> dict:
    rev_a = sum(r[2] for r in rows)
    rev_b = sum(r[3] for r in rows)
    eb_a = sum(r[4] for r in rows)
    eb_b = sum(r[5] for r in rows)
    return {
        "rev_actual": rev_a, "rev_budget": rev_b,
        "rev_variance": rev_a - rev_b,
        "rev_variance_pct": (rev_a - rev_b) / rev_b * 100 if rev_b else 0,
        "ebitda_actual": eb_a, "ebitda_budget": eb_b,
        "ebitda_variance": eb_a - eb_b,
    }
# executive_summary.py:54-71 division_breakdown(rows) is the second candidate transformer.
# daily_report.py builds the payload as {"days": {"YYYYMMDD": [rows...]}} (build_report_data,
# daily_report.py:155-182); the template consumes exactly that shape client-side.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/data.py:354
class PandasAgent(IntentRouterMixin, BasicAgent):
    def attach_dm(self, dm: DatasetManager) -> None: ...            # line 475
    def add_dataframe(self, name, df, metadata=None, ...) -> str:   # line 2224
    # also: add_query, refresh_data, list_dataframes, ask (forces PythonPandasTool)

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:501
class DatasetManager(AbstractToolkit):
    async def add_dataset(...): ...                                  # line 962
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:  # line 2250
    async def fetch_dataset(...): ...                                # line 3266

# From packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:144
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store: ArtifactStore,
                 template_dirs: Optional[Any] = None,
                 templates: Optional[Dict[str, str]] = None,
                 emit_a2ui: bool = False,
                 recipe_store: Optional[AbstractRecipeStore] = None,
                 recipe_runner: Optional[RecipeRunner] = None,
                 dataset_manager: Optional[Any] = None, **kwargs) -> None: ...  # line 177
    # tools: infographic_render, infographic_render_template, infographic_list_templates,
    #        infographic_get_template_contract, infographic_validate_blocks, build_block;
    #        + 4 recipe tools (save/list/run/get_recipe_contract) when recipe_store is set.
class InfographicValidationError(Exception): ...     # line 93
class InfographicRenderResult(BaseModel): ...        # line 124

# From packages/ai-parrot/src/parrot/storage/artifacts.py:27
class ArtifactStore:
    def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None: ...
    async def save_artifact(self, user_id: str, agent_id: str, session_id: str,
                            artifact: Artifact) -> None: ...

# From packages/ai-parrot/src/parrot/storage/overflow.py:20
class OverflowStore:
    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB
    def __init__(self, file_manager: FileManagerInterface) -> None: ...
    async def maybe_offload(self, data, key_prefix) -> Tuple[Optional[dict], Optional[str]]: ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel):        # line 74 — transformer name + inputs + params + output_key
class InfographicRecipe(BaseModel):    # ~line 163; .transforms: list[TransformStep]  (line 180)

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
# "Recipes reference transformations by registered name — never stored/executed code (spec G1)"
def infographic_transformer(name, ...):  # line 164 — registration decorator
# TransformerRegistry.register raises on re-registering a DIFFERENT function (line ~103)

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class AbstractRecipeStore(ABC):        # line 125 — save/get/list/delete keyed by (name, owner)
class FileRecipeStore(AbstractRecipeStore):  # line 165 — on-disk recipe store

# From packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                    # __init__ line 194
    async def run(self, name: str, *, params: dict | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
# SECURITY: falsy pctx ⇒ DatasetManager PBAC fails OPEN; callers must build a real
# PermissionContext (parrot.auth.permission.build_principal_context).
```

#### Verified Imports
```python
# Confirmed via packages/ai-parrot/src/parrot/storage/__init__.py:
from parrot.storage import OverflowStore              # __init__.py:17
from parrot.storage import ConversationSQLiteBackend  # __init__.py:21 (also Postgres/Mongo)
from parrot.storage.backends import build_overflow_store
# build_overflow_store(override=None) -> OverflowStore — resolves PARROT_OVERFLOW_STORE;
# default for non-dynamodb backends is LOCAL filesystem under PARROT_OVERFLOW_LOCAL_PATH.
from parrot.interfaces.file.abstract import FileManagerInterface  # overflow.py:17 imports it
# Local/S3/GCS/Temp implementations: parrot/interfaces/file/{local,s3,gcs,tmp}.py
```

#### Key Attributes & Constants
- `OverflowStore.INLINE_THRESHOLD` → `int`, 200 KB (parrot/storage/overflow.py:34)
- `_URL_EXPIRY_SECONDS` via env `INFOGRAPHIC_URL_EXPIRY_SECONDS`, default 604800 (parrot/storage/artifacts.py:24)
- Template splice anchor: `<script type="application/json" id="report-data">` at
  `sdd/artifacts/budget_variance_dashboard_Template.html:106` (file size 259,581 bytes)
- Mixin pattern references: `parrot/bots/mixins/{identity,intent_router,model_switching}.py`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.mixins.InfographicAuthoringMixin`~~ — to be created by this feature
- ~~`DataInfographicAgent`~~ — no such class anywhere; the feature ships a mixin, not a subclass
- ~~data-splice / `report-data` handling in `InfographicToolkit`~~ — zero hits in
  `infographic_toolkit.py`; `render_template` is Jinja-only today
- ~~a standalone `FileStore` artifact abstraction~~ — disk persistence is
  SQLite `ConversationBackend` + local `FileManagerInterface` overflow, NOT a new store class
- ~~a filesystem `ConversationBackend`~~ — backends are sqlite/postgres/mongodb/dynamodb only
- ~~`SectionDescriptor`~~ — to be created; today's closest analogue is the positional block
  contract returned by `get_template_contract`
- ~~registered transformers `day_totals`/`division_breakdown`~~ — exist only as plain functions
  in `sdd/artifacts/executive_summary.py`; must be ported + registered for tier-2

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The `SectionDescriptor` contract is the shared spine — the
  toolkit's data-splice mode, the mixin's validation gate, and the publish path all consume it.
  Only the domain-transformer registration (porting `day_totals`/`division_breakdown`) and
  docs/fixtures are genuinely independent.
- **Cross-feature independence**: Touches `parrot/tools/infographic_toolkit.py`, which FEAT-324
  follow-ups may also touch — check `sdd/tasks/index/` for in-flight infographic work before
  cutting the worktree. No overlap with storage or bots/flows in-flight specs identified.
- **Recommended isolation**: `per-spec` (one worktree, sequential tasks).
- **Rationale**: descriptor-first sequencing (contract → toolkit mode → mixin → publish path →
  fixtures/e2e) has hard dependencies at each step; parallel worktrees would all block on the
  contract task anyway.

---

## Open Questions

- [x] Transformer **promotion flow** (agent-proposed transform code → human review → registered
  `@infographic_transformer`): in scope for v1 as a gap-report + suggested-source output only, or
  does v1 also need tooling (e.g. a `document_skill`-style write path)? — *Owner: jesuslara*:
  v1 emits the gap report (with suggested transformer source) only; no promotion tooling.
- [x] Should tier-1 descriptors persist the ad-hoc REPL code as **audit metadata** (never
  executed) or omit code entirely to avoid any temptation to replay it? — *Owner: jesuslara*:
  do NOT persist python code — tier-1 descriptors record datasets/params/section mapping only.
- [x] Which **service principal** do scheduled refreshes run under, and who provisions it
  (`build_principal_context` inputs) for the daily budget-variance job? — *Owner: jesuslara*:
  a **system account** entity must be created (new system-principal concept); scheduled
  refreshes run under it via `build_principal_context`. Provisioning that entity is part of
  this feature's scope (or a prerequisite task in the spec).
- [x] Where does the `SectionDescriptor` live for tier-2 recipes — additive versioned field on
  `InfographicRecipe`, or a parallel descriptor store keyed by the same `(name, owner)`? —
  *Owner: spec author*: additive versioned field on `InfographicRecipe`.
- [x] Template registration for budget_variance: `template_dirs` on-disk registry vs in-memory
  `add_template` at agent configure time — and does the 259 KB template ship in the repo or get
  deployed as data? — *Owner: jesuslara*: registered via `template_dirs`; the template
  directory stays **gitignored** for now (deployed as data, not versioned). NOTE:
  `.gitignore` already has a global `templates/` rule (line 245), which covers this if the
  directory is named `templates/`.
- [x] Email/Teams **delivery** of the generated report (the original script emailed via Outlook):
  reuse FEAT-324 `RenderSpec.delivery` in v1 or defer? — *Owner: jesuslara*: v1 MUST use
  `RenderSpec.delivery` for report delivery.
