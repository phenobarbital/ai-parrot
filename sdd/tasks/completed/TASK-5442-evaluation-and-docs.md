# TASK-5442: Host evaluation and documentation — table page splits

**Feature**: FEAT-861 — PageIndex Optimizer Fixes 4 — Page Splits for Long Table Leaves
**Spec**: `sdd/specs/pageindex-optimizer-fixes-4.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-5441
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. TASK-5441 adds `table_page_splits` / `TABLE_SPLIT_MIN_SHARE` and `split_at(titles=)`. This task
measures the result on the real NIST 800-53 and AICPA PDFs with the deterministic `optimizer_eval` (host only: the
corpus PDFs are git-ignored and live in the main checkout) and documents the rule and the result in the two wiki pages
named in the spec's `docs:` frontmatter. Every number comes from a report written in this task (with its sha256) or
from the per-leaf dump of the same code.

---

## Scope

- Run `optimizer_eval` (deterministic) on 800-53 + AICPA with the feature branch's code.
- Dump the 800-53 optimized tree's leaves over target and the page-range piece titles (scratch script, not committed).
- `wiki/knowledge/pageindex-tree-optimizer.md`: describe the page-split fallback.
- `wiki/knowledge/pageindex-layout-structure.md`: add the report row, an 800-53 result row and an AICPA result row,
  and an "After FEAT-861" paragraph.
- `test_optimizer_docs.py`: assert the two new names.

**NOT in scope**: code changes, AICPA titles in any committed file (`redistributable: false` — metrics only), LLM runs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | page-split fallback paragraph |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | FEAT-861 report + result rows, "After FEAT-861" paragraph |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | MODIFY | names assertion |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import optimizer_eval  # verified: optimizer_eval.py:257 main(argv) ; runnable with python -m
from parrot.knowledge.pageindex import PageIndexToolkit  # verified: used by the FEAT-859 per-leaf dump (scratch only)
from parrot.knowledge.pageindex.optimizer import owned_tokens, OptimizerSettings  # verified: optimizer.py:164, :37
```

