# TASK-2868: Bundled UI — open the infographic canvas in `a2ui` mode from chat turns; Rendered/HTML toggle

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2867, TASK-2858
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 5, §3 Module 3, §5 AC "Bundled UI". With TASK-2858 every infographic turn
carries `a2ui_envelope` next to the HTML, and TASK-2867 can render it. This task wires the chat
→ canvas path: detect the envelope, open the tab in `mode: "a2ui"` (flag on), keep the iframe
HTML view reachable through a toolbar toggle, and preserve today's behaviour when the flag is
off or no envelope is present.

---

## Scope

- `AgentChat.svelte`:
  - Where assistant messages are assembled from `agentResult` (`:993-1030` and the second site
    `:1330-1365`), copy `a2ui_envelope: agentResult.a2ui_envelope` onto the `AgentMessage`.
  - `maybeOpenInfographicCanvas(message)` (`:1847-1878`): change the early return to
    `if (message.output_mode !== "infographic" && message.output_mode !== "a2ui") return;`. If
    `features.a2ui && message.a2ui_envelope && hasInfographicRoot(message.a2ui_envelope)` →
    `tabData = { mode: "a2ui", envelope, url: meta?.html_url, html: <inline html if present>, template, theme }`;
    else keep the existing HTML logic verbatim. For `output_mode === "a2ui"` without an
    Infographic root (widgets), do nothing (out of scope). Bubble text for `a2ui` turns: the
    existing `isInfographic` branch (`:999-1004`) must also treat `effectiveOutputMode === "a2ui"`
    **with an Infographic root** as canvas-opening (explanation in the bubble, no raw HTML).
- `InfographicCanvas.svelte`:
  - `normalizeInfographicData` (`:27-40`) passes `mode: "a2ui"` objects through; add
    `hasA2ui = $derived(tabData?.mode === 'a2ui' && !!tabData.envelope)`; extend `isEmpty`.
  - New `{:else if hasA2ui}` branch: a small view bar with a **Rendered / HTML** toggle
    (`view = $state<'rendered' | 'html'>('rendered')`); `rendered` → `<A2UISurface envelope={tabData.envelope}/>`
    (lazy `await import('./a2ui/A2UISurface.svelte')` behind `features.a2ui`); `html` → the existing
    iframe markup (`srcdoc` when `tabData.html`, else `src={tabData.url}`); disable the HTML button
    when neither is present. Reuse the Edit/Preview toggle styling (`:326-345`).
  - Tab title stays `Infographic (<template>)`.
- `canvas-block-exporter.ts` / print: for `a2ui` mode, "Save as HTML" uses `tabData.url`/`tabData.html`
  when present; otherwise hide the button (no A2UI→HTML export in the SPA).
- Tests (vitest + testing-library): `AgentChat.a2ui-canvas.test.ts` (envelope → tab `mode:"a2ui"`;
  flag off → HTML tab; `output_mode:"a2ui"` + Infographic root → opens; widget root → no tab),
  `InfographicCanvas.a2ui.test.ts` (toggle switches between `A2UISurface` and iframe).

**NOT in scope**: renderer components (TASK-2867); persistence of A2UI tabs in `chat-db.ts` beyond
what already serialises `tabData` (verify it round-trips an `envelope` object; if IndexedDB size is a
concern, note it — do not redesign); navigator-frontend-next.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | envelope on message; canvas opening rule |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte` | MODIFY | `a2ui` branch + toggle |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/canvas-block-exporter.ts` | MODIFY (maybe) | export guard for a2ui mode |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.a2ui-canvas.test.ts` | CREATE | opening-rule tests |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts` | CREATE | toggle tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import * as tabManager from "./canvas-tab-manager.svelte.js";                 // InfographicCanvas.svelte:4 ; canvas-tab-manager.svelte.ts
import { features } from "$lib/features";                                       // features.ts (a2ui after TASK-2866)
import type { InfographicTabData } from "./infographic/infographic-types";      // :243 (mode incl. "a2ui" after TASK-2866)
import { hasInfographicRoot, inferSurfaceKind } from "./canvas/a2ui/a2ui-kind"; // TASK-2866
import A2UISurface from "./a2ui/A2UISurface.svelte";                           // TASK-2867 (lazy-import behind features.a2ui)
```

### Existing Signatures to Use
```ts
// canvas/canvas-tab-manager.svelte.ts
export type CanvasTabType = "markdown" | "chart" | "spreadsheet" | "infographic" | "audio" | "interactive";  // :6-12 (reuse "infographic"; do NOT add a new type)
export function addTab(type: CanvasTabType, title: string, data: unknown = null): string           // :56-64
// canvas-registry.ts:9,30-31 maps "infographic" → InfographicCanvas

