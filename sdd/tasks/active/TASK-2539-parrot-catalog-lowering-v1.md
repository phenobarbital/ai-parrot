# TASK-2539: Catálogo parrot: mover a catalog/parrot/, Card→InfoCard, lower() a primitivas v1.0, DataTable→ChildTemplate, allowed_*

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL
**Depends-on**: TASK-2536, TASK-2538
**Assigned-to**: unassigned
**Parallel**: false — Toca los 8 componentes propios; secuencial tras primitivas y bake.

---

## Context

Módulo 5 (parte componentes). G4 y G9. `BasicNode` pasa a la forma v1.0.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `catalog/base.py`: `BasicNode` v1.0 (`id?`, `component`, `child?`, `children?: list[BasicNode]|ChildTemplate`, `metadata?`, props top-level `extra="allow"`); helper `to_components(tree) -> list[Component]` (aplana a adjacency list con ids deterministas).
- `git mv catalog/components catalog/parrot`; `card.py` → `infocard.py` con `@register_component("InfoCard")`; actualizar imports y `__init__`.
- Reescribir `lower()` de `InfoCard, Chart, DataTable, Map, KPICard, Timeline, Infographic, Report`: `Text{text, variant}` + `metadata.extensions.parrot_role`; `Card{child}` (+`parrot_variant`); `Column/Row{children, justify, align}`; `Tabs` para secciones de Report/Infographic cuando >1; `Divider`; `List` para listas; `Image{url, fit}`; `DataTable` → `Column` con `children: ChildTemplate{componentId:'<id>-row', path:'/tables/<id>'}` y celda `Text{text:{path:'col'}}` (relativo) + `parrot_component_id`.
- Declarar `allowed_parents/children` por componente (p. ej. Report/Infographic solo bajo `root`/`Column`).
- Eliminar `form.py` del registro (sustituido en TASK-2540); quitar `requires_actions` de los que ya no lo necesiten.
- Actualizar tests de componentes.

**NOT in scope**: `build_form`/export (TASK-2540). Renderers (2543+). Adapter (2541).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | BasicNode v1.0 + to_components |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/*.py` | CREATE | movidos desde components/ (git mv) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/` | DELETE | tras mover |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_*.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_datatable_row_materialization.py` | MODIFY | → template |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/  (se MUEVE a catalog/parrot/ en TASK-2539)
card.py: CARD_SCHEMA :16 ; @register_component("Card") class CardComponent: lower(component, data_model) -> BasicTree :34-60
chart.py:57 ChartComponent · datatable.py:87 DataTableComponent (_lower_row :50-83; contrato dos fases :124-137)
map.py:60 MapComponent · kpicard.py:34 KPICardComponent · timeline.py:44 TimelineComponent
form.py:60 FormComponent (requires_actions=True) · infographic.py:83 InfographicComponent · report.py:82 ReportComponent
# cada uno expone SCHEMA e INSTRUCTIONS y un lower() puro que emite BasicNode(component="Text", properties={"role":..., "text":...}) etc.
```
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"                 # line 38
class ProducerOrigin(str, Enum): LLM / TOOL                           # line 41
class BasicNode(BaseModel): extra="allow"; component: str; properties: dict; children: list["BasicNode"]  # line 53
BasicTree = BasicNode                                                 # line 75
class ComponentDefinition(BaseModel): name; catalog_id = DEFAULT_CATALOG_ID; schema_ (alias "schema"); instructions = ""; requires_actions = False  # line 79
@dataclass class RegisteredComponent: definition; component_cls      # line 100
class CatalogError :112 ; ComponentContractError :116 ; CatalogValidationError.__init__(...) :124/:133
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(...) -> decorator (exige lower())              # line 57 / :81
def unregister_component(name) :105 ; get_component(name) -> RegisteredComponent :110
def list_components() -> list[ComponentDefinition] :119
def catalog_instructions() -> str :124   # línea 131: f"{d.name}: {d.instructions}".rstrip(": ") — bug latente
def _iter_nested_component_names(value) -> list[str] :138
def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None  # line 165
```

### Does NOT Exist
- ~~`Text.role`~~ — usar `metadata.extensions.parrot_role`
- ~~`Card{title,...}`~~ — es `InfoCard`; `Card` v1.0 sólo tiene `child`
- ~~`BasicNode.properties`~~ — deja de existir tras este task

---

## Implementation Notes

Los roles conocidos (title, subtitle, badge, body, footer, caption, axis, series, label, value, delta, column-header, cell, header, heading, section, event-title, timestamp, notice, summary…) se preservan en `parrot_role` para que los renderers sigan estilando.

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
- [ ] `get_component('InfoCard')` OK y `get_component('Card')` resuelve al básico
- [ ] Cada `lower()` produce un árbol cuyos componentes validan contra el catálogo básico (`validate_envelope`)

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2539:
    def test_lower_emits_v1_primitives[8](self): ...  # ver spec §4
    def test_text_role_in_extensions(self): ...  # ver spec §4
    def test_datatable_lowers_to_child_template(self): ...  # ver spec §4
    def test_infocard_registered_card_resolves_basic(self): ...  # ver spec §4
    def test_allowed_parents_declared(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2539 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
