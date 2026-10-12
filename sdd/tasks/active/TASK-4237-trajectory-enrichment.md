# TASK-4237: Trajectory enrichment — carry usage, tool calls, model and metadata from AIMessage into Trajectory

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `SingleTurnRollout.run` and `ConversationalRollout.run` keep only the
response text and the latency (`eval/rollout.py:220-247`, `:315-355`). `AIMessage.usage`,
`.tool_calls`, `.model` and `.metadata` never reach the `Trajectory`, so nothing downstream
(groundedness, token accounting, guardrail-flag analysis) can work from a persisted run.
This task adds two additive fields to `Trajectory` and three `getattr`-tolerant extraction
helpers used by both rollouts. Mock bots that return a bare `type("M", (), {"content": ...})`
(every existing test) must keep working with defaults.

---

## Scope

- Add `model: str | None = None` and `response_metadata: dict[str, Any]` to `Trajectory`.
- Add `_usage_from_response`, `_tool_calls_from_response`, `_metadata_from_response` to
  `eval/rollout.py` next to `_extract_text`.
- `SingleTurnRollout.run`: populate `tokens`, agent `TurnRecord.tool_calls`, `model`,
  `response_metadata`.
- `ConversationalRollout.run`: per-agent-turn `tool_calls`; `tokens` accumulated over turns;
  `model` / `response_metadata` from the last agent turn (also on the error path).
- Tests appended to `tests/eval/test_rollout.py`.