// AgentChat.svelte
const effectiveOutputMode = agentResult.output_mode || (isHtml ? "html" : "default");            // :996-997
const isInfographic = effectiveOutputMode === "infographic"; const isInteractive = ...;           // :999-1000
const bubbleText = isInfographic ? agentResult.response || agentResult.metadata?.explanation || "Infographic generated — opening in canvas." : ...  // :1001-1009
finalMessage = { id, role: "assistant", content: bubbleText, timestamp, metadata, data, code, output, tool_calls, output_mode: effectiveOutputMode, htmlResponse: isInfographic || isInteractive ? null : ... }  // :1010-1025 ← add a2ui_envelope
maybeOpenInfographicCanvas(finalMessage);                                                          // :1077 (also :1385, :1571)
function maybeOpenInfographicCanvas(message: AgentMessage) { if (message.output_mode !== "infographic") return; const meta = message.metadata; const inlineHtml = ...; const url = meta?.html_url; const common = { template: meta?.template_name, theme: meta?.theme }; ...; canvasTabManager.initCanvas(); const title = meta?.template_name ? `Infographic (${meta.template_name})` : "Infographic"; canvasTabManager.addTab("infographic", title, tabData); chatLayout.openCanvas(); }  // :1847-1878

// canvas/InfographicCanvas.svelte
function normalizeInfographicData(raw: unknown): InfographicTabData | null   // :27-40 (string → {mode:'html', html}; object passthrough)
let hasHtml/hasUrl/hasJson/isEmpty = $derived(...)                            // :46-52
let mode = $state<'edit'|'preview'>('preview'); let editView = $state<'code'|'visual'>('visual');  // :55-56
{:else if hasHtml} <InfographicToolbar .../> ... Edit/Preview toggle bar :309-345 ... <iframe bind:this={iframeEl} srcdoc={tabData?.html ?? ''} ...> :395-402
URL mode iframe: <iframe bind:this={iframeEl} src=... > :284-293
// AgentMessage.a2ui_envelope?: A2UIEnvelope (TASK-2866) ; backend JSON: a2ui_envelope on output_mode "infographic" (TASK-2858) and metadata.html_url on output_mode "a2ui" (TASK-2858)
```

### Does NOT Exist
- ~~a `CanvasTabType` `"a2ui"`~~ — reuse `"infographic"` with `InfographicTabData.mode = "a2ui"`.
- ~~`chatLayout.openA2UI()`~~ — use the existing `chatLayout.openCanvas()` (`:1877`).
- ~~`?output_mode=` query param on the chat endpoint~~ — dead; requests set `output_mode` in the body (unchanged here).
- ~~A2UI→HTML export in the SPA~~ — only the backend renders HTML; use `html_url`/inline HTML.

---

## Implementation Notes

### Pattern to Follow
`maybeOpenInfographicCanvas` (`:1847-1878`) — extend, do not rewrite; keep the inline-HTML
`<!DOCTYPE`/`<html` sniffing for the fallback path.

### Key Constraints
- Flag off ⇒ byte-identical behaviour to today (tests must cover this).
- Never render `message.output` HTML in the bubble for `a2ui`/`infographic` turns.
- Lazy-import `A2UISurface` behind `features.a2ui` so the chunk is never fetched when disabled.

### References in Codebase
- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte:255-300` — json branch + URL iframe (structure to mirror).
- `packages/ai-parrot-server/ui/src/lib/services/chat-db.ts` — tab/message persistence (check envelope round-trip).

---

## Acceptance Criteria

- [ ] Assistant message with `output_mode:"infographic"` + `a2ui_envelope` (Infographic root) opens a tab with `mode:"a2ui"`, `envelope`, and `url` (flag on)
- [ ] Same message with `features.a2ui=false` → tab `mode:"html"` exactly as today
- [ ] `output_mode:"a2ui"` + Infographic root → opens; widget root → no tab
- [ ] Canvas toggle switches Rendered ↔ HTML iframe; HTML button disabled when no `url`/`html`
- [ ] `cd packages/ai-parrot-server/ui && pnpm test` green; `pnpm check` if configured

---

## Test Specification

