# TASK-3836: Admin canvas wiring for linked surfaces

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3835, TASK-3833
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 6. It also covers §9 S2 ("route linked surfaces through a generic canvas path") and the UI half of §9 S3 ("carry the persisted surface id").

Even once TASK-3835 lifts a linked envelope into `response.a2ui_envelope`, the admin UI still drops it. `buildInfographicTabData` returns `null` for every `output_mode: "a2ui"` turn whose root is not `Infographic`/`Report` (infographic-tab-builder.ts:60). Linked surfaces have `Chart`/`DataTable`/`Column` roots. In addition, `InfographicCanvas` renders `<A2UISurface envelope=…/>` without `persistedSurfaceId` (InfographicCanvas.svelte:353). The server-lane **Refresh** button, which is gated on that prop (A2UISurface.svelte:187), therefore never appears.

### Carrier decision for the persisted surface id (evidence)

The id travels in **`message.metadata.a2ui_surface_id`**. There is no new top-level message field and no server change.

1. TASK-3835 writes `response.metadata["a2ui_surface_id"]` (bots/base.py `ask()`).
2. The server's `OutputMode.A2UI` JSON branch forwards `response.metadata` **verbatim**. It copies `dict(response.metadata)` and adds model, provider and so on (`packages/ai-parrot-server/src/parrot/handlers/agent.py:2804-2823`).
3. `AgentChat.svelte` spreads the server metadata into the message at every construction site (`metadata: { ...agentResult.metadata, ... }` :1016, `...result.metadata` :1355 and :1545).
4. `AgentMessage.metadata` is `AgentChatMetadata` (types/agent.ts:30), which is generated with an index signature `[k: string]: unknown` (types/generated/AgentChatMetadata.d.ts). It already types the key, and generated files must not be hand-edited.

For these reasons `types/agent.ts` is **not** modified. The spec skeleton's `agent.ts:51 a2ui_surface_id?` would be a field that nothing populates without also editing AgentChat.svelte's three construction sites. The streaming path is out of scope: its final envelope carries a fixed `metadata` and **no `output_mode`** (agent.py:2640-2681), so no a2ui canvas opens from a streamed turn today, regardless of this task.

---

## Scope

- Add `export function isLinkedSurface(envelope)` to `a2ui-kind.ts`. It is true when the envelope's `createSurface` carries a non-empty `metadata.extensions.parrot_data_sources`, and it reuses `getDataSources` (linked/types.ts:43).
- In `buildInfographicTabData`:
  - An `output_mode === 'a2ui'` turn opens an a2ui tab when the root is Infographic-like **or** `isLinkedSurface(envelope)`.
  - The tab data carries `persistedSurfaceId` from `message.metadata?.a2ui_surface_id` when it is a string.
- Add `persistedSurfaceId?: string` to `InfographicTabData` (infographic-types.ts).
- Pass `persistedSurfaceId={tabData?.persistedSurfaceId}` to `A2UISurface` in `InfographicCanvas.svelte`.
- Tests:
  - A new `infographic-tab-builder.test.ts`. There is no test file of that name today; the existing builder tests live in `AgentChat.a2ui-canvas.test.ts`, which is left unchanged.
  - One new case in `InfographicCanvas.a2ui.test.ts`: the Refresh button appears only with `persistedSurfaceId`.
  - A pytest wrapper `tests/ui/test_vitest_a2ui_canvas_linked.py`.

