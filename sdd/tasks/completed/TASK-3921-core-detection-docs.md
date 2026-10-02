# TASK-3921: Bring the orchestrator docs in line with direct-importer core detection

**Feature**: FEAT-620 — Direct-Importer Core Detection for the Merge-Tier Gate
**Spec**: `sdd/specs/test-scope-impact-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3920
**Assigned-to**: unassigned

---

## Context

Implements spec §2 M4.

`docs/dev_loop/sdd-coder-orchestrator.md` §"Core detection and escalation"
documents the metric TASK-3919 replaces and the list TASK-3920 regenerates:

- line 583-587 describes core as "transitive source fan-in — every source
  module that imports it, directly or indirectly … `≥ DEFAULT_CORE_FANIN_THRESHOLD`
  (50)". All three facts change.
- line 593-596 carries a 2026-09-17 code-review cost callout stating
  `CORE_PATHS` has 724 entries and that `clients/base.py` / `bots/abstract.py`
  escalate to ~25 of ~26 distributions.

Depends on TASK-3920 because the final `CORE_PATHS` entry count is not known
until the generator runs.

---

## Scope

- Rewrite the metric description: direct importers, threshold 30, with the
  measured separation as the justification.
- Replace the cost callout with what the feature actually delivered — it was a
  statement of the problem FEAT-620 fixes, so it is resolved, not deleted:
  record the before/after so the history stays legible.
- Point `CORE_PATHS`'s provenance at `scripts/sdd/regen_core_paths.py` instead
  of the git-ignored `artifacts/logs/feat-563-core-fanin.tsv`.

**NOT in scope**: any code change; any other section of the orchestrator doc;
`docs/` files other than the one listed; the spec itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | §"Core detection and escalation": metric, threshold, provenance, cost callout |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# None — this task is documentation only and writes no Python.
```

### Existing Signatures to Use
```text
# docs/dev_loop/sdd-coder-orchestrator.md:582   "### Core detection and escalation"
# docs/dev_loop/sdd-coder-orchestrator.md:583-587
#   A changed source module is *core* when its transitive source fan-in - every source module that
#   imports it, directly or indirectly, found by one AST pass over the worktree
#   (`test_scope/impact.py`'s `ImportIndex`/`source_fanin`) - is `>= DEFAULT_CORE_FANIN_THRESHOLD`
#   (50), or its path is listed in `CORE_PATHS` (the manual override for AST-under-counted dynamic
#   imports/registries/the `parrot.tools.<x>` <-> `parrot_tools.<x>` meta_path redirect - measured by
#   the TASK-3318 spike; see `artifacts/logs/feat-563-core-fanin.tsv`).
# docs/dev_loop/sdd-coder-orchestrator.md:593
#   > **Cost callout (code review, 2026-09-17).** `CORE_PATHS` currently has 724 measured entries,
```

### Values this task must state (verify before writing)
```text
DEFAULT_CORE_FANIN_THRESHOLD  = 30            # set by TASK-3919; read policy.py, do not assume
len(CORE_PATHS)               = <run it>      # set by TASK-3920; read policy.py, do not assume
measured separation           = dsl.py 2 direct importers vs clients/base.py 35,
                                bots/abstract.py 31, tools/abstract.py 151, conf.py 174
                                (dev@76a7d7b22, 2688 modules, 28 distributions)
```

### Does NOT Exist
- ~~`artifacts/logs/feat-563-core-fanin.tsv`~~ — cited by the current text, but
  `artifacts/` is git-ignored and the file is not in the checkout. The
  replacement provenance is `scripts/sdd/regen_core_paths.py`.
- ~~a "transitive fan-in" code path after TASK-3919~~ — do not describe one as
  still present, even as a fallback.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/dev_loop/sdd-coder-orchestrator.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Read the shipped values, do not copy them from this task file.** The entry
  count in particular depends on TASK-3920's generator run. Open `policy.py` and
  count.
- The cost callout is dated and attributed ("code review, 2026-09-17"). Keep it
  as a resolved note with its original date plus the resolution, rather than
  erasing a finding that was correct when written.