**NOT in scope**: `cost_usd` (needs `CostCalculator`, spec Non-Goal); any metric; changes to
`EvalRunner`; exports in `eval/__init__.py` (TASK-4243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/models.py` | MODIFY | two additive `Trajectory` fields |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | helpers + both rollouts populate the new data |
| `packages/ai-parrot/tests/eval/test_rollout.py` | MODIFY | three new tests appended |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.models import EvalTask, TokenUsage, ToolCallRecord, Trajectory, TurnRecord  # verified: eval/models.py:18,82,46,96,64
from parrot.eval.sandbox.base import Sandbox, NoopSandbox                                  # verified: eval/sandbox/base.py; NoopSandbox :209
from parrot.eval import ConversationalRollout, SingleTurnRollout                           # verified: eval/__init__.py:68-74
from parrot.models.basic import CompletionUsage, ToolCall                                  # verified: models/basic.py:48,23 (tests only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/models.py
class ToolCallRecord(BaseModel):   # line 46: name: str; arguments: dict; result: Any | None; error: str | None; latency_ms: float | None
class TurnRecord(BaseModel):       # line 64: role: Literal[...]; content: str | None; tool_calls: list[ToolCallRecord]; timestamp: float
class TokenUsage(BaseModel):       # line 82: prompt: int = 0; completion: int = 0; total: int = 0
class Trajectory(BaseModel):       # line 96: model_config = ConfigDict(extra="allow"); ...; trace_context: dict[str, str] | None = None  # line 128 (last field)

# packages/ai-parrot/src/parrot/eval/rollout.py
class SingleTurnRollout(RolloutStrategy):     # line 190
    async def run(self, bot, task, sandbox) -> Trajectory:   # body: `response = await bot.ask(question)` :220; `return Trajectory(` :229; `final_output=text,` :233
class ConversationalRollout(RolloutStrategy): # line 252
    async def run(...)                                        # `response = await bot.conversation(` :315; agent TurnRecord built :325-331; `final_output=final_output,` :352
def _extract_question(task: EvalTask) -> str:        # line 362
def _extract_text(response: Any) -> str | None:      # line 384 — reads .content / .response / .text

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):         # line 23: id, name, arguments: Dict[str, Any], result, error, execution_time: Optional[float] (seconds)
class CompletionUsage(BaseModel):  # line 48: prompt_tokens :76, completion_tokens :79, total_tokens :82

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):        # line 93: model :140, usage: CompletionUsage :143, tool_calls: List[ToolCall] :157, metadata: Dict[str, Any] :194, content property :225
```

### Does NOT Exist
- ~~`Trajectory.model`~~, ~~`Trajectory.response_metadata`~~ — this task adds them.
- ~~`ToolCallRecord.id`~~ — no id field; do not add one.
- ~~`AIMessage.response`~~, ~~`AIMessage.text`~~ — text is the `content` property.
- ~~`TokenUsage.__add__`~~ — accumulate by constructing a new `TokenUsage` with summed ints.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/eval/rollout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/eval/test_rollout.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/models.py#Trajectory",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#TurnRecord",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#ToolCallRecord",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#TokenUsage",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#SingleTurnRollout",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#ConversationalRollout",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#_extract_text",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ToolCall",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every extraction is `getattr(response, "<attr>", None)`-tolerant: existing tests pass bots whose
  response has only `content`.
- New `Trajectory` fields MUST have defaults — `EvalRunner._run_attempt` (`runner.py:239`) rebuilds
  trajectories with `model_copy(update=...)` and the Postgres sink dumps them to JSONB.
- `ToolCall.execution_time` is seconds; `ToolCallRecord.latency_ms` is milliseconds (×1000).
- `metadata` is copied with `dict(...)` so later mutation of the `AIMessage` cannot leak in.

### References in Codebase
- `packages/ai-parrot/src/parrot/eval/rollout.py:384` — `_extract_text` is the pattern for tolerant extraction.
- `packages/ai-parrot/tests/eval/test_rollout.py` — mock-bot style to keep.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two fields to `Trajectory` after `trace_context` — *why*: additive, defaulted, so `model_copy(update=...)` in the runner and all existing constructors keep working.
2. Add the three helpers below `_extract_text` — *why*: one place, reused by both rollouts, mock-safe.
3. Wire `SingleTurnRollout.run` — *why*: the single-turn path is what the Q&A benchmark (TASK-4243) uses.
4. Wire `ConversationalRollout.run`, accumulating tokens per agent turn — *why*: multi-turn cost must be the sum, not the last turn.
5. Append the tests and run the validation commands.

### `packages/ai-parrot/src/parrot/eval/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    trace_context: dict[str, str] | None = None' packages/ai-parrot/src/parrot/eval/models.py)
# AFTER — insert below `    trace_context: dict[str, str] | None = None` (verified: eval/models.py:128)
    model: str | None = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)
```
Also extend the class docstring `Attributes:` list with `model` ("Model identifier of the last
agent response, when known") and `response_metadata` ("``AIMessage.metadata`` of the last agent
response — guardrail reports, routing trace, …").
**Why**: both fields are read by TASK-4239 (`response_metadata`) and TASK-4241 (`model` for the
judge ≠ model-under-test check in detail); defaults keep every existing call site valid.

### `packages/ai-parrot/src/parrot/eval/rollout.py` (MODIFY — helpers)
```python
# occurrences: 1 (verified: grep -c 'def _extract_text(response: Any) -> str | None:' packages/ai-parrot/src/parrot/eval/rollout.py)
# BEFORE — insert above `def _extract_text(response: Any) -> str | None:` (verified: eval/rollout.py:384)
# Also extend the import block (rollout.py:24-28) to: EvalTask, TokenUsage, ToolCallRecord, Trajectory, TurnRecord
def _usage_from_response(response: Any) -> TokenUsage:
    """Map ``response.usage`` (``CompletionUsage``) to ``TokenUsage``; zeros when absent.

    Reads ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens`` tolerantly so
    mock responses without a ``usage`` attribute yield ``TokenUsage()``.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or 0) or (prompt + completion)
    return TokenUsage(prompt=prompt, completion=completion, total=total)


def _tool_calls_from_response(response: Any) -> list[ToolCallRecord]:
    """Map ``response.tool_calls`` (``list[ToolCall]``) to ``ToolCallRecord``; ``[]`` when absent.

    ``ToolCall.execution_time`` is seconds; ``ToolCallRecord.latency_ms`` is milliseconds.
    """
    records: list[ToolCallRecord] = []
    for call in getattr(response, "tool_calls", None) or []:
        exec_time = getattr(call, "execution_time", None)
        records.append(
            ToolCallRecord(
                name=str(getattr(call, "name", "")),
                arguments=dict(getattr(call, "arguments", None) or {}),
                result=getattr(call, "result", None),
                error=getattr(call, "error", None),
                latency_ms=(float(exec_time) * 1000.0) if exec_time is not None else None,
            )
        )
    return records


def _metadata_from_response(response: Any) -> tuple[str | None, dict[str, Any]]:
    """Return ``(response.model, dict(response.metadata))``; ``(None, {})`` when absent."""
    model = getattr(response, "model", None)
    metadata = getattr(response, "metadata", None)
    return (str(model) if model else None, dict(metadata) if isinstance(metadata, dict) else {})
```
**Why**: the three helpers are the only place that knows the `AIMessage` shape; keeping them
tolerant (never raising) preserves the "mock bot returns a bare object" contract of every
existing rollout test.

### `packages/ai-parrot/src/parrot/eval/rollout.py` (MODIFY — SingleTurnRollout.run)
```python
# occurrences: 1 (verified: grep -c '            response = await bot.ask(question)' packages/ai-parrot/src/parrot/eval/rollout.py)
# AFTER — insert below `            response = await bot.ask(question)` (verified: eval/rollout.py:220)
            tokens = _usage_from_response(response)
            tool_calls = _tool_calls_from_response(response)
            model, response_metadata = _metadata_from_response(response)
# Then: give the agent TurnRecord `tool_calls=tool_calls,` and the returned Trajectory
# (anchor `                final_output=text,` verified: eval/rollout.py:233, occurrences 1) these extra kwargs:
#                 tokens=tokens,
#                 model=model,
#                 response_metadata=response_metadata,
```
**Why**: extraction happens right after the call, before `_extract_text`, so an exception in
`_extract_text` still leaves the `except` path untouched (error trajectories stay minimal).

### `packages/ai-parrot/src/parrot/eval/rollout.py` (MODIFY — ConversationalRollout.run)
```python
# occurrences: 1 (verified: grep -c '                response = await bot.conversation(' packages/ai-parrot/src/parrot/eval/rollout.py)
# Before the `try:` of the loop initialise accumulators next to `final_output: Any = None` (rollout.py:293):
        tokens = TokenUsage()
        model: str | None = None
        response_metadata: dict[str, Any] = {}
# AFTER the `response = await bot.conversation(...)` call completes (anchor verified: eval/rollout.py:315):
                turn_usage = _usage_from_response(response)
                tokens = TokenUsage(
                    prompt=tokens.prompt + turn_usage.prompt,
                    completion=tokens.completion + turn_usage.completion,
                    total=tokens.total + turn_usage.total,
                )
                model, response_metadata = _metadata_from_response(response)
# Give the agent TurnRecord (rollout.py:325-331) `tool_calls=_tool_calls_from_response(response),`
# and BOTH `return Trajectory(` sites (error path :339, success path :348 — anchor `            final_output=final_output,` :352, occurrences 1)
# the kwargs `tokens=tokens, model=model, response_metadata=response_metadata`.
```
**Why**: tokens are a running sum (spec AC "ConversationalRollout accumulates tokens"); model and
metadata describe the last answer, which is what `final_output` is. The error path also carries
what was accumulated so far so a partial conversation is still accountable.

### `packages/ai-parrot/tests/eval/test_rollout.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_llm_user_simulator_returns_none_on_error():' packages/ai-parrot/tests/eval/test_rollout.py)
# APPEND at end of file (last existing test is `async def test_llm_user_simulator_returns_none_on_error():`, verified: test_rollout.py:123)
from parrot.models.basic import CompletionUsage, ToolCall


def _ai_message_like(text: str = "Revenue was $1,243,500.") -> object:
    """Minimal object with the AIMessage attributes the rollouts read."""
    return type("Msg", (), {
        "content": text,
        "model": "fake:model-under-test",
        "usage": CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        "tool_calls": [ToolCall(id="t1", name="get_revenue", arguments={"q": "Q3"},
                                result={"revenue": 1243500}, execution_time=0.02)],
        "metadata": {"guardrails": {"groundedness": {"score": 1.0}}},
    })()


async def test_single_turn_copies_usage_tool_calls_model_metadata():
    bot = AsyncMock()
    bot.ask.return_value = _ai_message_like()
    async with NoopSandbox() as sb:
        tr = await SingleTurnRollout().run(bot, EvalTask(task_id="t", inputs={"query": "q"}), sb)
    # FILL IN: assert tr.tokens.total == 15, tr.turns[0].tool_calls[0].name == "get_revenue",
    #          latency_ms == 20.0, tr.model == "fake:model-under-test", "guardrails" in tr.response_metadata — bounded by AC-1


async def test_single_turn_defaults_without_usage():
    # FILL IN: bare `type("M", (), {"content": "x"})()` response → tokens all 0, tool_calls [], model None, response_metadata {} — bounded by AC-2


async def test_conversational_accumulates_tokens():
    # FILL IN: bot.conversation returns _ai_message_like() three times; simulator yields two follow-ups then None;
    #          assert tr.tokens.total == 45 and tr.model set and every agent turn has 1 tool call — bounded by AC-3
```
**Why**: the fixture object mirrors exactly the attributes the helpers read, without importing
`AIMessage` (its constructor needs many fields and `navconfig`).

### FILL IN checklist
- [ ] `test_rollout.py::test_single_turn_copies_usage_tool_calls_model_metadata` — assertions; bounded by AC-1
- [ ] `test_rollout.py::test_single_turn_defaults_without_usage` — body; bounded by AC-2
- [ ] `test_rollout.py::test_conversational_accumulates_tokens` — simulator stub + assertions; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: an `AIMessage`-shaped response yields `tokens.total == usage.total_tokens`, agent `TurnRecord.tool_calls` mirroring `AIMessage.tool_calls` (latency in ms), `model` and `response_metadata` populated.
- [ ] AC-2: a response exposing only `content` yields `TokenUsage()` zeros, `[]`, `None`, `{}` — all pre-existing `test_rollout.py` tests still pass unchanged.
- [ ] AC-3: `ConversationalRollout` sums tokens across agent turns and carries `model`/`response_metadata` of the last turn (also on the exception path).
- [ ] `Trajectory(...)` with no new kwargs still validates; `EvalRunner` tests in `tests/eval/test_runner.py` pass.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/models.py packages/ai-parrot/src/parrot/eval/rollout.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_rollout.py -q`
- `pytest packages/ai-parrot/tests/eval/test_models.py -q`
- `pytest packages/ai-parrot/tests/eval/test_runner.py -q`

---

## Test Specification

See the blueprint block for `test_rollout.py` — three tests: full extraction, defaults, accumulation.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — before writing ANY code, `grep -c` every anchor above; a count of 0 means drift: stop and report
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the three files listed (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4237 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
