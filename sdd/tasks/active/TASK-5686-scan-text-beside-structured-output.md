# TASK-5686: Scan the text answer beside a structured output with the OUTPUT guardrails

**Feature**: FEAT-898 — OUTPUT guardrails — scan the text answer beside a structured output
**Spec**: `sdd/specs/bots-abstract-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:062128ff0d48`

---

## Context

`AbstractBot._run_output_pipeline` returns early when `response.output` is not a `str`, so a text
`response.response` beside a dict / DataFrame / HTML output reaches the caller unscanned. `AIMessage.to_text`
prefers that text (spec §1). This task scans it with the same OUTPUT pipeline and applies the verdict to
`response.response` only. The structured `output` is never rewritten.

---

## Scope

- `_run_output_pipeline`: the early return keeps the no-guardrails case and a non-`str` output with no non-empty
  `str` `response.response`. Pick the text to scan (`output` for a `str`, `response.response` otherwise), build the
  `GuardrailContext` once, run the pipeline, and hand a structured outcome to the new helper. Update the docstring
  paragraph at `:3313–3316`.
- New private method `_apply_verdict_beside_structured_output(response, text, outcome, ctx) -> AIMessage`, placed
  before `_propagate_output_verdict`. BLOCK sets `response.response = _OUTPUT_BLOCKED_TEXT`,
  `metadata["error"] = "security_block"` and `block_reason`. Otherwise it writes the verdict text to
  `response.response` and merges `flag_reports`. Every case sets `_OUTPUT_VERDICT` to `(id(response), text,
  <verdict text>, ctx)`.
- `test_finalize_persist_turn.py`: add the four new tests from spec §4.

**NOT in scope**: scanning the structured payload (`output` / `structured_output`); `PandasAgent.ask`;
`issue:8f65307982dd`; any change to the `str`-output path, `_propagate_output_verdict`, `_stored_turn_text`,
`GuardrailPipeline` or `base.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | narrowed early return, shared ctx, structured branch, new helper, docstring |
| `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` | MODIFY | four tests added |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import _OUTPUT_BLOCKED_TEXT  # verified: abstract.py:235
from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage  # verified: tests/integration/test_guardrails_output.py:23-28
from parrot.bots.guardrails.pipeline import PipelineOutcome  # verified: pipeline.py:62
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:21
from parrot.models.basic import CompletionUsage  # verified: test_finalize_persist_turn.py:22
from .test_turn_publish_after_save import SECRET, Client, RecordingPublisher, _SecretClient, _bot  # verified: test_finalize_persist_turn.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
_OUTPUT_VERDICT: ContextVar[Optional[Tuple[int, str, str, Any]]]  # line 233
_OUTPUT_BLOCKED_TEXT = "This response could not be delivered due to a content policy violation."  # line 235
async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3297
#   :3313-3316 docstring "Mirrors the pre-migration channel-egress guard … left untouched"
#   :3326 _OUTPUT_VERDICT.set(None) ; :3327 pipeline = … ; :3328 early return (the edit site)
#   :3331-3345 ctx = GuardrailContext(...) ; :3346 outcome = await pipeline.run(response.output, ctx)
#   :3348-3370 str path: original, BLOCK branch, non-blocked branch (unchanged)
async def _propagate_output_verdict(self, response, original, pipeline, ctx, blocked_text=None) -> None  # line 3372
async def _stored_turn_text(self, response, plain, method="persist") -> Optional[str]  # line 3404
#   :3422-3426 reuses verdict[2] when id matches and plain == verdict[1]
# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class PipelineOutcome(BaseModel):  # line 62 — content: str | None (:78), blocked (:79), reason (:80), flag_reports (:81)
# packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
async def _guarded_bot(client: Client) -> BaseBot  # line 27 — BaseBot + SecretsGuardrail on OUTPUT
async def _stored(bot: BaseBot)  # line 37
class _DataFrameClient(Client)  # line 92
def _passing_message(response: str) -> AIMessage  # line 316
class _ExplanationSecretClient(Client)  # line 370 — output={"html": "<b>chart</b>"}, response=f"your key is API_KEY={SECRET}"
async def test_text_the_pipeline_never_scanned_is_still_redacted_before_it_is_persisted()  # line 380
# packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
# Client._msg → AIMessage(output="reply", ...) ; SECRET = "sk-1234abcdefghij" ; _bot(...)
```

### Does NOT Exist
- ~~`AbstractBot._apply_verdict_beside_structured_output`~~ — created by this task.
- ~~a scan of `response.response` when `output` is not a `str`~~ — added by this task.
- ~~a guardrail hook that walks a dict / DataFrame `output`~~ — none, and none is added.

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
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._stored_turn_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The `str`-output path behaves exactly as before: same pipeline call, same BLOCK branch, same non-blocked
  branch. Only the variable passed to `pipeline.run` is renamed.
- Never put a non-`str` `output` in a boolean context or compare it with `==` (DataFrame ambiguity).
- `_apply_verdict_beside_structured_output` is synchronous and never touches `response.output`.
- `black` line length 120; Google-style docstrings; strict type hints.

### References in Codebase
- `abstract.py:3349-3356` — the `str` BLOCK branch, whose metadata keys the structured BLOCK mirrors.

---

## Implementation Blueprint

### Steps (in order)
1. Add the four tests. Run them on the unmodified code: the redaction, echo and BLOCK tests must FAIL. *Why*: a
   mutation check proves the tests pin the gap. The no-text-answer test passes on both.
2. Narrow the early return, add the structured branch and the helper, and update the docstring.
3. Run the Validation Commands, `ruff check` and `black --check`.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — `_run_output_pipeline`, :3326-3346)
```python
        _OUTPUT_VERDICT.set(None)
        pipeline = self._guardrail_pipelines[GuardrailStage.OUTPUT]
        # A structured/DataFrame `output` is never rewritten; the text answer kept beside it in `response.response`
        # (what `to_text` prefers) is scanned instead (issue:062128ff0d48). No text answer: nothing to scan.
        structured = not isinstance(response.output, str)
        text = response.response if structured else response.output
        if not pipeline.has_guardrails or (structured and (not isinstance(text, str) or not text)):
            return response

        ctx = GuardrailContext(...)  # unchanged
        outcome = await pipeline.run(text, ctx)
        if structured:
            return self._apply_verdict_beside_structured_output(response, text, outcome, ctx)

        original = response.output
        # … unchanged str path
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (ADD — before `_propagate_output_verdict`)
```python
    def _apply_verdict_beside_structured_output(
        self, response: AIMessage, text: str, outcome: PipelineOutcome, ctx: GuardrailContext
    ) -> AIMessage:
        """Apply an OUTPUT verdict on the text answer beside a structured output (issue:062128ff0d48). …"""
        if outcome.blocked:
            response.response = _OUTPUT_BLOCKED_TEXT
            _OUTPUT_VERDICT.set((id(response), text, _OUTPUT_BLOCKED_TEXT, ctx))
            response.metadata["error"] = "security_block"
            if outcome.reason:
                response.metadata["block_reason"] = outcome.reason
            return response
        verdict = outcome.content if outcome.content is not None else text
        _OUTPUT_VERDICT.set((id(response), text, verdict, ctx))
        response.response = verdict
        if outcome.flag_reports:
            response.metadata.setdefault("guardrails", {}).update(outcome.flag_reports)
        return response
```

### `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` (MODIFY — append after :380's test)
```python
async def test_a_text_answer_beside_a_structured_output_is_redacted_for_the_caller(): ...
@pytest.mark.parametrize("entry", ["invoke", "conversation"])
async def test_a_question_echoed_beside_a_structured_output_is_redacted(entry: str): ...
@pytest.mark.parametrize("output", ["dict", "dataframe"])
async def test_a_structured_output_with_no_text_answer_runs_no_guardrail(output: str): ...
async def test_a_blocked_text_beside_a_structured_output(): ...  # local Guardrail subclass, OUTPUT stage
```

### FILL IN checklist
- [ ] Docstring wording for `_run_output_pipeline` and the helper — bounded by spec §2 Overview.
- [ ] Test bodies — bounded by spec §4 Unit Tests.

---

## Acceptance Criteria

- [ ] A non-empty `str` `response.response` beside a non-`str` `output` is scanned: a TRANSFORM rewrites it; a BLOCK
      replaces it with `_OUTPUT_BLOCKED_TEXT` and sets `metadata["error"] = "security_block"`; FLAG reports merge.
- [ ] A non-`str` `output` is never rewritten. With no text answer beside it, no guardrail runs.
- [ ] `ask()` against `_ExplanationSecretClient` runs the OUTPUT guardrails exactly once.
- [ ] The redaction, echo and BLOCK tests fail on the unmodified code and pass with the fix.
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
   (`parrot sdd worktree ensure --slug bots-abstract-fixes --feature-id FEAT-898`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/bots-abstract-fixes.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Close** with `parrot sdd task close TASK-5686 bots-abstract-fixes verified` and fill in the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
