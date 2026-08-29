# TASK-2543: RendererCapabilities.supported_*, RenderedArtifact.metadata['degraded'], SSR-HTML y PDF con 18 primitivas

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2540
**Assigned-to**: unassigned
**Parallel**: false — Abre el carril de renderers; toca core renderers/__init__ y artifacts (compartidos), por eso va primero y en serie.

---

## Context

Módulo 7 (parte core + ssr_html + pdf).

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `RendererCapabilities.supported_catalog_ids: list[str] = [BASIC_CATALOG_ID, DEFAULT_CATALOG_ID]`, `supported_components: set[str]`; `RenderedArtifact.metadata: dict[str, Any] = {}`.
- Helper en core `renderers/degrade.py`: `degrade(node, reason) -> BasicNode` (Text con `parrot_role='notice'`) + registro en una lista que el renderer vuelca a `metadata['degraded']`.
- `ssr_html.py`: dispatch por `node.component` para las 18 primitivas (Video→`<video controls poster>` o link, AudioPlayer→`<audio>`, Icon→nombre/`svgPath` inline, Tabs→secciones apiladas con títulos, Modal→inline, List, Divider→`<hr>`, inputs→valor solo lectura con label, Button→texto/deep link como hoy); estilos por `parrot_role`.
- `pdf.py`: hereda del SSR; declara `supported_components` sin Video/Audio (degradan a link).

**NOT in scope**: interactive-html/echarts/folium (2544); Adaptive Cards (2545).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | MODIFY | metadata |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_renderer_registry.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py` | MODIFY |  |

---

## Codebase Contract (Anti-Hallucination)

> Verificado 2026-08-28 sobre `dev`. Re-verificar con `grep`/`read` antes de implementar: las tareas previas de esta feature cambian estos archivos.

### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface            # packages/ai-parrot/src/parrot/outputs/a2ui/models.py
from parrot.outputs.a2ui.serialization import serialize, deserialize       # packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py:48/:64
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, catalog_instructions, validate_envelope  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:57-165
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, BasicNode, ComponentDefinition, CatalogValidationError  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:38-124
from parrot.outputs.a2ui.renderers import RendererCapabilities, AbstractA2UIRenderer, register_a2ui_renderer  # packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py:48-97
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
_RENDERER_NAMESPACE = "parrot.outputs.a2ui_renderers"                 # line 35
class RendererCapabilities(BaseModel): interactive: bool; supports_actions: bool; supports_updates: bool; output: str  # line 48
class AbstractA2UIRenderer(ABC): capabilities; async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str"  # line 65/:77
def register_a2ui_renderer(name, capabilities) :97 ; get_a2ui_renderer(name) :130
# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py
class RenderedArtifact(BaseModel): artifact_id; mime_type; content XOR path; filename; title; surface   # line 41  (SIN campo metadata)
```
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_CONTAINER_COMPONENTS = {"Column":"a2ui-col","Row":"a2ui-row","Card":"a2ui-card"} :47
@register_a2ui_renderer("ssr_html", RendererCapabilities(...)) :50 ; class SSRHTMLRenderer :59 ; _render_component :109 ; _render_basic(node: BasicNode) -> str :129 (solo Text/Image/contenedores)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py: PDFRenderer :99 ; _rasterize(document: str) -> bytes :137 (weasyprint lazy :36)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py: InteractiveHTMLRenderer :217 ; _render_top :261 ; _render_descriptor :271 ; _render_via_lowering :292 ; _render_basic :310 ; _render_chart :333 ; _render_datatable :387 ; _render_infographic :423 ; _BEHAVIOR_JS inline ES2017 ; _CHART_JS_SOURCE vendorizado ; _safe_json
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py: EChartsRenderer :56 ; _build_option(props) :110 ; _wrap_html :139
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py: FoliumMapRenderer :61 ; _iter_points :116
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py: AdaptiveCardsRenderer :64 ; render() emite deep links como TextBlock(text=f"{link.action_label}: {link.url}") :81-84 ; _element_for_component :101 ; _map_node(node: BasicNode) -> ACElement :120
```

### Does NOT Exist
- ~~`RendererCapabilities.supported_components` / `supported_catalog_ids`~~, ~~`RenderedArtifact.metadata`~~ — no existen hasta TASK-2543

---

## Implementation Notes

Los 6 registros `@register_a2ui_renderer` de los otros renderers deben seguir importando (añadir `supported_components` mínimo allí también para no romper el import; su cobertura real llega en 2544/2545).

### Key Constraints
- Async donde aplique; Pydantic v2; docstrings Google; `self.logger`/`logging.getLogger(__name__)`.
- Invariantes: G8 (a2ui core no importa `parrot.bots`/`parrot.clients`/DatasetManager), G3 (`version` sólo en `serialization.py`), G4 (`lower()` obligatorio salvo primitivas), `test_no_exec`.
- Wire siempre v1.0: props top-level, `{"path"}`, sobre por clave. Semántica de presentación en `metadata.extensions.parrot_*`.
- `source .venv/bin/activate` antes de cualquier comando; `uv` para deps.

### References in Codebase
- Spec §2 Data Models / New Public Interfaces y §6 Codebase Contract.
- Schemas oficiales: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/*.json` (desde TASK-2534) o `https://raw.githubusercontent.com/google/A2UI/90157ec10f36cf8e192daa71c95d2684af20c756/specification/v1_0/`.

