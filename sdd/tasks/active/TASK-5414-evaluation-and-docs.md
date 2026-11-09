# TASK-5414: Evaluation runs and documentation — wiki/knowledge/pageindex-layout-structure.md

**Feature**: FEAT-856 — PageIndex Layout Fixes — Enumerated Enhancement Headings
**Spec**: `sdd/specs/pageindex-layout-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5412, TASK-5413
**Assigned-to**: unassigned

**Discovered-from**: `issue:92245af971f3`

---

## Context

Spec §3 Module 3 and §5. The prototype numbers in spec §2 were measured with monkeypatched code; this task re-measures
with the real code from the feature worktree on the host (the corpus is git-ignored and lives only in the main
checkout), checks the §5 thresholds, and documents the enumerated-row rule and the increasing level map. It is the
task that resolves `issue:92245af971f3`.

---

## Scope

- Run the four-pair `layout_eval` and the 800-53 + AICPA `optimizer_eval` on the host with the worktree code.
- Build the 800-53 tree once and check the nesting / full-title criteria of §5.
- Update `wiki/knowledge/pageindex-layout-structure.md`: heading-detection rule 5 (enumerated rows), the hybrid-rule
  paragraph (increasing map), the evaluation section (both runs with report paths and sha256, `CONTROL SUMMARIES` /
  `issue:38e4627b2284` note), the re-import gotcha.
- Assert the new names in `test_layout_docs.py`.

**NOT in scope**: code changes (TASK-5412, TASK-5413); `layout_eval.py` / `optimizer_eval.py`; committing anything
under `artifacts/`; AICPA titles (metrics only — `manifest.yaml` marks it `redistributable: false`); the optimizer
footer bug (`issue:38e4627b2284`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | rules, evaluation, gotcha |
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
def test_page_has_frontmatter_and_names() -> None:           # line 10 — names tuple ends with
    #     "BOLD_REPEAT_MIN_PAGES",                            # line 27
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_eval.py
def main(argv: Optional[list[str]] = None) -> int            # line 173 — --pair LABEL=PDF::TREE, --internal,
    #   --min-confidence, --out; writes <UTC>.json and <UTC>.md
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py
DEFAULT_OUT = Path("artifacts/logs/optimizer_eval")          # line 32
def main(argv: Optional[list[str]] = None) -> int            # line 257 — positional PDFs, --target-leaf-tokens,
    #   --min-leaf-tokens, --llm, --out; JSON report with results[] (nodes_before/after, leaves_before/after,
    #   leaf_tokens_p50/p90/max, leaves_over_target_before/after)
# packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py
async def build_page_index(...)                              # options structure_mode, structure_min_confidence,
    #   if_add_node_summary, if_add_doc_description; result["structure"], result["structure_report"]
# wiki/knowledge/pageindex-layout-structure.md
#   "4. **Bookmark rule.**" line 57 (last heading-detection rule, ends line 60)
#   "**Hybrid rule.**" line 72
#   "## Evaluation" line 131; "**Threshold:**" line 210; "**Body-size bold lines …" line 213
#   "## Gotchas" line 219; "- **Re-imports after FEAT-855.**" line 222
```

### Does NOT Exist
- ~~a committed copy of the corpus or of `artifacts/logs/*`~~ — both git-ignored; cite path + sha256.
- ~~`parrot sdd techwiki check` as a pytest~~ — not a registered runner; it stays an acceptance criterion.
- ~~an enhancement count or depth in `layout_eval`'s report~~ — read them from the built tree (Step 3).

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
- Host only, never a coder seat: the runs read `corpus/compliance_soc2_hipaa/` from the main checkout. Run from the
  main checkout with `PYTHONPATH=<worktree>/packages/ai-parrot/src` and confirm the import resolves to the worktree
  (`python -c "import parrot.knowledge.pageindex.layout as L; print(L.__file__)"`) — never `python -I`, which drops
  `PYTHONPATH`.
- Every number in the page is copied from a report or the tree check, with the report's path and sha256. If the
  corpus is missing, the page says "not run" and the §5 evaluation criteria are reported unmet.
- AICPA: metrics only. 800-53 and CSF 2.0 are public NIST documents; their titles may be quoted.
- If a run misses a §5 threshold, do not tune code here: record the numbers, mark the task `done-with-issues`, and say
  which threshold failed.

---

## Implementation Blueprint

### Steps (in order)
1. Four-pair `layout_eval` — the wiki page's command with corpus paths
   `corpus/compliance_soc2_hipaa/raw/<pdf>::corpus/compliance_soc2_hipaa/trees/<tree>.json`, `--internal aicpa_tsc
   --min-confidence 0.6 --out artifacts/logs/layout_eval` — *why*: §5 layout criteria.
2. `python -m parrot.knowledge.pageindex.optimizer_eval corpus/compliance_soc2_hipaa/raw/nist_800_53_r5.pdf
   corpus/compliance_soc2_hipaa/raw/aicpa_tsc_2017.pdf --out artifacts/logs/optimizer_eval/feat_856_deterministic`
   — *why*: §5 optimizer criteria (defaults: target 1500, min 200, no LLM).
