# TASK-4780: Bundled UI: A2UIMermaidDiagram.svelte + mermaid dependency (M6)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / G7, AC-8. NOT delegation-eligible (spec §3 table): the lazy `import('mermaid')`
lifecycle inside Svelte 5 runes, the host-theme mapping, the DOMPurify SVG profile and the jsdom mock strategy need
judgement. This task creates the renderer component and adds the npm dependency; TASK-4781 wires it into `A2UINode`.

---

## Scope

- `pnpm add mermaid@^11.17.2` in `packages/ai-parrot-server/ui` (latest 11.x on 2026-10-27; npm `latest` is 12.2.0 but the spec pins 11.x).
- Create `A2UIMermaidDiagram.svelte` (Svelte 5 runes only) per the spec §3 M6 skeleton.
- Create `A2UIMermaidDiagram.test.ts` (vitest, `mermaid` mocked, REAL DOMPurify for the label-preservation test).
- Verify `pnpm build` puts mermaid in its own async chunk (`ls dist/assets | grep -i mermaid`).
- Real-browser smoke check (labeled flowchart + class diagram, labels visible after sanitization); save evidence
  under `artifacts/logs/FEAT-753-mermaid-smoke.*` (git-ignored dir → `git add -f` if the evidence must be committed).

**NOT in scope**: the `A2UINode.svelte` dispatch branch (TASK-4781); a new feature flag (reuse `features.a2ui`); `themeVariables`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte` | CREATE | lazy mermaid render + DOMPurify + fallback |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.test.ts` | CREATE | vitest with mocked mermaid |
| `packages/ai-parrot-server/ui/package.json` | MODIFY | add mermaid dependency |
| `packages/ai-parrot-server/ui/pnpm-lock.yaml` | MODIFY | lockfile update from pnpm add |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_mermaid_diagram.py` | CREATE | pytest wrapper running the vitest suite |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
// TS / Svelte
import DOMPurify from 'dompurify';            // verified: package.json:38 "dompurify": "^3.4.17" (check an existing import site with grep -rn "from 'dompurify'" src)
// mermaid is lazily imported only:  (await import('mermaid')).default   — idiom: ECharts.svelte:110 `fullEchartsPromise ??= import("echarts")`
import { render, screen, waitFor } from '@testing-library/svelte';   // test precedent: A2UINode.test.ts
import { describe, it, expect, vi } from 'vitest';
```

### Existing Signatures to Use
```python
// packages/ai-parrot-server/ui/package.json — "dompurify": "^3.4.17" (line 38); "marked": "^15.0.4", (line 46); NO "mermaid"
// scripts: "build": "pnpm generate && vite build" (line 12), "test": "vitest run" (line 14)
// ECharts.svelte:110 — lazy module promise cached at module scope
// A2UIGraph.svelte — `<script module>` exports typed props + pure helpers (lines 1-75); no --accent-* tokens (lines 7-12)
// A2UINode.test.ts:20 — vi.mock('$lib/features', () => ({ features }))
```

