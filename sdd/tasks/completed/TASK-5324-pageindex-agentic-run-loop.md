# TASK-5324: `AgenticRetriever.run` — wrapped tools, supervised provider loop, deadline, repair, bundle

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5323
**Assigned-to**: unassigned

---

## Context

Spec §2 "Bounds (M3)", "Exact character budget", "Deadline (M3/M4)", "Prompting", "Provider
support"; §3 Module 3; AC-2, AC-9..AC-11, AC-17..AC-19. This is the stage-2 engine: it wraps
the four snapshot read tools with the ledger, registers them on the dedicated client, runs
`client.ask(..., tools=..., use_tools=True)` as an owned task under one deadline and the
call-cap stop event, parses/repairs the answer, validates citations and builds the bundle.

---

## Scope

- Add to `AgenticRetriever` (in `agentic.py`): `__init__(*, client, model, read_tools, load_revision)`,
  `async run(*, tree_name, query, candidates, outline, generation, budget_chars, max_reads,
  max_tool_calls, deadline, draft_answer) -> EvidenceBundle`, and `_wrap(tool, ledger, controller, read_lock)`.
- `_wrap`: returns a `ToolkitTool` with the same `name`, `description`, `args_schema`. On call:
  `admit()` — if refused, wait on cancellation (`await asyncio.Event().wait()`) without reading;
  for `read_pages`/`read_segments`: under `read_lock` → `ledger.charge(kwargs.get("max_chars", 12000))`
  (catch `BudgetExhausted` → return `BUDGET_MESSAGE`, mark `budget_hit`) → call the tool with
  `max_chars=max(grant, 500)` → `ReadResult.model_validate` → `clip_read_result(result, grant)` →
  `ledger.record` → return `clipped.model_dump()`; metadata tools (`list_documents`, `outline`)
  run without charging. Always `controller.done()` in `finally`.
- `run`: `clear_tools()` on the clone's manager + `register_tools(wrapped)`; build prompt
  (query + `frame_text` of candidates and outline + read-first instruction; `draft_answer=False`
  asks for citations only); owned `asyncio.Task` for `client.ask(prompt=..., system_prompt=SYSTEM_PROMPT,
  tools=None, use_tools=True, model=self._model)`; race it against `controller.stop.wait()` and the
  remaining deadline (`deadline - loop.time()`); on stop/deadline cancel + await the provider task.
- Precedence: timeout > max_tool_calls > parse_error > budget > no_tool_calls > answered.
  On timeout / call cap: no answer, no citations, no repair; reads = ledger.
- Parse: `parse_answer(output)`; on `None`, one repair `client.ask(prompt=frame_text(output, source="model-output"),
  system_prompt=DATA_FRAMING_INSTRUCTION + <extract-JSON instruction>, structured_output=AgenticAnswer,
  use_tools=False)` bounded by the remaining deadline; still `None` → `stopped="parse_error"`.
- Validation: preload each distinct `(doc_id, revision)` from the proposed citations with
  `asyncio.to_thread(self._load_revision, doc_id, rev)` under the deadline, then call
  `validate_citations` with an in-memory dict lookup.
- Bundle: `grounded = bool(kept)`, `usage` from `AIMessage.usage.model_dump()` (ints only; `{}` if absent),
  `tool_calls = controller.admitted`, `chars_read = ledger.chars_read`, `rendered_citations`.
- External cancellation of `run` itself propagates after cancelling/awaiting the owned task (re-raise).
- Before returning, `clear_tools()` the clone's manager so no read can be recorded after return.
- Tests (append to `test_agentic_retrieval.py`) with a `ScriptedToolLoopClient`.

