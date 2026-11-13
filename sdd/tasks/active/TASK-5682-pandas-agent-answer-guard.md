# TASK-5682: PandasAgent.ask — OUTPUT guardrail verdict on the returned answer

**Feature**: FEAT-893 — PandasAgent.ask — OUTPUT guardrails on the returned answer
**Spec**: `sdd/specs/bots-data-fixes-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3e29dbe2f16a`

---

## Context

`PandasAgent.ask` is a full override that never reaches `BaseBot.ask`, and it never runs the OUTPUT guardrail
stage. The answer it returns (`response.response`, a plain-text `output`, the `explanation` of a structured
`PandasAgentResponse`) reaches the caller unscanned, for example without `SecretsGuardrail` redaction, and
`AnswerMemory` stores the same raw text (spec §1). This task adds one private method, `_guard_answer`, and calls
it on all six return sites of `ask()`. `answer_memory` and the persisted turn then reuse the judged text.

---

## Scope

- Add `from .abstract import _OUTPUT_BLOCKED_TEXT` and
  `from .guardrails.base import GuardrailContext, GuardrailStage` to `bots/data.py`.
- Add `PandasAgent._guard_answer(response, data_response=None, method="ask") -> AIMessage` immediately before
  `async def ask(`, implementing spec §2 Overview item 1.
- Main path: call `_guard_answer` after the markdown-table repair, before `answer_memory.store_interaction`,
  then re-read `answer_text`. The persisted `assistant_text` becomes the judged text instead of a second
  `_stored_turn_text` scan. Update the stale `# PandasAgent has NO output pipeline` comment.
- The five early returns (`data.py:2033`, `:2056`, `:2069`, `:2081`, `:2096`) become
  `return await self._guard_answer(response, data_response)`.
- Create `packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py` with the spec §4 unit tests.

