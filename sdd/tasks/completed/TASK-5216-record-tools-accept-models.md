# TASK-5216: coder_record_review/coder_record_feedback accept validated models

**Feature**: FEAT-812 — coder_record_review/feedback accept validated models, and re-dispatched attempts never collide
**Spec**: `sdd/specs/ledger-coder-reviews-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3b913ffd77cd`

---

## Context

Spec §1 B1 / §2 "B1". Since commit `197fdeaaa0`, `AbstractTool._shallow_dump` keeps nested models
intact after argument validation. `SddCoderToolkit` installs `CoderRecordReviewArgs`
(`review: CoderReview`) and `CoderRecordFeedbackArgs` (`feedback: CoderFeedback`) as the tools'
`args_schema`, so through the MCP adapter the methods receive model instances, and
`CoderReview(**review)` / `CoderFeedback(**feedback)` raise
`argument after ** must be a mapping, not CoderReview`. Every `coder_record_review` call in the
FEAT-806 run failed this way.

---

## Scope

- Replace `CoderReview(**review)` with `CoderReview.model_validate(review)` in
  `SddCoderToolkit.coder_record_review`.
- Replace `CoderFeedback(**feedback)` with `CoderFeedback.model_validate(feedback)` in
  `SddCoderToolkit.coder_record_feedback`.
- Add tests: both tools executed through `MCPToolAdapter` reach the engine with a model instance;
  both methods called directly with a plain dict still work.

**NOT in scope**: changing `AbstractTool._shallow_dump`; the attempt-collision defect (TASK-5217);
any change to `coder_reviews.py` / `coder_feedback.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | `model_validate` instead of `**` unpacking |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit  # verified: sdd_coder/toolkit.py
from parrot.mcp.adapter import MCPToolAdapter  # verified: used in test_feedback.py:278
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback  # verified: test_feedback.py:13
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview  # verified: test_feedback.py:15
from unittest.mock import AsyncMock  # verified: test_feedback.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:355
async def coder_record_feedback(self, feature: str, worktree: str, feedback: Dict[str, Any], execution_id: str) -> CoderResult
#   line 373: self._engine.record_feedback(feature, worktree, CoderFeedback(**feedback), execution_id=execution_id),
# toolkit.py:377
async def coder_record_review(self, feature: str, worktree: str, review: Dict[str, Any], execution_id: str) -> CoderResult
#   line 391: self._engine.record_review(feature, worktree, CoderReview(**review), execution_id=execution_id),
# toolkit.py:186 — _create_tool_from_method sets tool.args_schema = self.arg_models[name]
# toolkit.py:97-98 — arg_models: "coder_record_feedback": CoderRecordFeedbackArgs, "coder_record_review": CoderRecordReviewArgs
# sdd_coder/models.py:739/745 — CoderRecordFeedbackArgs(CoderPlanArgs).feedback: CoderFeedback; CoderRecordReviewArgs.review: CoderReview
# CoderReview fields: task_id, attempt_uid, backend, model, fix_commits, review_evidence, execution_id
#   model_config = {'extra': 'forbid', 'str_strip_whitespace': True}
# test_feedback.py:22 — def feedback(**overrides) -> CoderFeedback  (valid feedback factory)
# test_feedback.py:273 — test_feedback_tool_validates_source_through_mcp_adapter(three_seat_roster)
#   pattern: tool = next(t for t in toolkit.get_tools() if t.name == "coder_record_feedback")
#            result = await MCPToolAdapter(tool).execute({...})  -> dict with "isError"
# conftest.py:195 — fixture three_seat_roster() -> RosterConfig
```

### Does NOT Exist
- ~~`CoderReview.from_dict`~~ / ~~`CoderFeedback.parse`~~ — use Pydantic v2 `model_validate`.
- ~~`SddCoderToolkit.engine`~~ — the attribute is `self._engine`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_record_feedback"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `toolkit.py` line 373 and 391 — swap `**` unpacking for `model_validate`, because the
   validated argument is already a model through MCP but a dict when called directly, and
   `model_validate` accepts both.
