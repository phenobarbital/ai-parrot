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

FEAT-420 layers an optional, declarative **narrative** step onto tier 2
(`SectionDescriptor.narrative`) plus a first-class declarative **layout**
(`SectionDescriptor.layout`) for the A2UI publish path — see the "Tier 2 —
publication" section below and `docs/outputs/infographic-recipes.md` §6
("Narrative (FEAT-420)") for the full determinism-boundary contract (numbers
always deterministic, prose always best-effort and never blocking).

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

### `layout` and `narrative` (FEAT-420, both optional)

Two additive fields target the **tier-2 publish path** specifically
(`publish_recipe`, below) — neither affects tier-1 rendering:

```python
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec

descriptor = SectionDescriptor(
    template="budget_variance.html",
    mode="data-splice",
    sections=[...],
    layout=LayoutSpec(                       # A2UI catalog-component tree
        component="Infographic",
        properties={"variance": {"$bind": "/variance_analysis"}},
    ),
    narrative=NarrativeSpec(                  # reference to a skill, never code
        skill="budget-narrative",
        facts_key="narrative_facts",          # a transform step's output_key
        output_key="narrative",               # data_model key the prose lands in
    ),
)
```

- **`layout`** (`LayoutSpec`) — when set, `publish_recipe` saves it **verbatim**
  as the recipe's `layout` instead of building today's template-based
  `LayoutSpec` (`component="Infographic"`, `properties={"template": ...}`).
  Absent → unchanged legacy behaviour (spec criterion G-G). This is the
  first-class declarative alternative for the A2UI publish path — see
  "Tier 1 — one-shot authoring" below for the equivalent tier-1/data-splice
  override point.
- **`narrative`** (`NarrativeSpec`) — always carried through to the saved
  recipe unchanged (never interpreted or validated by
  `InfographicAuthoringMixin` itself). `skill` is a registered skill *name*,
  never a prompt or template string; `facts_key` must name a prior
  transform step's `output_key` (typically the `narrative_facts`
  transformer's output). See `docs/outputs/infographic-recipes.md` §6 for
  how the saved recipe replays this at `RecipeRunner.run()` time.

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
pandas REPL tools conversationally) for richer transformations **on this
tier-1/data-splice path**.

This override point is tier-1-only. For the tier-2/A2UI publish path
(`publish_recipe`, below), the first-class declarative alternative is
`SectionDescriptor.layout` (a `LayoutSpec` used verbatim, with `$bind`
pointers into the assembled `dataModel` — no python override needed) — see
"The section descriptor contract" above and `docs/outputs/infographic-recipes.md`
§2 for the full `$bind` walkthrough.

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

"Full coverage" is a **per-section** check: every `SectionSpec.name` in
`descriptor.sections` must resolve to a registered transformer (its name,
normalised to a Python identifier via `re.sub(r"\W+", "_", name).strip("_")`
— e.g. `"top-movers"` → `top_movers`). There is no partial-save; the first
unmapped section anywhere in `descriptor.sections` downgrades the *entire*
publish to a `GapReport`, even if every other section resolves. To reach
full coverage, either name each section to match an already-registered
transformer, or register the missing transformer (via
`@infographic_transformer`, e.g. as `library.py` does for
`narrative_facts`) and re-run `publish_recipe`.

`descriptor.layout` and `descriptor.narrative` (FEAT-420, both optional —
see "The section descriptor contract" above) are carried straight through
to the saved `InfographicRecipe`'s `layout`/`narrative` fields, unchanged,
on a full-coverage publish. A section whose `datasets` entries are actually
prior transform steps' `output_key`s (as `narrative_facts` declares —
`requires_columns={}`) is **excluded** from the saved recipe's
`data_sources`, since it names a `TransformStep.output_key`, not a
`DatasetManager` alias to fetch.

The `section_descriptor` field is additive — the recipe `schema_version` stays
`1` and pre-existing recipes still load.

**Reference implementation** (FEAT-420): `agents/finance_reporter.py`'s
`FinanceReporter` (`NarrativeMixin + InfographicAuthoringMixin + PandasAgent`)
demonstrates the full tier-2/A2UI path — `report_descriptor()` and
`dashboard_descriptor()` both declare `layout`/`narrative` and publish via
`publish_recipe`. `FinanceReporter` is now **A2UI-only**: it no longer
demonstrates the tier-1 data-splice path (`generate_infographic` +
`_build_section_payload`), which its pre-FEAT-420 version did. The
data-splice render mode itself is unaffected and remains fully supported —
see "Tier 1 — one-shot authoring" above for a data-splice example.

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

`run_scheduled_refresh` needs **no change** to support FEAT-420 narration
either — it takes a `RecipeRunner` **instance**, and narrator injection
happens once, at that instance's construction (`RecipeRunner(store,
dataset_manager, narrator=...)`, see `docs/outputs/infographic-recipes.md`
§6 "Injecting a narrator"). A `recipe_runner` built without a `narrator`
still replays a recipe with a `narrative` block deterministically — the
narrative step is simply skipped (spec criterion G-E).

---

## See also

- [`InfographicToolkit`](infographic_toolkit.md) — render/validate/recipe tools.
- FEAT-324 recipes: `docs/outputs/infographic-recipes.md`.
- FEAT-420 narrative layer, full determinism-boundary contract (numbers
  always deterministic, prose always best-effort and never blocking),
  figure guard, and optional `$bind` bindings:
  `docs/outputs/infographic-recipes.md` §6 ("Narrative (FEAT-420)").
- Spec: `sdd/specs/dataagent-infographic.spec.md`.
- Spec: `sdd/specs/finance-reporter-tier2-narrative.spec.md`.
