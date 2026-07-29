# Infographic Authoring for Data Agents (FEAT-326)

`InfographicAuthoringMixin` turns any `DatasetManager`-bearing agent (e.g.
`PandasAgent`) into an **infographic author**: it inspects a machine-enforced
section descriptor, builds each section's data, renders an HTML artifact
(data-splice or Jinja), persists it, and — optionally — publishes a
deterministic, replayable [FEAT-324](infographic_toolkit.md) recipe.

This is the *authoring* half of the workflow that produced the standalone
"Budget Variance" daily report; the *deterministic replay* half is FEAT-324's
`RecipeRunner`. This feature adds one new render mode (**data-splice**) and does
not build a parallel replay path.

---

## Composition

`InfographicAuthoringMixin` is a **cooperative mixin** (same pattern as
`ModelSwitchingMixin`). Mix it in **before** the agent class:

```python
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin

class ReportingAgent(InfographicAuthoringMixin, PandasAgent):
    ...

agent = ReportingAgent(
    name="reporter",
    artifact_store=artifact_store,       # builds an InfographicToolkit for you
    recipe_store=recipe_store,           # enables publish_recipe (tier 2)
    template_dirs=["/srv/infographic-templates"],  # data-splice template registry
)
```

Pass a pre-built toolkit instead of the pieces with
`infographic_toolkit=<InfographicToolkit>`. The mixin registers the toolkit's
tools on the agent and binds it (prompt guidance + render scope) — the standard
`infographic_*` tools remain available for conversational authoring.

The MRO stays cooperative: `IntentRouterMixin` behaviour on `PandasAgent` is
untouched.

---

## The section descriptor contract

A `SectionDescriptor` (Pydantic, `extra="forbid"`) declares which data fills each
section of a template. It is validated **fail-fast**: rendering never starts
with unmet datasets/columns, and the error enumerates *every* deficit.

```python
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec

descriptor = SectionDescriptor(
    template="budget_variance.html",
    mode="data-splice",                  # or "jinja"
    splice_marker_id="report-data",      # data-splice only
    sections=[
        SectionSpec(
            name="days",
            target="/days",              # JSON-pointer (data-splice) or context key (jinja)
            datasets=["snapshots"],      # required DatasetManager aliases
            columns={"snapshots": ["rev_actual", "rev_budget"]},  # required columns
            shape="mapping",             # records | scalar | mapping | table
        ),
    ],
)
```

- `validate_descriptor_datasets(descriptor, dataset_manager)` — checks every
  section's datasets/columns against `DatasetManager.get_dataset_entry`.
- `validate_payload_shape(descriptor, payload)` — checks an assembled payload
  against each section's declared `shape`.

Both raise a single `InfographicValidationError` listing all deficits.

---

## Tier 1 — one-shot authoring

```python
result, provenance = await agent.generate_infographic(
    "budget_variance.html", descriptor, params={"title": "Daily Budget Variance"},
)
```

Flow: **validate → build section data → render → persist → return provenance**.

- Data-splice mode injects the JSON payload into the template's
  `<script type="application/json" id="...">` marker (the template is otherwise
  byte-identical). Jinja mode renders through the template engine.
- The artifact persists through the existing `ArtifactStore` (SQLite backend +
  local-filesystem overflow; switching to S3 is a `PARROT_OVERFLOW_STORE`
  change, no code change).
- `ProvenanceDescriptor` records the descriptor, dataset snapshot timestamps,
  the artifact id, and `tier="one-shot"` — **never** the python code used to
  build the data (FEAT-324 G1 stays inviolable).

The default programmatic build shapes each section's declared datasets/columns
per `SectionSpec.shape`; override `_build_section_payload` (or drive the agent's
pandas REPL tools conversationally) for richer transformations.

### Data-splice mode directly on the toolkit

```python
result = await toolkit.render_data_template(
    "budget_variance.html", payload, descriptor=descriptor, marker_id="report-data",
)
```

numpy/pandas scalars are coerced; `NaN`/`Infinity` are rejected loudly (they
would otherwise produce invalid JSON). A missing marker raises
`InfographicValidationError("SPLICE_MARKER_MISSING", ...)`.

Templates for this mode are registered via `template_dirs` (on-disk registry).
The deployed template directory is deliberately **gitignored** — deployed as
data, not versioned.

---

## Tier 2 — publication (recipe + gap report)

```python
recipe_or_gap = await agent.publish_recipe(
    "budget-daily", descriptor,
    owner=None,
    delivery={"provider": "email", "recipients": ["ops@example.com"]},
    overwrite=False,
)
```

`publish_recipe` maps each section onto a **registered** `@infographic_transformer`
(resolved by the section's name, normalised to an identifier) as a
`TransformStep`:

- **Full coverage** → saves an `InfographicRecipe` carrying the descriptor
  (additive optional `section_descriptor` field) and `RenderSpec.delivery`. From
  then on, refresh is a FEAT-324 `RecipeRunner.run()` — chat tool, REST, or
  scheduler. Nothing new to build.
- **Partial coverage** → returns a `GapReport` listing each unmapped section with
  a `suggested_source` transformer skeleton **for human review and
  registration** (never executed). The recipe is **not** saved.
- A `(name, owner)` collision requires `overwrite=True`.

The `section_descriptor` field is additive — the recipe `schema_version` stays
`1` and pre-existing recipes still load.

---

## Scheduled refresh — the system account

Scheduled refreshes have no interactive user, but `RecipeRunner.run()` must
receive a real `PermissionContext` (a falsy `pctx` makes `DatasetManager`'s PBAC
guards fail **open**). A config-declared **system account** provides one:

```bash
export PARROT_SYSTEM_ACCOUNT_ID=svc-reports
export PARROT_SYSTEM_ACCOUNT_TENANT=acme         # optional
export PARROT_SYSTEM_ACCOUNT_ROLES=reports.run   # optional, comma-separated
```

```python
from parrot.auth.system_account import run_scheduled_refresh

# Fail-closed: raises SystemAccountNotProvisioned if no account is configured;
# never forwards pctx=None.
await run_scheduled_refresh(recipe_runner, "budget-daily")
```

`resolve_system_account_context()` builds the `PermissionContext` via
`parrot.auth.permission.build_principal_context`; `run_scheduled_refresh` is the
caller-side guard that passes it as `pctx`. `RecipeRunner` itself is unchanged.

---

## See also

- [`InfographicToolkit`](infographic_toolkit.md) — render/validate/recipe tools.
- FEAT-324 recipes: `docs/outputs/infographic-recipes.md`.
- Spec: `sdd/specs/dataagent-infographic.spec.md`.