**NOT in scope**:
- `A2UISurface.svelte`, which is owned by TASK-3833 (serverRefresh / currentParams). This task only passes an existing prop (`persistedSurfaceId?: string`, A2UISurface.svelte:37).
- `types/agent.ts`, `AgentChat.svelte`, `handlers/agent.py` and the generated types. See the carrier decision above.
- The tab title (`"Infographic"` from `maybeOpenInfographicCanvas`, AgentChat.svelte:1860-1865) and an admin page that lists surfaces.
- Widget-only a2ui turns **without** `parrot_data_sources`. They must keep returning `null`, as the existing test in AgentChat.a2ui-canvas.test.ts:79-83 checks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` | MODIFY | New export `isLinkedSurface` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts` | MODIFY | Open a tab for linked roots; carry `persistedSurfaceId` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` | MODIFY | `InfographicTabData.persistedSurfaceId?: string` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte` | MODIFY | Pass `persistedSurfaceId` to `A2UISurface` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.test.ts` | CREATE | Linked widget/Column root opens a tab; plain widget → null; id carried |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts` | MODIFY | Refresh button present only with `persistedSurfaceId` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py` | CREATE | pytest wrapper running the canvas vitest files |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```ts
// a2ui-kind.ts:11 (existing)
import type { A2UIEnvelope, CreateSurface, WireComponent } from './a2ui-types';
// NEW in a2ui-kind.ts — verified export at linked/types.ts:43 (types.ts itself only imports types from '../a2ui-types', no cycle)
import { getDataSources } from './linked/types';
// infographic-tab-builder.ts:15-17 (existing)
import { hasInfographicRoot } from './a2ui/a2ui-kind';
import type { A2UIEnvelope } from './a2ui/a2ui-types';
import type { InfographicTabData } from './infographic/infographic-types';
// tests (verified in InfographicCanvas.a2ui.test.ts:2-21 and AgentChat.a2ui-canvas.test.ts:6-7)
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
```
```python
# wrapper — verified tests/ui/_vitest.py:15 and test_vitest_a2ui_linked_types.py:3
from ._vitest import run_vitest
```

### Existing Signatures to Use
```ts
// canvas/a2ui/a2ui-kind.ts
const INFOGRAPHIC_LIKE_ROOTS = new Set(['Infographic', 'Report']);                          // :18
export function hasInfographicRoot(envelope: A2UIEnvelope | null | undefined): boolean;     // :42-46
// canvas/a2ui/linked/types.ts
export const DATA_SOURCES_EXTENSION = 'parrot_data_sources';                                // :37
export function getDataSources(surface: CreateSurface): LinkedSources | null;               // :43-49 (null when absent/non-object/empty)
// canvas/a2ui/a2ui-types.ts
export interface CreateSurface { surfaceId; catalogId?; components; dataModel?; metadata?: { extensions?: Record<string, unknown> } }  // :63-71
export interface A2UIEnvelope { version: "v1.0"; createSurface: CreateSurface }            // :75-78
// canvas/infographic-tab-builder.ts
export interface InfographicMessageLike { output_mode?; output?; metadata?: {html_inline_omitted?; html_url?; template_name?; theme?: unknown} | null; a2ui_envelope?: A2UIEnvelope }  // :20-30
export function buildInfographicTabData(message: InfographicMessageLike, features: { a2ui: boolean }): InfographicTabData | null;  // :41-83
// canvas/infographic/infographic-types.ts
export interface InfographicTabData { mode: "json"|"html"|"a2ui"; html?; url?; infographic?; query?; template?; theme?; envelope?: A2UIEnvelope }  // :246-264
// canvas/a2ui/A2UISurface.svelte
// props { envelope: A2UIEnvelope; persistedSurfaceId?: string; transformsBase?: string }   // :33-37
// Refresh button rendered only `{#if sources}` … `{#if persistedSurfaceId}` <button>Refresh</button>  // :166, :187-191
// refresh policy 'manual' never fetches (A2UISurface.linked.test.ts header comment :1-2)
// canvas/canvas-tab-manager.svelte.ts — resetCanvas/initCanvas/addTab/setActiveTab used by InfographicCanvas.a2ui.test.ts:32-44
```
```python
# packages/ai-parrot-server/tests/ui/_vitest.py
def run_vitest(*files: str) -> None  # :15 — skips when pnpm / ui node_modules are absent
```

### Does NOT Exist
- ~~`packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.test.ts`~~. It does not exist today; this task creates it. The builder's current tests are in `components/agents/AgentChat.a2ui-canvas.test.ts`.
- ~~`isLinkedSurface`~~ anywhere in the UI (this task creates it) · ~~`InfographicTabData.persistedSurfaceId`~~ · ~~a persisted surface id on messages or tabs~~ (spec §6).
- ~~`AgentMessage.a2ui_surface_id`~~. It is deliberately not added (carrier decision).
- ~~`AgentChatMetadata.a2ui_surface_id` as a named field~~. It is covered by the index signature; do not edit `types/generated/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts#hasInfographicRoot",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.ts#getDataSources",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts#buildInfographicTabData",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts#InfographicMessageLike",
    "sym:packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts#InfographicTabData",
    "sym:packages/ai-parrot-server/tests/ui/_vitest.py#run_vitest"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- `isLinkedSurface` mirrors `hasInfographicRoot` (null-safe on `envelope`) and delegates to `getDataSources`, the TS twin of Python's `has_data_sources`. That keeps a single definition of "linked".