**NOT in scope**: clone-lock, pinning, stage-1 search, toolkit kwargs (TASK-5325).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | MODIFY | `__init__`, `run`, `_wrap` on `AgenticRetriever` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | MODIFY | Loop tests + scripted client |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractTool, ToolkitTool        # tools/toolkit.py:37 (ToolkitTool); AbstractTool via tools/abstract.py:283
from parrot.knowledge.pageindex.read_ledger import BudgetExhausted, ReadLedger      # TASK-5320
from parrot.knowledge.pageindex.citations import render_citations, validate_citations   # TASK-5322
from parrot.knowledge.pageindex.segments import DocumentRevision, ReadResult         # segments.py:59, :110
from parrot.models.responses import AIMessage                                        # models/responses.py:94; usage :144 (CompletionUsage, pydantic), tool_calls :158
# already in agentic.py from TASK-5323: AbstractClient, frame_text, DATA_FRAMING_INSTRUCTION, clip_read_result, _ToolCallController, ...
```
Verify `from parrot.tools.toolkit import AbstractTool` resolves before using it (grep `AbstractTool` imports at the top of `tools/toolkit.py`); if not, import it from `parrot.tools.abstract`.

### Existing Signatures to Use
```python
# clients/base.py
async def ask(self, prompt, model=None, ..., system_prompt=None, history=None, structured_output=None,
              tools=None, use_tools=None, ...) -> AIMessage                                       # :1944 (abstract)
tool_manager.clear_tools() -> None                                                                 # tools/manager.py:1444
tool_manager.register_tools(tools: list[AbstractTool]) -> None                                     # tools/manager.py:1072
tool_manager.execute_tool(tool_name, parameters, permission_context=None, *, return_tool_result=False)  # :1799 (scripted client uses it)
tool_manager.list_tools() -> list[str]                                                             # :1415

