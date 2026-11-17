# TASK-5749: Documentation — `wiki/sdd-tooling/sdd/necessity-ladder.md`

**Feature**: FEAT-908 — Necessity Ladder — least-new-code gate in the SDD flow
**Spec**: `sdd/specs/ponytail-like-stairway.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5748
**Assigned-to**: unassigned

---

## Context

> Spec §10 (docs policy `required`) and §3 Module 6 (M6), documentation part. One authored wiki
> page explains the ladder: the seven rungs and their evidence, the Lean Review, how the table
> binds tasks and review, the `# shortcut:` convention and where the reuse-first list lives.
> It also adds the seventh contract-test method, which checks the page.
> Last in the graph: it documents what TASK-5741 … TASK-5747 add (reached through TASK-5748).

---

## Scope

**Ladder**: R7 · reuses the authored-page template (`sdd/templates/techwiki-page.md`) · est. ~80 LOC

- Create `wiki/sdd-tooling/sdd/necessity-ladder.md` from the techwiki page template.
- Add `test_wiki_page_documents_the_ladder` to `TestNecessityLadderContract` in
  `tests/sdd_scripts/test_necessity_ladder_contract.py`.

**NOT in scope**: `wiki/_index.yaml` (sections are listed there, not pages); any API reference
page (spec `docs.api_modules` is empty); the FEAT-909 command section (added by FEAT-909).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/sdd/necessity-ladder.md` | CREATE | Authored page |
| `tests/sdd_scripts/test_necessity_ladder_contract.py` | MODIFY | Seventh test method (file created by TASK-5748) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none beyond what tests/sdd_scripts/test_necessity_ladder_contract.py already imports (pathlib.Path)
```

### Existing Signatures to Use
```text
# sdd/templates/techwiki-page.md — frontmatter `title`, `summary`; sections:
#   ## Purpose · ## Public API · ## Configuration & Parameters · ## Usage Examples · ## Gotchas · ## Related
# Sibling pages (same directory): wiki/sdd-tooling/sdd/decision-audit.md,
#   wiki/sdd-tooling/sdd/test-selection-validation-contract.md
# tests/sdd_scripts/test_necessity_ladder_contract.py (from TASK-5748):
#   class TestNecessityLadderContract — last method `test_conventions_name_reuse_first`; helper `_read(rel)`
# Docs check: `parrot sdd techwiki check --spec sdd/specs/ponytail-like-stairway.spec.md --root .`
#   reads the spec's `docs.pages` and fails when a page is missing.
```

### Does NOT Exist
- ~~`wiki/sdd-tooling/sdd/necessity-ladder.md`~~ — created by this task
- ~~`ref:` API links for this feature~~ — no Python API; list headings and line formats instead
- ~~`parrot sdd spec ladder`~~ — FEAT-909; mention it only as planned, never as available

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/sdd-tooling/sdd/necessity-ladder.md", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_necessity_ladder_contract.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Describe what the commands now do; do not restate every Lean Review row — link to the command.
- Plain prose, short sentences; the page is read by people deciding whether a module is needed.

---

## Implementation Blueprint

### Steps (in order)
1. Write the page below; complete the two FILL IN paragraphs — *why*: spec §10 lists this page.
2. Append the test method to the contract test — *why*: makes the page a checked deliverable.
3. Run the Validation Commands and `parrot sdd techwiki check --spec sdd/specs/ponytail-like-stairway.spec.md --root .`.

### `wiki/sdd-tooling/sdd/necessity-ladder.md` (CREATE)
````markdown
---
title: Necessity Ladder (FEAT 908)
summary: How the SDD flow decides whether a module has to be written at all, and how that decision binds tasks and review.
---

# Necessity Ladder (FEAT-908)

## Purpose

The code a feature produces is fixed by its spec: `/sdd-task` and the coders build only what the
spec's Interface Skeletons name. The Necessity Ladder is the check, applied while the spec is
written, that each module is needed and that nothing already in reach does the job.
Each candidate module walks the rungs in order and stops at the first one that fully covers it:

| Rung | Question | Evidence the spec must carry |
|---|---|---|
| R1 | Does a Goal or acceptance criterion need it? | If not: a `Deferred:` line in §1 Non-Goals |
| R2 | Is it already in this repository? | `verified: path:NN`, also in §6 |
| R3 | Does the standard library do it? | The symbol |
| R4 | Is it a feature of a platform already in the stack? | The symbol + one `path:NN` where it is used |
| R5 | Does a declared dependency do it? | The manifest line + the symbol |
| R6 | Can it be one change at an existing site? | Its MODIFY row in §6 Edit Sites |
| R7 | None of the above: write the minimum | A §6 "Does NOT Exist" entry + the query that came back empty |

## Public API

- Spec template §3 `#### Necessity Ladder` table: `Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC`, then a `Totals:` line.
- Spec template §1 `- Deferred: <thing> — <what would justify building it>`; §7 optional `### Known Shortcuts`.
- `/sdd-spec` §4c builds the table, §5a Lean Review (checks L1–L10) checks it, §7 prints a `Ladder:` line.
- `/sdd-proposal` and `/sdd-brainstorm` state *If not built* for every new capability and list the rest as deferred.
- Tasks open their `## Scope` with `**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`.

## Configuration & Parameters

No flag: the ladder always runs. Rung R5 reads the repository's reuse list, `sdd/CONVENTIONS.md`
§ Reuse first (ai-parrot keeps its list in `codebase-conventions.md`: `asyncdb`, `navconfig`,
`navigator-auth`, `navigator-eventbus`).

## Usage Examples

<!-- FILL IN: one filled ladder table with three rows (an R2 reuse, an R5 dependency, an R7 new
     module with its "Does NOT Exist" query) and its Totals line — bounded by the template format above -->

## Gotchas

- Never cut: validation at trust boundaries, error handling that prevents data loss, security,
  accessibility, anything a governing decision or the user requires.
- A capability the brainstorm, proposal or intake requires is kept; doubting it opens a §8 question.
- "Est. LOC" is a reference: around twice the estimate is a review finding to explain, never a blocker.
- A deliberately limited solution carries `# shortcut: <limit>, <when to upgrade>` in code and a
  Known Shortcuts row in the spec; the reviewer flags one without the other.

## Related

<!-- FILL IN: links to ./decision-audit.md and ./test-selection-validation-contract.md, one line each on how they relate -->
````
**Why this shape**: the six sections come from `sdd/templates/techwiki-page.md`; the rung table
and the Gotchas repeat the spec's rules 1–9 in reader terms.

### `tests/sdd_scripts/test_necessity_ladder_contract.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-5748: grep -c "def test_conventions_name_reuse_first" → 1)
# AFTER — append as the last method of class TestNecessityLadderContract (below test_conventions_name_reuse_first)
    def test_wiki_page_documents_the_ladder(self) -> None:
        """The wiki page exists and names the rungs R1–R7, the Lean Review and the binding rule."""
        text = _read("wiki/sdd-tooling/sdd/necessity-ladder.md")
        for marker in ("| R1 |", "| R7 |", "Lean Review", "**Ladder**:", "# shortcut:", "Reuse first"):
            assert marker in text, marker
```

### FILL IN checklist
- [ ] Usage Examples: one three-row example table + Totals line — bounded by the template format in Public API
- [ ] Related: two relative links to sibling pages that exist — bounded by "Existing Signatures to Use"

---

## Acceptance Criteria

- [ ] `wiki/sdd-tooling/sdd/necessity-ladder.md` exists with the six template sections (spec AC 12)
- [ ] `parrot sdd techwiki check --spec sdd/specs/ponytail-like-stairway.spec.md --root .` reports the page present
- [ ] `test_wiki_page_documents_the_ladder` passes; the whole contract file passes
- [ ] All Validation Commands pass

---

## Validation Commands

- `pytest tests/sdd_scripts/test_necessity_ladder_contract.py::TestNecessityLadderContract::test_wiki_page_documents_the_ladder -q`
- `pytest tests/sdd_scripts/test_necessity_ladder_contract.py -q`

---

## Test Specification

The method in the blueprint is the whole test.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug ponytail-like-stairway --feature-id FEAT-908`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5748 must be `"done"` in `sdd/tasks/index/ponytail-like-stairway.json`
4. **Verify the Codebase Contract** — the contract test file and its last method exist
5. **Update status** in `sdd/tasks/index/ponytail-like-stairway.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the blueprint, complete every FILL IN
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5749 ponytail-like-stairway verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