- The canvas test copies `openA2uiTab()` from `InfographicCanvas.a2ui.test.ts:32-44` and the linked envelope from `A2UISurface.linked.test.ts:25-52`, with `refresh: { policy: 'manual' }` so the lane never calls `fetch`.

### Key Constraints
- Every existing `AgentChat.a2ui-canvas.test.ts` case must stay green. In particular a widget root **without** `parrot_data_sources` → `null` for both flag values.
- With `features.a2ui` off, a linked a2ui turn falls through to the HTML fallback, which yields `null` unless html/url exist. Do not special-case it: the a2ui canvas is feature-flagged by design.
- Only accept `persistedSurfaceId` when `typeof metadata.a2ui_surface_id === 'string'` and it is non-empty, because the metadata is untyped `unknown` from the wire.
- Svelte 5 runes only. InfographicCanvas already uses `$derived`/`$state`, and the change is a prop pass-through.
- pnpm + vitest. This needs Node ≥24 and `pnpm install --frozen-lockfile` (spec §7). The wrapper skips when `node_modules` is absent (_vitest.py:17-18). Record whether it actually ran in the Completion Note.

### References in Codebase
- `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.a2ui-canvas.test.ts`: the builder decision table.
- `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py`: a multi-file wrapper.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `isLinkedSurface` to `a2ui-kind.ts`. *Why*: the builder guard and the tests import it.
2. Add `persistedSurfaceId?` to `InfographicTabData`. *Why*: the builder return type must allow it.
3. Update `buildInfographicTabData`. *Why*: this is the S2 fix; it is the only place that decides whether a tab opens.
4. Pass the prop in `InfographicCanvas.svelte`. *Why*: it enables the Refresh (server lane) button.
5. Write both vitest files and the wrapper. Run the wrapper, and record in the Completion Note whether it ran or skipped.

### `…/canvas/a2ui/a2ui-kind.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -cF "import type { A2UIEnvelope, CreateSurface, WireComponent } from './a2ui-types';" packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts)
// AFTER — insert below that import (verified: a2ui-kind.ts:11)
import { getDataSources } from './linked/types';

// occurrences: 1 (verified: grep -cF 'export function hasInfographicRoot(envelope: A2UIEnvelope | null | undefined): boolean {' …/a2ui-kind.ts)
// APPEND at end of file (after hasInfographicRoot's closing brace, :46)

/** True when `envelope` is a FEAT-598 linked surface — its `createSurface` carries a non-empty
 * `metadata.extensions.parrot_data_sources` (FEAT-611 M6). Root-agnostic: linked surfaces are
 * usually Chart/DataTable/Column roots, which `hasInfographicRoot` rejects. */
export function isLinkedSurface(envelope: A2UIEnvelope | null | undefined): boolean {
  // FILL IN: return false for a missing envelope/createSurface; else getDataSources(envelope.createSurface) !== null
  //   — bounded by getDataSources' null contract (linked/types.ts:43-49)
}
```

### `…/canvas/infographic/infographic-types.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -cF '  envelope?: A2UIEnvelope;' packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts)
// AFTER — insert below `  envelope?: A2UIEnvelope;` (verified: infographic-types.ts:263)
  /**
   * Persisted `ui_surfaces` row id (FEAT-611 M6) — from `message.metadata.a2ui_surface_id`, set by the
   * bot when `publish_surface` ran in the same turn. When present, `A2UISurface` shows the server-lane
   * Refresh (`POST /api/v1/ui/surfaces/{id}/refresh`).
   */
  persistedSurfaceId?: string;
