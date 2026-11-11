# TASK-5541: Documentation — `wiki/tools/accounting-metrics-layer.md`, `wiki/tools/semantic-layer.md`, README

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5538, TASK-5539
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, §10 Documentation (`docs.policy: required`), AC19. Writes the user-facing page for the
accounting layer, points to it from the semantic-layer page, and replaces the README "Layering" paragraph with
the actual contract.

---

## Scope

- Create `wiki/tools/accounting-metrics-layer.md` from `sdd/templates/techwiki-page.md`, covering everything in
  spec §3 M10: model YAML reference (every key, `amount_convention` table, selectors, intervals, retained natures),
  request contract, allowed cumulative/grain matrix and partial buckets, exact evaluation / rounding / overflow,
  determinism and golden-file policy (`REGENERATE_GOLDENS=1`), audit entry fields and `lineage_ref` replay,
  governance posture (per-metric `DatasetPolicyGuard`, allow without guard or context; `__validate__` privilege;
  actual policy keys `dataset:accounting:...` with action `dataset:read`) next to the fail-closed `sl_*` posture,
  the `DuckDBEngine` API, MCP-local config under `toolkits:`, CLI (`--snapshot`, `--journal-arrow`), host scheduler
  wiring (`register_accounting_schedules(app["scheduler_manager"], factory)` with the same toolkit instance),
  required snapshot provider/manifests, `FINANCE_*` settings.
- Update `wiki/tools/semantic-layer.md`: a short section before `## Example agents` pointing to the new page and
  stating the two governance postures.
- Update `packages/ai-parrot-semantic/README.md`: replace the Layering sentence with the actual contract.

**NOT in scope**: code changes; `wiki/_index.yaml` (lists sections only — no edit needed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/tools/accounting-metrics-layer.md` | CREATE | user-facing page |
| `wiki/tools/semantic-layer.md` | MODIFY | pointer section |
| `packages/ai-parrot-semantic/README.md` | MODIFY | layering contract |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `sdd/templates/techwiki-page.md` — page template.
- `wiki/tools/semantic-layer.md` headings: `:3` Installation and clean-room format, `:41` Authorization and
  identity, `:68` Tools and audit, `:100` Guarded dataset hand-off, `:114` MCP-local configuration,
  `:159` `## Example agents` (occurrences: 1).
- `packages/ai-parrot-semantic/README.md:8-9` — Layering text; anchor
  `The accounting extension must remain independently importable.` (occurrences: 1).
- `.parrot/mcp-toolkits.yaml:1-5` — entries live under a top-level `toolkits:` key with `class:` and `kwargs:`.
- Every symbol documented must exist in the merged code of TASK-5523..5540 — read it, do not copy from the spec.

### Does NOT Exist
- ~~`docs/semantic/`~~ — docs live under `wiki/tools/`.
- ~~a per-page entry in `wiki/_index.yaml`~~ — sections only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/tools/accounting-metrics-layer.md", "action": "CREATE"},
    {"path": "wiki/tools/semantic-layer.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/README.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged modules (`parrot/semantic/accounting/*`, `parrot/interfaces/duckdb_engine.py`,
   `parrot/scheduler/accounting_jobs.py`) — *why*: document what shipped, not the spec.
2. Write the new page from the template.
3. Edit the two existing files.
4. Run the techwiki check.

### `wiki/tools/semantic-layer.md` (MODIFY)
```markdown
<!-- BEFORE `## Example agents` (verified: wiki/tools/semantic-layer.md:159) — occurrences: 1 -->
## Accounting metrics

Chart-of-accounts rollups (revenue, EBITDA, …) are served by the `finance_*` tools of
`parrot.semantic.accounting` — see [accounting-metrics-layer](accounting-metrics-layer.md). Their visibility is
per metric through `DatasetPolicyGuard` and allows every metric when no guard or no permission context is
configured; the `sl_*` tools on this page fail closed instead.

```

### `packages/ai-parrot-semantic/README.md` (MODIFY)
```markdown
<!-- REPLACE line 9 `The accounting extension must remain independently importable.` — occurrences: 1 -->
The accounting compile path (`parrot.semantic.accounting` models, grammar, loader, validation, compiler,
evaluation) imports without the governed stack; its toolkit and runtimes share this package's audit ledger,
executor and compile cache.
```

### `wiki/tools/accounting-metrics-layer.md` (CREATE)
```markdown
# FILL IN: the page per Scope, following sdd/templates/techwiki-page.md section order.
```

### FILL IN checklist
- [ ] New page body — bounded by spec §3 M10 and the merged code.

---

## Acceptance Criteria

- [ ] The three files exist / are updated as scoped.
- [ ] `parrot sdd techwiki check --spec sdd/specs/accounting-metrics-layer.spec.md --root .` passes (AC19).

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_packaging.py -q`

Also run (acceptance, not a registered test runner):
`parrot sdd techwiki check --spec sdd/specs/accounting-metrics-layer.spec.md --root .`

---

## Test Specification

Documentation task — validated by the techwiki check.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any content
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** — run the Validation Commands
8. **Commit** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5541 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
