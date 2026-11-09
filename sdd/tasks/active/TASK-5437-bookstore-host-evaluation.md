# TASK-5437: Run reviewed host corpus evaluation and promote measured defaults

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5431, TASK-5436
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Run only on the owner host with the real library and explicit model, never fabricate a substitute corpus in a worker sandbox.
- Re-index the two legacy EPUBs with --force --no-llm, verify stored addresses, review the 21 spec-drafted handwritten questions with the owner, then freeze all 56 questions.
- Generate the 35 sampled-segment questions once through the harness; fixture stores original questions, provenance, revision/generation and gold addresses only.
- Execute the exact 140-row protocol and record all failures/skips, metrics and SHA256s in artifacts/logs/bookstore_agentic_eval/<timestamp>/.
- Only when coverage qualifies, promote the recommended single tested setting to Bookstore-local defaults for None arguments; explicit overrides remain authoritative and PageIndex defaults stay unchanged.
- If host/corpus/model/owner gold review or coverage is unavailable, retain actual evidence and leave this task incomplete; do not invent metrics or silently waive acceptance.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-858/agentic-eval-questions.json` | CREATE | Scoped deliverable described above |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` | MODIFY | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No Python imports are introduced by this documentation task.

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179
class Bookstore:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:1240
async def agentic_retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
        draft_answer: bool = True,
        budget_chars: Optional[int] = None,
        max_reads: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> dict[str, Any]:
```


### Dependency-produced contracts

- TASK-5431: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
- TASK-5436: serializes overlapping writes to packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- No valid frozen host question fixture or measured Bookstore default recommendation exists at planning time.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "sdd/state/FEAT-858/agentic-eval-questions.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.agentic_retrieve"
  ]
}
```

## Implementation Notes

TASK-5431: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py; TASK-5436: serializes overlapping writes to packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py; Exclusive host-only execution mutates shared corpus EPUB trees/catalog and calls the provider outside declared committed files.

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Run only on the owner host with the real library and explicit model, never fabricate a substitute corpus in a worker sandbox. **Why**: Committed fixture has owner-reviewed handwritten questions and real pinned gold addresses for seven intended books, with documented missing-book failures if any.
2. Re-index the two legacy EPUBs with --force --no-llm, verify stored addresses, review the 21 spec-drafted handwritten questions with the owner, then freeze all 56 questions. **Why**: Actual report accounts for all 140 planned rows, separates provenance, includes tree shape/hashes, and stores no source text/answers.
3. Generate the 35 sampled-segment questions once through the harness; fixture stores original questions, provenance, revision/generation and gold addresses only. **Why**: Coverage satisfies the spec thresholds before promotion; chosen values equal a single tested recommended setting and explicit overrides still work.
4. Execute the exact 140-row protocol and record all failures/skips, metrics and SHA256s in artifacts/logs/bookstore_agentic_eval/<timestamp>/. **Why**: A deterministic regression derives expected defaults from recorded numeric evidence; no runtime dependence on the host report is introduced.
5. Only when coverage qualifies, promote the recommended single tested setting to Bookstore-local defaults for None arguments; explicit overrides remain authoritative and PageIndex defaults stay unchanged. **Why**: Committed fixture has owner-reviewed handwritten questions and real pinned gold addresses for seven intended books, with documented missing-book failures if any.
6. If host/corpus/model/owner gold review or coverage is unavailable, retain actual evidence and leave this task incomplete; do not invent metrics or silently waive acceptance. **Why**: Actual report accounts for all 140 planned rows, separates provenance, includes tree shape/hashes, and stores no source text/answers.

### `sdd/state/FEAT-858/agentic-eval-questions.json` (CREATE)

```json
{
  "schema_version": 1,
  "feature_id": "FEAT-858",
  "questions": []
}

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
# FILL IN: after qualifying host evidence, add Bookstore-local constants for the tested
# budget_chars/max_reads setting and resolve only None inputs in agentic_retrieve.
# Keep max_tool_calls=20 and timeout_s=120; leave PageIndex defaults untouched.
# Never guess values: copy recommendation from the report, with report path/hash in task evidence.
# Preserve explicit arguments and earlier facade/error/snapshot behavior; AC-3, AC-4.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` (MODIFY)

```python
# Dependency-created file from TASK-5436; absent at base, so no fabricated grep count.
# Planned attachment anchor: def test_frozen_plan_has_140_rows() -> None:
# Expected occurrences after the prerequisite lands: 1; run grep -cF then, not claimed measured now.
# Append the scoped tests below; preserve every predecessor test.
# Append to the dependency-created numeric evaluation test module.
def test_bookstore_defaults_match_recorded_recommendation() -> None:
    """Only the measured tested setting becomes Bookstore defaults; overrides still win."""
    # FILL IN: freeze qualifying numeric evidence and recommended values from the actual report,
    # assert None resolution/explicit forwarding without reading a host file at runtime; AC-3, AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `sdd/state/FEAT-858/agentic-eval-questions.json` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Committed fixture has owner-reviewed handwritten questions and real pinned gold addresses for seven intended books, with documented missing-book failures if any.
- [ ] AC-2: Actual report accounts for all 140 planned rows, separates provenance, includes tree shape/hashes, and stores no source text/answers.
- [ ] AC-3: Coverage satisfies the spec thresholds before promotion; chosen values equal a single tested recommended setting and explicit overrides still work.
- [ ] AC-4: A deterministic regression derives expected defaults from recorded numeric evidence; no runtime dependence on the host report is introduced.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.

### Host execution and evidence (mandatory, separate from deterministic Validation Commands)

This task is **host-only**. The scheduler must hand it to the operator's host after its
prerequisites land; a sandbox worker must report missing access and leave it pending.
Do not execute the JSON starter as a valid fixture: populate all questions and addresses
before evaluation. Empty or placeholder addresses are an acceptance failure.

Use the actual resolved library path and the reviewed fixture:

```text
bookstore add <verified-zaratustra-epub> --force --no-llm
bookstore add <verified-kierkegaard-epub> --force --no-llm
python -m parrot.knowledge.bookstore.agentic_eval --library <verified-library> --questions sdd/state/FEAT-858/agentic-eval-questions.json --llm google:gemini-3.5-flash-lite --concurrency 1
```

Angle-bracket paths above are operator inputs, not claimed filesystem locations. Activate
the host venv first. Follow spec §4 for question-generation mode, review, frozen seed,
80% coverage, exact quality/median tie-break rule, retries and report privacy. Record the
report path, SHA256, fixture hash, planned/completed rows, actual model and chosen setting
in the Completion Note. Do not commit raw books, answers or generated provider output.
The logs are intentional execution artifacts outside this task's committed file set.

## Agent Instructions

1. Run `$sdd-start TASK-5437` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

NOT COMPLETED - needs the owner host. The task requires the real library, an explicit model, re-indexing the two legacy EPUBs and the owner's review of the 21 handwritten questions; the worker sandbox cannot do this and must not fabricate a corpus. Two coder attempts (gpt-5.6-terra, gpt-5.6-sol) both returned empty_delivery. Harness from TASK-5436 is merged and ready. After the owner runs it, TASK-5438 (docs, depends on 5437) can proceed.
