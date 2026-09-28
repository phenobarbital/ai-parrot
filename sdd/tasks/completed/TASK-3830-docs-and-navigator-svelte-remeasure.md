# TASK-3830: Document the structural-tier changes and re-measure on `navigator-svelte`

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3820, TASK-3824, TASK-3826, TASK-3828, TASK-3829
**Assigned-to**: unassigned

---

## Context

Spec §5 Acceptance Criteria:

- the wikitoolkit docs cover the `Symbols:` status line, the `component` kind, `uses` in
  blast, and (after Q4) `--ns` on `symbols *`;
- the counts re-measured on `navigator-svelte` are recorded in the PR description.

The cheatsheet (`docs/wiki/cheatsheet.md`) is the user-facing reference for the `symbols`
commands. Its section §0 (install) and its structural-plane section are what change. The
cheatsheet is written in **Spanish**, so keep that language in its sections.

---

## Scope

- `docs/wiki/cheatsheet.md` §0 "Instalación": add a row stating that `ai-parrot[wiki-languages]`
  now brings the symbol tier (ast-grep). Without it, non-Python code gets outlines but **0
  symbols**, and `status` says so in its `Symbols:` line.
- `docs/wiki/cheatsheet.md` "Plano estructural de símbolos (FEAT-498)" section. Add examples
  for:
  - `symbols lookup AdminBulkBar` (a Svelte component) and `symbols lookup fieldsync/+page`
    (a qualified route);
  - `symbols blast <Component>`, which now follows `uses`;
  - `symbols lookup <name> --ns <namespace>`, plus a note that hits from a namespace come
    qualified (`<ns>::sym:…`);
  - a note that installing the extra re-ingests the affected languages on the next plain
    `build` (no `--force`).
- **Re-measure** (manual, not committed): build `navigator-svelte` with this branch installed
  and record in this task's Completion Note, for the PR description:
  1. `component` symbol count (expected ≥ 1 per `.svelte`: 1,376 at spec time);
  2. `function` symbols with `node_kind == "variable_declarator"` (expected ≥ 600);
  3. `symbols blast AdminBulkBar` non-empty;
  4. zero `could not be evaluated` warnings;
  5. from a repo that federates it, `symbols lookup requireDashboardContainer` returns the
     `svelte::` hit.

**NOT in scope**: any code change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/wiki/cheatsheet.md` | MODIFY | install row + structural-plane examples (Spanish) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None: this is a docs-only task.

### Existing Signatures to Use
```markdown
<!-- docs/wiki/cheatsheet.md:23 --> ## 0. Instalación
<!-- docs/wiki/cheatsheet.md:30 --> | Comunidades Leiden (opcional) | `uv pip install leidenalg python-igraph` |
<!-- docs/wiki/cheatsheet.md:74 --> ### Plano estructural de símbolos (FEAT-498)
<!-- docs/wiki/cheatsheet.md:85 --> Ejecuta `symbols blast` **antes** de tocar una función/clase muy usada.
```

### Does NOT Exist
- ~~A separate English symbols guide to update~~: the cheatsheet is the reference.
  `docs/wiki-claude-code.md` only mentions the commands in passing, so leave it alone unless
  it contradicts the new behaviour.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/wiki/cheatsheet.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Every command example must be one that works after TASK-3820..3829. Run each one against a
  built plane before writing it down.

---

## Implementation Blueprint

### Steps (in order)
1. Add the install row. 2. Add the structural-plane examples and notes. 3. Re-measure on
`navigator-svelte` and record the numbers in the Completion Note.

### `docs/wiki/cheatsheet.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'Comunidades Leiden (opcional)' docs/wiki/cheatsheet.md) -->
<!-- AFTER the row `| Comunidades Leiden (opcional) | …` (verified: cheatsheet.md:30) -->
| Símbolos de JS/TS/Svelte/PHP/Rust/Perl | incluido en `ai-parrot[wiki-languages]` (ast-grep). Sin él hay outline pero **0 símbolos**; `wikitoolkit status` lo dice en la línea `Symbols:` |
```
```markdown
<!-- occurrences: 1 (verified: grep -c 'Ejecuta `symbols blast` \*\*antes\*\*' docs/wiki/cheatsheet.md) -->
<!-- BEFORE the line `Ejecuta `symbols blast` **antes** de tocar …` (verified: cheatsheet.md:85) -->
<!-- FILL IN: a ```bash block with the Svelte component / route / --ns examples from §Scope,
     plus 2–3 lines of notes: `uses` in blast, qualified ids from namespaces, and the one-time
     automatic re-ingest after installing the extra — bounded by "every example was run" -->
```

### FILL IN checklist
- [ ] Examples block and notes (in Spanish). Bound: each command was run for real.
- [ ] Re-measure numbers in the Completion Note. Bound: the five checks in §Scope.

---

## Acceptance Criteria

- [ ] The cheatsheet documents: the extra, the `Symbols:` line, `component` symbols, qualified
      routes, `uses` in blast, and `--ns` on `symbols *`.
- [ ] The Completion Note records the five `navigator-svelte` measurements.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_cli_symbols.py -q`

---

## Test Specification

Docs-only. The validation command is a smoke test of the `symbols` CLI whose examples this
task documents. The packaging itself is pinned by TASK-3820's own test.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm every `Depends-on` task is `done`.
3. Edit, run each example, re-measure, and stage only `docs/wiki/cheatsheet.md`.
4. Close with `scripts/sdd/close_task.sh TASK-3830 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note with the measurements.

---

## Completion Note

Docs done (install row + examples block + notes, Spanish). Every example was run against a plane built from a copy of navigator-svelte/src (a35d4ba06; 1376 .svelte, 1929 .ts; copy in scratchpad because the primary checkout is read-only). Re-measure (wikitoolkit build --no-git, 50s wall, ai-parrot branch HEAD): (1) component symbols = 1376 = one per .svelte; (2) function symbols with node_kind=variable_declarator = 996 (>=600); (3) 'symbols blast AdminBulkBar' returns the root but EMPTY impacted — correct: nothing in src/ references AdminBulkBar (grep confirms); 'blast Spinner' is non-empty (ModalMultipleContent, DashboardLoader, InsightsInfographicModal, JsonSchemaDrawer...). The docs example uses Spinner. (4) zero 'could not be evaluated' warnings; (5) from a federating repo, 'symbols lookup requireDashboardContainer' returns svelte::sym:src/lib/fn/dashboard/domain/context.ts#requireDashboardContainer with default routing and with --ns svelte. 'symbols lookup fieldsync/+page' returns the route components with qualname (app)/[programs]/fieldsync/+page. uses edges: 1028 (707 extracted, 321 inferred); 15817 symbols total. status shows 'Symbols   : enabled' and 'javascript: ast-grep' in a fresh process. FOLLOW-UP (out of scope, not fixed): the JS import resolver does not resolve the SvelteKit $lib alias, so only ~39 of ~194 importers of common/Icon.svelte get a references/uses edge; uses recall is bounded by that pre-existing limitation. Id-superset check (before/after id sets) not run. Side effect to note: an earlier stray 'wikitoolkit build --path .' in the scratchpad resolved to the worktree and wrote ignored .parrot/wiki (removed).