# tools/toolkit.py
ToolkitTool(name, bound_method, description=None, args_schema=None, **kwargs)                      # :42
tool.name, tool.description, tool.args_schema                                                      # abstract.py:298-300
# Wrapped tools from TASK-5321 are ToolkitTool instances; call the underlying coroutine through
# `await tool.bound_method(**kwargs)` (NOT tool.execute — it wraps results in ToolResult).
```

### Does NOT Exist
- ~~a turn cap argument on `ask()`~~ — bound via the controller + deadline.
- ~~`AbstractClient.cancel()`~~ — cancel the owned `asyncio.Task`.
- ~~`ReadLedger.charge` inside `_read`~~ — charging happens only in the wrapper.
- ~~raising `BudgetExhausted` to stop the provider loop~~ — providers swallow tool exceptions; it is caught in the wrapper.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.ask",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.clear_tools",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

- `max(grant, 500)` then clip: `_read` floors `max_chars` at 500 (toolkit.py:782), so request
  at least 500 and cut to the grant — because only clipped ranges may reach the model/ledger (AC-18).
- Hold `read_lock` across charge→read→clip→record so parallel dispatch cannot overspend.
- `no_tool_calls`: provider returned normally and `controller.admitted == 0` → `grounded=False`
  (spec Provider support). Keep the answer/citations validation anyway (they will all be `revision_unread`).
- `budget`: set when any wrapper returned `BUDGET_MESSAGE` and the answer parsed normally.
- Deadline is a `loop.time()` float computed by the caller (TASK-5325); never restart it.
- Scripted client: subclass `AbstractClient`, implement abstract methods minimally, `ask()` iterates
  scripted `(tool_name, kwargs)` through `self.tool_manager.execute_tool`, catching `Exception`
  like a provider; returns `AIMessage(...)` with scripted output/usage. A variant loops forever;
  a variant dispatches with `asyncio.gather` (parallel); a slow variant sleeps.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports; add `__init__`, `_wrap`, `run` to `AgenticRetriever`.
2. Fill the supervisor, precedence and repair.
3. Add the scripted client + tests; run.

### `agentic.py` (MODIFY)
```python
# AFTER `    """Runs the bounded stage-2 loop on a dedicated client (run/_wrap added by TASK-5324)."""`
# occurrences: 1 (verified after TASK-5323: grep -cF 'run/_wrap added by TASK-5324' agentic.py) — replace that docstring with:
    """Runs the bounded stage-2 loop on a dedicated client holding only ledger-wrapped read tools."""

    _READ_TOOLS = ("read_pages", "read_segments")

    def __init__(self, *, client: AbstractClient, model: Optional[str], read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None:
        self._client = client
        self._model = model
        self._read_tools = list(read_tools)
        self._load_revision = load_revision
        self.logger = logging.getLogger(__name__)

    def _wrap(self, tool: AbstractTool, ledger: ReadLedger, controller: _ToolCallController,
              read_lock: asyncio.Lock, flags: dict[str, bool]) -> AbstractTool:
        """Admit a counted call, then serialize charge/read/clip/record for segment reads.

        Return BUDGET_MESSAGE for read-budget refusal. Signal the supervisor when the last
        admitted call finishes; do not raise BudgetExhausted to terminate the provider loop."""
        is_read = tool.name.endswith(self._READ_TOOLS)
        inner = tool.bound_method

        async def call(**kwargs: Any) -> Any:
            if not await controller.admit():
                await asyncio.Event().wait()          # refused: never read, wait to be cancelled
            try:
                if not is_read:
                    return await inner(**kwargs)
                async with read_lock:
                    # FILL IN: charge (BudgetExhausted -> flags["budget"]=True; return BUDGET_MESSAGE),
                    #          kwargs["max_chars"]=max(grant,500); raw=await inner(**kwargs);
                    #          clipped=clip_read_result(ReadResult.model_validate(raw), grant); ledger.record(clipped);
                    #          return clipped.model_dump() — AC-2, AC-18
                    raise NotImplementedError
            finally:
                await controller.done()

        return ToolkitTool(name=tool.name, bound_method=call, description=tool.description,
                           args_schema=tool.args_schema)

    async def run(self, *, tree_name: str, query: str, candidates: list[dict[str, Any]],
                  outline: dict[str, Any], generation: Optional[int], budget_chars: int, max_reads: int,
                  max_tool_calls: int, deadline: float, draft_answer: bool) -> EvidenceBundle:
        """Stage 2 (see spec §2). Never raises for budget, timeout or parse failures; external cancellation propagates."""
        # FILL IN: ledger/controller/lock/flags; wrap; clear_tools + register_tools on self._client.tool_manager;
        #          prompt; owned task; race (task, stop.wait task, remaining deadline) with asyncio.wait;
        #          cancel+await losers in finally; precedence; parse/repair within remaining time;
        #          preload revisions via to_thread under deadline; validate; clear_tools; build EvidenceBundle — AC-9..AC-11, AC-17, AC-19
        raise NotImplementedError
```
**Why**: the extra `flags` parameter (beyond the spec skeleton) carries the "budget refusal
happened" signal from the wrappers to `run` for `stopped="budget"`; it is request-local.
Split `run` into private helpers (`_build_prompt`, `_supervise`, `_repair`, `_validate`) if it
exceeds ~60 lines.

### `test_agentic_retrieval.py` (MODIFY — append)
```python
# FILL IN: ScriptedToolLoopClient (+ forever, parallel, slow variants) per Implementation Notes
# FILL IN: test_wrapped_reads_record_and_refuse_after_budget -> stopped="budget" — AC-2
# FILL IN: test_budget_100_clips_below_500_floor (initial 100 and 100-remaining) — AC-18
# FILL IN: test_call_cap_cancels_forever_loop: stopped="max_tool_calls", admitted == cap, no repair, task done,
#          no ledger writes after return; parallel variant never exceeds cap — AC-17
# FILL IN: test_timeout_slow_client: stopped="timeout", partial reads, no exception — AC-11
# FILL IN: test_stalled_repair_times_out: no answer/citations, repair cancelled — AC-19
# FILL IN: test_parse_failure_repair_success / parse_error
# FILL IN: test_all_citations_invalid_grounded_false (answer kept) — AC-10
# FILL IN: test_no_tool_calls — AC-11; test_draft_answer_false
# FILL IN: test_external_cancellation_propagates_after_cleanup — AC-17
```

### FILL IN checklist
- [ ] wrapper read path
- [ ] `run` (+ helpers)
- [ ] scripted clients and tests

---

## Acceptance Criteria

- [ ] AC-2, AC-10, AC-11, AC-17, AC-18 (budget part), AC-19 at the retriever level.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`

---

## Test Specification

Spec §4 Test Data: provider-like forever loop, parallel dispatch, stalled repair, 100-char budget.

---

## Agent Instructions

1. Re-verify anchors in `agentic.py` (written by TASK-5323).
2. `ruff check --fix`; run validation with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit: `feat(pageindex-agentic-retrieval): TASK-5324 — bounded agentic run loop`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 449s. Merged (lint 3e0e4b215b, 1 residual style finding left for /sdd-done).

Validation: direct run of agentic_retrieval/citations/read_ledger/read_tools/toolkit/agentic_snapshot tests → 111 passed at HEAD ea45ed6c37.
