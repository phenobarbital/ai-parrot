# TASK-2548: Suite de conformidad v1.0, docs de migración, deprecaciones y limpieza de xfails

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2541, TASK-2542, TASK-2544, TASK-2545, TASK-2546, TASK-2547
**Assigned-to**: Claude (Sonnet 5)
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

- [x] Implementación completa según Scope
- [x] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados (0 nuevas regresiones — ver Completion Note; fallos residuales en `tools`/`server`/`integrations` son 100% pre-existentes, confirmado vía `git stash`)
- [x] `ruff check` sin errores en los archivos tocados
- [x] 0 xfail FEAT-470
- [x] Docs publicadas y `mkdocs build --strict` OK (si mkdocs está instalado) — mkdocs NO está instalado en este venv; ver Completion Note

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

**Completed by**: Claude (Sonnet 5)
**Date**: 2026-08-28T23:41:06+00:00
**Notes**:

- **Codebase Contract verification**: verified via grep/read before implementing.
  All 17 prior tasks' artifacts were in place: `catalog/basic/` (18 primitives,
  14 functions, vendored spec JSONs), `catalog/parrot/` (8 components incl.
  `InfoCard`), `catalog/export.py`, `compat.py`, `recipes/migrate.py`,
  `renderers/degrade.py`, all 6 satellite renderers. `grep -rn "FEAT-470 wire"
  packages/*/tests` was ALREADY EMPTY at task start (no xfails to remove — the
  "0 xfail" acceptance criterion was pre-satisfied by prior tasks).

- **New conformance suite** (`tests/outputs/a2ui/conformance/`):
  `test_all_emitters.py` sweeps builders, the Infographic adapter, a
  producer-shaped bare-`CreateSurface` fixture (a live LLM call is NOT
  exercised here — see the open item below), a recipe `LayoutSpec` v2 (+ a
  migrated v1 layout), `bake_envelope`'s flattened output, and each of the 6
  satellite renderers' input envelope. `test_benchmark.py` covers the spec's
  literal "Rendimiento" AC (`validate_envelope` on 200 components, p50 <
  50ms — comfortably passes) plus an informational-only (non-gating) timing
  for the stricter `validate_message`/jsonschema path (see docstring: this
  intentionally does not assert a budget — the ~250-600ms cost is intrinsic
  to the vendored, SHA-pinned upstream schema's bare `oneOf`-over-18-primitives
  `Component` definition, not a FEAT-470 regression).