- Match the surrounding prose: this doc uses backticked symbol names, `>`
  blockquote callouts, and em-dashes. No new heading levels.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` — the
  source of truth for both numbers.
- `sdd/specs/test-scope-impact-tech-debt.spec.md` §1 — the measurement tables to
  draw the justification from.

---

## Implementation Blueprint

### Steps (in order)
1. Read `policy.py` for the shipped threshold and the regenerated entry count —
   *why*: both changed in the two preceding tasks and the doc must state what ships.
2. Rewrite the metric paragraph — *why*: it currently describes the defect as the design.
3. Convert the cost callout into a resolved note — *why*: it stated the problem this
   feature fixes; leaving it unqualified would read as a live warning.

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'A changed source module is \*core\* when its transitive source fan-in' docs/dev_loop/sdd-coder-orchestrator.md)
# REPLACE the paragraph at docs/dev_loop/sdd-coder-orchestrator.md:583-587 (verified: :583)
A changed source module is *core* when its **direct** source fan-in — the number of source
modules that import it, found by one AST pass over the worktree
(`test_scope/impact.py`'s `ImportIndex`/`source_fanin`) — is `≥ DEFAULT_CORE_FANIN_THRESHOLD`
(30), or its path is listed in `CORE_PATHS` (the override for AST-under-counted dynamic
imports/registries/the `parrot.tools.<x>` ↔ `parrot_tools.<x>` meta_path redirect —
regenerated by `scripts/sdd/regen_core_paths.py`).

# FILL IN: one or two sentences giving the measured justification for "direct"
# -- bounded by spec §1: name the leaf-vs-hub separation and that the transitive
# metric saturated (leaf 1041 > genuine core 1024).
```
**Why**: the sentence is the doc's definition of core, so every later paragraph
("A core hit escalates the package suite of every distribution that
(transitively) imports the changed module") reads against it. Note that clause
stays true — escalation *reach* is still transitive; only *detection* is direct.
Do not change it.

```markdown
# occurrences: 1 (verified: grep -c 'Cost callout (code review, 2026-09-17)' docs/dev_loop/sdd-coder-orchestrator.md)
# REPLACE the callout at docs/dev_loop/sdd-coder-orchestrator.md:593-596 (verified: :593)
# FILL IN: rewrite as a resolved note keeping the 2026-09-17 date and attribution,
# stating the before (724 CORE_PATHS entries; clients/base.py and bots/abstract.py
# escalating to ~25 of ~26 distributions) and the after (the shipped entry count,
# read from policy.py; detection now direct) with a pointer to FEAT-620
# -- bounded by: state only numbers you read from policy.py.
```
**Why**: the finding was accurate and is the reason this feature exists; a
resolved note preserves why the list shrank, which a deletion would lose.

### FILL IN checklist
- [ ] Metric justification sentences; bounded by spec §1's measurements.
- [ ] Resolved cost callout; bounded by reading the shipped numbers from `policy.py`.

---

## Acceptance Criteria

- [ ] The doc no longer describes core detection as transitive.
- [ ] The stated threshold matches `DEFAULT_CORE_FANIN_THRESHOLD` in `policy.py`.
- [ ] The stated `CORE_PATHS` entry count matches the committed tuple.
- [ ] `CORE_PATHS` provenance points at `scripts/sdd/regen_core_paths.py`, not the
      git-ignored TSV.
- [ ] The 2026-09-17 callout survives as a dated, resolved note.
- [ ] No code file is modified by this task.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_paths.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py -q`

---

## Test Specification

Documentation-only; there is no test that reads this file. The two commands above
are the regression check that the numbers the doc states are the ones that ship —
run them and read the shipped values from `policy.py` rather than inventing a
doc-linting test.

---

## Agent Instructions

Modify only `docs/dev_loop/sdd-coder-orchestrator.md`. Do not touch `policy.py`,
`impact.py` or the spec.

---

## Completion Note

**Completed**: 2026-10-01 — verified.

Both passages in `docs/dev_loop/sdd-coder-orchestrator.md`
§"Core detection and escalation" now match what ships. Values were read from
`policy.py` in this worktree, not copied from the task file:
`DEFAULT_CORE_FANIN_THRESHOLD = 30` (policy.py:15) and 29 `CORE_PATHS` entries
(`grep -c '^    "packages/'`).

Changes:
- The metric paragraph says **direct** fan-in, threshold 30, and points
  `CORE_PATHS` provenance at `scripts/sdd/regen_core_paths.py` instead of the
  git-ignored `artifacts/logs/feat-563-core-fanin.tsv`. A second paragraph gives
  the measured justification (leaf 1041 > core 1024 under the old metric; 2 vs
  35/31/151 under the new one).
- The "A core hit escalates the package suite…" sentence is now its own
  paragraph and was rewrapped. Its content is unchanged and still correct:
  escalation *reach* stays transitive, only *detection* became direct.
- The 2026-09-17 cost callout is kept with its date and attribution and marked
  resolved. Worth recording: its own closing sentence listed "re-run the S4
  measurement with a narrower `CORE_PATHS` curation pass" as one of three
  options, which is what FEAT-620 did — so the note says which option was taken
  rather than just asserting a fix. The part of the callout that still stands
  (`XDIST_SAFE_DISTRIBUTIONS` ships empty, so a genuine core hit is still a
  large serial run) is explicitly preserved.

**Tests**: 5 passed — `test_core_paths.py`, `test_core_calibration.py`. These
are the regression check that the numbers stated in the doc are the ones that
ship; there is no doc-linting test and none was invented.

**No code file was modified by this task** — `git status` showed only
`docs/dev_loop/sdd-coder-orchestrator.md`.
