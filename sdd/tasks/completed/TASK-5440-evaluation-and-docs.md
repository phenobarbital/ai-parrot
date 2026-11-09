# TASK-5440: Host evaluation and documentation — document running lines

**Feature**: FEAT-859 — PageIndex Optimizer Fixes 3 — Document-Wide Running Lines for Pseudo-Headings
**Spec**: `sdd/specs/pageindex-optimizer-fixes-3.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-5439
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. TASK-5439 adds `document_running_keys` / `RUNNING_LINE_MIN_DENSITY`. This task measures the result
on the real NIST 800-53 PDF with the deterministic `optimizer_eval` (host only: the corpus PDFs are git-ignored and live
in the main checkout) and documents the rule and the result in the two wiki pages named in the spec's `docs:`
frontmatter. Every number comes from a report written in this task, with its sha256.

---

## Scope

- Run `optimizer_eval` (deterministic) on 800-53 + AICPA with the feature branch's code.
- Dump the 800-53 optimized tree's leaves over target and any node titled `… PAGE <n>` (scratch script, not committed).
- `wiki/knowledge/pageindex-tree-optimizer.md`: describe the document running-line rule.
- `wiki/knowledge/pageindex-layout-structure.md`: add a result row; replace the "still cut once at a footer …
  `issue:5a605ae51f61`" sentence with the measured outcome.
- `test_optimizer_docs.py`: assert the two new names.

**NOT in scope**: code changes, AICPA titles in any committed file (`redistributable: false` — metrics only), LLM runs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | document-wide running-line rule |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | FEAT-859 result row + replace the open-issue sentence |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | MODIFY | names assertion |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import optimizer_eval  # verified: optimizer_eval.py:257 main(argv) ; runnable with python -m
from parrot.knowledge.pageindex import PageIndexToolkit  # verified: used by the FEAT-856 per-leaf dump (scratch only)
from parrot.knowledge.pageindex.optimizer import owned_tokens, OptimizerSettings  # verified: optimizer.py:162, :35
```

### Existing Signatures to Use
```text
optimizer_eval CLI (optimizer_eval.py:257-265): inputs PDF_OR_DIR..., --target-leaf-tokens (default 1500),
  --min-leaf-tokens (default 200), --llm (default none = deterministic), --out DIR
wiki/knowledge/pageindex-tree-optimizer.md:83   ignored once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times. Pieces created from a paged revision (a PDF)
wiki/knowledge/pageindex-layout-structure.md:270  | nist_800_53_r5 | FEAT-856 + FEAT-857 | 1259 → 722 | 341 / 735 / 3864 | 1 / 5 |
wiki/knowledge/pageindex-layout-structure.md:286  `C-5`, `C-7`) are still cut once at a footer (`APPENDIX C PAGE 434`): the repeat rule counts footers inside one leaf,
test_optimizer_docs.py:48          "PSEUDO_HEADING_MAX_REPEATS",   (inside test_optimizer_page_documents_feat_853_fixes)
```

### Does NOT Exist
- ~~a committed per-leaf dump tool~~ — the titles check uses a scratch script (blueprint below), not committed.
- ~~titles in the `optimizer_eval` JSON report~~ — the report has counts and token percentiles only; titles come from the
  dump.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-tree-optimizer.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex-layout-structure.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Run from the **main checkout root** (corpus paths are relative to it) with
  `PYTHONPATH=<worktree>/packages/ai-parrot/src`; confirm `parrot.knowledge.pageindex.optimizer.__file__` points into the
  worktree before trusting the numbers. Never `python -I` (it ignores `PYTHONPATH`).
- Deterministic only (no `--llm`). No coder seat: the numbers must be copied from the report, never estimated.
- Expected (spec §2 prototype): 800-53 footer-titled nodes 3 → 0; leaves over target 5 → 8 (`TABLE C-3` / `C-5` /
  `C-7` become single leaves just over 1,500); max leaf 3,864. If the run disagrees, document what it measured and say
  so in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. `python -m parrot.knowledge.pageindex.optimizer_eval corpus/compliance_soc2_hipaa/raw/nist_800_53_r5.pdf
   corpus/compliance_soc2_hipaa/raw/aicpa_tsc_2017.pdf --out artifacts/logs/optimizer_eval/feat859_<short-sha>_deterministic`
   — because the wiki tables quote this report's numbers; record its path and `sha256sum`.
2. Run the scratch per-leaf dump below on 800-53 — because the report carries no titles.
3. Edit the two wiki pages, then the docs test.
4. Run the validation commands and `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes-3.spec.md --root .`.

### Scratch per-leaf dump (not committed; write it under the session scratchpad)
```python
# FILL IN: mirror optimizer_eval for one PDF: PageIndexToolkit(adapter=None, storage_dir=<tmp>, scan_injection=False,
#   optimize_on_import=False, optimizer_settings=OptimizerSettings(target_leaf_tokens=1500, min_leaf_tokens=200,
#   llm_passes=False)); create_tree; import_pdf(..., with_summaries=False, structure_mode="layout");
#   optimize(apply=True, llm_passes=False); then list (owned_tokens, title) of leaves over 1500 and every node whose title
#   matches r"\bPAGE\s+\d+\s*$" — bounded by: node count must equal the report's nodes_after.
```