### Existing Signatures to Use
```text
optimizer_eval CLI (optimizer_eval.py:257-265): inputs PDF_OR_DIR..., --target-leaf-tokens (default 1500),
  --min-leaf-tokens (default 200), --llm (default none = deterministic), --out DIR
wiki/knowledge/pageindex-tree-optimizer.md:96     moves the split leaf's key items onto the piece that now owns their anchor.
wiki/knowledge/pageindex-layout-structure.md:265  | FEAT-859 branch (`60237d38c6`) | `feat859_60237d38c6_deterministic/…` | `38036a23…` |
wiki/knowledge/pageindex-layout-structure.md:272  | nist_800_53_r5 | FEAT-859 | 1259 → 719 | 341 / 755 / 3864 | 1 / 8 |
wiki/knowledge/pageindex-layout-structure.md:273  | aicpa_tsc_2017 | all four | 17 → 16 | 1273 / 11239 / 27651 | 4 / 4 |
wiki/knowledge/pageindex-layout-structure.md:298  arxiv fixture, CSF 2.0, HIPAA, AICPA and three book PDFs, the same code leaves every split unchanged.
test_optimizer_docs.py:50          "RUNNING_LINE_MIN_DENSITY",   (inside test_optimizer_page_documents_feat_853_fixes)
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
- Expected (spec §2 prototype, cached revisions): 800-53 leaves over target 8 → 1 (only the enhancement
  `(17) … DOMAIN AUTHENTICATION`, 1,704), max leaf 3,864 → 1,704, 21 page-range pieces of 557–1,277 tokens; AICPA max
  leaf 27,651 → 4,206, over target 4 → 3. If the run disagrees, document what it measured and say so in the Completion
  Note.
- AICPA: metrics only. Do not write its node titles (including the split leaf's title) into either page.

---

## Implementation Blueprint

### Steps (in order)
1. `python -m parrot.knowledge.pageindex.optimizer_eval corpus/compliance_soc2_hipaa/raw/nist_800_53_r5.pdf
   corpus/compliance_soc2_hipaa/raw/aicpa_tsc_2017.pdf --out artifacts/logs/optimizer_eval/feat861_<short-sha>_deterministic`
   — because the wiki tables quote this report's numbers; record its path and `sha256sum`.
2. Run the scratch per-leaf dump below on 800-53 — because the report carries no titles.
3. Edit the two wiki pages, then the docs test.
4. Run the validation commands and `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes-4.spec.md --root .`.

### Scratch per-leaf dump (not committed; write it under the session scratchpad)
```python
# FILL IN: mirror optimizer_eval for one PDF: PageIndexToolkit(adapter=None, storage_dir=<tmp>, scan_injection=False,
#   optimize_on_import=False, optimizer_settings=OptimizerSettings(target_leaf_tokens=1500, min_leaf_tokens=200,
#   llm_passes=False)); create_tree; import_pdf(..., with_summaries=False, structure_mode="layout");
#   optimize(apply=True, llm_passes=False); then list (owned_tokens, title, start_index, end_index) of leaves over 1500
#   and of every node whose title ends with "(page N)" / "(pages N-M)" — bounded by: node count must equal the
#   report's nodes_after.
```

### `wiki/knowledge/pageindex-tree-optimizer.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF "   moves the split leaf's key items onto the piece that now owns their anchor.") -->
<!-- AFTER that line (:96, end of step 4 "Expand at headings") insert, indented 3 spaces like the step: -->
FILL IN: 3–5 sentences — a leaf with no heading and no pseudo-heading split point that is mostly table
(`TABLE_SPLIT_MIN_SHARE`, 0.5 of its owned tokens) and whose `table` segments sit on at least two pages is split at page
boundaries by `table_page_splits`: the first `table` segment plus the first segment of later pages, packed from the last
page backward up to `target_leaf_tokens` (so a short trailing page joins the piece before it) and coalesced to
`min_leaf_tokens`. The text before the table stays with the parent. Pieces are titled after the leaf plus `(page N)` /
`(pages N-M)` via `split_at(..., titles=…)`; the expand action's source stays `"layout"`. A single-page table and a
table segment larger than the target are not split. Cite `issue:f31b01d845b0`.
```

### `wiki/knowledge/pageindex-layout-structure.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '| FEAT-859 branch (`60237d38c6`) |') :265 — add a row below it: -->
| FEAT-861 branch (`FILL IN short sha`) | `FILL IN report path relative to artifacts/logs/optimizer_eval/` | `FILL IN sha256` |
<!-- occurrences: 1 (verified: grep -cF '| nist_800_53_r5 | FEAT-859 | 1259 → 719 | 341 / 755 / 3864 | 1 / 8 |') :272 — add a row below it: -->
| nist_800_53_r5 | FEAT-861 | FILL IN nodes before → after | FILL IN p50 / p90 / max | FILL IN over before / after |
<!-- occurrences: 1 (verified: grep -cF '| aicpa_tsc_2017 | all four | 17 → 16 | 1273 / 11239 / 27651 | 4 / 4 |') :273 —
     relabel "all four" → "before FEAT-861" and add a row below it: -->
| aicpa_tsc_2017 | FEAT-861 | FILL IN | FILL IN | FILL IN |
<!-- occurrences: 1 (verified: grep -cF 'arxiv fixture, CSF 2.0, HIPAA, AICPA and three book PDFs, the same code leaves every split unchanged.') :298
     — add a blank line and a paragraph after it: -->
