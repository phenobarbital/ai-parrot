# TASK-3793: dsl.ts + conditions.ts against shared contract fixtures

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3792, TASK-3770, TASK-3774
**Assigned-to**: unassigned

---

## Context

Spec G1: one descriptor, one Python reference executor, **N renderer executors, one set of
golden fixtures**. The bundled UI is one of those renderers and implements its own port of
the transform DSL (spec §7 "DSL v1 semantics") and of `derive_conditions` (spec §7
"`derive_conditions` rules", S5). Parity is enforced by running the SAME JSON fixtures the
Python executor passes (spec M12, AC7): `contract/fixtures/dsl/*.json` (written by TASK-3773/TASK-3774)
and `contract/fixtures/conditions/*.json` (written by TASK-3770). Spec M11 says the DSL port is
delegation-eligible once the fixtures exist.

---

## Scope

- Implement `applyTransform(rows, spec, frames)` covering the ten ops, byte-for-byte the
  semantics of spec §7 (the fixtures are the contract, not prose).
- Implement `deriveConditions(request, locked)` — the TS twin of Python `derive_conditions`.
- `TransformError` with `sourceKey` / `opIndex` (spec §7: "a Python `TransformError` ↔ a TS
  thrown `TransformError` with the same `(source_key, op_index)`").
- `ref` specs return rows unchanged here (`ref` modules are loaded by TASK-3794's `loadRef`).
- Vitest suites parametrised over EVERY fixture file in both directories + pytest wrapper.

**NOT in scope**: fetching, scheduling, `ref` loading (TASK-3794); Svelte wiring (TASK-3795);
adding/changing fixtures (a DSL change must add fixtures on the Python side first — spec §7
risks). If a fixture looks wrong, STOP and report; never special-case it in TS.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts` | CREATE | `applyTransform`, `TransformError` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts` | CREATE | `deriveConditions` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.test.ts` | CREATE | golden over `contract/fixtures/dsl/*.json` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.test.ts` | CREATE | golden over `contract/fixtures/conditions/*.json` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```typescript
import { readdirSync, readFileSync } from 'node:fs';          // precedent: ui/src/lib/icons.test.ts:2
import { join, resolve } from 'node:path';                     // precedent: ui/src/lib/icons.test.ts:3
import { describe, expect, it } from 'vitest';                 // A2UISurface.test.ts:7
import type { Row, TransformSpec, SourceRequest } from './types';   // created by TASK-3792 (names as re-exported there)
```

### Existing Signatures to Use
```text
Shared fixtures (package data, created by TASK-3770/TASK-3773/TASK-3774):
  packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/<op>_<case>.json
      {"input": [...rows], "frames"?: {"<sibling key>": [...rows]}, "ops": [...], "expected": [...rows]}   (spec §4)
  packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/<case>.json
      {"request": {...SourceRequest}, "locked": {...}, "expected": {...}}                              (spec M12)
Fixture ACCESS (verified approach): vitest runs under Node (environment jsdom, vitest.config.ts) with cwd = ui/
  (tests/ui/_vitest.py runs `pnpm exec vitest run` with cwd=UI_DIR). Read with node:fs — NOT an import —
  so vite's server.fs.allow never applies:
     const CONTRACT = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract');
  (ui = packages/ai-parrot-server/ui → ../.. = packages/). icons.test.ts already reads files cwd-relatively.
Python reference (read before porting — semantics source): packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py (TASK-3773/TASK-3774),
  linked/conditions.py (TASK-3770), op models in linked/models.py (TASK-3769: discriminator field "op").
```

### Does NOT Exist
- ~~A TS DSL/conditions implementation anywhere in `ui/src`~~ — created here.
- ~~`golden/linked/` under `packages/ai-parrot/tests/`~~ — the fixtures live in the package at `linked/contract/fixtures/` (spec M12/S7).
- ~~`eval`/`new Function` for `derive`~~ — forbidden: `expr` is a binary tree of `+ - * /` over column names and numeric constants only.
- ~~an npm dependency for data frames (arquero, danfo)~~ — no new npm packages; plain arrays of records.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

> **Wire-name note (fixed by TASK-3769 `linked/models.py`)**: the union discriminator is `op` (`"op": "filter"`), so the
> Filter comparison field is **`operator`** (`eq|ne|gt|ge|lt|le|in|contains`), NOT `op` as spec §7 prose writes it;
> Join's sibling key is `with` on the wire (`with_` attribute, alias — dump with `by_alias=True`); the derive
> expression is a recursive `{operator, left, right}` tree where a string operand is a column and a number a constant.
> Fixtures, `dsl.py` and `dsl.ts` all use these names.


### DSL v1 semantics (spec §7, verbatim — binding)
- `select {columns}` keep+order; `rename {mapping}`; `filter {column, op ∈ eq|ne|gt|ge|lt|le|in|contains, value}` (null never matches); `group_by {by, aggregate: {col: sum|avg|count|min|max}}`; `sort {by: [{column, direction}]}` (stable; nulls last); `limit {n}`; `derive {name, expr}` where `expr` is a binary tree of `+ - * /` over column names and numeric constants only (`/` by zero → null); `pivot {index, columns, values, aggregate}`; `join {with: <sibling key>, how ∈ inner|left, on: [{left, right}]}` — equality only, `null` never matches, colliding column names take `<with>_` prefix, one join per step; `union {sources: [<sibling keys>]}` — concatenation on the intersection of column names, in order.
- Row records are `orient="records"`; dates serialize ISO-8601; numeric dtypes preserved.

### `derive_conditions` rules (spec §7, verbatim — binding)
- Output keys in this order: placeholders (request order) with `locked` values overriding same-named keys; then `filter` entries verbatim; then `fields`, `ordering`, `grouping` only when non-empty; then `limit` and `offset` mapped to the same dialect keys `build_conditions` uses. `querylimit` and `refresh` are never emitted. The exact key names are fixed by the first conditions fixture, not by prose.

### Key Constraints
- Pure functions; never mutate inputs (copy rows) — same contract as Python `apply_transform`.
- Key ORDER matters for `deriveConditions` (the renderer POSTs the object; equality is checked
  on the Python side with dict order) — build the output by insertion in rule order; the test
  compares `Object.keys(out)` as well as values.
- Rows arrive as JSON: datetimes are ISO strings. Comparisons (`gt/ge/lt/le`, sort) on two ISO
  datetime strings must compare instants (`Date.parse`), not lexicographically — `tz_datetime_roundtrip`
  pins this; output values stay the original strings.
- Error fixtures: if a fixture carries an error expectation (key name fixed by TASK-3773 — read the
  files), assert `TransformError` with the same `opIndex`.

---

## Implementation Blueprint

### Steps (in order)
1. Read `linked/dsl.py`, `linked/conditions.py`, `linked/models.py` and EVERY fixture file — *why*: fixtures + Python are the contract; prose is a summary.
2. Write `conditions.ts` and its golden test first — *why*: smallest surface, validates the fixture-loading approach.
3. Write `dsl.ts` op by op; run `dsl.test.ts` after each op — *why*: the golden suite localises failures to one fixture.
4. Write the pytest wrapper; run `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py -q`.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts` (CREATE)
```typescript
/**
 * Canonical request → QuerySource conditions (FEAT-598, spec §7 / S5).
 * TS twin of `parrot.outputs.a2ui.linked.conditions.derive_conditions`; pinned by
 * `contract/fixtures/conditions/*.json`. Never emits `querylimit` or `refresh` (lane-time keys).
 */
import type { SourceRequest } from './types';

export function deriveConditions(
  request: SourceRequest,
  locked: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  // FILL IN: placeholders in request order, locked values overriding same-named keys (locked-only keys appended after, as Python does) — bounded by §7 rule 1 + fixtures
  // FILL IN: filter entries verbatim — bounded by §7 rule 2
  // FILL IN: fields / ordering / grouping only when non-empty; then limit / offset under the dialect key names the fixtures use — bounded by §7 rules 3-4
  return out;
}
```
**Why**: a single insertion-ordered builder mirrors Python's dict order, so the renderer POSTs exactly what M3 validated.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts` (CREATE)
```typescript
/**
 * Transform DSL v1 executor for the bundled renderer (FEAT-598, spec §7 "DSL v1 semantics").
 * Ten declarative ops, no code. Parity with the Python reference is enforced by the shared
 * `contract/fixtures/dsl/*.json`. A `ref` spec returns rows unchanged (loaded by `ref.ts`).
 */
import type { Row, TransformSpec } from './types';

export class TransformError extends Error {
  constructor(
    message: string,
    public readonly sourceKey: string | null,
    public readonly opIndex: number,
  ) {
    super(message);
    this.name = 'TransformError';
  }
}

type Op = { op: string; [k: string]: unknown };

/** Apply `spec.ops` in order; `frames` maps sibling source keys to their already-transformed rows. */
export function applyTransform(
  rows: Row[],
  spec: TransformSpec | null | undefined,
  frames: Record<string, Row[]>,
  sourceKey: string | null = null,
): Row[] {
  if (!spec || !spec.ops) return rows.map((r) => ({ ...r }));
  let current: Row[] = rows.map((r) => ({ ...r }));
  (spec.ops as Op[]).forEach((op, i) => {
    current = applyOp(current, op, frames, sourceKey, i);
  });
  return current;
}

function applyOp(rows: Row[], op: Op, frames: Record<string, Row[]>, key: string | null, i: number): Row[] {
  switch (op.op) {
    case 'select':
    case 'rename':
    case 'filter':
    case 'sort':
    case 'limit':
    case 'derive':
      // FILL IN: one helper per op — bounded by §7 semantics + the matching fixtures (missing column → TransformError(key, i))
      return rows;
    case 'group_by':
    case 'pivot':
    case 'join':
    case 'union':
      // FILL IN: relational ops; join/union read `frames[op.with]` / `frames[s]` (unknown key → TransformError) — bounded by §7 semantics + fixtures
      return rows;
    default:
      throw new TransformError(`unknown op '${op.op}'`, key, i);
  }
}
```
**Why this shape**: a closed `switch` over the discriminator keeps the op set closed (spec G7) and makes an unknown op a thrown `TransformError`, matching Python. Split helpers into the same file if it exceeds ~80 lines per block — no new files.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3793): TS DSL passes EVERY shared contract fixture (spec AC7).
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { applyTransform } from './dsl';

const DSL_DIR = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl');
const files = readdirSync(DSL_DIR).filter((f) => f.endsWith('.json')).sort();

describe('dsl golden fixtures', () => {
  it('finds the shared fixtures', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  it.each(files)('%s', (file) => {
    const fx = JSON.parse(readFileSync(join(DSL_DIR, file), 'utf8'));
    // FILL IN: error-expectation fixtures → expect(() => …).toThrow(TransformError) with matching opIndex — key name fixed by TASK-3773
    expect(applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {})).toEqual(fx.expected);
  });
});
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.test.ts` (CREATE)
```typescript
// FEAT-598 (TASK-3793): deriveConditions matches every shared conditions fixture, key order included (S5).
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { deriveConditions } from './conditions';

const DIR = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions');
const files = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe('deriveConditions golden fixtures', () => {
  it.each(files)('%s', (file) => {
    const fx = JSON.parse(readFileSync(join(DIR, file), 'utf8'));
    const out = deriveConditions(fx.request, fx.locked ?? {});
    expect(out).toEqual(fx.expected);
    expect(Object.keys(out)).toEqual(Object.keys(fx.expected));
  });
  // FILL IN: never emits querylimit / refresh even when present in request — bounded by §7 rule
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py` (CREATE)
```python
"""FEAT-598 (TASK-3793): run the TS DSL + conditions golden suites from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_dsl_vitest() -> None:
    """dsl.ts and conditions.ts pass every shared contract fixture."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/linked/dsl.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/conditions.test.ts",
    )
```

### FILL IN checklist
- [ ] `conditions.ts` — three rule groups in order; bounded by §7 + fixtures (key order asserted).
- [ ] `dsl.ts` — six row-local ops; bounded by §7 + `select_*`/`rename_*`/`filter_*`/`sort_*`/`limit_*`/`derive_*` fixtures.
- [ ] `dsl.ts` — `group_by`/`pivot`/`join`/`union`; bounded by §7 + relational fixtures (null never matches; `<with>_` prefix).
- [ ] ISO-datetime comparison; bounded by `tz_datetime_roundtrip`.
- [ ] Error-fixture handling in `dsl.test.ts`; bounded by TASK-3773's fixture key.
- [ ] `conditions.test.ts` — no `querylimit`/`refresh`.

---

## Acceptance Criteria

- [ ] AC7 (TS half): `dsl.ts`/`conditions.ts` pass EVERY fixture under `parrot/outputs/a2ui/linked/contract/fixtures/` (incl. null/timezone/dtype/ordering/join-collision/empty cases).
- [ ] No fixture is special-cased; no new npm dependency; no `eval`/`Function`.
- [ ] `TransformError` carries `sourceKey` + `opIndex`.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py -q`

---

## Test Specification

The two golden suites above ARE the test specification (parametrised over the shared directories). Add focused unit cases only for behaviour no fixture covers (e.g. unknown op → `TransformError`).

---

## Agent Instructions

1. **Read the spec** (§7 DSL + derive_conditions rules, M11, M12).
2. **Check dependencies** — TASK-3792, TASK-3770, TASK-3774 done (fixtures must exist on disk).
3. **Verify the Codebase Contract** (fixture dir exists; generated names in `types.ts`).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Verify**; move this file to `sdd/tasks/completed/`; index → `"done"`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
