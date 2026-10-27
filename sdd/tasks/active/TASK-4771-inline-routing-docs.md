# TASK-4771: Docs: inline component routing guide + extension table row

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4759, TASK-4765, TASK-4767, TASK-4769
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (docs half) — the feature's public contract, and what FEAT-753,
FEAT-754 and FEAT-756 will read instead of this spec.

Two deliverables: a new guide covering the route grammar, `routes.yaml`, the marker and
the registration contract; and one row in the existing `metadata.extensions` table in
`docs/outputs/a2ui-v1.md`, which that document's own rules require for any new
extension key.

Runs last because it documents what the other tasks actually built — write it from the
merged code, not from the spec, and record any deviation you find.

---

## Scope

- Write `docs/outputs/inline-a2ui-component-routing.md`: route grammar, `routes.yaml` (agent + tenant, merge order), the `parrot_presentation` marker, the FEAT-756 hook, and the FEAT-753/754 registration contract.
- Add the `parrot_presentation` row to the extension-key table in `docs/outputs/a2ui-v1.md`.

**NOT in scope**: navigator-frontend-next documentation (out of scope for this feature), and the conformance test (TASK-4770).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/inline-a2ui-component-routing.md` | CREATE | Feature guide |
| `docs/outputs/a2ui-v1.md` | MODIFY | parrot_presentation extension row |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
# Documentation task — no imports. Every code reference in the guide must be
# copy-pasteable and verified against the merged branch before committing.
```

### Existing Signatures to Use
```python
# docs/outputs/a2ui-v1.md:151-158 — the extension-key table rows to append to:
| `parrot_role` | Presentation role of a lowered `Text` ... |
| `parrot_variant` | Which Parrot component a lowered `Card` stands in for ... |
| `parrot_component_id` | ... |
| `parrot_optional` | ... |
| `parrot_unit`, `parrot_trend`, `parrot_series_data`, ... | ... |
| `parrot_data_sources` | **Surface-level** (`createSurface.metadata.extensions`, FEAT-598) ... |
| `parrot_param` | ... |            # <- :158, the last row today

# The doc's own rule (a2ui-v1.md:241):
#   "**Extension keys** (add to the `metadata.extensions` table above): ..."

```

