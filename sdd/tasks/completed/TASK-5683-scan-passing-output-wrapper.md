# TASK-5683: Scan a presentation wrapper in `response.response` when the OUTPUT pipeline passes

**Feature**: FEAT-894 — OUTPUT guardrails — scan a presentation wrapper when the output passes
**Spec**: `sdd/specs/bots-abstract-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:a20713dc67a6`

---

## Context

`AbstractBot._run_output_pipeline` hands the OUTPUT verdict to `response.response` only on BLOCK or TRANSFORM.
On PASS, a distinct string there reaches the caller unscanned. Examples are `get_response`'s markdown
"**Question** / **Answer** / **Sources**" block (used by `invoke` / `conversation`) and a formatter's wrapped string
in `ask()`. `AIMessage.to_text` prefers that string (spec §1). This task calls `_propagate_output_verdict` on every
non-blocked outcome. Its existing early returns keep a plain `ask()` at one pipeline run.

---

## Scope

- `_run_output_pipeline`: move `await self._propagate_output_verdict(response, original, pipeline, ctx)` out of
  the TRANSFORM `if`, so it runs for every non-blocked outcome. Rewrite the comment above it.
- `_run_output_pipeline` and `_propagate_output_verdict` docstrings: state that the verdict reaches a distinct
  wrapper on PASS too, and that an alias or an empty wrapper costs no second run.
- `test_finalize_persist_turn.py`: replace `test_a_passing_response_runs_the_output_guardrails_once` with
  `test_a_passing_response_scans_each_distinct_text_once`, and add the three new tests from spec §4.

**NOT in scope**: `issue:8f65307982dd` (`_persist_turn_unit` transaction / serialization); the `lint:duplicate-slug`
issues; structured (non-`str`) outputs and the early return at `abstract.py:3321`; `ask_stream`; any change to
`_stored_turn_text`, `_OUTPUT_VERDICT`, the BLOCK branch or `GuardrailPipeline`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | unconditional propagate call + comment + two docstrings |
| `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` | MODIFY | one test replaced, three added |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage  # verified: tests/integration/test_guardrails_output.py:23-28
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:20
from parrot.models.basic import CompletionUsage  # verified: test_finalize_persist_turn.py:21
from .test_turn_publish_after_save import SECRET, Client, RecordingPublisher, _SecretClient, _bot  # verified: test_finalize_persist_turn.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3296
#   :3341 original = response.output ; :3342-3349 BLOCK branch (unchanged)
#   :3351-3356 non-blocked: comment, _OUTPUT_VERDICT.set(...), TRANSFORM if → propagate (the edit site)
async def _propagate_output_verdict(self, response, original, pipeline, ctx, blocked_text=None) -> None  # line 3363
#   :3379 early return when response.response is not a non-empty str or equals response.output
#   :3386-3390 wrapped string → pipeline.run(alias, ctx); blocked → response.output; else rewritten text

# packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
async def _guarded_bot(client: Client) -> BaseBot  # line 26 — BaseBot + SecretsGuardrail on OUTPUT
# test_a_passing_response_runs_the_output_guardrails_once  line 271-290 (parametrized ask/invoke/conversation)

# packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
# Client._msg → AIMessage(output="reply", ...) line 36 ; SECRET = "sk-1234abcdefghij" line 281 ; _bot(...) line 75

# packages/ai-parrot/src/parrot/bots/guardrails/base.py
class Guardrail(ABC):  # line 97 — name, stages, priority, on_error; abstract async check(content, ctx)
```

### Does NOT Exist
- ~~a scan of `response.response` on PASS~~ — added by this task.
- ~~a FLAG-only capability flag on `Guardrail`~~ — none. The wrapper scan runs the whole pipeline.
- ~~`test_a_passing_response_scans_each_distinct_text_once`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._run_output_pipeline",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._propagate_output_verdict"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_OUTPUT_VERDICT.set(...)` stays before the propagate call and keeps recording the `output` verdict.
- `_propagate_output_verdict`'s early return is the only gate for the extra run. Add no second check in
  `_run_output_pipeline`.
- The BLOCK branch is byte-identical.
- `black` line length 120; Google-style docstrings.

### References in Codebase
- `abstract.py:3363-3390` — `_propagate_output_verdict`, reused unchanged except its docstring.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three new tests and the replaced count test. Run them on the unmodified code: the wrapper tests and
   the `invoke` / `conversation` count cases must FAIL — *why*: a mutation check proves the tests pin the gap.