FILL IN: **After FEAT-861.** The seven `TABLE C-*` leaves are split at page boundaries (`table_page_splits`, see
[pageindex-tree-optimizer.md](pageindex-tree-optimizer.md)) into page-range pieces such as
`TABLE C-17: SYSTEM AND SERVICES ACQUISITION FAMILY (page 481)`; give the piece count and size range from the dump, the
over-target count and max leaf from the report, and name the one leaf still over the target. AICPA: its largest leaf
(27,651 tokens, a table over pages 14–67) is split — metrics only, no titles. Close with which other probe documents
were unchanged (`issue:f31b01d845b0`).
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        "RUNNING_LINE_MIN_DENSITY",' test_optimizer_docs.py)
# AFTER — insert below `        "RUNNING_LINE_MIN_DENSITY",` (:50)
        "table_page_splits",
        "TABLE_SPLIT_MIN_SHARE",
```
**Why**: the docs test keeps the page and the code names in step; the layout page already carries its own docs test
(`test_layout_docs.py`), which must keep passing.

### FILL IN checklist
- [ ] report path + sha256, copied numbers (800-53 and AICPA rows)
- [ ] dump result: page-range pieces (count, size range) and the leaves still over target
- [ ] the optimizer-page paragraph and the layout-page rows + "After FEAT-861" paragraph

---

## Acceptance Criteria

- [ ] The report exists under `artifacts/logs/optimizer_eval/feat861_*`, and every number in the wiki edits is copied
      from it (or from the dump of the same code) with the report's sha256.
- [ ] The dump shows no 800-53 `TABLE C-*` leaf over the target; AICPA's largest leaf is split.
- [ ] Both pages describe the rule; no AICPA title appears in either page.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes-4.spec.md --root .` reports ok.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q`

---

## Test Specification

No new tests: `test_optimizer_docs.py` gains two names; `test_layout_docs.py` must keep passing.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes-4 --feature-id FEAT-861`)
2. **Read the spec** at the path listed above
3. **Verify the Codebase Contract** before writing anything
4. **Update status** in `sdd/tasks/index/pageindex-optimizer-fixes-4.json` → `"in-progress"`; commit only that file
5. **Run the evaluation on the host**, then edit the pages, completing every `FILL IN`
6. **Verify** with the validation commands and the techwiki check
7. **Commit** only the files this task lists
8. **Close** with `parrot sdd task close TASK-5442 pageindex-optimizer-fixes-4 verified`
9. Fill in the Completion Note, commit the SDD state

---

## Completion Note

**Completed by**: sdd-fix session (Claude)
**Date**: 2026-11-09
**Notes**: Host `optimizer_eval` (deterministic, target 1500 / min 200) with `PYTHONPATH` on the worktree (module path
confirmed, `table_page_splits` present): report
`artifacts/logs/optimizer_eval/feat861_90442976dc_deterministic/optimizer_eval-20261109T183947944098Z.json`, sha256
`018fb80a935c7943cad38158ddb25bfab0c11b38fef4c4badf5c1599e9e09229`. 800-53: 1259 -> 740 nodes, p50/p90/max
350/780/1704, over target 1/1; AICPA: 17 -> 39, 1208/1474/4206, over 4/3. Per-leaf dump (same code): 800-53 739 nodes
below the root, 21 page-range pieces of 557-1,277 tokens, 8 expansions, no footer-titled node, only
`(17) INFORMATION FLOW ENFORCEMENT | DOMAIN AUTHENTICATION` (1,704) over target; AICPA 23 pieces of 667-1,470 tokens.
All figures match the spec's prototype. The 8-PDF cached-revision probe re-run on the final code leaves the arxiv
fixture, CSF 2.0, HIPAA and the three books identical to `dev`. Wiki: page-split paragraph in the optimizer page (step
4), report row + two result rows + "After FEAT-861" paragraph in the layout page; no AICPA title in either page.
`test_optimizer_docs.py` + `test_layout_docs.py` 5 passed; techwiki check ok. Docs commit `5601dbec90`.

**Deviations from spec**: none. The AICPA "all four" row was relabelled "before FEAT-861 (all four runs above)" so the
new FEAT-861 row reads unambiguously.
