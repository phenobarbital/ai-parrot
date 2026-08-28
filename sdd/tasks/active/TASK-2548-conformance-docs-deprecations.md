# TASK-2548: Suite de conformidad v1.0, docs de migración, deprecaciones y limpieza de xfails

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2541, TASK-2542, TASK-2544, TASK-2545, TASK-2546, TASK-2547
**Assigned-to**: unassigned
**Parallel**: false — Cierre: depende de todo.

---

## Context

Módulo 10.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `tests/outputs/a2ui/conformance/`: para cada emisor (builders, adapter, producer fixtures, recipes, bake output, cada renderer que devuelva JSON) validar contra `agent_to_renderer.json`; benchmark `validate_envelope` 200 componentes < 50 ms p50.
- Quitar todos los `xfail(reason='FEAT-470 wire')` introducidos en 2532; la suite completa en verde.
- `docs/outputs/a2ui-v1.md` (wire, catálogos, extensions parrot_*, degradación por renderer, Teams submit), sección en `docs/migration/feat-273-a2ui-deprecations.md` (dialecto → v1.0, `Card`→`InfoCard`, recetas), `mkdocs.yml`; textos de `outputs/formats/__init__.py` mencionan `InfoCard`.
- Ampliar `test_import_rule` a `catalog/basic/` y `compat.py`; `test_no_exec` sobre el árbol completo.

**NOT in scope**: Nada nuevo de producto.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | CREATE |  |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_benchmark.py` | CREATE |  |
| `docs/outputs/a2ui-v1.md` | CREATE |  |
| `docs/migration/feat-273-a2ui-deprecations.md` | MODIFY |  |
| `mkdocs.yml` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | textos |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py` | MODIFY |  |

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
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py: _A2UI_REPLACEMENTS :13-24 ; _warn_if_deprecated :28-36 ; infographic-HTML :134-141
# tests guard: tests/outputs/a2ui/test_no_exec.py ; adapters/test_import_rule.py ; recipes/test_import_rule.py
```

### Does NOT Exist
- ~~`xfail` residuales~~ — deben quedar 0 (`grep -rn 'FEAT-470 wire' packages/*/tests` vacío)

---

## Implementation Notes

Ejecutar `pytest packages/ai-parrot/tests/outputs packages/ai-parrot-visualizations/tests packages/ai-parrot/tests/a2a packages/ai-parrot/tests/tools packages/ai-parrot-server/tests packages/ai-parrot-integrations/tests -q` y guardar salida en `artifacts/logs/feat-470-final-pytest.log`.

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
- [ ] 0 xfail FEAT-470
- [ ] Docs publicadas y `mkdocs build --strict` OK (si mkdocs está instalado)

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2548:
    def test_conformance_all_emitters(self): ...  # ver spec §4
    def test_validate_envelope_benchmark(self): ...  # ver spec §4
    def test_import_rule_covers_basic_and_compat(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2548 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