### Does NOT Exist
- ~~`docs/outputs/inline-a2ui-component-routing.md`~~ — this task creates it.
- ~~a `parrot_presentation` row in `a2ui-v1.md`~~ — absent; this task adds it.
- ~~an `a2ui_`-prefixed key for this marker~~ — `a2ui_` is reserved for official extensions (`a2ui-v1.md:146-148`); the key is `parrot_presentation`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/outputs/inline-a2ui-component-routing.md",
      "action": "CREATE"
    },
    {
      "path": "docs/outputs/a2ui-v1.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Write from the merged code, not from the spec.** This task runs last precisely so the docs describe what shipped. If something differs from the spec, document the code and note the deviation in the Completion Note.
- The `parrot_presentation` row must say **surface-level** (`createSurface.metadata.extensions`), exactly as the `parrot_data_sources` row does — the distinction matters because most rows in that table are node-level.
- Every code snippet in the guide must be copy-pasteable and verified: a `routes.yaml` example that actually loads, a label that actually parses, a kwarg that actually exists.
- Cover the four audiences the spec names: an operator writing `routes.yaml`; a frontend reading the marker; FEAT-753/754 registering a new component; FEAT-756 using the precedence hook.
- Keep the guide in the house style of `docs/outputs/a2ui-linked-surfaces.md`.

### References in Codebase
- `docs/outputs/a2ui-v1.md:140-162` — the extensions section and its table.
- `docs/outputs/a2ui-linked-surfaces.md` — the house style for an outputs guide.
- Spec §2 "Route registration contract" and "Hook contract for FEAT-756" — the two contracts to restate for an external reader.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-read the merged implementation of the route grammar, bank loader, emitter and bubble — *why*: the docs must describe shipped behaviour, and several details were corrected during implementation.
2. Write the guide covering the four audiences — *why*: three in-flight features will read this instead of the spec.
3. Add the extension row marked surface-level — *why*: `a2ui-v1.md`'s own rules require a row for every new key, and the level distinction is load-bearing.
4. Verify every snippet — *why*: a `routes.yaml` example that does not load is worse than no example.

### `docs/outputs/inline-a2ui-component-routing.md` (CREATE)
```markdown
# Inline A2UI Component Routing (FEAT-755)

<!-- FILL IN each section from the MERGED code. Required sections: -->

## What it does
<!-- The selector on "Default (Auto)" now yields a KPI card / Timeline / Graph / InfoCard
     from the user's phrasing. Explicit mode or /trigger still wins. -->

## Route grammar
<!-- `a2ui:<ComponentName>` beside plain OutputMode values; parse/make helpers and where
     they live; what makes a component eligible (registered, requires_actions=False). -->

## Configuring the phrase bank (`routes.yaml`)
<!-- Agent level and tenant level paths; merge order defaults <- agent <- tenant;
     extend vs replace; what happens to an invalid file or key (warn + skip).
     Include a COMPLETE, loadable example. -->

## The `parrot_presentation` marker
<!-- Surface-level; payload fields; what a renderer should do with it; how it overrides
     the root-component kind heuristic. -->

## Adding a new inline component (FEAT-753 / FEAT-754)
<!-- The registration contract, as numbered steps: register display-only; add utterances;
     optional authoring notes; optional SOURCE_MODEL; optional feasibility rule. -->

## The precedence hook (FEAT-756)
<!-- explicit > router (mode + hint) > metric default shape > agent default; how a
     cooperative _resolve_output_mode override plugs into the slot. -->

## Degradation
<!-- The failure reasons and what the user sees; text-only transports. -->
```
**Why this shape**: the section order follows the four audiences the spec names, so each reader can stop once they reach their own section.

### `docs/outputs/a2ui-v1.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '| `parrot_param` |' docs/outputs/a2ui-v1.md) -->
<!-- AFTER — append one row below the `parrot_param` row (verified: a2ui-v1.md:158) -->
| `parrot_presentation` | **Surface-level** (`createSurface.metadata.extensions`, FEAT-755): how the surface was produced — `{"kind": "widget", "inline": true, "origin": "chat_turn", "component": "KPICard"}`. Set by the inline emitter so renderers stop inferring widget-vs-dashboard from the root component; overrides the `inferSurfaceKind()` heuristic |
```
**Why**: appended after `parrot_param` to keep the two surface-level keys (`parrot_data_sources`, `parrot_presentation`) adjacent at the end of the table, and worded to mirror the `parrot_data_sources` row that already marks itself surface-level.

### FILL IN checklist
- [ ] `inline-a2ui-component-routing.md` — all seven sections, written from merged code; bounded by AC-1/AC-2/AC-4
- [ ] `a2ui-v1.md` — the extension row; bounded by AC-3

---

## Acceptance Criteria

- [ ] **AC-1**: the guide covers route grammar, `routes.yaml` (both levels + merge order), the marker, the FEAT-753/754 registration contract, the FEAT-756 hook, and degradation.
- [ ] **AC-2**: every snippet is verified against the merged code — the `routes.yaml` example loads, the labels parse, the kwarg exists.
- [ ] **AC-3**: `docs/outputs/a2ui-v1.md` gains a `parrot_presentation` row marked **surface-level**, consistent with the `parrot_data_sources` row.
- [ ] **AC-4**: any difference between the spec and what shipped is documented as shipped and noted in the Completion Note.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py -q`

---

## Test Specification

No new tests — this task is documentation.

The Validation Commands above are a smoke check that the behaviour being documented
still passes after any doc-driven correction. If writing the guide reveals a genuine
bug, open a ledger issue rather than fixing it here (out of scope), and note it in the
Completion Note.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
