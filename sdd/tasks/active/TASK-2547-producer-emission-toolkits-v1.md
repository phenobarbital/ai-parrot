# TASK-2547: Productor LLM v1.0 (structured_output, instructions básico+parrot, re-prompt con códigos), emission y toolkits

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2540
**Assigned-to**: unassigned
**Parallel**: false — Toca producer y los dos toolkits; puede correr en paralelo con 2546 en la práctica pero comparte fixtures — se deja secuencial.

---

## Context

Módulo 9. Spike de tasa first-shot.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `producer.py`: `structured_output=StructuredOutputConfig(output_type=CreateSurface)` v1.0; prompt del sistema con `catalog_instructions()` (básico + parrot) y regla de `root`; `_repair_prompt` incluye `code` y ruta del error; eliminar el parámetro no-op `catalog=` o hacerlo efectivo (`surface_catalog_id`).
- `infographic_toolkit.py` / `interactive_toolkit.py`: `_build_a2ui_envelope*` usan builders v1.0 (sin cambio de API pública).
- Spike: script en `scripts/` o test `@llm` que corre 20 prompts y registra la tasa en `artifacts/logs/feat-470-producer-rate.md` (umbral ≥ 85 %).

**NOT in scope**: Runtime (FEAT-469).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py` | MODIFY | si aplica |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/tools/interactive_toolkit.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_producer.py` | MODIFY |  |
| `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py` | MODIFY |  |
| `packages/ai-parrot/tests/tools/test_toolkits_a2ui_migration.py` | MODIFY |  |
| `artifacts/logs/feat-470-producer-rate.md` | CREATE | evidencia |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/producer.py
DEFAULT_MAX_ATTEMPTS = 3 :45 ; class ProducerResult(BaseModel) :48
def _extract_envelope(output) -> tuple[Optional[CreateSurface], Optional[str]] :71
def _repair_prompt(base_prompt: str, error_text: str, offending: Any) -> str :91
# generate_envelope(...) ~:110-192: client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface)); param `catalog=` no-op (:114); degrade-to-text
# packages/ai-parrot/src/parrot/outputs/a2ui/emission.py: def finalize_a2ui_response(response: Any) -> None :18
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py: emit_a2ui :171/:217 ; _build_a2ui_envelope, _build_a2ui_envelope_from_layout :501-969 ; build_surface freeze :1295
# packages/ai-parrot/src/parrot/tools/interactive_toolkit.py: emit_a2ui :94 ; _build_a2ui_envelope via build_card :~345
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py: _DEFAULT_COMPONENT_ID = "blk-000" :37 ; _binding :40 ; build_surface :44 · build_chart :71 · build_kpicard :91 · build_card :111 · build_datatable :128 · build_infographic :151
```

### Does NOT Exist
- ~~`producer.generate_envelope(catalog=...)` efectivo~~ — hoy es no-op (:114)

---

## Implementation Notes

Degrade-to-text se conserva. El test `@llm` es opcional en CI.

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
- [ ] Envelopes de ambos toolkits validan con `validate_envelope`
- [ ] Evidencia del spike guardada

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2547:
    def test_producer_uses_v1_structured_output(self): ...  # ver spec §4
    def test_repair_prompt_includes_code(self): ...  # ver spec §4
    def test_toolkits_emit_v1_envelopes(self): ...  # ver spec §4
    def test_e2e_llm_producer_first_shot_rate(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2547 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
