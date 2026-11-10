# TASK-5411: Evaluation run and documentation — wiki/knowledge/pageindex-layout-structure.md

**Feature**: FEAT-855 — PageIndex Layout Structure Fixes
**Spec**: `sdd/specs/pageindex-layout-structure-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5408, TASK-5409, TASK-5410
**Assigned-to**: unassigned

**Discovered-from**: `issue:a3d282c67ed0`

---

## Context

Spec §3 Module 4, §5 (evaluation criteria) and §10. The issue was measured by the documented four-pair layout
evaluation; it is resolved only when the same run, with the real code, meets the spec's thresholds. The wiki page also
carries three errors this feature exposed: it says outlines with any page decrease are rejected, its "Open question 2"
paragraph says body-size standalone bold lines are not headings (the code makes them headings), and it calls the CSF
2.0 misses "mid-level sections" (they are figure captions).

**Host only.** The corpus (`corpus/compliance_soc2_hipaa/`) is git-ignored and exists only in the main checkout on
the host. Run the evaluation from the feature worktree's code (`PYTHONPATH=<worktree>/packages/ai-parrot/src`) with
the PDFs read from the main checkout. Never run it from a coder seat, and never write a number that is not in the
report: copy each value from the report and cite its path and sha256, or write "not run".

---

## Scope

- Run the four-pair `layout_eval` (wiki § Evaluation command, `--min-confidence 0.6`, `--internal aicpa_tsc`) and
  check every §5 threshold.
- Update `wiki/knowledge/pageindex-layout-structure.md`: outline repair (`bookmarks_dropped`, `CandidateScore.dropped`,
  `BOOKMARK_MAX_DROPPED_SHARE`); bold-row rule (`bold_sizes`, visual rows, guards, `BOLD_REPEAT_MIN_PAGES`); bookmark
  rule guard; the new run table with report path + sha256 next to the 2026-11-09 baseline; the CSF caption finding;
  replace the "Open question 2" paragraph; a re-import gotcha (changed markdown → new revision).
- Extend `test_layout_docs.py` with the new names.
- Open the follow-up ledger issue for 800-53 control enhancements (spec Non-Goals).

**NOT in scope**: code changes (TASK-5408–5410); `layout_eval.py`; committing anything under `artifacts/`;
AICPA titles (metrics only — `manifest.yaml` marks it `redistributable: false`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | rules, evaluation, corrections |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` | MODIFY | assert the new names |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test_layout_docs.py uses only pathlib (verified: test_layout_docs.py:3)
from pathlib import Path
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py
REPO = Path(__file__).resolve().parents[5]                   # line 5
PAGE = WIKI / "pageindex-layout-structure.md"                # line 7
def test_page_has_frontmatter_and_names() -> None:           # line 10 — tuple of names ends with
    #     "layout_eval",                                      # line 24
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_eval.py
DEFAULT_OUT = Path("artifacts/logs/layout_eval")            # line 22
def main(argv: Optional[list[str]] = None) -> int            # line 173 — --pair LABEL=PDF::TREE, --internal,
    #   --min-confidence, --recall-floor, --out; writes <UTC>.json and <UTC>.md
