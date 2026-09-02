---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI optional-binding lowering (`parrot_optional` reaches the wire)

**Feature ID**: FEAT-499
**Date**: 2026-09-02
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`LayoutSpec.metadata.extensions.parrot_optional` is a **write-only field**.
Authors declare it, `RecipeRunner` reads it for its own drift check and logs
that the binding "will be omitted rather than aborting the run" — and then
the render aborts anyway.

The chain, verified hop by hop on `dev`:

1. `RecipeRunner._check_bind_drift_or_raise` (`runner.py:595`) reads the
   layout-level set via the module helper `_optional_paths(layout)`
   (`runner.py:127`), finds `/narrative`, and logs the "will be omitted"
   line.
2. `_assemble_envelope_or_raise` (`runner.py:623`) then calls
   `build_infographic` (`builders.py:203`) or `build_surface`
   (`builders.py:50`). **Neither accepts or propagates `metadata`** — the
   wire component is built as
   `Component(id=component_id, component=component, **properties)`, so the
   layout's metadata is discarded at the boundary.
3. `baking._optional_paths(component)` (`baking.py:187`) reads
   `parrot_optional` off **each individual wire `Component`'s** metadata,
   gets an empty set, and `_resolve_value` (`baking.py:96`) raises.

Observed failure:

```
parrot.outputs.a2ui.baking.BakeError: Unresolvable data-model path '/narrative':
member 'narrative' not found in {...}
→ RecipeRunException(stage="render")
```

This is the FEAT-470 TASK-2542 v1→v2 migration seam. In v1 the marker rode
inline on the props as `{"$bind": ..., "optional": true}`, where
`compat.normalize_legacy_component` (`compat.py:140`) hoisted it into
**that component's own** `metadata.extensions.parrot_optional` — exactly
where `baking` looks. v2 moved the marker up to the `LayoutSpec` and never
built the return path down.

**Blast radius is every v2 recipe with an optional binding, not just
finance.** It also kills two FEAT-420 acceptance criteria outright:

- **G-E** (a published recipe replays deterministically with no narrator
  configured) — the no-narrator replay is precisely the case that crashes.
- **G-H** (the figure guard discards a whole narrative rather than let an
  invented figure through) — the guard works, discards the prose, and the
  render then crashes *because* the guard did its job.

Independently corroborated before this spec: `agents/flex_dashboard.py:553`
documents the same root cause from FEAT-491 and works around it by never
binding `/narrative` at all — which is not available to
`agents/finance_reporter.py`, whose `Report` profile is narrative-first.

A second, smaller defect sits directly downstream on the serving side:
`SurfaceNegotiationService._respond_html` (`ui_surfaces.py:232`) wraps only
its *import* in `try/except` and calls `InteractiveHTMLRenderer().render()`
unguarded, so any `BakeError` escapes as an uncaught 500 with a traceback on
**both** `GET /api/v1/ui/surfaces/{surface_id}` and the `A2UIHandler` mirror
`GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` (`a2ui.py:246`).
The sibling `_refresh` (`ui_surfaces.py:480`) already models the right
behaviour, mapping `RecipeRunException` to 502/422.

### Goals

- **G1** — A `parrot_optional` pointer declared on a `LayoutSpec` is honoured
  at bake time: the binding is omitted, the surrounding structure renders,
  and the run does not abort.
- **G2** — G1 holds for **both** layout shapes: a composite the renderer
  intercepts and bakes whole (`Infographic`), and one the renderer **lowers**
  into a primitive tree first (`Report`). These have different mechanics —
  see §2.
- **G3** — The three currently-failing FinanceReporter e2e tests pass without
  weakening their assertions or removing the `/narrative` bindings.
- **G4** — A render failure on the serving lane returns a structured JSON
  error with an appropriate status, never an uncaught traceback, on both the
  REST route and the `A2UIHandler` mirror.
- **G5** — No change to the A2UI v1.0 wire contract: every emitted envelope
  still validates against `agent_to_renderer.json` (FEAT-470 G1).
  `metadata.extensions.parrot_*` is the sanctioned carrier (FEAT-470 G4).

### Non-Goals (explicitly out of scope)