### `wiki/knowledge/pageindex-tree-optimizer.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'ignored once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times. Pieces created from a paged revision (a PDF)') -->
<!-- AFTER the sentence ending "…is ignored once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times." (:83) insert: -->
FILL IN: 2–3 sentences — the per-leaf count misses a footer in a short leaf (a 2–3 page piece holds it once or
twice), so `pseudo_heading_segments` also drops titles that are running lines of the whole document:
`document_running_keys(revision)` returns the keys whose paged paragraphs sit on more than `PSEUDO_HEADING_MAX_REPEATS`
distinct pages, never twice on one page, covering at least `RUNNING_LINE_MIN_DENSITY` (0.8) of their page range;
`expand_at_headings` computes it once per document. Name what it keeps (Kant's spread section titles, reference labels
stacked on one page) and that unpaged revisions are unaffected. Cite `issue:5a605ae51f61`.
```

### `wiki/knowledge/pageindex-layout-structure.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '| nist_800_53_r5 | FEAT-856 + FEAT-857 |') :270 — add a row below it: -->
| nist_800_53_r5 | FEAT-859 | FILL IN nodes before → after | FILL IN p50 / p90 / max | FILL IN over before / after |
<!-- occurrences: 1 (verified: grep -c '`C-5`, `C-7`) are still cut once at a footer') :286-287 — replace the sentence
     "Three shorter tables … — ledger `issue:5a605ae51f61`." with: -->
FILL IN: FEAT-859 counts footers across the whole document (`document_running_keys`), so these three tables are no
longer cut at `APPENDIX C PAGE …`; they become single leaves just over the target (sizes from the dump). Add the
report path + sha256 next to the existing run list.
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "PSEUDO_HEADING_MAX_REPEATS",' test_optimizer_docs.py)
# AFTER — insert below `        "PSEUDO_HEADING_MAX_REPEATS",` (:48)
        "document_running_keys",
        "RUNNING_LINE_MIN_DENSITY",
```
**Why**: the docs test keeps the page and the code names in step; the layout page already carries its own docs test
(`test_layout_docs.py`), which must keep passing.

### FILL IN checklist
- [ ] report path + sha256, copied numbers (800-53 and AICPA rows)
- [ ] dump result: footer-titled nodes (expect none) and leaves over target with sizes
- [ ] the optimizer-page paragraph and the layout-page row + replacement sentence

---

## Acceptance Criteria

- [ ] The report exists under `artifacts/logs/optimizer_eval/feat859_*`, and every number in the wiki edits is copied
      from it (or from the dump of the same run) with the report's sha256.
- [ ] The dump shows no 800-53 node titled `… PAGE <n>`; AICPA's row is unchanged from the FEAT-857 run.
- [ ] Both pages describe the rule; the "still cut once at a footer" sentence is gone.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes-3.spec.md --root .` reports ok.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q`

---

## Test Specification

`test_optimizer_page_documents_feat_853_fixes` gains two names; no new test function.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes-3 --feature-id FEAT-859`)
2. **Read the spec** at the path listed above
3. **Verify the Codebase Contract** before writing anything
4. **Update status** in `sdd/tasks/index/pageindex-optimizer-fixes-3.json` → `"in-progress"`; commit only that file
5. **Run the evaluation on the host**, then edit the pages, completing every `FILL IN`
6. **Verify** acceptance criteria
7. **Commit** only the files this task lists
8. **Close** with `parrot sdd task close TASK-5440 pageindex-optimizer-fixes-3 verified`
9. Fill in the Completion Note, commit the SDD state

---

## Completion Note

**Completed by**: sdd-fix session (Claude)
**Date**: 2026-11-09
**Notes**: Host run on the final code (`60237d38c6`), `PYTHONPATH=<worktree>/packages/ai-parrot/src` (module path
verified in the dump), deterministic, target 1500 / min 200. Report
`artifacts/logs/optimizer_eval/feat859_60237d38c6_deterministic/optimizer_eval-20261109T172759957700Z.json`, sha256
`38036a234c771620c8861f816edece75cd1d2b0cec83a02477c956785e54a8ed`: 800-53 1259 → 719 nodes, p50/p90/max 341/755/3864,
over target 1/8; AICPA 17 → 16, 1273/11239/27651, 4/4 (unchanged). Per-leaf dump of the same run: 718 nodes below the
root (report counts the root), no title ending in `PAGE <n>`, over target: TABLE C-17 3864, C-18 3789, C-1 3213,
C-19 2828, C-7 1801, (17) INFORMATION FLOW ENFORCEMENT | DOMAIN AUTHENTICATION 1704, C-3 1654, C-5 1545. Matches the
spec §2 prototype. The plan_deterministic probe over 8 PDFs (5 corpus + arxiv + 3 books) leaves every split unchanged
outside 800-53. Docs tests 5 passed; `parrot sdd techwiki check` → `Docs: required — ok`.

**Deviations from spec**: the first host run (on `83f81064fa`) showed the running-line set recomputed per top-level
section (HIPAA 0.01 → 0.84 s); fixed in `60237d38c6` (TASK-5439 follow-up, see its note) and the evaluation re-run on
that commit — the numbers above are from the re-run and match the first run exactly.
