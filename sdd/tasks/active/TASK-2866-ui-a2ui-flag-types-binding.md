# TASK-2866: Bundled UI — `features.a2ui` flag, A2UI wire types, binding resolver, kind heuristic

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 G4, §2 New Public Interfaces (TypeScript), §3 Module 3. The bundled Svelte 5 SPA in
`packages/ai-parrot-server/ui` has no A2UI code at all (the only "a2ui" string is a generated
type). This task lays the non-visual foundation the renderer (TASK-2867) and the canvas
integration (TASK-2868) build on: a build-time flag, wire types, JSON-pointer binding resolution,
and the surface-kind heuristic from `docs/frontend/agentdashboard-a2ui-reference.md` §6.2.

---

## Scope

- `ui/vite.config.ts` — append `'A2UI'` to the `agentchatDefines` names array (`:22-31`) →
  `__AGENTCHAT_A2UI__` from `PUBLIC_AGENTCHAT_A2UI` (default `true`).
- `ui/src/lib/features.ts` — add `a2ui: __AGENTCHAT_A2UI__` to the frozen object (`:23-32`);
  declare the global in `ui/src/vite-env.d.ts` next to the other `__AGENTCHAT_*__` declarations
  (grep for `__AGENTCHAT_INFOGRAPHIC__` there).
- `ui/src/lib/types/agent.ts` — add `a2ui_envelope?: A2UIEnvelope` to `AgentMessage` (`:24-48`).
- New `ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts`: `A2UIEnvelope = { version: "v1.0";
  createSurface: CreateSurface }`, `CreateSurface = { surfaceId: string; catalogId?: string;
  components: WireComponent[]; dataModel?: Record<string, unknown> }`, `WireComponent = { id: string;
  component: string; [prop: string]: unknown }`, `Binding = { path: string }`, `SectionDescriptor =
  { component: string; properties?: Record<string, unknown> }`, `InfographicSection = { heading?;
  text?; components?: SectionDescriptor[] }`. Keep types structural (no runtime dependency);
  where `schemas/AgentChatResponse.json:160` already types `a2ui_envelope`, reuse/alias it.
- New `a2ui-binding.ts`: `isBinding(v): v is Binding`, `resolveBinding(value, dataModel)` — JSON
  Pointer (RFC 6901) resolution with `~0`/`~1` unescaping; `undefined` on a missing path;
  passthrough for non-bindings; `resolveProps(props, dataModel)` shallow-resolves every prop.
- New `a2ui-kind.ts`: `inferSurfaceKind(surface): "widget" | "infographic" | "dashboard"` exactly
  per doc §6.2 (root `Infographic`/`Report` → `dashboard` when `sections.length > 1` or
  `surfaceId.endsWith("-infographic")`, else `infographic`; anything else → `widget`), plus
  `hasInfographicRoot(envelope)`.
- `infographic-types.ts` — extend `InfographicTabData.mode` with `"a2ui"` and add
  `envelope?: A2UIEnvelope` (`:243-256`).
- Tests (vitest): `a2ui-binding.test.ts`, `a2ui-kind.test.ts`; extend `features.test.ts` for the new
  flag (mirror how `infographic` is asserted).