- Re-introducing the v1 inline `{"$bind": ..., "optional": true}` shape. The
  wire's `DataBinding` is `extra="forbid"` and has no such key; v2's
  metadata-based marker is the correct design and stays.
- Changing `RecipeRunner._check_bind_drift_or_raise`'s contract. Its
  layout-level read is correct — it is the *only* consumer that works today.
- Making unresolvable **non-optional** bindings survive. A required binding
  that does not resolve must still raise `BakeError`; that is the drift
  guard's whole purpose.
- Any FinanceReporter change. Its layouts already declare
  `metadata.extensions.parrot_optional` correctly and need no edit.

---

## 2. Architectural Design

### Overview

Two fixes, one per module.

**Module 1 — carry the marker to where baking looks.** `build_surface` and
`build_infographic` gain an optional `metadata` parameter, threaded by
`RecipeRunner._assemble_envelope_or_raise` from `recipe.layout.metadata`
onto the root `Component`. This alone fixes the `Infographic` branch.

It does **not** fix the `Report` branch, and the difference is the crux of
this spec. `InteractiveHTMLRenderer.render` (`interactive_html.py:571`)
calls `self._lower_composites(envelope)` **before** `bake_envelope`
(`interactive_html.py:572`), and `_lower_composites` (`:614`) skips only the
composites in `_INTERCEPTED` — `Chart`, `DataTable`, `Infographic`. So:

- `Infographic` layout → root component survives lowering intact, is baked
  whole (its nested section/KPICard/DataTable dicts live inside that one
  component's props), and `_optional_paths(root)` covers the entire subtree.
  **Root-level metadata is sufficient.**
- `Report` layout → `Report().lower(comp, data_model)` replaces the root
  with a tree of primitives, and the `/narrative` binding ends up on
  whichever lowered child carries it. That child has no metadata, so the
  root marker is gone before `bake_envelope` ever sees it. **Root-level
  metadata is NOT sufficient.**

So Module 1 must also make lowering propagate the marker: when
`_lower_composites` replaces a composite, each emitted child inherits the
parent's `metadata.extensions.parrot_optional` (union with its own, if any).
`SSRHTMLRenderer` uses the same lowering-then-bake order (FEAT-470
TASK-2543) and must get the identical treatment, or the `Report` profile
stays broken for `ssr-html` and `pdf` (`PDFRenderer(SSRHTMLRenderer)`).

**Module 2 — fail loudly but structurally.** `_respond_html` wraps the
render call and maps failures to a JSON error body, matching `_refresh`'s
existing shape. Both routes inherit the fix for free because they already
share the one `SurfaceNegotiationService` instance by design (FEAT-492 §2).

### Component Diagram

```
RecipeRunner._assemble_envelope_or_raise (runner.py:623)
   │  recipe.layout.metadata  ← NEW: threaded, previously dropped
   ▼
build_infographic / build_surface (builders.py:203 / :50)
   │  Component(metadata=...)  ← NEW parameter
   ▼
Renderer.render
   ├─ _lower_composites  ← NEW: propagate parrot_optional parent → children
   │     (Infographic intercepted & skipped; Report lowered)
   ▼
bake_envelope → _bake_component → _optional_paths(component)  (unchanged)
   ▼
binding omitted instead of BakeError


UISurfacesHandler.get ─┐
                       ├─→ SurfaceNegotiationService._respond_html
A2UIHandler._get_surface┘        │  ← NEW: guarded render → structured error
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `build_surface` / `build_infographic` (`builders.py:50`, `:203`) | extends signature | New optional `metadata` param; every existing caller keeps working (default `None`) |
| `RecipeRunner._assemble_envelope_or_raise` (`runner.py:623`) | modifies | Threads `recipe.layout.metadata` into both builder branches |
| `InteractiveHTMLRenderer._lower_composites` (`interactive_html.py:614`) | modifies | Propagates `parrot_optional` to lowered children |
| `SSRHTMLRenderer` lowering | modifies | Same change; `PDFRenderer` inherits it |
| `baking._optional_paths` / `_bake_component` (`baking.py:187`, `:194`) | uses, unchanged | Already correct — it is the only piece that was right all along |
| `SurfaceNegotiationService._respond_html` (`ui_surfaces.py:232`) | modifies | Guarded render + structured error |
| `A2UIHandler._get_surface` (`a2ui.py:246`) | uses, unchanged | Inherits Module 2 via the shared negotiation service |

### Data Models

No new models. `ComponentMetadata` (`outputs/a2ui/models.py:364`) and
`Component.metadata` (`:400`) already exist and already carry
`extensions.parrot_optional` — that is exactly what `compat.py:140` writes
on the legacy path.

### New Public Interfaces

```python
# parrot/outputs/a2ui/builders.py
def build_surface(
    component: str,
    properties: dict[str, Any],
    *,
    surface_id: str,
    component_id: str = _ROOT_COMPONENT_ID,
    data_model: dict[str, Any] | None = None,
    origin: ProducerOrigin = ProducerOrigin.LLM,
    metadata: ComponentMetadata | None = None,   # NEW
) -> CreateSurface: ...


def build_infographic(
    *,
    title: str,
    sections: Sequence[dict[str, Any]],
    subtitle: str | None = None,
    theme: str | None = None,
    surface_id: str = "infographic",
    data_model: dict[str, Any] | None = None,
    metadata: ComponentMetadata | None = None,   # NEW
) -> CreateSurface: ...
```

---

## 3. Module Breakdown

### Module 1: `parrot_optional` reaches the wire component (and survives lowering)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`,
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`,
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`,
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`
- **Responsibility**: Thread `LayoutSpec.metadata` onto the root wire
  `Component`, and propagate `metadata.extensions.parrot_optional` from a
  composite to the children it lowers into, so `baking._optional_paths`
  finds it in both the intercepted and the lowered case.
- **Depends on**: nothing (pure core + renderer change)

### Module 2: structured error on the HTML serving lane
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
- **Responsibility**: Guard the `render()` call in
  `SurfaceNegotiationService._respond_html` and return a structured JSON
  error, mirroring `_refresh`'s existing mapping instead of leaking a
  traceback. Covers the `A2UIHandler` mirror route automatically.
- **Depends on**: nothing (independent of Module 1; deliverable separately)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_build_surface_carries_metadata` | 1 | `build_surface(..., metadata=...)` puts it on the root `Component` |
| `test_build_infographic_carries_metadata` | 1 | Same for the `Infographic` branch |
| `test_builders_default_metadata_none` | 1 | Existing callers unaffected — no metadata key emitted |
| `test_runner_threads_layout_metadata` | 1 | `_assemble_envelope_or_raise` passes `recipe.layout.metadata` through |
| `test_optional_binding_omitted_intercepted` | 1 | `Infographic` layout + absent optional key → baked, binding dropped, no raise |
| `test_optional_binding_omitted_after_lowering` | 1 | `Report` layout (lowered) + absent optional key → baked, binding dropped, no raise |
| `test_required_binding_still_raises` | 1 | A non-optional unresolvable pointer STILL raises `BakeError` |
| `test_lowered_child_unions_own_and_parent_optional` | 1 | Child with its own `parrot_optional` keeps it and gains the parent's |
| `test_respond_html_render_failure_is_structured` | 2 | `render()` raising → JSON error body, no traceback |
| `test_respond_html_success_unchanged` | 2 | Happy path still returns `text/html` |
| `test_respond_html_missing_visualizations_still_501` | 2 | Existing ImportError branch not regressed |

### Integration Tests

| Test | Description |
|---|---|
| `test_report_profile_replay_no_narrator` | **Existing, currently failing** — must pass unmodified |
| `test_dashboard_profile_replay` | **Existing, currently failing** — must pass unmodified |
| `test_end_to_end_no_fabricated_figures` | **Existing, currently failing** — guard discards prose, render still succeeds |
| `test_surface_get_html_render_failure` | Mirror + REST route both return the structured error |

### Test Data / Fixtures

Reuse `packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py`'s
existing `wired_agent` / `recipe_store` fixtures and its `_FakeNarrator`
(`DERIVABLE` / `INVENTED`) — the failure is already reproduced there; no new
finance fixtures are needed.

---

## 5. Acceptance Criteria

- [ ] The three named e2e tests pass **without edits to the test file or to
      `agents/finance_reporter.py`'s layouts**
- [ ] A `Report`-layout (lowered) recipe with an absent optional binding
      renders instead of raising
- [ ] An `Infographic`-layout (intercepted) recipe with an absent optional
      binding renders instead of raising
- [ ] A non-optional unresolvable binding still raises `BakeError`
- [ ] `ssr-html` and `pdf` behave identically to `interactive-html` for both
      layout shapes
- [ ] `GET /api/v1/ui/surfaces/{id}` with `Accept: text/html` returns a
      structured JSON error (not a traceback) when the render fails
- [ ] `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{id}` returns the same
      structured error for the same input
- [ ] Every emitted envelope still validates against the v1.0
      `agent_to_renderer.json` schema (FEAT-470 G1 conformance suite green)
- [ ] No change to `build_surface`/`build_infographic` call sites elsewhere
- [ ] `pytest packages/ai-parrot/tests/ packages/ai-parrot-server/tests/` shows
      no NEW failures vs. the pre-change baseline (see §7 for the known
      pre-existing set)

---

## 6. Codebase Contract

> Line numbers verified against `dev` @ `84932e839` (2026-09-02).

### Verified Imports

```python
from parrot.outputs.a2ui.builders import build_infographic, build_surface   # builders.py:203, :50
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface  # models.py:400, :364
from parrot.outputs.a2ui.baking import BakeError, bake_envelope            # baking.py:46, :356
from parrot.outputs.a2ui.recipes.models import LayoutSpec                  # recipes/models.py:109
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
_ROOT_COMPONENT_ID = "root"                                          # line 43
def build_surface(component, properties, *, surface_id,
                  component_id=_ROOT_COMPONENT_ID, data_model=None,
                  origin=ProducerOrigin.LLM) -> CreateSurface:       # line 50
def build_infographic(*, title, sections, subtitle=None, theme=None,
                      surface_id="infographic",
                      data_model=None) -> CreateSurface:             # line 203

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception): ...                                      # line 46
_ABSENT = object()                                                   # line 53
def _resolve_value(value, *, data_model, scope_path, index,
                   optional_paths: set[str]) -> Any:                 # line 96
def _optional_paths(component: Component) -> set[str]:               # line 187
def _bake_component(component, *, data_model, scope_path, index,
                    id_suffix="") -> dict[str, Any]:                 # line 194
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]:  # line 356

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
def _collect_bind_pointers(value: Any) -> list[str]:                 # line 108
def _optional_paths(layout: LayoutSpec) -> set[str]:                 # line 127
class RecipeRunner:
    def _check_bind_drift_or_raise(self, recipe, data_model) -> None: # line 595
    def _assemble_envelope_or_raise(self, recipe, data_model):        # line 623
    async def _render_or_raise(self, recipe, envelope):               # line 647

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel):                                          # line 109
    metadata: Optional[ComponentMetadata] = None                      # line 150

# packages/ai-parrot-visualizations/.../a2ui_renderers/interactive_html.py
async def render(self, envelope, *, bake=True) -> RenderedArtifact:   # line 553
    lowered_envelope = self._lower_composites(envelope)               # line 571
    baked_components = bake_envelope(lowered_envelope)                # line 572
def _lower_composites(self, envelope) -> CreateSurface:               # line 614
    #  skips only `_INTERCEPTED` = Chart / DataTable / Infographic    # line 621

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class SurfaceNegotiationService:                                      # line 175
    async def _respond_html(self, record) -> web.Response:            # line 232
class UISurfacesHandler(BaseView):
    async def _refresh(self) -> web.Response:                         # line 480

# packages/ai-parrot-server/src/parrot/handlers/a2ui.py
    async def _get_surface(self) -> web.Response:                     # line 246
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_surface(metadata=)` | `Component(metadata=...)` | constructor kwarg | `builders.py:76`, `models.py:400` |
| `_assemble_envelope_or_raise` | `recipe.layout.metadata` | attribute read | `runner.py:623`, `recipes/models.py:150` |
| lowering propagation | `_optional_paths(component)` | metadata read at bake | `baking.py:187` |
| `_respond_html` guard | `_refresh`'s error shape | precedent to copy | `ui_surfaces.py:534-540` |

### Does NOT Exist (Anti-Hallucination)

- ~~`build_surface(..., optional_paths=[...])`~~ — no such parameter; the
  marker travels inside `ComponentMetadata.extensions`, not as its own arg.
- ~~`CreateSurface.metadata`~~ — the envelope has **no** envelope-level
  metadata field. Do not add one: `CreateSurface` is protocol-strict v1.0
  and a new top-level key would break FEAT-470 G1 conformance. Use the root
  `Component`'s `metadata.extensions` (the FEAT-470 G4 sanctioned carrier).
- ~~`LayoutSpec.optional`~~ / ~~`DataBinding.optional`~~ — neither exists.
  The wire `DataBinding` is `extra="forbid"`; the v1 inline `optional` key
  is legacy-only and reachable solely via `compat.normalize_legacy_component`.
- ~~`RecipeRunner.narrator.narrate_optional()`~~ — not a method. The
  narrative step is `_apply_narrative_best_effort` (`runner.py`), and the
  narrator protocol is just `narrate(facts, skill)`.
- ~~a `Report` entry in `_INTERCEPTED`~~ — `_INTERCEPTED` is Chart /
  DataTable / Infographic only (`interactive_html.py:621`). Adding `Report`
  to it is NOT the fix: it would change how Report renders, not how optional
  bindings resolve.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `metadata.extensions.parrot_*` is the sanctioned home for presentation
  semantics outside the v1.0 schema (FEAT-470 G4). Stay inside it.
- Additive, defaulted parameters only — every existing `build_surface` /
  `build_infographic` call site must keep working untouched.
- Union, never replace, when propagating to a lowered child that already
  carries its own `parrot_optional`.
- `self.logger` for the "optional binding omitted" path; it is an INFO-level
  degradation, not a warning.

### Known Risks / Gotchas

- **The two layout shapes fail differently.** Fixing only `build_*` makes
  the `Infographic` (dashboard) profile pass and leaves the `Report` profile
  still broken, because `Report` is lowered before baking. A green
  `test_dashboard_profile_replay` is therefore NOT evidence the feature is
  done — `test_report_profile_replay_no_narrator` is the one that proves the
  lowering path.
- **Three renderers, one behaviour.** `ssr_html` uses the same
  lowering-then-bake order and `PDFRenderer` subclasses it. A fix applied
  only to `interactive_html` silently leaves the PDF/SSR lanes broken.
- **Do not "fix" this by deleting the bindings.** `agents/flex_dashboard.py`
  legitimately worked around it that way under a no-core-changes constraint,
  but for a narrative-first `Report` the binding *is* the content.
- **Pre-existing failures to exclude from the baseline.** On `dev` @
  `84932e839`, `packages/ai-parrot/tests/unit/bots/` already fails
  independently of this work: `test_pandasagent_stale_data_variables` (3,
  fail in isolation) plus `test_infographic_authoring_mixin::
  test_validation_gate_blocks_before_render` and
  `test_flex_dashboard_agent::test_working_memory_and_infographic_toolkits_attached`
  (pass in isolation, fail in a full-directory run — test-ordering
  pollution). Do not attribute these to this feature, and do not fix them
  here.
- **FEAT-493 is landing concurrently** into the same files
  (`RenderSpec.layout` / TASK-2714 touched `runner.py:647`'s
  `_render_or_raise`; TASK-2715 added `catalog/parrot/filterbar.py`).
  Rebase before starting and re-check `runner.py` line numbers.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

- [ ] Should lowering propagate the **whole** `metadata.extensions` from
      parent to lowered children, or only the `parrot_optional` key?
      Whole-extensions is simpler and more future-proof for other
      `parrot_*` hints; key-only is narrower and cannot surprise an
      unrelated consumer. — *Owner: Jesus Lara*
- [ ] What status code should a failed HTML render return — `422`
      (unprocessable stored surface, matching `_refresh`'s non-`data` stage
      mapping) or `500`? `_refresh` uses 502 only for `stage="data"`, which
      has no analogue on a pure re-bake. — *Owner: Jesus Lara*
- [ ] Should `bake_envelope` additionally union optional paths across all
      components as a belt-and-braces guard, or is per-component resolution
      after correct propagation sufficient? — *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara + Claude | Initial draft from the FinanceReporter/A2UI compatibility review |