---

## Acceptance Criteria

- [ ] Implementación completa según Scope
- [ ] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados
- [ ] `ruff check` sin errores en los archivos tocados
- [ ] SSR renderiza un envelope con las 18 primitivas sin excepción y HTML escapado
- [ ] `RenderedArtifact.metadata['degraded']` lista las degradaciones

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2543:
    def test_renderer_capabilities_declared(self): ...  # ver spec §4
    def test_renderer_degradation_recorded(self): ...  # ver spec §4
    def test_ssr_html_all_primitives(self): ...  # ver spec §4
    def test_pdf_degrades_media_to_links(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2543 — <título corto>`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-28
**Notes**:
- **Stale Codebase Contract, corrected before implementing**: `RenderedArtifact`
  (`artifacts.py`) ALREADY had a `metadata: dict[str, Any] = Field(default_factory=dict)`
  field (added by an earlier, unrelated task) — the contract's "Does NOT
  Exist" note ("SIN campo metadata") was wrong. No code change was needed
  in `artifacts.py`; `test_artifacts.py` already covered it
  (`test_model_fields_match_spec` asserts `art.metadata == {}`), so it
  needed no MODIFY either despite being listed in Files to Create/Modify.
- `RendererCapabilities` (`renderers/__init__.py`): added
  `supported_catalog_ids: list[str]` (default `[BASIC_CATALOG_ID,
  DEFAULT_CATALOG_ID]`) and `supported_components: set[str]` (default
  empty set — each renderer declares its own).
- `renderers/degrade.py` (new): `degrade(node: BasicNode, reason) -> BasicNode`
  builds a `Text` placeholder (`metadata.extensions.parrot_role="notice"`);
  `degradation_record(node, reason) -> dict` builds the structured record a
  renderer appends to its own list before dumping it into
  `RenderedArtifact.metadata["degraded"]` (the helper holds no state itself
  — only the calling renderer knows the full set of degradations for one
  render pass).
- `ssr_html.py` full rewrite. Key architectural finding made while
  implementing (not previously documented anywhere): the CORRECT pipeline
  order is **lower every composite component FIRST** (via its own
  registered `lower()` + `to_components()`, replacing it in the envelope's
  flat component list) **then bake** — never the reverse. A composite like
  `DataTable` lowers to a row `ChildTemplate` (`template_source` + a
  `ChildTemplate` reference), and template/binding expansion is exclusively
  `bake_envelope`'s job; baking BEFORE lowering (my first attempt) leaves
  every composite's internal `ChildTemplate` never expanded, since baking
  only ever sees the envelope's OWN top-level (still-composite) components.
  This exact lowering-then-bake contract is independently pinned by the
  pre-existing `test_datatable_row_materialization.py` (`_surface_and_bake`
  helper: lower -> `to_components` -> wrap in a `CreateSurface` -> bake) —
  confirmed by reading it after my initial (baking-first) implementation's
  DataTable rows rendered empty. `_lower_composites()` does the flattening
  (a composite's `lower()` preserves the ORIGINAL component's id on its
  outermost node, so no cross-reference rewriting is needed for siblings
  that point at it); `_reconstruct()` then does pure id-reference resolution
  over the now-all-primitive baked dicts (no more `lower()` calls at
  reconstruction time). Dispatch: one `_render_<Name>` method per primitive
  (`Text/Image/Icon/Video/AudioPlayer/Row/Column/List/Card/Tabs/Modal/
  Divider/Button/TextField/CheckBox/ChoicePicker/Slider/DateTimeInput`),
  reading top-level (camelCase-aliased where the official schema uses one,
  e.g. `posterUrl`/`svgPath`) props off `node.model_extra`. Modal's
  `content` id-reference is resolved to a nested `BasicNode` during
  `_reconstruct` (not at render time) so `_render_Modal` can render it
  inline without needing `by_id` in scope.
- `pdf.py`: `PDFRenderer` now subclasses `SSRHTMLRenderer` directly (spec:
  "hereda del SSR") and overrides `_UNSUPPORTED = frozenset({"Video",
  "AudioPlayer"})` so both always degrade via the shared dispatch's own
  unsupported-check (weasyprint cannot play media in a static PDF);
  declares `supported_components = SSRHTMLRenderer.capabilities.supported_components
  - {"Video", "AudioPlayer"}`. `_build_intermediate_html` now returns
  `(document, degraded)` (propagating SSR's own degradation list into the
  PDF artifact's `metadata["degraded"]`) and reads Chart's baked dict
  directly (`_chart_svg(bc)`, top-level props — no more `bc["properties"]`).
- **Necessary "unblocking fix" pattern (same as prior tasks in this
  feature) — 1 file outside this task's own file list**:
  `test_e2e_ssr_html.py` was already UNCOLLECTABLE before this task
  (`ModuleNotFoundError: parrot.outputs.a2ui.catalog.components`, a stale
  import left over from TASK-2539's `catalog/components/` -> `catalog/parrot/`
  rename — confirmed via `git stash` that it failed identically before any
  of this task's changes). Rewrote its two tests to v1.0 conventions
  (`id="root"`, top-level props, `{"path"}` bindings) since it directly
  exercises this task's own DataTable-row-materialization path end-to-end.
- Verified end-to-end: a hand-built envelope covering all 18 primitives
  (nested inside Column/Row/List/Card/Tabs/Modal) renders without
  exception, fully HTML-escaped, zero external `src`/`href` (only deep-link
  anchors), zero `metadata["degraded"]` entries. An unknown component
  degrades to a visible notice + one `metadata["degraded"]` record.
- `pytest packages/ai-parrot-visualizations/tests/outputs/`
  (excluding `test_adaptive_cards.py`/`test_echarts.py`/
  `test_interactive_html.py` — TASK-2544/2545's own files, still importing
  the stale `catalog.components` path): 30 passed, 1 skipped (folium,
  optional dep). `packages/ai-parrot/tests/outputs/a2ui/` (excluding
  `test_producer.py`, TASK-2547's own file) + the recipes/toolkit-wiring
  consequential test dirs: 559 passed, 8 pre-existing failures (documented:
  `test_delivery_teams.py` missing `azure`; `test_infographic_toolkit_a2ui_wiring.py`'s
  `_infographic()` helper — TASK-2547's own file/root cause). `ruff check`
  (scoped to lines this task introduced; pre-existing style debt in
  `renderers/__init__.py`/test files confirmed via git-HEAD diff and left
  untouched): clean.

**Deviations from spec**: `test_e2e_ssr_html.py` modified beyond this
task's own file list — a necessary, narrowly-scoped consequence (it was
already broken/uncollectable before this task; fixing it directly exercises
this task's own rewritten renderer, same pattern as TASK-2538/2539/2541/2542).
`artifacts.py` was NOT modified despite being listed in Files to
Create/Modify — the `metadata` field it was meant to add already existed
(added by an earlier, unrelated task); the Codebase Contract's claim that
it didn't exist was stale.