2. Append the regression tests to `test_feedback.py`.
3. Run the Validation Commands.

### `toolkit.py` (MODIFY)
```python
# REPLACE `CoderFeedback(**feedback)` (occurrences: 1, verified: toolkit.py:373)
            self._engine.record_feedback(
                feature, worktree, CoderFeedback.model_validate(feedback), execution_id=execution_id
            ),
# REPLACE `CoderReview(**review)` (occurrences: 1, verified: toolkit.py:391)
            self._engine.record_review(feature, worktree, CoderReview.model_validate(review), execution_id=execution_id),
```
**Why**: `AbstractTool._shallow_dump` intentionally keeps nested models; the toolkit must not assume
a mapping.

### `test_feedback.py` (MODIFY — append at end of file)
```python
@pytest.mark.parametrize("tool_name", ["coder_record_review", "coder_record_feedback"])
async def test_record_tools_accept_validated_model_through_mcp_adapter(
    three_seat_roster: RosterConfig, tool_name: str
) -> None:
    """issue:3b913ffd77cd — the MCP adapter hands the method a model instance, not a mapping."""
    from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
    from parrot.mcp.adapter import MCPToolAdapter

    toolkit = SddCoderToolkit(roster=three_seat_roster)
    # FILL IN: replace toolkit._engine.record_review / record_feedback with AsyncMock(return_value={})
    # FILL IN: build the payload — review: valid CoderReview dict (task_id "TASK-0001", 8+ char attempt_uid,
    #          backend, model, fix_commits=[], review_evidence); feedback: feedback().model_dump();
    #          execution_id must be a valid UUID string (arg models validate it)
    # FILL IN: result = await MCPToolAdapter(tool).execute({...}); assert result["isError"] is False
    # FILL IN: assert the mock was awaited once and its 3rd positional arg is a CoderReview / CoderFeedback


async def test_record_tools_still_accept_plain_dicts(three_seat_roster: RosterConfig) -> None:
    """Direct calls with a mapping keep working."""
    # FILL IN: same AsyncMock setup; call toolkit.coder_record_review(...) and coder_record_feedback(...)
    #          directly with dict payloads; assert the engine mocks received model instances
```
**Why**: covers AC1–AC3; mocking the engine keeps the test about argument plumbing only.

### FILL IN checklist
- [ ] engine mocks installed on `toolkit._engine`
- [ ] valid payloads (UUID execution_id, valid CoderReview/CoderFeedback)
- [ ] adapter test asserts no error and model-instance argument
- [ ] direct-dict test

---

## Acceptance Criteria

- [ ] AC1: `coder_record_review` via `MCPToolAdapter` reaches `record_review` with a `CoderReview`.
- [ ] AC2: `coder_record_feedback` via `MCPToolAdapter` reaches `record_feedback` with a `CoderFeedback`.
- [ ] AC3: direct calls with plain dicts still work.
- [ ] Existing tests in `test_toolkit.py` and `test_feedback.py` stay green.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`

---

## Test Specification

See blueprint: parametrized MCP-adapter test for both tools + direct-dict test.

## Agent Instructions

Touch only the two files listed. Run with `PYTHONPATH=packages/ai-parrot/src` inside the worktree.

## Completion Note

Done 2026-11-05 (commit a703edeb43). `CoderReview(**review)` / `CoderFeedback(**feedback)` →
`model_validate(...)` in `toolkit.py`. Two regression tests in `test_feedback.py`: both tools through
`MCPToolAdapter` (parametrized) and direct dict calls. Mutation-checked: against the old toolkit the
adapter tests fail with the exact ledger error (`argument after ** must be a mapping`).
Validation: test_feedback.py + test_toolkit.py → 65 passed; ruff/black clean.

Superseded at merge time (2026-11-05): dev already carried the same fix in 2f6ffb810a with
equivalent tests, so the FEAT-812 merge of origin/dev took dev's toolkit.py/test_feedback.py and
this task leaves no diff against dev.