**NOT in scope**: Svelte components (TASK-2867); `InfographicCanvas`/`AgentChat` wiring (TASK-2868);
backend schema changes (`pnpm generate` only if `schemas/` changes — it does not here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/vite.config.ts` | MODIFY | `'A2UI'` define |
| `packages/ai-parrot-server/ui/src/lib/features.ts` | MODIFY | `a2ui` flag |
| `packages/ai-parrot-server/ui/src/vite-env.d.ts` | MODIFY | `__AGENTCHAT_A2UI__` declaration |
| `packages/ai-parrot-server/ui/src/lib/types/agent.ts` | MODIFY | `AgentMessage.a2ui_envelope` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts` | CREATE | wire types |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-binding.ts` | CREATE | resolver |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` | CREATE | heuristic |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` | MODIFY | `mode: "a2ui"`, `envelope` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-binding.test.ts` | CREATE | tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts` | CREATE | tests |
| `packages/ai-parrot-server/ui/src/lib/features.test.ts` | MODIFY | flag test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                                        // ui/src/lib/features.ts:23-32 (Object.freeze({voice, avatar, maps, charts, canvas, infographic, datasets, richEditor}))
import type { AgentMessage } from "$lib/types/agent";                           // ui/src/lib/types/agent.ts:24
import type { InfographicTabData, InfographicData } from "../infographic/infographic-types";  // infographic-types.ts:243, :180
import type { AgentChatResponse } from "$lib/types/generated/AgentChatResponse"; // generated: a2ui_envelope?: A2UiEnvelope :47
import { describe, expect, it, vi } from "vitest";                              // features-gating.test.ts:21
```

### Existing Signatures to Use
```ts
// ui/vite.config.ts
function agentchatFlag(value: string | undefined): boolean                          // :15-19 (undefined → true; 'false'/'0' → false)
function agentchatDefines(env): Record<string,string> { const names = ['VOICE','AVATAR','MAPS','CHARTS','CANVAS','INFOGRAPHIC','DATASETS','RICH_EDITOR'] as const; ... defines[`__AGENTCHAT_${name}__`] = JSON.stringify(agentchatFlag(env[`PUBLIC_AGENTCHAT_${name}`])) }  // :21-39
// vitest: separate ui/vitest.config.ts exists; `$app/environment` shimmed via alias (vite.config.ts:65) — check vitest.config.ts for `define` of the __AGENTCHAT_*__ globals in tests

// ui/src/lib/features.ts
export const features = Object.freeze({ voice: __AGENTCHAT_VOICE__, ..., infographic: __AGENTCHAT_INFOGRAPHIC__, datasets: __AGENTCHAT_DATASETS__, richEditor: __AGENTCHAT_RICH_EDITOR__ });  // :23-32

// ui/src/lib/types/agent.ts
export interface AgentMessage { id; role; content; timestamp; metadata?: AgentChatMetadata; data?; code?; output?; tool_calls?; output_mode?: string; htmlResponse?; sources?; documents?; type?; provider?; auth_url?; scopes?; audio_base64?; audio_format? }  // :24-48 (no a2ui_envelope today)

// ui/src/lib/components/agents/canvas/infographic/infographic-types.ts
export interface InfographicTabData { mode: "json" | "html"; html?: string; url?: string; infographic?: InfographicData; query?: string; template?: string; theme?: string; }  // :243-256

// ui/package.json: "test": "vitest run" :14 ; vitest ^3.2.7 ; @testing-library/svelte ^5.4.2 ; svelte ^5.55.7
// ui/schemas/AgentChatResponse.json: "a2ui_envelope": {...} :160 → generated type A2UiEnvelope (json2ts via `pnpm generate`)
// docs/frontend/agentdashboard-a2ui-reference.md §6.2 inferKind heuristic (reference implementation in TS)
```

### Does NOT Exist
- ~~`features.a2ui`, `__AGENTCHAT_A2UI__`~~ — created here.
- ~~`AgentMessage.a2ui_envelope`~~ — added here (only the generated `AgentChatResponse` has it today).
- ~~any `a2ui` directory or A2UI renderer in `ui/src`~~ — created by this and the next task.
- ~~a runtime JSON-pointer dependency~~ — implement RFC 6901 locally; do not add npm packages.
- ~~a `kind` field on the wire envelope~~ — the kind must be inferred (doc §6.2); it is explicit only on persisted `ui_surfaces` records.

---

## Implementation Notes

### Pattern to Follow
`features-gating.test.ts:21-33` uses `vi.hoisted` to mock `$lib/features`; `features.test.ts`
asserts flag wiring — extend both patterns rather than inventing new ones.

### Key Constraints
- Pure TypeScript modules (no Svelte) in this task so they are unit-testable in node.
- `resolveBinding` must not throw on malformed pointers — return `undefined`.
- Keep `InfographicTabData` backward compatible (`mode: "json" | "html" | "a2ui"`).

### References in Codebase
- `packages/ai-parrot-server/ui/src/lib/features.test.ts` — flag tests.
- `docs/frontend/agentdashboard-a2ui-reference.md` §4 (wire format), §6.2 (kind heuristic).

---

## Acceptance Criteria

- [ ] `features.a2ui` is `true` by default and `false` with `PUBLIC_AGENTCHAT_A2UI=false` (test)
- [ ] `resolveBinding({path:"/charts/chart-0/rows"}, dm)` returns the rows; missing path → `undefined`; non-binding passthrough; `~1`/`~0` unescaped
- [ ] `inferSurfaceKind` matches doc §6.2 for Infographic (1 vs >1 sections, `-infographic` suffix), Report, Chart roots
- [ ] `AgentMessage.a2ui_envelope` and `InfographicTabData.mode = "a2ui"` type-check (`pnpm check` if present, else `tsc --noEmit` via the project script)
- [ ] `cd packages/ai-parrot-server/ui && pnpm test` green

---

## Test Specification

```ts
// a2ui-binding.test.ts
import { describe, expect, it } from "vitest";
import { resolveBinding, isBinding, resolveProps } from "./a2ui-binding";

describe("resolveBinding", () => {
  const dm = { charts: { "chart-0": { rows: [{ m: "a", v: 1 }] } }, "a/b": { "c~d": 7 } };
  it("resolves a pointer", () => expect(resolveBinding({ path: "/charts/chart-0/rows" }, dm)).toEqual([{ m: "a", v: 1 }]));
  it("returns undefined on missing path", () => expect(resolveBinding({ path: "/nope/x" }, dm)).toBeUndefined());
  it("unescapes ~1 and ~0", () => expect(resolveBinding({ path: "/a~1b/c~0d" }, dm)).toBe(7));
  it("passes through non-bindings", () => expect(resolveBinding("literal", dm)).toBe("literal"));
  it("isBinding guards shape", () => { expect(isBinding({ path: "/x" })).toBe(true); expect(isBinding({ paths: "/x" })).toBe(false); });
});

// a2ui-kind.test.ts
it("one-section Infographic → infographic; two → dashboard; Chart root → widget", () => { ... });
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — open `vitest.config.ts` to see how `__AGENTCHAT_*__` globals are defined for tests before adding the new one
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2866-ui-a2ui-flag-types-binding.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