### Does NOT Exist
- ~~`A2UIMermaidDiagram.svelte`~~ / ~~`MermaidDiagramProperties`~~ — new in this task.
- ~~`$lib/features.mermaid`~~ / ~~`__AGENTCHAT_MERMAID__`~~ — no new flag.
- ~~`"mermaid"` in `ui/package.json`~~ — absent until this task adds it.
- ~~mermaid running in jsdom~~ — it cannot; every vitest mocks `mermaid`.
- ~~`export let`~~ — Svelte 4 syntax, forbidden.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/package.json",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/pnpm-lock.yaml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_mermaid_diagram.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme, htmlLabels: false,
  flowchart: { htmlLabels: false }, class: { htmlLabels: false } })` — HTML labels use `foreignObject`, which the
  SVG-only DOMPurify profile strips silently; never widen the sanitizer to keep HTML.
- `DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } })` then `{@html svgHtml}`.
- Unique render id per call from a MODULE-level counter (`a2ui-mermaid-${++counter}`), never the wire id alone.
- `await mermaid.parse(source)` failure or render failure → `status = 'error'`, show `<pre><code>` + short notice, never throw.
- Markup: optional `<h3>` title · `<figure role="img" aria-label={accessibleDescription}>` · optional `<figcaption>` ·
  always `<details><summary>Mermaid source</summary><pre><code>{source}</code></pre></details>`.
- Dark host detection: follow the existing app convention (grep for how ECharts/A2UIGraph detect dark mode) and pass a
  boolean into `resolveMermaidTheme`.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. `cd packages/ai-parrot-server/ui && pnpm add mermaid@^11.17.2` — *why*: lockfile must match; this is why the task is exclusive.
2. Create the component from the block — *why*: G7.
3. Write the vitest file (mocked mermaid; real DOMPurify) — *why*: AC-8.
4. `pnpm test` then `pnpm build` and check the async chunk — *why*: mermaid (~2–3 MB) must stay out of the main chunk.
5. Real-browser smoke check, save evidence to `artifacts/logs/` — *why*: mock-only success is insufficient (spec §7).

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte` (CREATE)
```svelte
<script module lang="ts">
  /** The MermaidDiagram component's own (already-resolved) top-level props. Mirrors MERMAIDDIAGRAM_SCHEMA. */
  export interface MermaidDiagramProperties {
    source: string;
    diagramType?: string;
    title?: string;
    caption?: string;
    theme?: 'default' | 'neutral' | 'dark' | 'forest' | 'base';
    accessibleDescription?: string;
  }

  type MermaidTheme = 'default' | 'neutral' | 'dark' | 'forest' | 'base';
  const THEMES: readonly MermaidTheme[] = ['default', 'neutral', 'dark', 'forest', 'base'];

  /** Pure: the wire `theme` hint wins, else 'dark' on a dark host, else 'default'. */
  export function resolveMermaidTheme(hint: string | undefined, hostIsDark: boolean): MermaidTheme {
    if (hint && (THEMES as readonly string[]).includes(hint)) return hint as MermaidTheme;
    return hostIsDark ? 'dark' : 'default';
  }

  let renderCounter = 0;
  let mermaidPromise: Promise<typeof import('mermaid').default> | undefined;
  function loadMermaid() {
    mermaidPromise ??= import('mermaid').then((m) => m.default);
    return mermaidPromise;
  }
</script>

<script lang="ts">
  import DOMPurify from 'dompurify';

  let { properties }: { properties: MermaidDiagramProperties } = $props();
  let status = $state<'loading' | 'ready' | 'error'>('loading');
  let svgHtml = $state('');

  $effect(() => {
    const source = properties.source;
    // FILL IN: hostIsDark detection following the app convention — bounded by resolveMermaidTheme tests
    const theme = resolveMermaidTheme(properties.theme, false);
    let cancelled = false;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme,
          htmlLabels: false,
          flowchart: { htmlLabels: false },
          class: { htmlLabels: false },
        });
        await mermaid.parse(source);
        const { svg } = await mermaid.render(`a2ui-mermaid-${++renderCounter}`, source);
        if (cancelled) return;
        svgHtml = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
        status = 'ready';
      } catch {
        if (!cancelled) status = 'error';
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

<!-- FILL IN: markup — optional <h3> title; <figure role="img" aria-label={properties.accessibleDescription}> with
     {@html svgHtml} when ready, a short "Diagram could not be rendered" notice + <pre><code> when error, a loading
     state otherwise; optional <figcaption>; ALWAYS <details><summary>Mermaid source</summary><pre><code>{properties.source}</code></pre></details>.
     Tailwind utilities only (match A2UIGraph.svelte styling). -->
```
**Why**: spec §3 M6 skeleton; the `mermaid` type import is type-only and does not pull the chunk.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.test.ts` (CREATE)
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  parse: vi.fn().mockResolvedValue(true),
  render: vi.fn().mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"></svg>' }),
}));
vi.mock('mermaid', () => ({ default: mermaidMock }));

import A2UIMermaidDiagram, { resolveMermaidTheme } from './A2UIMermaidDiagram.svelte';

describe('resolveMermaidTheme', () => {
  it('hint wins; dark host -> dark; default otherwise', () => {
    expect(resolveMermaidTheme('forest', true)).toBe('forest');
    expect(resolveMermaidTheme(undefined, true)).toBe('dark');
    expect(resolveMermaidTheme(undefined, false)).toBe('default');
  });
});

// FILL IN: 'renders the sanitized SVG and the <details> source' ; 'falls back on parse error' (parse rejects ->
//   <pre><code> + notice, no throw) ; 'preserves SVG labels through sanitization' — assert initialize was called with
//   htmlLabels:false globally and for flowchart/class; mock render with a representative SVG holding <text>/<tspan>
//   node + edge labels PLUS <script>, onclick= and <foreignObject>; real DOMPurify; labels survive, unsafe parts removed
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_mermaid_diagram.py` (CREATE)
```python
"""FEAT-753 (TASK-4780): run the MermaidDiagram vitest suite(s) from pytest."""

from ._vitest import run_vitest


def test_a2ui_mermaid_diagram_vitest() -> None:
    """MermaidDiagram UI behaviour passes and the existing A2UI suites stay green."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.test.ts",
    )
```
**Why**: `check_task_graph` only accepts pytest validation commands; `_vitest.run_vitest` (skips without pnpm) is the repo pattern.

### FILL IN checklist
- [ ] host dark-mode detection (follow existing convention)
- [ ] component markup (title / figure / caption / error fallback / always-present details)
- [ ] three FILL IN vitest cases (label-preservation uses real DOMPurify)
- [ ] build chunk check + browser smoke evidence in `artifacts/logs/`

---

## Acceptance Criteria

- [ ] AC-8: lazy import, `securityLevel: "strict"`, `startOnLoad: false`, htmlLabels disabled (global/flowchart/class),
      DOMPurify-sanitized SVG with labels preserved, always-present source block, code-block fallback.
- [ ] `pnpm build` emits mermaid in its own async chunk (`ls dist/assets | grep -i mermaid`).
- [ ] Real-browser smoke evidence saved under `artifacts/logs/`.
- [ ] `package.json` has `"mermaid": "^11.17.2"` and `pnpm-lock.yaml` is consistent (`pnpm install --frozen-lockfile` passes).

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_mermaid_diagram.py -q`

---

## Test Specification

See the vitest block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`).
2. **Read the spec** `sdd/specs/a2ui-mermaid-diagram.spec.md` (§2 decisions D1–D7, §6 contract, §7 constraints).
3. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/a2ui-mermaid-diagram.json`.
4. **Verify the Codebase Contract** — re-run the `grep -c` of every MODIFY anchor before editing; a count of 0 is drift: stop and report.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** the blueprint, then complete every `FILL IN` — touch only the files listed above.
7. **Validate**: `ruff check --fix <files>`, `black -l 120 <files>`, then the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`.
8. **Close** with `scripts/sdd/close_task.sh <TASK-ID> a2ui-mermaid-diagram verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: [agent name]
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
