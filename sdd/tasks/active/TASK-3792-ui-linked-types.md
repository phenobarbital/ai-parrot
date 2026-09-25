# TASK-3792: Linked TS types from JSON Schema + CreateSurface.metadata

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3771
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (bundled UI executor lane) starts with the wire types: the bundled
`ai-parrot-server/ui` must read `createSurface.metadata.extensions.parrot_data_sources`
(spec §2 G2) and type it from the published JSON Schema of `LinkedSources` (spec M1/M12),
never by hand. Today `CreateSurface` in `a2ui-types.ts` has **no** `metadata` field
(`a2ui-types.ts:63-68`), and generated UI types are produced ONLY by
`scripts/generate_ts_types.py` (Pydantic → `ui/schemas/*.json`) followed by `pnpm generate`
(`json2ts` → `src/lib/types/generated/*.d.ts`).

This task is **exclusive** (`parallel: false`): `pnpm generate` rewrites the whole shared
`src/lib/types/generated/` directory and `generate_ts_types.py` rewrites every committed
`ui/schemas/*.json`.

---

## Scope

- Register `LinkedSources` (from TASK-3769's `parrot.outputs.a2ui.linked.models`, whose schema
  is exported by TASK-3771) in `scripts/generate_ts_types.py::_models()`.
- Run the exporter → commit the new `ui/schemas/LinkedSources.json` (all other schema files
  must come out byte-identical; if one does not, STOP and report — unrelated drift).
- Run `pnpm generate` → commit the new `src/lib/types/generated/LinkedSources.d.ts` (other
  generated files must be byte-identical).
- Create `linked/types.ts`: friendly re-exports of the generated types + the `Row` alias +
  a pure `getDataSources(surface)` accessor.
- Add `metadata?: { extensions?: Record<string, unknown> }` to `CreateSurface` in
  `a2ui-types.ts` (spec M11 skeleton).
- Tests: `linked/types.test.ts` + pytest wrapper `tests/ui/test_vitest_a2ui_linked_types.py`.