```

### `…/canvas/infographic-tab-builder.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -cF "import { hasInfographicRoot } from './a2ui/a2ui-kind';" …/infographic-tab-builder.ts)
// REPLACE :15 with
import { hasInfographicRoot, isLinkedSurface } from './a2ui/a2ui-kind';

// occurrences: 1 (verified: grep -cF '    theme?: unknown;' …/infographic-tab-builder.ts)
// AFTER — insert below `    theme?: unknown;` (verified: infographic-tab-builder.ts:27, inside InfographicMessageLike.metadata)
    a2ui_surface_id?: unknown;

// occurrences: 1 (verified: grep -cF '  const hasRoot = hasInfographicRoot(message.a2ui_envelope);' …/infographic-tab-builder.ts)
// AFTER — insert below that line (verified: :55)
  const linked = isLinkedSurface(message.a2ui_envelope);
  // FILL IN: const persistedSurfaceId = string & non-empty meta?.a2ui_surface_id, else undefined — bounded by Key Constraints

// occurrences: 1 (verified: grep -cF "if (message.output_mode === 'a2ui' && !hasRoot) return null;" …/infographic-tab-builder.ts)
// REPLACE :60 with
  if (message.output_mode === 'a2ui' && !hasRoot && !linked) return null;

// occurrences: 1 (verified: grep -cF 'if (features.a2ui && message.a2ui_envelope && hasRoot) {' …/infographic-tab-builder.ts)
// REPLACE :62 with
  if (features.a2ui && message.a2ui_envelope && (hasRoot || linked)) {
// and inside that return object, below `      envelope: message.a2ui_envelope,` (:65, occurrences: 1) add:
      ...(persistedSurfaceId ? { persistedSurfaceId } : {}),
```
**Why**: the conditional spread keeps the existing `toMatchObject` expectations byte-identical. No `persistedSurfaceId: undefined` key appears. Also update the comments at :57-59 and the module docblock (:11-13), which say that a widget-only a2ui turn never opens. They must now mention the linked exception.

### `…/canvas/InfographicCanvas.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -cF '<A2UISurface envelope={tabData?.envelope} />' …/InfographicCanvas.svelte) -->
<!-- REPLACE :353 with -->
					<A2UISurface envelope={tabData?.envelope} persistedSurfaceId={tabData?.persistedSurfaceId} />
```

### `…/canvas/infographic-tab-builder.test.ts` (CREATE)
```ts
// ai-parrot (FEAT-611 M6): linked surfaces (Chart/DataTable/Column roots + parrot_data_sources) open the a2ui canvas.
import { describe, expect, it } from 'vitest';
import { isLinkedSurface } from './a2ui/a2ui-kind';
import { buildInfographicTabData } from './infographic-tab-builder';

function linkedEnvelope(rootComponent: string) {
  return {
    version: 'v1.0' as const,
    createSurface: {
      surfaceId: 'linked-activity',
      components: [{ id: 'root', component: rootComponent }],
      dataModel: {},
      metadata: { extensions: { parrot_data_sources: { activity: { kind: 'query_slug', slug: 'epson_field_activity', target: '/activity/rows' } } } },
    },
  };
}

const plainWidget = { version: 'v1.0' as const, createSurface: { surfaceId: 'chart', components: [{ id: 'root', component: 'Chart' }] } };

describe('isLinkedSurface', () => {
  it('detects parrot_data_sources', () => {
    expect(isLinkedSurface(linkedEnvelope('Chart'))).toBe(true);
  });
  it('rejects baked / empty / missing', () => {
    // FILL IN: plainWidget -> false; parrot_data_sources: {} -> false; undefined/null -> false
  });
});