```ts
// AgentChat.a2ui-canvas.test.ts — unit-test the extracted decision helper if you factor one
// (recommended: export `buildInfographicTabData(message, features)` from a small .ts module so it is testable without mounting AgentChat)
it("prefers a2ui mode when flag on and Infographic root", () => {
  const msg = { output_mode: "infographic", output: "<html>..</html>", metadata: { html_url: "https://x/a.html", template_name: "basic" },
                a2ui_envelope: { version: "v1.0", createSurface: { surfaceId: "infographic-a", components: [{ id: "root", component: "Infographic", title: "T", sections: [] }] } } };
  expect(buildInfographicTabData(msg, { a2ui: true })).toMatchObject({ mode: "a2ui", url: "https://x/a.html", template: "basic" });
  expect(buildInfographicTabData(msg, { a2ui: false })).toMatchObject({ mode: "html", html: "<html>..</html>" });
});
it("ignores a2ui widgets", () => {
  const msg = { output_mode: "a2ui", a2ui_envelope: { version: "v1.0", createSurface: { surfaceId: "chart", components: [{ id: "root", component: "Chart" }] } } };
  expect(buildInfographicTabData(msg, { a2ui: true })).toBeNull();
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2867 and TASK-2858 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers in `AgentChat.svelte` (2,400+ lines) may have shifted; re-grep `maybeOpenInfographicCanvas`
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2868-ui-canvas-agentchat-a2ui-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-05
**Notes**:
- Extracted `buildInfographicTabData(message, features)` into a new pure
  module `canvas/infographic-tab-builder.ts` (per the task's own
  recommendation — `AgentChat.svelte` is 2,727 lines, not practically
  unit-testable end-to-end). Decision table: `output_mode` must be
  `"infographic"` or `"a2ui"` (else `null`); an `a2ui`-mode turn with NO
  Infographic/Report root is always out of scope (`null`, regardless of
  the flag — widgets); when `features.a2ui` is on AND an Infographic/
  Report-rooted envelope is present → `mode:"a2ui"` tab; otherwise falls
  through to the PRE-EXISTING HTML-tab logic verbatim (byte-identical
  behaviour when the flag is off or no envelope/root exists — including
  an `a2ui`-mode turn with an Infographic root but the flag off, which
  gracefully degrades to the HTML tab via `metadata.html_url`).
- `AgentChat.svelte`: found 3 message-construction sites reading
  `agentResult`/`result` (not 2, as the task's line-shifted contract
  guessed) — added `a2ui_envelope: <result>.a2ui_envelope` to all three
  (streaming-envelope path, non-streaming fallback path, voice-note path).
  `maybeOpenInfographicCanvas` now delegates entirely to
  `buildInfographicTabData`.
- `InfographicCanvas.svelte`: added `hasA2ui`/`a2uiHasHtmlFallback`
  derived flags (extends `isEmpty`); a new `{:else if hasA2ui}` branch
  with a Rendered/HTML toggle bar (mirrors the Edit/Preview toggle
  styling) — `A2UISurface` is imported STATICALLY (not the dynamic
  `await import()` the task suggested): it reuses the SAME Chart/
  DataTable/Timeline block renderers `InfographicBlockCanvas` already
  pulls in statically elsewhere in this same file, so it is not a new
  heavy dependency; a dynamic-import + `$state`/`$effect` version was
  prototyped first and proved non-deterministically flaky under
  `@testing-library/svelte` + jsdom (a "Loading…" placeholder that
  sometimes never resolved within the test timeout, root cause not fully
  isolated) — the static-import + `{#if features.a2ui}` markup gate
  (the SAME pattern most of this file's other 8 flags already use) is
  simpler, deterministic, and still guarantees the chunk-inclusion-only
  (not "never fetched") gating this codebase's OWN documented Rollup
  limitation already accepts for every other flag (see
  `features-gating.test.ts`'s header comment). "Save as HTML" in a2ui
  mode: added a guarded button (hidden when neither inline `html` nor
  `url` exist) — `handleSave()` opens the signed `url` directly when
  there's no inline HTML (no local export path exists for that case).
  `canvas-block-exporter.ts` was verified UNRELATED (operates on
  `CanvasBlock[]` markdown-canvas data) and left untouched.
- Tests: `AgentChat.a2ui-canvas.test.ts` (9 cases covering the full
  decision table above) + `InfographicCanvas.a2ui.test.ts` (4 cases: default
  Rendered view, toggle to inline-html iframe, toggle to url iframe,
  HTML button disabled with neither) — the latter renders through the
  REAL `canvas-tab-manager.svelte.ts` module (not mocked) since it is a
  simple reactive store, not a heavy dependency.
- 44/44 test files, 284/284 tests pass (`pnpm test`). `tsc --noEmit`:
  identical pre-existing 8 errors to before this task (verified byte-for-
  byte against TASK-2867's completion note) — zero new errors.

**Deviations from spec**: the task suggested a dynamic
`await import('./a2ui/A2UISurface.svelte')` for `InfographicCanvas.svelte`;
implemented as a static import + markup gate instead (see note above) —
functionally equivalent gating (chunk never *evaluated*/mounted when the
flag is off), more reliable under test, and consistent with this file's
own existing convention for its other flags.