**NOT in scope**: the DSL/conditions port (TASK-3793), fetch/scheduler/ref (TASK-3794), any Svelte
change (TASK-3795). Do NOT hand-edit anything under `src/lib/types/generated/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/generate_ts_types.py` | MODIFY | register `LinkedSources` in `_models()` |
| `packages/ai-parrot-server/ui/schemas/LinkedSources.json` | CREATE | exporter output (committed) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/LinkedSources.d.ts` | CREATE | `pnpm generate` output (committed) |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.ts` | CREATE | re-exports + `Row` + `getDataSources` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.test.ts` | CREATE | vitest for `getDataSources` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts` | MODIFY | `CreateSurface.metadata` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py` | CREATE | pytest wrapper |

> Deviation from the plan table: `scripts/generate_ts_types.py` is added because
> `packages/ai-parrot-server/tests/test_ts_codegen.py::test_schemas_in_sync_with_committed`
> asserts `set(ui/schemas/*.json) == set(_models())` — a hand-dropped `LinkedSources.json`
> fails that drift gate.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/generate_ts_types.py — _models() does lazy imports inside the function body (L47-80)
from parrot.outputs.a2ui.linked.models import LinkedSources   # created by TASK-3769 (RootModel[dict[str, LinkedDataSource]])
```
```typescript
// a2ui/*.ts use relative imports; $lib alias resolves to ui/src/lib (vitest.config.ts resolve.alias)
import type { CreateSurface } from '../a2ui-types';                     // a2ui-types.ts:63
import type { LinkedSources } from '$lib/types/generated/LinkedSources'; // created HERE by pnpm generate
import { describe, expect, it } from 'vitest';                           // A2UISurface.test.ts:7 convention
```

### Existing Signatures to Use
```python
# scripts/generate_ts_types.py
def _models() -> dict[str, type[BaseModel]]:          # L37; lazy imports L47-80
    from parrot.handlers.toolkit_persistence import UserToolkitOverride   # L80 (last import)
    return { ..., "UserToolkitOverride": UserToolkitOverride, }             # L108 (last entry), dict closes L109
def export_schemas(output_dir: Path = SCHEMAS_DIR) -> dict[str, Path]      # json.dumps(schema, indent=2, sort_keys=True) + "\n"
# CLI: `python scripts/generate_ts_types.py` (needs PYTHONPATH with the worktree's packages/*/src — module docstring)
```
```typescript
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts
export interface CreateSurface {            // L63
  surfaceId: string;                         // L64
  catalogId?: string;                        // L65
  components: WireComponent[];               // L66
  dataModel?: Record<string, unknown>;       // L67
}                                            // L68 — NO metadata today
export interface A2UIEnvelope { version: "v1.0"; createSurface: CreateSurface; }   // L72-75
// WireComponent.metadata?: { extensions?: Record<string, unknown> }  L38 — same shape to reuse
```
```text
ui/package.json "generate": json2ts -i schemas -o src/lib/types/generated --bannerComment "// GENERATED by scripts/generate_ts_types.py — DO NOT EDIT"
packages/ai-parrot-server/tests/ui/_vitest.py: run_vitest(*files) — runs `pnpm exec vitest run <files>` with cwd=ui/, skips without pnpm/node_modules
```

### Does NOT Exist
- ~~`CreateSurface.metadata` in `a2ui-types.ts`~~ — added here.
- ~~`ui/schemas/LinkedSources.json`, `src/lib/types/generated/LinkedSources.d.ts`, `a2ui/linked/`~~ — created here.
- ~~a TypeScript package published for third parties~~ — never (spec G1); these types are the bundled UI's own.
- ~~A hand-maintained `LinkedDataSource` TS interface~~ — forbidden; types come from `pnpm generate`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/generate_ts_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/schemas/LinkedSources.json", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/types/generated/LinkedSources.d.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/generate_ts_types.py#_models"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- TS `strict`; types only from the generated file. `linked/types.ts` may alias/re-export but
  never re-declare a field — because drift between Python and TS must be a `tsc` failure.
- `json2ts` names `$defs` interfaces by their JSON Schema `title`. The exact exported names
  (`LinkedDataSource`, `SourceRequest`, `ParamSpec`, `RefreshPolicy`, `TransformSpec`,
  `TransformRef`, the ten op models) depend on TASK-3769's model/class names — READ the generated
  `.d.ts` before writing the re-exports.
- Run the exporter with the worktree's sources first on `PYTHONPATH`
  (`PYTHONPATH="$(pwd)/packages/ai-parrot-server/src:$(pwd)/packages/ai-parrot/src" python scripts/generate_ts_types.py`)
  — otherwise the shared venv's editable install (main checkout) is imported.

### References in Codebase
- `packages/ai-parrot-server/tests/test_ts_codegen.py` — the drift gate this task must keep green.
- `packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py` — wrapper pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Add `LinkedSources` to `_models()` — *why*: the codegen drift gate requires every committed schema to come from the script.
2. Run the exporter, `git diff --stat packages/ai-parrot-server/ui/schemas` — *why*: only `LinkedSources.json` may be new; any other diff is unrelated drift → STOP.
3. `cd packages/ai-parrot-server/ui && pnpm generate` — *why*: produces `LinkedSources.d.ts`; other generated files must not change.
4. Write `linked/types.ts` against the ACTUAL generated names — *why*: re-exports compile only if names match.
5. Add `metadata` to `CreateSurface` — *why*: spec M11 skeleton; `getDataSources` reads it.
6. Write the vitest + pytest wrapper, run `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py packages/ai-parrot-server/tests/test_ts_codegen.py -q`.

### `scripts/generate_ts_types.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    from parrot.handlers.toolkit_persistence import UserToolkitOverride' scripts/generate_ts_types.py)
# AFTER — insert below `    from parrot.handlers.toolkit_persistence import UserToolkitOverride` (verified: scripts/generate_ts_types.py:80)
    # FEAT-598 — linked-surface descriptor (createSurface.metadata.extensions.parrot_data_sources)
    from parrot.outputs.a2ui.linked.models import LinkedSources

# occurrences: 1 (verified: grep -c '        "UserToolkitOverride": UserToolkitOverride,' scripts/generate_ts_types.py)
# AFTER — insert below `        "UserToolkitOverride": UserToolkitOverride,` (verified: scripts/generate_ts_types.py:108)
        # FEAT-598 — A2UI linked surfaces
        "LinkedSources": LinkedSources,
