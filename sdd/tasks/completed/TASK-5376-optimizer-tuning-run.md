# TASK-5376: Deterministic tuning run of target_leaf_tokens (host/orchestrator only)

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
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

**Completed**: 2026-11-09 | **Status**: partial — tuning run NOT run

No code changed; `OptimizerSettings.target_leaf_tokens` stays 1500.

Not run: the four compliance PDFs do not exist (`corpus/compliance_soc2_hipaa/raw/` is absent in the primary checkout) and `corpus/compliance_soc2_hipaa/fetch.py` needs network access, which the worker sandbox does not have. No metrics table is reported because no report was produced (a single-PDF run on the arxiv fixture prints `tuned_target: None`, since `tuned_target` needs at least 3 trees, so it cannot settle the default either).

Follow-ups filed: issue:7111d74a3066 (run the deterministic tuning on the host; AC-19 unmet until then) and issue:336eef8010a1 (LLM-mode tuning run, required by this task).

**Addendum 2026-11-09 (host run, closes issue:7111d74a3066 and issue:336eef8010a1).** The tuning run was executed on
the host over the four compliance PDFs and the arXiv fixture (`dev @ 09c95b1646`), plus three Spanish PDFs from the
local Bookstore library, deterministically and in LLM mode (`google:gemini-3.5-flash-lite`). Report paths and sha256:
`artifacts/logs/optimizer_eval/deterministic_corpus_only/optimizer_eval-20261109T122507348707Z.json` `b7affece84d877fe28cfbe3d8ce1a428d6d5c4e296de09b47a77484b4b824e43` (suggested target 1100);
`artifacts/logs/optimizer_eval/deterministic/optimizer_eval-20261109T121801073795Z.json` `fe02a470e2101f067a99475a6ff5851e587f1b737a70266df82666193a5890e2` (8 PDFs, suggested 2100);
`artifacts/logs/optimizer_eval/llm_small/optimizer_eval-20261109T122255854142Z.json` `680cdf81a824923dd7efccbfa2061434eef880068b12572388a7435a75ade3d9` (suggested 2200);
`artifacts/logs/optimizer_eval/llm_800_53/optimizer_eval-20261109T122706159755Z.json` `7651c039e41d02c793fb80f4f9aff8050d576c4ecb9790663639c8520a777660`.
Every metric is copied into `wiki/knowledge/pageindex-tree-optimizer.md` § Evaluation. Decision (Jesus Lara):
`target_leaf_tokens` stays 1500 — the suggestion is a pooled p75 and swings with corpus composition
(`issue:adae36a70919`). Bugs surfaced by the run: `issue:66f376157327`, `issue:33ad15e686e9`, `issue:ab5235978ad7`,
`issue:0a693a57b138`.