**NOT in scope**: persisting turns on the early-return paths (a separate ledger issue); scanning data, code,
chart, map, A2UI or HTML payloads; any change to `abstract.py`, `base.py` or `guardrails/`; the 7 pre-existing
ruff findings in `data.py` (`issue:aee666627fc7`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `_guard_answer` + six call sites + judged persisted text |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py` | CREATE | regression tests (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.data import PandasAgent, PandasAgentResponse  # verified: data.py:124, :415
from parrot.bots.guardrails.base import GuardrailContext, GuardrailStage  # verified: abstract.py:133
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail  # verified: test_finalize_persist_turn.py:231
from parrot.bots.abstract import _OUTPUT_BLOCKED_TEXT  # verified: abstract.py:237
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:20
from parrot.models.basic import CompletionUsage  # verified: test_finalize_persist_turn.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
_OUTPUT_BLOCKED_TEXT = "This response could not be delivered due to a content policy violation."  # line 237
class AbstractBot:
    self._guardrail_pipelines: Dict[GuardrailStage, GuardrailPipeline]  # line 755
    def _output_extras(self, response: AIMessage, pipeline: GuardrailPipeline) -> Dict[str, Any]  # line 3289
    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3296
        # no-op unless pipeline.has_guardrails and isinstance(response.output, str)
        # BLOCK: output = _OUTPUT_BLOCKED_TEXT; metadata["error"] = "security_block"; metadata["block_reason"]
        # TRANSFORM: output rewritten; an aliased/wrapped response.response rewritten too (_propagate_output_verdict)
    async def _stored_turn_text(self, response, plain, method="persist") -> Optional[str]  # line 3392
        # builds GuardrailContext(stage=OUTPUT, agent_name=self.name,
        #   user_id=str(response.user_id) if response.user_id is not None else None,
        #   session_id=response.session_id, method=method, extras=self._output_extras(response, pipeline))
    def _merge_guardrail_reports(self, response: AIMessage, flag_reports: Dict[str, Dict[str, Any]]) -> None  # line 3431

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class PipelineOutcome(BaseModel):  # line 62 — content: str | None; blocked: bool; reason: str | None; flag_reports
class GuardrailPipeline:
    @property
    def has_guardrails(self) -> bool  # line 135
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 151

# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgentResponse(BaseModel):  # line 124 — explanation: str (+ data, data_variable(s), code)
class PandasAgent(IntentRouterMixin, BasicAgent):  # line 415
    async def ask(self, question, session_id=None, user_id=None, use_conversation_history=True, memory=None,
                  ctx=None, structured_output=None, output_mode=None, format_kwargs=None,
                  return_structured=True, use_tools=True, **kwargs) -> AIMessage  # line 1362
        # :1676 data_response = response.output if isinstance(response.output, PandasAgentResponse) else None
        # :1996 infographic_envelope = self._extract_last_infographic_result(response.tool_calls)
        # :2059 interactive_envelope = self._extract_last_interactive_result(response.tool_calls)
        # :2070 explanation = self._finalize_interactive_response(response, interactive_envelope)
        # :2226-2237 answer_text = ...; markdown repair; response.response = answer_text
        # :2239 await self.answer_memory.store_interaction(response.turn_id, question, answer_text)
        # :2263 _stored_text = (await self._stored_turn_text(response, str(answer_text))) if answer_text else None

# packages/ai-parrot/src/parrot/memory/agent.py
class AnswerMemory:  # line 7
    async def get(self, turn_id: str) -> Optional[Dict[str, Any]]  # line 26

# packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
class _PandasClient:  # line 165 — ask() returns AIMessage(output="ok", response="ok", ...)
def _pandas(use_source: bool = True) -> PandasAgent  # line 180 — stub client, InMemoryConversation, RecordingPublisher
# packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py — exports SECRET (imported at test_finalize_persist_turn.py:23)
```

### Does NOT Exist
- ~~`_run_output_pipeline` / `_guard_answer` in `bots/data.py`~~ — added by this task.
- ~~`PandasAgent.ask_stream`~~ — not overridden; `BaseBot.ask_stream` already runs the pipeline.
- ~~a public "judge this text" helper on `AbstractBot`~~ — do not add one; `abstract.py` is out of scope.
- ~~`tests/unit/bots/test_pandasagent_output_guardrails.py`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/data.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent.ask",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._run_output_pipeline",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._output_extras",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._merge_guardrail_reports"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No OUTPUT guardrails → `_guard_answer` returns before touching anything (byte-identical answer).
- Each distinct text is judged at most once per call: a cache seeded with what `_run_output_pipeline` already
  judged.
- BLOCK on any answer text replaces `response.response`, a `str` `output` and `data_response.explanation` with
  `_OUTPUT_BLOCKED_TEXT`. Data, code and artifacts stay in place, matching `_run_output_pipeline`.
- `black` line length 120; Google-style docstrings; strict type hints; `self.logger` only.

### References in Codebase
- `bots/abstract.py:3296-3341` (`_run_output_pipeline`) and `:3392-3429` (`_stored_turn_text`): the context
  and outcome handling to mirror.
- `bots/base.py:1772-1785`: `BaseBot.ask` runs the pipeline, then persists the judged text.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two imports. *Why*: the guard needs the OUTPUT stage, the context type and the canned BLOCK notice
   `BaseBot` uses.
2. Add `_guard_answer` before `ask()`.
3. Wire the main path (guard → `store_interaction` → persistence with the judged text) and the five early
   returns.
4. Write the tests, then run `black`, `ruff check` and the Validation Commands.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from .mixins.intent_router import IntentRouterMixin' data.py)
# INSERT after line 29:
from .abstract import _OUTPUT_BLOCKED_TEXT
from .guardrails.base import GuardrailContext, GuardrailStage
```

### `data.py` (MODIFY — new method, inserted before `    async def ask(` at :1362)
```python
    async def _guard_answer(
        self,
        response: AIMessage,
        data_response: Optional[PandasAgentResponse] = None,
        method: str = "ask",
    ) -> AIMessage:
        """Give the answer ``ask()`` returns an OUTPUT guardrail verdict (FEAT-893).
        ... (spec §2 Overview item 1) ...
        """
        pipeline = self._guardrail_pipelines[GuardrailStage.OUTPUT]
        if not pipeline.has_guardrails:
            return response
        before = response.response
        response = await self._run_output_pipeline(response, method=method)
        if response.metadata.get("error") == "security_block":
            # FILL IN: apply the block to response.response and data_response.explanation; return
        judged: Dict[str, str] = {}
        if isinstance(response.output, str):
            judged[response.output] = response.output
        if isinstance(response.response, str) and response.response != before:
            judged[response.response] = response.response
        # FILL IN: one lazily built GuardrailContext; judge response.response then data_response.explanation
        # (non-empty str only, cache first); merge FLAG reports; TRANSFORM writes back; BLOCK → block every
        # text field + metadata error/block_reason, then return
        return response
```

### `data.py` (MODIFY — five early returns)
```python
# :2033 (infographic A2UI), :2056 (infographic HTML), :2069 (interactive A2UI), :2081 (interactive HTML),
# :2096 (inline A2UI):  return response  →  return await self._guard_answer(response, data_response)
```

### `data.py` (MODIFY — main path, before `                await self.answer_memory.store_interaction(` at :2239)
```python
                # FEAT-893: the answer returned, remembered and persisted carries ONE OUTPUT verdict.
                response = await self._guard_answer(response, data_response)
                answer_text = getattr(response, "response", None) or response.content
```
and at :2263:
```python
                    _stored_text = str(answer_text) if answer_text else None
```
Rewrite the comment block at :2245-2253 (it still says "PandasAgent has NO output pipeline").

### FILL IN checklist
- [ ] `_guard_answer` body, bounded by spec §2 Overview item 1.
- [ ] Tests as listed in spec §4 Unit Tests, built on `_pandas()` / `_PandasClient` / `SECRET`.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py
      packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` passes from the worktree with
      `PYTHONPATH=packages/ai-parrot/src`.
- [ ] With `SecretsGuardrail` on OUTPUT, no field of the returned `AIMessage` (`output`, `content`, `response`,
      `to_text`, structured `explanation`) contains the secret, on the main path and on an early-return path.
- [ ] `AnswerMemory` and the persisted turn hold the redacted text, and each distinct answer text is judged
      once.
- [ ] A BLOCKing OUTPUT guardrail yields the canned notice and `metadata["error"] == "security_block"`.
- [ ] With no OUTPUT guardrails the returned answer is unchanged.
- [ ] `ruff check` passes on the new test file, and `bots/data.py` gains no new ruff findings.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py -q`

---

## Test Specification

See spec §4 Unit Tests.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**, never on `base_branch`
   (`parrot sdd worktree ensure --slug bots-data-fixes-2 --feature-id FEAT-893`).
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract** before writing any code.
5. **Update status** in `sdd/tasks/index/bots-data-fixes-2.json` to `"in-progress"` (set `started_at`) and commit only that index file.
6. **Implement** from the Implementation Blueprint.
7. **Verify** all acceptance criteria by running the Validation Commands.
8. **Commit the code**, staging only the files listed above.
9. **Close the task** with `parrot sdd task close TASK-5682 bots-data-fixes-2 verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Resolves**: `issue:3e29dbe2f16a`
**Deviations from spec**:
