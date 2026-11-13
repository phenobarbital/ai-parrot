# TASK-5673: Single memory lifecycle in ask, stream and invoke

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5672, TASK-5654, TASK-5670
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes AgentMemoryMixin and shared brain-contract tests from TASK-5672; Consumes bind_memory_scope/reset_memory_scope from TASK-5654; Consumes single prepare_context/record_event path from TASK-5670

## Context

Implement the bounded A1 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

**FEAT-886 merged — satisfied (spec rev 0.5).** PR #2121 (durable conversation memory) was merged into `dev`
as `bfdbe3fd84`; it rewrote every BaseBot and PandasAgent site this task edits. The anchors below are verified
there. Follow spec §2 "FEAT-886 integration contract" F1–F4, F6 and F9.

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- BasicAgent cooperative MRO and accepted constructor flags (`packages/ai-parrot/src/parrot/bots/agent.py`).
- One preparation/finalization in every public invocation path (`packages/ai-parrot/src/parrot/bots/base.py`).
- The same single preparation/finalization in `PandasAgent.ask`, a full override that never reaches `BaseBot.ask` (`packages/ai-parrot/src/parrot/bots/data.py`; spec F1).
- Real BaseBot ask/stream/invoke and PandasAgent.ask with stub client (`packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py`).
- Complete real Agent tenant/stream boundary coverage (`packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | BasicAgent cooperative MRO and accepted constructor flags |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | One preparation/finalization in every public invocation path |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | The same single preparation/finalization in PandasAgent.ask (spec F1) |
| `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` | CREATE | Real BaseBot ask/stream/invoke and PandasAgent.ask with stub client |
| `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` | MODIFY | Complete real Agent tenant/stream boundary coverage |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.bots.abstract import AbstractBot
from parrot.bots.agent import BasicAgent
from parrot.bots.base import BaseBot
from parrot.memory.agent_memory import AgentMemoryMixin
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.agent_memory.runtime import bind_memory_scope, reset_memory_scope, bind_memory_exposure, reset_memory_exposure
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/bots/agent.py:40`: `class BasicAgent(Chatbot, NotificationMixin):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/bots/base.py:130`: `class BaseBot(AbstractBot):` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` is created by TASK-5672; anchor `def test_lazy_missing_brain_and_public_service() -> None:` is planned, not an existing verified symbol.
- `packages/ai-parrot/src/parrot/bots/abstract.py`: 216:class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):
- `packages/ai-parrot/src/parrot/bots/base.py`: 130:class BaseBot(AbstractBot):
- `packages/ai-parrot/src/parrot/bots/agent.py`: 40:class BasicAgent(Chatbot, NotificationMixin):
- `packages/ai-parrot/src/parrot/bots/abstract.py:1724` — `AbstractBot.configure`: `async def configure(self, app=None) -> None:`
- `packages/ai-parrot/src/parrot/bots/abstract.py:6011` — `AbstractBot.cleanup`: `async def cleanup(self) -> None:`
- `packages/ai-parrot/src/parrot/bots/agent.py:86` — `BasicAgent.__init__`: `def __init__(self, name: str='Agent', agent_id: str='agent', use_llm: str='google', llm: str=None, tools: List[AbstractTool]=None, system_prompt: str=None, human_prompt: str=None, use_tools: bool=True, instructions: Optional[str]=None, dataframes: Optional[Dict[str, pd.DataFrame]]=None, **kwargs):`
- `packages/ai-parrot/src/parrot/bots/agent.py:179` — `BasicAgent.configure`: `async def configure(self, app=None) -> None:`
- `packages/ai-parrot/src/parrot/bots/base.py:237` — `BaseBot.conversation`: `async def conversation(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, return_context: bool=False, memory: Optional[Callable]=None, ensemble_config: dict=None, mode: str='adaptive', ctx: Optional[RequestContext]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, system_prompt: Optional[str]=None, use_tools: Optional[bool]=None, trace_context=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:726` — `BaseBot.invoke`: `async def invoke(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Callable]=None, ctx: Optional[RequestContext]=None, response_model: Optional[Type[BaseModel]]=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:1123` — `BaseBot.ask`: `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, a2ui_surface_state: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, system_prompt: Optional[str]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, use_tools: bool=True, trace_context=None, tenant: Optional[str]=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:1927` — `BaseBot.ask_stream`: `async def ask_stream(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, output_mode: OutputMode=OutputMode.DEFAULT, system_prompt: Optional[str]=None, use_tools: bool=True, trace_context=None, tenant: Optional[str]=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]:`
- `packages/ai-parrot/src/parrot/bots/data.py:415`: `class PandasAgent(IntentRouterMixin, BasicAgent):` (exact-line occurrence count 1 on `dev` `bfdbe3fd84`).
- `packages/ai-parrot/src/parrot/bots/data.py:1362` — `PandasAgent.ask` (`    async def ask(`, exact-line occurrence count 1): calls `self._on_pre_ask(` at :1512 and schedules `self._on_post_ask(` at :2282; `PandasAgent.invoke` (:1008) delegates to `self.ask`.

All line numbers in this section are verified on `dev` `bfdbe3fd84` (after PR #2121); also `_on_pre_ask` base.py:933 and `_on_post_ask` :951.

**FEAT-886 symbols this task attaches to** (on `dev` since `bfdbe3fd84`):
- `packages/ai-parrot/src/parrot/bots/abstract.py:2796` — `AbstractBot._persist_finalized_turn(self, response, *, question, user_id, session_id, turn_id, use_history, context_used=None, compaction=None, output_mode=None, started=None, assistant_text=None)`: the single finalize-then-persist step, called after the output pipeline at base.py:666 (`conversation`), :899 (`invoke`), :1780 (`ask`) and data.py:2264 (`PandasAgent.ask`).
- `packages/ai-parrot/src/parrot/bots/abstract.py:3392` — `AbstractBot._stored_turn_text(self, response, plain, method="persist") -> Optional[str]`: the stored text with the OUTPUT guardrail verdict applied.
- `packages/ai-parrot/src/parrot/bots/base.py:385,771,1230,1997` — each entry point reads `turn_id = kwargs.pop("turn_id", None) or str(uuid.uuid4())`.
- `packages/ai-parrot/src/parrot/bots/base.py:2188` — `ask_stream`'s nested `_save_stream_turn(error_text, commit=None)`; `except (asyncio.CancelledError, GeneratorExit):` at :2283 saves the partial turn with `error="stream cancelled by the caller"`.
- `packages/ai-parrot/src/parrot/memory/abstract.py:121` — `ConversationTurn.error: Optional[str] = None`.

### Does NOT Exist

- `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/data.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.cleanup",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.conversation",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.invoke",
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent",
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent.ask"
  ]
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/bots/agent.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class BasicAgent(Chatbot, NotificationMixin):' packages/ai-parrot/src/parrot/bots/agent.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/bots/agent.py:40: class BasicAgent(Chatbot, NotificationMixin):
from parrot.memory.agent_memory import AgentMemoryMixin

# Replace only the inheritance header; preserve the entire existing BasicAgent body.
class BasicAgent(AgentMemoryMixin, Chatbot, NotificationMixin):
    # FILL IN: pass accepted flags/config through cooperative construction — AC04/AC07.
    # Preserve existing skills, task-memory startup and configure_skipped handling.
    ...
```

**Why:** All public invocation paths need the same scope and finalization boundary; a cancelled stream can save history without inventing memory success.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class BaseBot(AbstractBot):' packages/ai-parrot/src/parrot/bots/base.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/bots/base.py:130: class BaseBot(AbstractBot):
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.agent_memory.runtime import (
    bind_memory_scope, reset_memory_scope, bind_memory_exposure, reset_memory_exposure,
)

# Modify invoke, ask and ask_stream inside BaseBot; do not add a second lifecycle to conversation.
# FILL IN: derive trusted scope before anonymous fallback; bind tokens/reset in finally — AC05.
# Spec F6: scope.agent_id = self.name (the existing episodic and ChatStorage key), never memory_key_id.
# Clear inherited runtime exposure at invocation entry; restore it on exit even on cancellation.
# Replace two persistent-memory preparations with one prepare_memory call — AC03.
# Finalize one response event on completed output; cancellation keeps history but earns no success — AC09.
# Preserve generic non-memory hooks, FEAT-886 hydration/raw-turn publication and partial-stream saves.
# FILL IN (spec F2): call complete_memory() beside self._persist_finalized_turn(...), after the output pipeline;
#   the response event text is the assistant_text passed there (await self._stored_turn_text(response, plain)),
#   never response.content/output. On ask_stream the event text is the streamed text that _save_stream_turn stores.
# FILL IN (spec F3): scope.turn_id is the turn_id the entry point persists (kwargs.pop("turn_id") or the one minted);
#   the response event_id derives deterministically from (agent_id, user_id, session_id, turn_id).
# FILL IN (spec F4): no response event when the persisted turn carries `error` (CancelledError, GeneratorExit, stream error).
```

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class PandasAgent(IntentRouterMixin, BasicAgent):' packages/ai-parrot/src/parrot/bots/data.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/bots/data.py:415: class PandasAgent(IntentRouterMixin, BasicAgent):
# PandasAgent.ask (`    async def ask(`, occurrences: 1) is a full override: it calls _on_pre_ask/_on_post_ask itself
# and never reaches BaseBot.ask, so the BaseBot change alone leaves it without the new lifecycle (spec F1).
# FILL IN: one prepare_memory call and one complete_memory call, sharing BaseBot's scope binding/reset — AC03/AC05.
# FILL IN: finalize beside its self._persist_finalized_turn(...) call, using its post-processed answer_text (F2/F3).
# PandasAgent.invoke delegates to self.ask: do not add a second lifecycle there.
# M3 exposure for PandasAgent is out of scope (spec F1): without a delivered-exposure manifest it earns no review.
```

**Why:** All public invocation paths need the same scope and finalization boundary; a cancelled stream can save history without inventing memory success.

### `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` (CREATE)

```python
"""Behavioral acceptance tests for Single memory lifecycle in ask, stream and invoke."""
import pytest

def test_ask_stream_invoke_single_owner() -> None:
    """Verify ask stream invoke single owner."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_cancelled_stream_preserves_history_only() -> None:
    """Verify cancelled stream preserves history only."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_direct_conversation_boundary_and_generic_hooks() -> None:
    """Verify direct conversation boundary and generic hooks."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_pandas_agent_single_lifecycle() -> None:
    """Verify PandasAgent.ask prepares and finalizes once and invoke adds no second lifecycle."""
    # FILL IN: real PandasAgent with stub client; event text equals the stored turn text (spec F1/F2).
    raise NotImplementedError

def test_event_identity_and_partial_turns() -> None:
    """Verify the response event follows the persisted turn_id and partial turns earn nothing."""
    # FILL IN: caller-supplied turn_id reused on retry; GeneratorExit (consumer closes the generator),
    # CancelledError and a stream error save history with `error` set and produce no memory event (spec F3/F4).
    raise NotImplementedError
```

**Why:** All public invocation paths need the same scope and finalization boundary; a cancelled stream can save history without inventing memory success.

### `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py from TASK-5672.
# Expected unique anchor: def test_lazy_missing_brain_and_public_service() -> None:
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC03: real BaseBot calls prepare/finalize once across ask/ask_stream/invoke; direct conversation behavior is documented and does not recursively repeat the lifecycle.
# FILL IN: AC05: transport-resolved identity is preserved before anonymous defaults; nested/concurrent requests and tool-manager clones remain isolated.
# FILL IN: AC09/AC15: cancelled/incomplete streams produce no successful review or profile extraction; history still obeys FEAT-886 and brain search/record tenant matches on ask and stream.
```

**Why:** All public invocation paths need the same scope and finalization boundary; a cancelled stream can save history without inventing memory success.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/bots/agent.py` — BasicAgent cooperative MRO and accepted constructor flags; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/bots/base.py` — One preparation/finalization in every public invocation path; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/bots/data.py` — The same single preparation/finalization in PandasAgent.ask; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` — Real BaseBot ask/stream/invoke and PandasAgent.ask with stub client; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` — Complete real Agent tenant/stream boundary coverage; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC03: real BaseBot calls prepare/finalize once across ask/ask_stream/invoke; direct conversation behavior is documented and does not recursively repeat the lifecycle.
- [ ] AC05: transport-resolved identity is preserved before anonymous defaults; nested/concurrent requests and tool-manager clones remain isolated. The scope's agent_id is the agent name even when memory_key_id differs (spec F6).
- [ ] AC09/AC15: cancelled/incomplete streams produce no successful review or profile extraction; history still obeys FEAT-886 and brain search/record tenant matches on ask and stream.
- [ ] AC03 (F1/F2): PandasAgent.ask prepares and finalizes exactly once, and its invoke adds no second lifecycle. On every entry point finalization runs beside `_persist_finalized_turn`, and the response event text equals the stored turn text.
- [ ] AC09 (F3/F4): the response event derives from the persisted turn_id (a retried caller-supplied turn_id is the same event); a turn saved with `error` (CancelledError, GeneratorExit, stream error) produces no memory event.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py -q`

## Test Specification

- `ask_stream_invoke_single_owner`: AC03: real BaseBot calls prepare/finalize once across ask/ask_stream/invoke; direct conversation behavior is documented and does not recursively repeat the lifecycle.
- `cancelled_stream_preserves_history_only`: AC05: transport-resolved identity is preserved before anonymous defaults; nested/concurrent requests and tool-manager clones remain isolated. The scope's agent_id is the agent name even when memory_key_id differs (spec F6).
- `direct_conversation_boundary_and_generic_hooks`: AC09/AC15: cancelled/incomplete streams produce no successful review or profile extraction; history still obeys FEAT-886 and brain search/record tenant matches on ask and stream.
- `pandas_agent_single_lifecycle`: AC03 (F1/F2): PandasAgent.ask prepares and finalizes exactly once, and its invoke adds no second lifecycle. On every entry point finalization runs beside `_persist_finalized_turn`, and the response event text equals the stored turn text.
- `event_identity_and_partial_turns`: AC09 (F3/F4): the response event derives from the persisted turn_id (a retried caller-supplied turn_id is the same event); a turn saved with `error` (CancelledError, GeneratorExit, stream error) produces no memory event.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