```
**Why**: `test_schemas_in_sync_with_committed` compares the committed file set with `_models()`; registering the model is the only legal way to add `LinkedSources.json`.

### `packages/ai-parrot-server/ui/schemas/LinkedSources.json` (CREATE)
```text
Generated — do not write by hand. Produced by step 2 (export_schemas → json.dumps(indent=2, sort_keys=True)).
```
**Why**: committed schema is the input of `pnpm generate` (the UI's CI never runs Python).

### `packages/ai-parrot-server/ui/src/lib/types/generated/LinkedSources.d.ts` (CREATE)
```text
Generated — do not write by hand. Produced by step 3 (`pnpm generate`), banner "// GENERATED by scripts/generate_ts_types.py — DO NOT EDIT".
```
**Why**: codebase rule — `src/lib/types/generated/` is never hand-edited.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.ts` (CREATE)
```typescript
/**
 * A2UI linked-surface wire types (FEAT-598, spec §2 Data Models / §3 Module 11).
 *
 * Friendly re-exports of the types GENERATED from the `LinkedSources` JSON Schema
 * (`ui/schemas/LinkedSources.json` → `pnpm generate`). Never re-declare a field here:
 * Python ↔ TS drift must surface as a type error, not a silent mismatch.
 */
import type { CreateSurface } from '../a2ui-types';
// FILL IN: import the generated names exactly as `LinkedSources.d.ts` exports them — bounded by the generated file
import type { LinkedSources } from '$lib/types/generated/LinkedSources';

export type { LinkedSources };
// FILL IN: re-export LinkedDataSource, SourceRequest, ParamSpec, RefreshPolicy, TransformSpec, TransformRef
//          (and the op union if json2ts emits one) under these names — alias with `export type X = Generated` when json2ts titles differ

/** One QuerySource result row, `orient="records"` (spec §7 DSL semantics). */
export type Row = Record<string, unknown>;

/** Extension key carrying the descriptor (spec G2). */
export const DATA_SOURCES_EXTENSION = 'parrot_data_sources';

/**
 * Return the surface's `parrot_data_sources` mapping, or `null` when the surface is baked
 * (no key, not an object, or empty) — the TS twin of Python's `has_data_sources`.
 */
export function getDataSources(surface: CreateSurface): LinkedSources | null {
  const raw = surface.metadata?.extensions?.[DATA_SOURCES_EXTENSION];
  // FILL IN: return null unless raw is a non-null, non-array object with ≥1 key — bounded by has_data_sources semantics (spec M1)
  return raw as LinkedSources;
}
```
**Why this shape**: keeps the generated types the single source of truth (G1) and gives TASK-3795 one accessor instead of ad-hoc property walks.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts` (MODIFY)
```typescript
// occurrences: 1 (verified: grep -c '  dataModel?: Record<string, unknown>;' packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts)
// AFTER — insert below `  dataModel?: Record<string, unknown>;` (verified: a2ui-types.ts:67, inside `export interface CreateSurface {` L63)
  /** Surface-level metadata (FEAT-598): `extensions.parrot_data_sources` carries the linked-surface
   * descriptor (spec G2). Same shape as `WireComponent.metadata`. */
  metadata?: { extensions?: Record<string, unknown> };
```
**Why**: spec M11 skeleton (`metadata NEW`); additive, so baked envelopes type-check unchanged (G9).

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3792): getDataSources — the TS twin of has_data_sources.
import { describe, expect, it } from 'vitest';
import type { CreateSurface } from '../a2ui-types';
import { getDataSources } from './types';

const base: CreateSurface = { surfaceId: 's1', components: [{ id: 'root', component: 'Chart' }] };

describe('getDataSources', () => {
  it('returns null for a baked surface', () => {
    expect(getDataSources(base)).toBeNull();
  });
  // FILL IN: empty mapping → null; non-object → null; one source → the mapping (use a minimal valid descriptor literal typed as LinkedSources)
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py` (CREATE)
```python
"""FEAT-598 (TASK-3792): run the linked-types vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_a2ui_linked_types_vitest() -> None:
    """getDataSources vitest passes."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/types.test.ts")
```

### FILL IN checklist
- [ ] `types.ts` re-exports — exact generated names; bounded by `LinkedSources.d.ts`.
- [ ] `types.ts::getDataSources` — null for absent/empty/non-object; bounded by spec M1 `has_data_sources`.
- [ ] `types.test.ts` — the three remaining cases.

---

## Acceptance Criteria

- [ ] `ui/schemas/LinkedSources.json` and `generated/LinkedSources.d.ts` are committed; NO other file under `ui/schemas/` or `generated/` changed.
- [ ] `CreateSurface.metadata?: { extensions?: Record<string, unknown> }` exists; existing A2UI vitest files still pass.
- [ ] `getDataSources` returns `null` for baked surfaces and the mapping for linked ones.
- [ ] Codegen drift gate green.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py -q`
- `pytest packages/ai-parrot-server/tests/test_ts_codegen.py -q`

---

## Test Specification

See the `types.test.ts` block above; minimum cases: baked → null, empty → null, non-object → null, one source → mapping.

---

## Agent Instructions

1. **Read the spec** (§2 Data Models, §3 Module 11).
2. **Check dependencies** — TASK-3771 (and transitively TASK-3769) must be done.
3. **Verify the Codebase Contract** (grep the anchors; re-run the counts).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Verify** acceptance criteria + validation commands.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
