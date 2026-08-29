# TASK-2547: Productor LLM v1.0 (structured_output, instructions básico+parrot, re-prompt con códigos), emission y toolkits

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2540
**Assigned-to**: Claude (sdd-worker)
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

> **Re-verificado 2026-08-28 al implementar** (contrato arriba estaba desactualizado
> tras TASK-2540/2543/2546 — el código real difería de lo anotado):
> - `catalog/base.py`: `CatalogValidationError.__init__(message, *, code=None,
>   issues=None, unknown_components=None, action_components=None)` — `.code`
>   (primer issue), `.issues: list[{"code","message","path"}]` (TODOS los
>   problemas, spec §7). NO existían `BasicNode.template_source`/`TabSpec` en
>   el contrato original — ya están en `catalog/base.py` (TASK-2539/2543).
> - `catalog/__init__.py`: `validate_envelope(envelope, *,
>   origin=ProducerOrigin.TOOL, surface_catalog_id: str | None = None) -> None`
>   — YA acepta `surface_catalog_id` (no existía cuando se escribió el
>   contrato original); es lo que este task usa para hacer efectivo el
>   `catalog=` de `generate_envelope`.
> - `catalog.parrot`/`catalog.basic` NO se importan en el import-chain de
>   `producer.py`; sólo se registran vía imports locales dispersos en otros
>   módulos (`builders.py` importa `catalog.parrot`; `catalog/__init__.py`
>   importa `catalog.basic` sólo dentro de funciones). `generate_envelope`
>   ahora importa AMBOS explícitamente (`_ensure_catalogs_registered()`)
>   antes de `catalog_instructions()`, para no depender del orden de import
>   del proceso.
> - `test_producer.py` (línea 8, baseline) hacía
>   `import parrot.outputs.a2ui.catalog.components` — módulo INEXISTENTE
>   (movido a `catalog/parrot/` en TASK-2539) → **ERROR de colección de
>   pytest** confirmado y corregido aquí (import actualizado +
>   fixtures reescritas a props top-level v1.0 con `id="root"`).
> - `serialize(CreateSurface)` produce el sobre-por-clave completo
>   (`{"version":"v1.0","createSurface":{...}}`), y `deserialize()` de ESE
>   dict devuelve un `A2UIAgentMessage` (envoltorio), NUNCA un
>   `CreateSurface` directo — `_extract_envelope` original asumía lo
>   segundo (roto para el caso `dict` de salida de `client.ask`); corregido
>   para aceptar tanto un dict "pelado" de `CreateSurface` (forma realista
>   de `structured_output`) como el sobre completo.
> - `_infographic()` en `test_infographic_toolkit_a2ui_wiring.py` asumía
>   `components[0]["properties"]` (dialecto viejo); v1.0 las props del
>   componente van top-level — 7 tests de ese archivo fallaban por esto
>   ANTES de este task (confirmado con `git stash`), corregidos aquí.

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

- [x] Implementación completa según Scope
- [x] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados
- [x] `ruff check` sin errores en los archivos tocados
- [x] Envelopes de ambos toolkits validan con `validate_envelope`
- [ ] Evidencia del spike guardada — harness implementado y documentado en
      `artifacts/logs/feat-470-producer-rate.md`, pero el spike de 20 prompts
      NO se ejecutó contra un LLM real en este entorno sandboxed (sin
      `ANTHROPIC_API_KEY`); la tasa ≥85% queda pendiente de verificación real.

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

**Completed by**: Claude (sdd-worker, Sonnet 5)
**Date**: 2026-08-28T22:55:35+00:00
**Notes**:

- `producer.py`: `generate_envelope` already used
  `StructuredOutputConfig(output_type=CreateSurface)` against the v1.0
  `CreateSurface` (verified — `catalog.parrot`/`models` were already wired by
  TASK-2532/2539/2540). Added `_ensure_catalogs_registered()` (imports
  `catalog.basic` + `catalog.parrot` for their registration side effect)
  called before `catalog_instructions()`, so the system prompt covers BOTH
  catalogs regardless of prior import order — `catalog_instructions()` itself
  only aggregates whatever is already registered, it does not import
  anything. Added an explicit "root" rule to the system prompt and to
  `_repair_prompt`'s reminder.
- `_repair_prompt` now takes `error: str | CatalogValidationError` — when a
  `CatalogValidationError` is passed (the catalog-validation-failure path),
  every issue's `code` and a JSON-pointer-style `path`
  (`/components/<id>`) are rendered explicitly via a new
  `_format_catalog_error` helper, covering ALL issues found (not just the
  first), matching `validate_envelope`'s "report every problem" contract
  (spec §7). The schema-violation/raw-text path still passes a plain string
  and behaves as before.
- `catalog=` param: chosen to make it **effective** (per the task's stated
  preference) rather than removing it — `validate_envelope` already accepts
  `surface_catalog_id` (added by an earlier task, contract was stale on
  this), so `catalog` is now forwarded there verbatim. Grepped the whole
  repo for `generate_envelope(` callers first: only tests call it, none pass
  `catalog=`, so this is a safe, zero-blast-radius signature tightening
  (`Any` → `str | None`).
- **Bug found and fixed in `_extract_envelope`**: `serialize(CreateSurface)`
  now produces the full envelope-by-key dict
  (`{"version":"v1.0","createSurface":{...}}`), and `deserialize()` of that
  dict returns an `A2UIAgentMessage` wrapper, never a bare `CreateSurface` —
  the old code assumed `deserialize()` would hand back a `CreateSurface`
  directly (true in the pre-v1.0 dialect, false now). Fixed to: (a) route an
  envelope-by-key dict (has `"createSurface"`/`"version"`) through
  `deserialize()` and unwrap `.create_surface`; (b) route a **bare**
  `CreateSurface`-shaped dict (the realistic `structured_output` shape a
  client actually returns) through `CreateSurface.model_validate()` directly.
  Both shapes are now covered by tests.
- **Stale-import bug confirmed and fixed** (flagged by TASK-2546 as a
  sibling-task finding): `test_producer.py` line 8 imported
  `parrot.outputs.a2ui.catalog.components`, a module removed by TASK-2539
  (moved to `catalog/parrot/`) — this caused a pytest **collection ERROR**
  for the whole file at baseline (confirmed via `git stash`). Fixed the
  import and rewrote every fixture to v1.0 shape (top-level props, explicit
  `id="root"`, since `validate_envelope` now enforces `MISSING_ROOT`).
- `infographic_toolkit.py` / `interactive_toolkit.py`: both
  `_build_a2ui_envelope*` paths already called the v1.0 builders/adapter
  correctly (confirmed by reading them in full — `infographic_toolkit.py`
  already had a TASK-2542 comment noting "props live top-level, not nested
  under a properties key"; `interactive_toolkit.py` already used
  `build_card`). No functional changes needed there. Fixed two stale
  docstring references to the legacy `{"$bind": "/pointer"}` binding syntax
  in `infographic_toolkit.py` (now `{"path": "/pointer"}`) — these are
  LLM/tool-caller-facing docstrings for `freeze_recipe`'s `layout_properties`
  param and `_build_a2ui_envelope_from_layout`, so the stale syntax was a
  real (if minor) footgun for callers.
