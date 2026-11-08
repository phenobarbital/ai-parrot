# TASK-5376: Deterministic tuning run of target_leaf_tokens (host/orchestrator only)

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5375, TASK-5372
**Assigned-to**: unassigned

---

## Context

Spec §3 M6 "Tuning run" and AC-19. **Executed by the sdd-worker orchestrator or on the host, never by a coder seat**:
in FEAT-845 (TASK-5344) a coder seat invented a metrics table for this corpus. Every number in the Completion Note is
copied from the written report.

## Scope

- Run once, deterministically (no `--llm`):
  ```bash
  MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
  PYTHONPATH=packages/ai-parrot/src python -m parrot.knowledge.pageindex.optimizer_eval     "$MAIN_ROOT/corpus/compliance_soc2_hipaa/raw/nist_800_53_r5.pdf"     "$MAIN_ROOT/corpus/compliance_soc2_hipaa/raw/nist_csf_2_0.pdf"     "$MAIN_ROOT/corpus/compliance_soc2_hipaa/raw/hipaa_45cfr164_2022.pdf"     "$MAIN_ROOT/corpus/compliance_soc2_hipaa/raw/aicpa_tsc_2017.pdf"     packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf
  sha256sum <printed report path>
  ```
- If `tuned_target` printed a value, set `target_leaf_tokens` default in `OptimizerSettings` to it; otherwise leave 1500.
  No other default changes.
- Open the follow-up ledger issue:
  `wikitoolkit ledger open --kind tech_debt --severity minor --discovered-from spec:FEAT-846 --about file:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py --title "Optimizer LLM-mode tuning run" --body "Run optimizer_eval with --llm on the host; measure llm_heading_splits, key_items, summary lengths; settle summary_max_words, max_key_items, routing_tokens_per_child."`

**NOT in scope**: committing the report (gitignored); any other default; an LLM-mode run.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | target_leaf_tokens default only, when tuned_target returns a value |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# optimizer.py (TASK-5364): class OptimizerSettings(BaseModel): target_leaf_tokens: int = 1500
# optimizer_eval.py (TASK-5375): main(argv) prints the report path and tuned_target(report, OptimizerSettings())
```

### Does NOT Exist
- ~~the compliance PDFs inside a worktree~~ — gitignored; read them from the primary checkout (`$MAIN_ROOT`)
- ~~a metrics table not copied from the report~~ — forbidden; if the run fails, write "not run" with the error

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Fewer than three PDFs readable, or the run fails → Completion Note says "not run" + error; no default change.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY — only if tuned_target returned a value)
```python
# REPLACE `    target_leaf_tokens: int = 1500` (occurrences: 1 — verify with grep -c before editing)
    target_leaf_tokens: int = <tuned_target value>   # FILL IN: value copied from the printed tuned_target; tuned by FEAT-846 TASK-5376
```
**Why**: the rule (spec AC-19) allows exactly this one edit.

**FILL IN checklist**
- [ ] run executed  - [ ] report path + sha256 + PDF count + suggested + tuned_target in the Completion Note
- [ ] default edited or left at 1500  - [ ] ledger issue id in the Completion Note

---

## Acceptance Criteria

- [ ] AC-19 satisfied; `pytest test_optimizer.py` still passes after any default change.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py -q`

---

## Test Specification

No new tests (the run is not a test; AC-1 forbids a `real_llm` test).

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5376 — Deterministic tuning run of target_leaf_tokens (host/orchestrator only)`.

---

## Completion Note

*(Agent fills this in when done)*
