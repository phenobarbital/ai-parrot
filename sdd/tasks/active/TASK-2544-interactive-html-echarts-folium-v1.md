# TASK-2544: interactive-html, ECharts y Folium sobre primitivas v1.0

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L
**Depends-on**: TASK-2543
**Assigned-to**: unassigned
**Parallel**: true — Archivos distintos de TASK-2545; paralelizable.

---

## Context

Módulo 7 (parte interactive/echarts/folium).

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `interactive_html.py`: `_render_basic` cubre las 18 primitivas (Tabs con `data-tabs` reutilizando el JS existente, List, Divider, inputs HTML nativos deshabilitados salvo que `supports_actions` — sigue `False`), lee `Chart`/`DataTable` con props top-level y `{path}`; `_BEHAVIOR_JS` sólo gana selectores para Tabs genéricos.
- `echarts.py`, `folium_map.py`: leer props top-level/`{path}`; declarar `supported_components`.

**NOT in scope**: Runtime JS de funciones/acciones (fuera de alcance).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` | MODIFY |  |

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
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_CONTAINER_COMPONENTS = {"Column":"a2ui-col","Row":"a2ui-row","Card":"a2ui-card"} :47
@register_a2ui_renderer("ssr_html", RendererCapabilities(...)) :50 ; class SSRHTMLRenderer :59 ; _render_component :109 ; _render_basic(node: BasicNode) -> str :129 (solo Text/Image/contenedores)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py: PDFRenderer :99 ; _rasterize(document: str) -> bytes :137 (weasyprint lazy :36)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py: InteractiveHTMLRenderer :217 ; _render_top :261 ; _render_descriptor :271 ; _render_via_lowering :292 ; _render_basic :310 ; _render_chart :333 ; _render_datatable :387 ; _render_infographic :423 ; _BEHAVIOR_JS inline ES2017 ; _CHART_JS_SOURCE vendorizado ; _safe_json
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py: EChartsRenderer :56 ; _build_option(props) :110 ; _wrap_html :139
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py: FoliumMapRenderer :61 ; _iter_points :116
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py: AdaptiveCardsRenderer :64 ; render() emite deep links como TextBlock(text=f"{link.action_label}: {link.url}") :81-84 ; _element_for_component :101 ; _map_node(node: BasicNode) -> ACElement :120
```
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
_RENDERER_NAMESPACE = "parrot.outputs.a2ui_renderers"                 # line 35
class RendererCapabilities(BaseModel): interactive: bool; supports_actions: bool; supports_updates: bool; output: str  # line 48
class AbstractA2UIRenderer(ABC): capabilities; async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str"  # line 65/:77
def register_a2ui_renderer(name, capabilities) :97 ; get_a2ui_renderer(name) :130
# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py
class RenderedArtifact(BaseModel): artifact_id; mime_type; content XOR path; filename; title; surface   # line 41  (SIN campo metadata)
```

### Does NOT Exist
- ~~`@a2ui/lit` vendorizado~~ — no; fuera de alcance

---

## Implementation Notes

Mantener `_safe_json` y el bundle Chart.js.

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
- [ ] Tabs/List/Divider/inputs presentes en el DOM del HTML interactivo

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2544:
    def test_interactive_html_renders_new_primitives(self): ...  # ver spec §4
    def test_interactive_chart_reads_top_level_props(self): ...  # ver spec §4
    def test_echarts_capabilities(self): ...  # ver spec §4
    def test_folium_capabilities(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2544 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