describe('buildInfographicTabData — linked', () => {
  it('linked widget root opens tab', () => {
    // FILL IN: {output_mode:'a2ui', a2ui_envelope: linkedEnvelope('Chart')} + {a2ui:true} -> toMatchObject({mode:'a2ui', envelope})
  });
  it('linked Column root opens tab', () => {
    // FILL IN: same with linkedEnvelope('Column')
  });
  it('plain non-Infographic root still returns null', () => {
    // FILL IN: plainWidget -> null for a2ui:true and a2ui:false (mirrors AgentChat.a2ui-canvas.test.ts:79-83)
  });
  it('carries persistedSurfaceId from metadata.a2ui_surface_id', () => {
    // FILL IN: metadata {a2ui_surface_id:'srf-1'} -> result.persistedSurfaceId === 'srf-1';
    //   non-string (123) or '' -> 'persistedSurfaceId' not in result
  });
  it('flag off degrades to null without html/url', () => {
    // FILL IN: linkedEnvelope('Chart'), {a2ui:false}, no metadata -> null
  });
});
```

### `…/canvas/InfographicCanvas.a2ui.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -cF "  it('still falls back to the url iframe when html is an empty string', async () => {" …/InfographicCanvas.a2ui.test.ts)
// BEFORE — insert above that `it(` (verified: :90), inside `describe('InfographicCanvas — a2ui mode'`
  it('passes persistedSurfaceId to A2UISurface (server-lane Refresh shown only then)', async () => {
    // FILL IN: build a linked envelope (Text root, one source with refresh:{policy:'manual'} — copy
    //   A2UISurface.linked.test.ts:25-52) and openA2uiTab({ envelope: linked, persistedSurfaceId: 'srf-1' });
    //   render(InfographicCanvas, { data: null }); expect(await screen.findByRole('button', { name: 'Refresh' })).toBeInTheDocument();
    //   then openA2uiTab({ envelope: linked }) re-render -> queryByRole('button', { name: 'Refresh' }) is null
    //   — bounded by: never real network (manual policy); openA2uiTab's `...overrides` already lets `envelope` be replaced (:37-42)
  });

```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py` (CREATE)
```python
"""FEAT-611 (TASK-3836): run the admin-canvas linked-surface vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_a2ui_canvas_linked_vitest() -> None:
    """Linked roots open the a2ui canvas with persistedSurfaceId; existing canvas decision table stays green."""
    run_vitest(
        "src/lib/components/agents/canvas/infographic-tab-builder.test.ts",
        "src/lib/components/agents/AgentChat.a2ui-canvas.test.ts",
        "src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
    )
```

### FILL IN checklist
- [ ] `a2ui-kind.ts::isLinkedSurface`: the null-safe delegate to `getDataSources`.
- [ ] `infographic-tab-builder.ts`: the `persistedSurfaceId` string guard; the conditional spread; the updated comments.
- [ ] `infographic-tab-builder.test.ts`: every `it` body.
- [ ] `InfographicCanvas.a2ui.test.ts`: the Refresh present/absent case.

---

## Acceptance Criteria

- [ ] An `output_mode: 'a2ui'` turn whose envelope carries `parrot_data_sources` (Chart or Column root) opens an a2ui canvas tab when `features.a2ui` is on (spec §4 row `infographic-tab-builder.test.ts::linked widget root opens tab`).
- [ ] Plain non-Infographic roots without data sources still return `null`. All `AgentChat.a2ui-canvas.test.ts` cases pass unchanged.
- [ ] `message.metadata.a2ui_surface_id` reaches `A2UISurface` as `persistedSurfaceId`, and the Refresh button renders only then.
- [ ] No edits to `A2UISurface.svelte`, `types/agent.ts` or `types/generated/`.
- [ ] The vitest wrapper passes. If it skips, the Completion Note says so and records the Node/pnpm state.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py -q`

---

## Test Specification

See the CREATE and MODIFY test blocks above: 7 builder/kind cases, 1 canvas case, and 1 pytest wrapper.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec**: §3 M6, §9 S2/S3.
3. **Check dependencies**: TASK-3835 and TASK-3833 must be `done`.
4. **Verify the Codebase Contract**: re-run each `grep -cF`. After TASK-3833 lands, re-check that `A2UISurface.svelte` still gates Refresh on `persistedSurfaceId`.
5. **Update status** in `sdd/tasks/index/a2ui-linked-e2e-parallel.json` → `"in-progress"`.
6. **Implement** from the Blueprint, and complete every `FILL IN`.
7. **Verify** by running the Validation Commands.
8. **Commit the code**. Stage only the seven files listed.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3836 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**, including whether vitest actually ran.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `types/agent.ts` is not modified (carrier = `metadata.a2ui_surface_id`, see Context). The builder tests live in a new `infographic-tab-builder.test.ts`.