2. Move the propagate call and rewrite the comment and docstrings — *why*: the verdict reaches the wrapper on PASS.
3. Run the Validation Commands, `ruff check` and `black --check`.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — non-blocked branch, :3351-3356)
```python
        # `pipeline.run` returns the working content on every non-blocked pass. A TRANSFORM rewrites `output`; on
        # PASS and TRANSFORM alike the verdict then reaches a distinct presentation wrapper in `response.response`
        # (issue:a20713dc67a6). `_propagate_output_verdict` skips an alias or an empty wrapper, so a plain PASS still
        # runs the guardrails once.
        _OUTPUT_VERDICT.set((id(response), original, outcome.content if outcome.content is not None else original, ctx))
        if outcome.content is not None and outcome.content != original:
            response.output = outcome.content
        await self._propagate_output_verdict(response, original, pipeline, ctx)
```

### `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` (MODIFY)
```python
@pytest.mark.parametrize(("entry", "expected_runs"), [("ask", 1), ("invoke", 2), ("conversation", 2)])
async def test_a_passing_response_scans_each_distinct_text_once(entry: str, expected_runs: int):
    # same body as the replaced test; assert len(runs) == expected_runs, and for 2 runs that
    # "**Question**" is in runs[1] and not in runs[0]

async def test_a_passing_output_still_scans_its_wrapper(): ...
@pytest.mark.parametrize("entry", ["invoke", "conversation"])
async def test_a_question_echoed_in_the_markdown_wrapper_is_redacted(entry: str): ...
async def test_a_blocked_wrapper_falls_back_to_the_passing_output(): ...  # local Guardrail subclass, OUTPUT stage
```

### FILL IN checklist
- [ ] Docstring wording for both methods — bounded by spec §2 Overview.
- [ ] Test bodies — bounded by spec §4 Unit Tests.

---

## Acceptance Criteria

- [ ] On PASS, a distinct `response.response` is scanned: a TRANSFORM rewrites it, a BLOCK replaces it with
      `response.output`.
- [ ] `ask()` without a wrapper runs the OUTPUT guardrails exactly once.
- [ ] The new wrapper tests fail on the unmodified code and pass with the fix.
- [ ] The Validation Commands pass from the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] `ruff check` passes; `black --check` leaves the changed lines unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py -q`
- `pytest packages/ai-parrot/tests/integration/test_guardrails_output.py -q`
- `pytest packages/ai-parrot/tests/integration/test_security_guardrails_e2e.py -q`

---

## Test Specification

See spec §4 Unit Tests.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug bots-abstract-tech-debt --feature-id FEAT-894`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/bots-abstract-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5683 bots-abstract-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: 2026-11-14 · **Verification**: verified · **Code commit**: `d4f24dc697`

- `_run_output_pipeline` now calls `_propagate_output_verdict` on every non-blocked outcome. Before, it called it
  only inside the TRANSFORM `if`. The comment and both docstrings say the verdict reaches a distinct wrapper on
  PASS too. The BLOCK branch, `_OUTPUT_VERDICT` and `_stored_turn_text` are unchanged.
- Tests: `test_a_passing_response_runs_the_output_guardrails_once` became
  `test_a_passing_response_scans_each_distinct_text_once` (`ask` → 1 run; `invoke` / `conversation` → 2, the second
  being the markdown block). Added `test_a_passing_output_still_scans_its_wrapper`,
  `test_a_question_echoed_in_the_markdown_wrapper_is_redacted[invoke|conversation]` and
  `test_a_blocked_wrapper_falls_back_to_the_passing_output`.
- Mutation check: on the unfixed code the 6 new or changed wrapper cases FAIL, and `[ask-1]` passes. With the fix,
  the four Validation Contract files pass: 76 passed (`PYTHONPATH=packages/ai-parrot/src`).
- `ruff check` passes. `black --check -l 120` reports both files, but both were already non-conformant on
  `origin/dev` (same hunk count before and after: 7 in `abstract.py`, 8 in the test file). No hunk touches a
  changed line.
- Out of scope, as the spec says: `issue:8f65307982dd` (not claimed), and the structured-output early return at
  `abstract.py:3321`. The latter is filed as its own ledger issue.
