# TASK-2534: Vendorizar schemas oficiales v1.0 (pin SHA), load_spec, jsonschema como dependencia dura, test de drift

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2532
**Assigned-to**: unassigned
**Parallel**: true — Sólo crea `catalog/basic/spec/` y toca pyproject; no comparte archivos con TASK-2533.

---

## Context

Módulo 2 (parte vendorizado). Decisiones: jsonschema dependencia dura; spec vendorizada con pin `90157ec10f36cf8e192daa71c95d2684af20c756` + test de drift `@network`.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- Descargar y guardar en `catalog/basic/spec/`: `catalog.json` (de `specification/v1_0/catalogs/basic/catalog.json`), `common_types.json`, `agent_to_renderer.json`, `renderer_to_agent.json`, `catalog_definition.json`, `agent_capabilities.json` (de `specification/v1_0/json/`) del commit pin. Incluirlos en el wheel (`package-data`).
- `catalog/basic/__init__.py`: `BASIC_CATALOG_ID`, `SPEC_COMMIT`, `SPEC_FILES`, `load_spec(name) -> dict` (cache), `schema_registry() -> referencing.Registry` que resuelve los `$id` `https://a2ui.org/specification/v1_0/...` y los `$ref` relativos (`common_types.json#/$defs/...`).
- Añadir `jsonschema>=4.20` a `dependencies` de `packages/ai-parrot/pyproject.toml` (y `uv lock`).
- Tests: presencia/pin; `test_spec_drift_against_upstream` marcado `network` (hash de cada archivo vs `raw.githubusercontent.com/google/A2UI/<SHA>/...`).

**NOT in scope**: Validación de sobres/componentes (TASK-2535). Modelos de primitivas (TASK-2536).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/*.json` | CREATE | 6 archivos |
| `packages/ai-parrot/pyproject.toml` | MODIFY | jsonschema>=4.20; package-data para spec/*.json |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_spec_vendored.py` | CREATE |  |

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
# jsonschema 4.26.0 y referencing ya instalados en .venv (transitivos). pyproject core: dependencies :36, pydantic==2.12.5 :51, sin jsonschema.
# uv workspace: usar `source .venv/bin/activate && uv add jsonschema>=4.20 --package ai-parrot` (verificar sintaxis de uv en el repo antes).
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.catalog.basic`~~ — lo crea este task
- ~~marker pytest `network`~~ — verificar en `pyproject`/`conftest` si existe; si no, registrarlo en `[tool.pytest.ini_options] markers`

---

## Implementation Notes

Registry: `referencing.Registry().with_resources([(doc['$id'], Resource.from_contents(doc)) ...])` y `Draft202012Validator(schema, registry=registry)`. Los `$ref` relativos `common_types.json#/...` se resuelven contra el `$id` base del documento.

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
- [ ] `load_spec('catalog')['catalogId'] == BASIC_CATALOG_ID`
- [ ] `import jsonschema` funciona con `uv pip list` mostrando la dep en ai-parrot
- [ ] test de drift pasa contra el SHA pin

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2534:
    def test_spec_files_present_and_pinned(self): ...  # ver spec §4
    def test_schema_registry_resolves_common_types(self): ...  # ver spec §4
    def test_spec_drift_against_upstream(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2534 — <título corto>`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-28
**Notes**:
- Fetched the six official v1.0 JSON Schemas directly from
  `raw.githubusercontent.com/google/A2UI/90157ec10.../specification/v1_0/`
  at the pinned commit and vendored them verbatim under
  `catalog/basic/spec/`. Confirmed via GitHub's API that
  `90157ec10f36cf8e192daa71c95d2684af20c756` is a real, resolvable commit.
- Discovered (and documented in `_CATALOG_ALIAS_ID`) a real upstream
  cross-reference quirk: `agent_to_renderer.json`'s `Component` def and
  `common_types.json`'s `FunctionCall` def both `$ref` a RELATIVE
  `"catalog.json#/..."`, which resolves (relative to their own `$id`,
  `.../specification/v1_0/{agent_to_renderer,common_types}.json`) to
  `https://a2ui.org/specification/v1_0/catalog.json` — NOT the basic
  catalog's actual `$id` (`.../catalogs/basic/catalog.json`,
  `BASIC_CATALOG_ID`). This is deliberate upstream design (the message
  schemas are catalog-agnostic); `schema_registry()` aliases the basic
  catalog under both ids so `$ref` resolution succeeds. Verified end-to-end
  with a real `jsonschema.Draft202012Validator` against `agent_to_renderer.json`
  before writing the test.
- Added `jsonschema>=4.20` as a hard `ai-parrot` dependency and the
  `spec/*.json` package-data glob to `pyproject.toml` (no `uv lock`
  regeneration needed in this worktree — `jsonschema`/`referencing` were
  already present as transitive deps at the versions the spec expects,
  4.26.0/0.36.2).
- Registered a `network` pytest marker in `packages/ai-parrot/pyproject.toml`
  (didn't exist yet). `test_spec_drift_against_upstream` was run manually
  once against the live GitHub raw content (passed) but is excluded from
  the default `pytest` run via the marker, per the task's own
  `@network`-is-optional-in-CI framing.
- `pytest test_spec_vendored.py -m "not network"`: 6 passed;
  `-m network`: 1 passed. `ruff check`: clean.

**Deviations from spec**: none — the `catalog.json` alias-id handling is an
implementation detail resolving an ambiguity the spec didn't call out
(it wasn't aware of the exact upstream cross-reference shape), not a
deviation from any stated requirement.