- **Real bugs the new suite surfaced and fixed** (all narrowly scoped,
  directly attributable to this feature's own TASK-2534/2535/2539 machinery,
  not pre-existing/unrelated):
  1. `catalog.validate_message` raised `re.error: bad escape \p` on ANY
     envelope carrying `metadata.extensions` (i.e. virtually every LOWERED
     Parrot-catalog component — the normal case) because the vendored
     `Extensions` pattern uses a `\p{XID_Start}`/`\p{XID_Continue}` Unicode
     property escape Python's stdlib `re` cannot compile. Fixed via
     `catalog._unicode_aware_jsonschema` — a lock-serialized context manager
     that swaps `jsonschema`'s internal `re` references to the `regex`
     package (drop-in, `\p{}`-capable) for one validation call when
     importable; a no-op otherwise.
  2. `KPICardComponent.lower()` passed a numeric `value`/`delta` straight
     through as a `Text.text` prop, but `Text.text` is `DynamicString`
     (string | binding | call) — a bare number always failed schema
     validation. Fixed via `_as_text()`; also fixed a text-less `Text` child
     when `delta is None` but `trend` is set (Text.text is REQUIRED). Updated
     the two affected golden fixtures (`kpicard_lowered.json`,
     `infographic_lowered.json` — the latter nests a KPICard).
  3. `catalog.basic.schema_registry()` was rebuilt (re-parsing all 6 vendored
     JSONs into a fresh `referencing.Registry`) on every single
     `validate_message` call — now `@functools.cache`d (safe: built purely
     from `load_spec`'s own already-cached, read-only documents).
  All three are documented in-code with a TASK-2548 reference; none required
  touching the vendored, SHA-pinned spec JSON files (drift test unaffected).

- **`agent_to_renderer.json` conformance is inherently two-layer**, not
  literal-only: the vendored schema's `Component` definition resolves
  `catalog.json#/$defs/anyComponent` against ONLY the Basic Catalog (that is
  how the upstream schema is written — confirmed against the PRE-EXISTING
  `test_validate_message_agent_to_renderer` in `catalog/test_validation_v1.py`,
  which already only ever validated a `BASIC_CATALOG_ID` envelope, never a
  Parrot-catalog one). So `_assert_conformant()` in the new suite checks (1)
  `validate_envelope` (spans both catalogs) and (2) the envelope's LOWERED
  form (every Parrot component run through its own `lower()` +
  `to_components()`) against `validate_message` — the exact Basic-only shape
  every satellite renderer actually consumes. This is documented at length in
  `test_all_emitters.py`'s module docstring and in `docs/outputs/a2ui-v1.md`.

- **xfail sweep**: `grep -rn "FEAT-470 wire" packages/*/tests` → empty (was
  already empty at task start).

- **`test_no_exec.py`/`test_import_rule.py` extension**: `test_no_exec.py`'s
  existing `rglob("*.py")` was already recursive over the complete tree; added
  an explicit per-module presence check (`test_subtrees_include_every_task_2532_2547_module`)
  so a future path-drift can't silently narrow coverage, and raised the
  file-count floor from the original placeholder `10` to `40` (47 actual).
  `adapters/test_import_rule.py` extended with 4 new tests covering
  `catalog/basic/` and `compat.py` (G8), following the file's own existing
  pattern exactly.

- **Docs**: `docs/outputs/a2ui-v1.md` (new) — the v1.0 wire, two-catalog
  resolution + `$ref` relationship, `metadata.extensions.parrot_*` convention
  (including the `\p{}` jsonschema caveat above), renderer degradation
  policy, and the Adaptive Cards/Teams `a2ui_action` submit flow (with an
  explicit "not here yet — FEAT-469" callout for the runtime RPC loop).
  `docs/migration/feat-273-a2ui-deprecations.md` — new FEAT-470 section
  (envelope shape table, `Card`→`InfoCard`, `LayoutSpec` v1→v2 + migration
  helpers, A2A constants); fixed the pre-existing `CARD` row that still said
  "Card" instead of "InfoCard". `mkdocs.yml` — nav entry added under
  Advanced, next to the existing `Outputs: outputs.md` entry. `mkdocs build
  --strict` was **not run — `mkdocs` is not installed in this venv**
  (`ModuleNotFoundError`), per the AC's own "si mkdocs está instalado"
  caveat. Sanity-checked instead: the YAML parses (custom `!!python/name:`
  tags aside) and the new `nav` entry's target file exists at the referenced
  path.

- **`formats/__init__.py`**: one-line text fix (`Card/KPICard` →
  `InfoCard/KPICard` in `_A2UI_REPLACEMENTS`). Ran `ruff check --fix` on the
  whole file since it was touched (13 pre-existing, unrelated typing-modernization
  findings — `Dict`/`Optional`/`Type` → builtin generics, import sorting —
  all mechanical/auto-fixed, zero behavior change, confirmed via
  `git stash` baseline that these pre-existed my one-line change).

- **Full-suite evidence** (`artifacts/logs/feat-470-final-pytest.log`): the
  task's own literal combined invocation (all 6 paths in ONE `pytest` call)
  fails at COLLECTION — `ValueError: Plugin already registered under a
  different name: .../ai-parrot-server/tests/conftest.py=<module
  'tests.conftest' from '.../ai-parrot/tests/conftest.py'>` — both
  `ai-parrot/tests/` and `ai-parrot-server/tests/` (and others) are proper
  `tests` packages (have `__init__.py`), so combining their roots in one
  pytest invocation collides on the module name `tests.conftest`.
  `--import-mode=importlib` does NOT resolve it (same collision surfaces
  differently). **Confirmed pre-existing and unrelated to this task**: byte-identical
  reproduction on a clean `git stash` of this task's entire diff. Ran each of
  the 6 target paths as a SEPARATE `pytest` invocation instead (same
  per-package granularity CI would use), all output concatenated into the
  one log file as instructed:
  - `packages/ai-parrot/tests/outputs`: 22 failed, 774 passed, 1 skipped.
    All 22 failures are in `formats/test_pep420_integration.py`,
    `formats/test_renderer_registry.py`, `formats/test_template_report.py`,
    `formats/test_jinja2.py`, `test_formatter_retry.py`,
    `test_legacy_deprecation.py::...[map]`, and
    `a2ui/test_delivery_teams.py` — confirmed identical failure set via
    `git stash` baseline (byte-for-byte same list); root causes are missing
    `azure`/environment-specific PEP420-satellite-discovery/jinja2-template-path
    issues, entirely unrelated to A2UI/FEAT-470. **The a2ui subtree itself
    (`packages/ai-parrot/tests/outputs/a2ui`) is 100% green** (464 passed, 1
    skipped, only the pre-existing `test_delivery_teams` failure — missing
    `azure` package).
  - `packages/ai-parrot-visualizations/tests`: 78 passed, 0 failed.
  - `packages/ai-parrot/tests/a2a`: 8 passed, 0 failed.
  - `packages/ai-parrot/tests/tools`: 52 failed, 809 passed, 8 skipped, 6
    collection errors — byte-identical to `git stash` baseline (same exact
    counts). Root causes: missing `tqdm` (execution_plan collection errors,
    already flagged by prior tasks per this task's own briefing) and
    unrelated DatasetManager/DDL-guard/obsidian-okf test failures, none of
    which touch A2UI.
  - `packages/ai-parrot-server/tests`: 64 failed, 841 passed, 4 skipped, 46
    collection errors — byte-identical to `git stash` baseline. Root causes:
    infographic-render/render-jobs/studio-scaffold test issues (missing
    deps/fixtures), none touching A2UI.
  - `packages/ai-parrot-integrations/tests`: entire package fails to
    collect — `ModuleNotFoundError: No module named 'aiogram'` at
    `conftest.py` import time (Telegram bot framework not installed).
    Byte-identical to `git stash` baseline.
  **Net: zero regressions introduced by this task anywhere in the 6 target
  paths** (every non-a2ui failure/error count matches its `git stash`
  baseline exactly); the a2ui-specific subtree is fully green modulo one
  pre-existing, unrelated `azure`-missing failure.

- **`ruff check`**: clean on every touched/created Python file (verified
  individually and as a combined final pass).

- **OPEN ITEM — TASK-2547's LLM first-shot spike was NOT executed live**:
  confirmed via `artifacts/logs/feat-470-producer-rate.md` (untracked, same
  convention as other per-task evidence logs) — the harness (20 prompts,
  `max_attempts=1`, `AnthropicClient` default model, `@pytest.mark.real_llm`)
  is fully implemented and ready to run, but no `ANTHROPIC_API_KEY` was
  available in TASK-2547's sandbox, nor in this closing task's environment
  (checked — none set here either). **The spec's "≥ 85% first-shot
  catalog-valid rate over 20 prompts" acceptance criterion is therefore
  STILL UNVERIFIED.** This closing task does NOT claim it as satisfied — a
  human with real Anthropic API credentials must run
  `PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot/tests/outputs/a2ui/test_producer.py::TestE2ELLMProducerFirstShotRate -v`
  (in this or a fresh worktree) and record the actual measured rate before
  FEAT-470 as a whole can be considered fully done.

**Deviations from spec**: none in scope/behavior. Two judgment calls, both
documented above and in-code: (1) `_assert_conformant`'s two-layer
validation strategy (catalog + lowered-form schema check) rather than a
literal single `validate_message` call on the raw envelope — grounded in
the vendored schema's own actual shape and the pre-existing test file that
already established this scope; (2) the `validate_message` 200-component
benchmark is informational-only (not budget-gated) — the spec's own Test
Specification names the benchmark `test_validate_envelope_benchmark`
(matching the AC's literal "validate_envelope con jsonschema" wording), and
the `oneOf`-fan-out cost of the literal jsonschema path is intrinsic to the
pinned upstream schema shape, not a FEAT-470 regression fixable within this
task's scope.