- `emission.py`: verified — `finalize_a2ui_response` is envelope-agnostic
  (duck-typed pass-through of whatever dict/model it's handed); it does not
  assume the pre-v1.0 dialect shape anywhere that would raise on a v1.0
  envelope. One cosmetic-only degradation was noted but NOT fixed (out of
  scope — no test file for `emission.py` is in this task's Files table, and
  fixing it would touch a file/tests not listed): its "human-readable
  fallback" title extraction does `envelope.get("surfaceId")` on the
  OUTER dict, which only exists in the pre-v1.0 dialect; for a v1.0
  envelope-by-key dict (`{"version":...,"createSurface":{"surfaceId":...}}`)
  this now always misses and falls back to the generic `"[A2UI surface]"`
  string instead of including the surface id. Not a correctness bug (no
  exception, `a2ui_envelope`/`output_mode` are still set correctly) — purely
  a less-informative fallback message. Left as-is per the task's
  "verify-only, no changes if envelope-agnostic" instruction; flagging for
  TASK-2548 (conformance/docs closer) or a follow-up if the cosmetic gap is
  judged worth closing.
- **Test fixes discovered while running the suite**:
  `test_infographic_toolkit_a2ui_wiring.py`'s `_infographic()` helper
  assumed `components[0]["properties"]` (pre-v1.0 nesting) — 7 of its tests
  were failing at baseline (confirmed via `git stash` diff, not something I
  introduced). Fixed the helper to return `components[0]` directly (v1.0:
  props are top-level).
- Added the 4 tests named in the task's Test Specification:
  `test_producer_uses_v1_structured_output` (+ two supporting tests
  asserting the system prompt covers both catalogs and states the root
  rule), `test_repair_prompt_includes_code` (+ multi-issue and
  plain-string-backward-compat variants), `test_toolkits_emit_v1_envelopes`
  (in `test_toolkits_a2ui_migration.py`, covering BOTH toolkits — builds a
  real envelope via each toolkit's `_build_a2ui_envelope`, asserts v1.0
  top-level shape + `id="root"`, and re-validates via `validate_envelope`
  after reconstructing the `CreateSurface`), and
  `test_e2e_llm_producer_first_shot_rate` (marked `@pytest.mark.real_llm`,
  the repo's existing convention for opt-in live-LLM tests — see
  `tests/conftest.py`/`tests/agents/test_obsidian.py` — skipped unless
  `PARROT_TEST_REAL_LLM=1`).
- **Spike (AC "first-shot rate ≥ 85%")**: the harness is fully implemented
  (20 prompts, `max_attempts=1`, `AnthropicClient` default model
  `claude-sonnet-4-5`) but **was NOT actually executed** in this sandboxed
  run — no `ANTHROPIC_API_KEY` was available. This is documented honestly in
  `artifacts/logs/feat-470-producer-rate.md` rather than fabricating a pass
  rate. **This one acceptance criterion is NOT verified by this task run.**
- Test/regression evidence: `pytest` on the 3 required files → 38 passed, 1
  skipped (the `real_llm` spike). Broader regression check on
  `tests/outputs/a2ui/` + `tests/tools/` (excluding
  `tests/tools/execution_plan/`, which fails to collect at baseline too —
  missing `tqdm`, unrelated): baseline (via `git stash`) 60 failed / 1230
  passed; after this task 53 failed / 1254 passed — **0 new failures**, 7
  previously-broken tests fixed (the stale `properties`-nesting assumption
  above). Full log: `artifacts/logs/feat-470-task-2547-tests.log` (local
  evidence, not committed — same convention as TASK-2544's log).
- `ruff check` on touched files: `producer.py`,
  `test_infographic_toolkit_a2ui_wiring.py`, `test_toolkits_a2ui_migration.py`,
  `test_producer.py` all clean. `infographic_toolkit.py`: confirmed (via
  `git stash` diff) its pre-existing 158 ruff findings are 100% unchanged by
  this task's 2-line docstring edit — left untouched (fixing that debt is
  out of this task's scope and would produce an unrelated ~150-line diff
  across a 1941-line file another in-flight task also touches).

**Deviations from spec**: none in scope/behavior. The one honest gap is the
spike not being executable here (credentials), called out above and in
`artifacts/logs/feat-470-producer-rate.md` rather than silently marked
done.