3. Build the 800-53 tree with `build_page_index(pdf, adapter=None, options={"structure_mode": "layout",
   "structure_min_confidence": 0.6, "if_add_node_summary": "no", "if_add_doc_description": "no"})` from a scratch
   script and count: nodes whose title starts with `(<digits>)` and contains ` | `; how many sit directly under a
   control node (title matching `^[A-Z]{2}-\d+ `); how many titles end with `|`, `AND`, `OF`, `WITH` or `—` — *why*:
   §5 nesting and full-title criteria, which neither eval report shows.
4. `sha256sum` both JSON reports — *why*: the page cites them.
5. Edit the wiki page (below) and the docs test.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "BOLD_REPEAT_MIN_PAGES",' test_layout_docs.py)
# AFTER — insert below `        "BOLD_REPEAT_MIN_PAGES",` (verified: test_layout_docs.py:27)
        "enumerated_lines",
        "ENUMERATED_SEPARATOR",
        "MAX_CONTINUATION_ROWS",
        "_level_to_depth",
```

### `wiki/knowledge/pageindex-layout-structure.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c -F '4. **Bookmark rule.**' pageindex-layout-structure.md) — after the rule's
     last line (verified: :60), add rule 5: -->
5. **Enumerated rows (FEAT-856).** <FILL IN: a block's first row = bold `(1)`-style enumerator span + caps-only text
   containing `ENUMERATED_SEPARATOR` (`|`); up to `MAX_CONTINUATION_ROWS` caps continuation rows (same block, or the
   next block's first row); recorded in `LayoutProfile.enumerated_lines`; level one below the lowest bold row (max 6);
   running lines and the 3-page repeat filter excluded; the 800-53 enhancement example; no `|` → not a heading>

<!-- occurrences: 1 (verified: grep -c -F '**Hybrid rule.**' pageindex-layout-structure.md) — after the paragraph's
     bullet list (verified: :72-75), add: -->
<FILL IN: the map is strictly increasing (`_level_to_depth`): a level whose majority depth is not deeper than the
   nearest shallower kept level is dropped and its unanchored headings nest one level below it; the 800-53 PL-10
   example (raw `{1: 1, 2: 1, 3: 2, 5: 3, 6: 3}` → `{1: 1, 3: 2, 5: 3}`); bookmark items keep their depth>

<!-- occurrences: 1 (verified: grep -c -F '**Threshold:**' pageindex-layout-structure.md) — above it (verified: :210): -->
<FILL IN: "Runs after FEAT-856" — layout_eval table (four pairs, same columns as above) and optimizer_eval table
   (800-53 and AICPA: nodes, leaves, p50/p90/max, over target before/after) with both report paths + sha256; the tree
   check counts; the `page_agreement` 0.805 → 0.799 artifact (SECURITY AND PRIVACY ATTRIBUTES matches an earlier
   enhancement); `CONTROL SUMMARIES` still split by the optimizer fallback with footer titles — issue:38e4627b2284>

<!-- occurrences: 1 (verified: grep -c -F '- **Re-imports after FEAT-855.**' pageindex-layout-structure.md) — below it (:222): -->
- **Re-imports after FEAT-856.** <FILL IN: 800-53-style PDFs gain enumerated headings and any PDF whose hybrid map was
  not increasing re-places its inserted headings, so their revision ids change on re-import>
```

### FILL IN checklist
- [ ] Steps 1–4 run on the host; numbers copied
- [ ] wiki rule 5, hybrid paragraph, runs section, gotcha
- [ ] docs test names

---

## Acceptance Criteria

- [ ] `layout_eval` report (host, real code): nist_800_53 source `hybrid`, `recall_top` = `recall_all` = 1.0,
      `page_agreement` ≥ 0.79; arxiv 17 layout nodes and 1.0 / 1.0 / 1.0; nist_csf_2_0 22 nodes, `recall_all` 0.643,
      `page_agreement` 1.0; aicpa_tsc 16 nodes, `recall_top` 1.0, `recall_all` 0.611.
- [ ] `optimizer_eval` report: nist_800_53_r5 `leaves_over_target_after` ≤ 2 and `leaf_tokens_max` ≤ 2000;
      aicpa_tsc_2017 16 nodes after, `leaf_tokens_max` 27651.
- [ ] Tree check: every `(n) … | …` node sits directly under a control node; no such title ends with `|`, `AND`, `OF`,
      `WITH` or `—`.
- [ ] The wiki page documents rule 5, the increasing map, both runs (paths + sha256), the `CONTROL SUMMARIES` note and
      the gotcha; AICPA appears as metrics only.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-layout-fixes.spec.md --root .` passes.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q` passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q`

---

## Test Specification

```python
# test_layout_docs.py — extend the names tuple only (see blueprint); no new test functions
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-fixes --feature-id FEAT-856`); run the evaluations from the
   main checkout on the host with `PYTHONPATH` pointing at the worktree
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5412 and TASK-5413 must be `"done"` in `sdd/tasks/index/pageindex-layout-fixes.json`
4. **Verify the Codebase Contract** before writing anything
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — Steps 1–5, completing every `FILL IN`
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5414 pageindex-layout-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