# wiki/knowledge/pageindex-layout-structure.md
#   "## How structure is chosen" line 21 — Bookmarks candidate paragraph (rejection rules) line 32
#   "## Evaluation" line 103 — four-pair command lines 113-119, 2026-11-09 run table lines 136-145,
#   CSF "mid-level sections" sentence lines 147-150, "Open question 2" paragraph line 155
#   "## Gotchas" line 156
```

### Does NOT Exist
- ~~a committed copy of the corpus or of `artifacts/logs/layout_eval/*`~~ — both git-ignored; cite path + sha256.
- ~~`parrot sdd techwiki check` as a pytest~~ — it is not a registered runner; it stays an acceptance criterion.
- ~~a drop count in the eval markdown table~~ — read `candidates[].dropped` from the JSON report.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-layout-structure.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py#test_page_has_frontmatter_and_names"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every metric in the page comes from the new report; keep the 2026-11-09 baseline table as the "before".
- AICPA: metrics only. 800-53 and CSF 2.0 are public NIST documents; their titles may be quoted.
- If the run misses a §5 threshold, do not tune the code here: record the numbers, mark the task
  `done-with-issues`, and report which threshold failed.

---

## Implementation Blueprint

### Steps (in order)
1. From the main checkout, run (host):
   `PYTHONPATH=<worktree>/packages/ai-parrot/src python -m parrot.knowledge.pageindex.layout_eval --pair arxiv=<fixture pdf>::<fixture tree> --pair nist_800_53=corpus/compliance_soc2_hipaa/raw/nist_800_53_r5.pdf::corpus/compliance_soc2_hipaa/trees/nist_800_53.json --pair nist_csf_2_0=…/nist_csf_2_0.pdf::…/nist_csf_2_0.json --pair aicpa_tsc=…/aicpa_tsc_2017.pdf::…/aicpa_tsc.json --internal aicpa_tsc --min-confidence 0.6 --out artifacts/logs/layout_eval`
   — *why*: the issue's own measurement; worktree code, main-checkout corpus.
2. `sha256sum` the JSON report; read `structure_source`, `recall_*`, `page_agreement`, `layout_nodes` and the bookmarks
   candidate's `confidence` / `dropped` from it — *why*: §5 thresholds.
3. Edit the wiki page sections listed in Scope — *why*: spec §10.
4. Add the names to `test_layout_docs.py` — *why*: the docs test is in the Validation Contract.
5. `wikitoolkit ledger open --kind feature_gap --severity minor --discovered-from spec:FEAT-855 --about
   sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout --title "800-53 control
   enhancements are not headings; long controls stay over the optimizer target" --body …` — *why*: spec Non-Goals.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "layout_eval",' test_layout_docs.py)
# AFTER — insert below `        "layout_eval",` (verified: test_layout_docs.py:24)
        "bookmarks_dropped",
        "bold_sizes",
        "BOLD_REPEAT_MIN_PAGES",
```

### `wiki/knowledge/pageindex-layout-structure.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Evaluation$' pageindex-layout-structure.md) — anchor (verified: :103) -->
<!-- FILL IN: under "## How structure is chosen", rewrite the Bookmarks-candidate rejection sentence (line 32) for the
     5 % out-of-order tolerance, and add a "Bold rows" paragraph (bold_sizes, visual rows, guards,
     BOLD_REPEAT_MIN_PAGES, one level per size) and a "Bookmark rule" sentence (prefix-only, no body-text prose) —
     bounded by spec §2 Overview -->
<!-- FILL IN: under "## Evaluation", add "Four-pair run (<date>, host, feat-FEAT-855 @ <sha>)" with the report path,
     sha256 and the table copied from the report; replace the CSF "mid-level sections" sentence with the figure-caption
     finding; replace the "Open question 2" paragraph with the actual rule and the 82 → 4 evidence — bounded by AC -->
<!-- FILL IN: under "## Gotchas", add the re-import gotcha (changed headings → new revision) -->
```

### FILL IN checklist
- [ ] evaluation run, report sha256, thresholds checked
- [ ] wiki sections — numbers copied from the report only
- [ ] ledger follow-up issue opened (record its id in the Completion Note)

---

## Acceptance Criteria

- [ ] Report meets spec §5: nist_800_53 source `bookmarks`/`hybrid`, bookmarks `dropped == 1`, confidence ≥ 0.95,
      `recall_all` ≥ 0.95, `page_agreement` ≥ 0.75, `layout_nodes` ≤ 420; aicpa_tsc `recall_all` ≥ 0.6 and
      `recall_top` = 1.0; arxiv 1.0 / 1.0 / 1.0 with 17 nodes; nist_csf_2_0 `recall_all` 0.643 with 22 nodes.
- [ ] The wiki page cites the report path and sha256; AICPA appears as metrics only.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-layout-structure-fixes.spec.md --root .` passes.
- [ ] The follow-up ledger issue exists with `discovered_from: spec:FEAT-855`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q`

---

## Test Specification

The extended `test_page_has_frontmatter_and_names` (names above) is the test; no new test file.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure-fixes --feature-id FEAT-855`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5408, TASK-5409, TASK-5410 must be `"done"` in the per-spec index
4. **Run the evaluation on the host** (see Context) — never from a coder seat
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — complete every `FILL IN` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit** — stage only the files this task lists (never `artifacts/`)
9. **Close the task** with `parrot sdd task close TASK-5411 pageindex-layout-structure-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session agent:sdd-fix:cdd27bba
**Date**: 2026-11-09
**Notes**: Host run from the main checkout with `PYTHONPATH=<worktree>/packages/ai-parrot/src` (feature branch at
72267fd08b; the JSON carries `CandidateScore.dropped`, which only the branch code has). Layout report
`artifacts/logs/layout_eval/20261109T135450Z.json`, sha256 `76fbc0356b4614eda6bc4fe1e3bf282b274d9d3ca299e84b763bf8b80e80fca0`:

| Pair | Source | Bookmarks conf / dropped | recall_top | recall_all | page_agreement | layout_nodes |
|---|---|---|---:|---:|---:|---:|
| arxiv | hybrid | 1.000 / 0 | 1.000 | 1.000 | 1.000 | 17 |
| nist_800_53 | hybrid | 0.997 / 1 | 1.000 | 1.000 | 0.805 | 391 |
| nist_csf_2_0 | hybrid | 1.000 / 0 | 0.643 | 0.643 | 1.000 | 22 |
| aicpa_tsc | layout | 0.000 / 0 | 1.000 | 0.611 | 1.000 | 16 |

Every spec §5 threshold is met (800-53: source hybrid, dropped 1, confidence 0.997 >= 0.95, recall_all 1.000 >= 0.95,
page_agreement 0.805 >= 0.75, layout_nodes 391 <= 420; AICPA recall_all 0.611 >= 0.6, recall_top 1.0; arxiv and CSF
unchanged). Optimizer (deterministic, 800-53): `artifacts/logs/optimizer_eval/feat_855_deterministic/optimizer_eval-20261109T135423866777Z.json`,
sha256 `25d4a7c30c990fddbfac320465df8f996966639f7af7dd6407612a63c7ba83b1` — 392 -> 326 nodes, 290 leaves, p50/p90/max
611/1694/28862, 35 over target. Facts written to the wiki were re-checked with the final code: 82 body-size bold
candidates in 800-53, 58 removed as list markers + 20 as list tails/lead-ins, 4 kept; all 7 remaining AICPA misses sit
in markdown table lines (checked locally, titles not recorded). Wiki page updated (outline repair, heading-detection
rules, new run, CSF caption finding, corrected body-size bold-line paragraph, gotchas); docs test extended with
`bookmarks_dropped`, `bold_sizes`, `BOLD_REPEAT_MIN_PAGES` — 2 passed; `parrot sdd techwiki check` → Docs: required — ok.
Follow-up ledger issue opened: `issue:92245af971f3` (800-53 control enhancements, discovered_from spec:FEAT-855).

**Deviations from spec**: none
