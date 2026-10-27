# TASK-4783: Docs: MermaidDiagram wire contract + frontend contract (M7)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 / AC-10. The wire contract for every consumer (navigator-frontend-next included) and the
FEAT-755 handoff (schema location, instructions, utterance constant, lift artifact type).

---

## Scope

- `docs/outputs/a2ui-v1.md`: add `MermaidDiagram` to the Parrot catalog row (line 78); new section
  `## MermaidDiagram — opaque Mermaid source (FEAT-753)` BEFORE `## Adaptive Cards and the Teams submit flow` (line 474)
  (wire shape · four validation codes · lowered fallback table · renderer matrix · relationship with Graph · LLM/tool lanes);
  `metadata.extensions` table: `parrot_role` gains `"mermaid-source"`, new keys `parrot_diagram_type`, `parrot_mermaid_theme`.
- `docs/frontend/agentdashboard-a2ui-reference.md`: §5.2 heading (line 497) and the "still 10 composites" sentence
  (line 616) → 11; §5.3 renderer table (~line 582) interactive-html row notes MermaidDiagram = lowered code block (+degraded);
  new `### 5.5 MermaidDiagram (FEAT-753)` BEFORE `## 6. Dashboards, infographics and widgets` (line 710) with the frontend
  contract (lazy mermaid.js, securityLevel strict, htmlLabels off, DOMPurify SVG profile, fallback) and an example envelope.

**NOT in scope**: code; the brainstorm/FEAT-755 docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-v1.md` | MODIFY | catalog row, new section, extensions table |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | 11 composites, renderer table, §5.5 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# docs-only task — no imports
```

### Existing Signatures to Use
```python
# docs/outputs/a2ui-v1.md
| **Parrot** (this codebase's presentation layer) | `https://parrot.dev/catalogs/v1` | `InfoCard`, ... |   # line 78
## Adaptive Cards and the Teams submit flow   # line 474
# docs/frontend/agentdashboard-a2ui-reference.md
### 5.2 Parrot presentation catalog — 10 composites (`catalog/parrot/*.py`)   # line 497
alongside Basic and Parrot (§5.1/§5.2, still 10 composites — viz-core is   # line 616
## 6. Dashboards, infographics and widgets   # line 710
```

### Does NOT Exist
- ~~a `Graph`-style typed vocabulary for MermaidDiagram~~ — it is opaque source; say so explicitly.
- ~~mermaid.js in the interactive-HTML lane~~ — D5: lowered code block only (Q3 open).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/outputs/a2ui-v1.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/frontend/agentdashboard-a2ui-reference.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Copy the wire schema (spec §2), the four codes (spec §2 Data Models), the degradation strings (spec §7) and the tool
  result shape verbatim. Example envelope: the §2 tool result's `a2ui_envelope` wrapped as `{"version": "v1.0", "createSurface": …}`.
- Check the §5.2 table body: add a `MermaidDiagram` row listing `catalog/parrot/mermaiddiagram.py`.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Edit `a2ui-v1.md` at the three sites — *why*: AC-10.
2. Edit the frontend reference at the four sites — *why*: navigator-frontend-next implements from it.
3. Grep for any other "10 composites" mention and update it.

### `docs/outputs/a2ui-v1.md` (MODIFY)
```markdown
<!-- occurrences: 1 — line 78 catalog row: append `, \`MermaidDiagram\`` to the Parrot component list (FILL IN: keep the row's existing order, append at the end) -->
<!-- occurrences: 1 (verified: grep -c '## Adaptive Cards and the Teams submit flow') — line 474; BEFORE it: -->
## MermaidDiagram — opaque Mermaid source (FEAT-753)

<!-- FILL IN: wire shape (schema table), validation codes table (4 rows), lowered fallback table (spec §2),
     renderer matrix (bundled UI native · ssr-html/pdf code block · adaptive_cards monospace · interactive-html code block ·
     A2A/Telegram lowered text), relationship with Graph (opt-in graph_spec_from_mermaid_source), LLM lane (FEAT-755) vs
     tool lane (render_mermaid_diagram) -->
```

### `docs/frontend/agentdashboard-a2ui-reference.md` (MODIFY)
```markdown
<!-- line 497: "10 composites" -> "11 composites"; line 616: "still 10 composites" -> "still 11 composites" -->
<!-- occurrences: 1 (verified: grep -c '## 6. Dashboards, infographics and widgets') — line 710; BEFORE it: -->
### 5.5 MermaidDiagram (FEAT-753)

<!-- FILL IN: frontend contract (lazy import('mermaid'), initialize({startOnLoad:false, securityLevel:'strict',
     htmlLabels:false, flowchart:{htmlLabels:false}, class:{htmlLabels:false}}), DOMPurify svg profile, unique render ids,
     code-block fallback, always-visible source) + example envelope -->
```

### FILL IN checklist
- [ ] new a2ui-v1.md section content
- [ ] new §5.5 content + §5.3 renderer-table note

---

## Acceptance Criteria

- [ ] AC-10: both docs document the component and the composite count reads 11 everywhere.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog.py -q`

---

## Test Specification

Docs-only; the validation command is a smoke run of the catalog suite (docs reference its behavior).

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
