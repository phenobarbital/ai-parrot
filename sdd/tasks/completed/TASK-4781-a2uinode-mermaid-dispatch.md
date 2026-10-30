# TASK-4781: Bundled UI: dispatch MermaidDiagram in A2UINode (M6)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4780
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (mechanical part). Adds the `{:else if component === 'MermaidDiagram'}` branch BEFORE the
`HtmlDocument` branch and the vitest rows; existing placeholder behaviour for unknown components stays green.

---

## Scope

- Import `A2UIMermaidDiagram` (+ type `MermaidDiagramProperties`) in `A2UINode.svelte` next to `A2UIGraph`.
- Add the dispatch branch before `{:else if component === 'HtmlDocument'}`.
- Add `A2UINode dispatches MermaidDiagram` to `A2UINode.test.ts` (mock `mermaid`); keep the line-239 test unchanged.

**NOT in scope**: the component itself (TASK-4780); any change to the HtmlDocument or Graph branches.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` | MODIFY | MermaidDiagram dispatch branch + import |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.test.ts` | MODIFY | dispatch test |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_node_mermaid.py` | CREATE | pytest wrapper running the vitest suites |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import A2UIMermaidDiagram, { type MermaidDiagramProperties } from './A2UIMermaidDiagram.svelte';  // created by TASK-4780
import A2UIGraph from './A2UIGraph.svelte';  // verified: A2UINode.svelte:18 (place the new import next to it)
```

### Existing Signatures to Use
```python
// A2UINode.svelte
let resolved = $derived(resolveProps(properties, dataModel));  // line 38
{:else if component === 'HtmlDocument'}  // line 250 — insert the new branch immediately BEFORE it
// A2UINode.test.ts
vi.mock('$lib/features', () => ({ features }));  // line 20
  it('rejects a bare Graph on a Parrot-default surface (unsupported placeholder)', () => {  // line 239 — keep green
```

### Does NOT Exist
- ~~a `features.mermaid` flag~~ — reuse `features.a2ui` (already gating the whole A2UI tree).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.test.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_node_mermaid.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `MermaidDiagram` is a Parrot-catalog component: dispatch on a bare `MermaidDiagram` (no catalogId check needed —
  check how the HtmlDocument branch guards its catalog and mirror it exactly).
- The test file must `vi.mock('mermaid', …)` at top level (jsdom cannot run mermaid).

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Add the import — *why*: dispatch target.
2. Insert the branch before HtmlDocument — *why*: spec §6 edit site.
3. Add the vitest case; run Validation Commands.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` (MODIFY)
```svelte
<!-- (a) occurrences: 1 (verified: grep -c "import A2UIGraph from './A2UIGraph.svelte';") — line 18; AFTER it: -->
	import A2UIMermaidDiagram, { type MermaidDiagramProperties } from './A2UIMermaidDiagram.svelte';
<!-- (b) occurrences: 1 (verified: grep -c "{:else if component === 'HtmlDocument'}") — line 250; BEFORE it: -->
{:else if component === 'MermaidDiagram'}
	<A2UIMermaidDiagram properties={resolved as unknown as MermaidDiagramProperties} />
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.test.ts` (MODIFY)
```ts
// top level, next to the existing vi.mock calls:
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    parse: vi.fn().mockResolvedValue(true),
    render: vi.fn().mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"></svg>' }),
  },
}));
// occurrences: 1 (verified: grep -c "it('rejects a bare Graph on a Parrot-default surface (unsupported placeholder)'") — line 239
// BEFORE that `it(`, add:
  it('dispatches MermaidDiagram', async () => {
    // FILL IN: render(A2UINode, { descriptor: { component: 'MermaidDiagram', properties: { source: 'flowchart TD\n a --> b\n',
    //   diagramType: 'flowchart' } }, dataModel: {} }); await findByTestId('mermaid-svg'); the <details> source is present
  });
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_node_mermaid.py` (CREATE)
```python
"""FEAT-753 (TASK-4781): run the MermaidDiagram vitest suite(s) from pytest."""

from ._vitest import run_vitest


def test_a2ui_node_mermaid_vitest() -> None:
    """MermaidDiagram UI behaviour passes and the existing A2UI suites stay green."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/A2UINode.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
    )
```
**Why**: `check_task_graph` only accepts pytest validation commands; `_vitest.run_vitest` (skips without pnpm) is the repo pattern.

### FILL IN checklist
- [ ] dispatch test body
- [ ] confirm the HtmlDocument branch's catalog guard and mirror it

---

## Acceptance Criteria

- [ ] `A2UINode dispatches MermaidDiagram` passes; the existing unknown-component placeholder test (line 239) still passes.
- [ ] `a2ui-kind.test.ts` still green.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_node_mermaid.py -q`

---

## Test Specification

See the MODIFY block for the test file.

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

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-10-27
**Notes**: Added the import and the `MermaidDiagram` dispatch branch before `HtmlDocument` in A2UINode.svelte (no catalog guard: HtmlDocument's branch has none either), the mocked-mermaid dispatch test and the pytest wrapper. Two pre-existing A2UINode tests (`DataTable applies columns[].format`, `KPICard honours format`) fail under `LANG=es_ES.UTF-8` (they format with the default locale while the component pins en-US); they also fail on a clean tree. Both wrappers pass with `LANG=en_US.UTF-8`. Not touched here.

**Deviations from spec**: none
