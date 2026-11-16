# TASK-5674: Final delivery exposure and trusted tool attribution

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5673, TASK-5669, TASK-5664, TASK-5656, TASK-5670
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes single invocation lifecycle and overlapping BaseBot from TASK-5673; Consumes whole-block delivered refs/digest from TASK-5669; Consumes cite/review from TASK-5664; Consumes accepted evidence models from TASK-5656; Consumes overlapping manager event routing from TASK-5670

## Context

Implement the bounded M3 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

G3: ACCEPTED in the spec section "Gate amendment accepted for TASK-5674" (rev 0.8), E1–E13: the `tool_runtime` adapter (E1–E5, E7), the 200-character signature comparison (E6), the verified-check schema (E8), exposure at final packing (E9), `cited`-only attribution (E10), tool-event routing (E11) and the evidence reference (E12). The blueprint's FILL IN items are superseded by that section where they disagree. Generic tool return values are still not a substitute: a normal return is `incomplete` and earns no review.

**FEAT-886 merged — satisfied (spec rev 0.5).** PR #2121 was merged into `dev` as `bfdbe3fd84`; it rewrote the
BaseBot sites this task edits. The anchors below were re-verified on the feature branch after merging `dev` `a8f4df5cf3` (merge `6123d22199`).
Exposure for `PandasAgent.ask` is out of scope (spec F1): its events carry no exposure manifest and earn no review.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Citation checks and request-local runtime tool events (`packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py`).
- Compose memory capture with existing task observer (`packages/ai-parrot/src/parrot/tools/manager.py`).
- Mint exposure at final prompt delivery and record provider outcomes (`packages/ai-parrot/src/parrot/bots/base.py`).
- Connect delivered manifests and reviews to event routing (`packages/ai-parrot/src/parrot/memory/unified/manager.py`).
- Delivered-version, recovery, guard and cancellation tests (`packages/ai-parrot/tests/memory/dynamics/test_attribution.py`).
- Compare error signatures on their first 200 normalized characters (spec E6) (`packages/ai-parrot/src/parrot/memory/dynamics/grade.py`, `packages/ai-parrot/tests/memory/dynamics/test_core.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` | CREATE | Citation checks and request-local runtime tool events |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Compose memory capture with existing task observer |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Mint exposure at final prompt delivery and record provider outcomes |
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY | Connect delivered manifests and reviews to event routing |
| `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` | CREATE | Delivered-version, recovery, guard and cancellation tests |
| `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` | MODIFY | Cut the memory's normalized signature to 200 characters before comparing (spec E6) |
| `packages/ai-parrot/tests/memory/dynamics/test_core.py` | MODIFY | Long-signature AGAIN case |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import MemoryEvent, MemoryRequestScope
from .runtime import bind_memory_exposure, reset_memory_exposure
from parrot.bots.base import BaseBot
from parrot.memory.dynamics.models import MemoryCitation, MemoryExposure
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.tools.manager import ToolManager
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/tools/manager.py:1737`: `    async def _observed(` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/bots/base.py:137`: `class BaseBot(AbstractBot):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:57`: `class UnifiedMemoryManager:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/tools/manager.py`: 292:class ToolManager(MCPToolManagerMixin):
- `packages/ai-parrot/src/parrot/bots/base.py:298` — `BaseBot.conversation`: `async def conversation(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, return_context: bool=False, memory: Optional[Callable]=None, ensemble_config: dict=None, mode: str='adaptive', ctx: Optional[RequestContext]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, system_prompt: Optional[str]=None, use_tools: Optional[bool]=None, trace_context=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:787` — `BaseBot.invoke`: `async def invoke(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Callable]=None, ctx: Optional[RequestContext]=None, response_model: Optional[Type[BaseModel]]=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:1218` — `BaseBot.ask`: `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, a2ui_surface_state: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, system_prompt: Optional[str]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, use_tools: bool=True, trace_context=None, tenant: Optional[str]=None, **kwargs) -> AIMessage:`
- `packages/ai-parrot/src/parrot/bots/base.py:2046` — `BaseBot.ask_stream`: `async def ask_stream(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, output_mode: OutputMode=OutputMode.DEFAULT, system_prompt: Optional[str]=None, use_tools: bool=True, trace_context=None, tenant: Optional[str]=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:90` — `UnifiedMemoryManager.__init__`: `def __init__(self, namespace: MemoryNamespace, conversation_memory: Optional[ConversationMemory]=None, episodic_store: Optional[EpisodicMemoryStore]=None, skill_registry: Optional[Any]=None, config: Optional[MemoryConfig]=None, cross_domain_router: Optional[CrossDomainRouter]=None, user_memory_store: UserMemoryStore | None=None, extraction_client: Any | None=None, brain_service: Any | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:118` — `UnifiedMemoryManager.configure`: `async def configure(self, **kwargs: Any) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:133` — `UnifiedMemoryManager.cleanup`: `async def cleanup(self) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:148` — `UnifiedMemoryManager.get_context_for_query`: `async def get_context_for_query(self, query: str, user_id: str, session_id: str) -> MemoryContext:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:265` — `UnifiedMemoryManager.record_interaction`: `async def record_interaction(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None:`
- `packages/ai-parrot/src/parrot/memory/dynamics/grade.py:13` — `_normalize_signature(value: str | None) -> str | None`; `:28` — `select_grade(signal: ReviewSignal, *, attribution: Attribution | None, memory_error_signature: str | None, verified_recovery: bool) -> Grade | None`.
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:305` — `EpisodicMemoryStore.cite(self, memory_ids: list[str], *, namespace: MemoryNamespace, exposure_id: str) -> MemoryCitation`; `:353` — `EpisodicMemoryStore.review(self, memory_ids: list[str], signal: ReviewSignal, *, namespace: MemoryNamespace, exposure_id: str) -> list[ReviewReceipt]` (read-only here: this task does not edit `store.py`).
- `packages/ai-parrot/src/parrot/tools/abstract.py:252` — `class ToolResult(BaseModel)` with `success: bool = True`, `status: str = "success"`, `error: Optional[str] = None`; use `model_fields_set` (spec E4), never these defaults.
- `packages/ai-parrot/src/parrot/tools/manager.py:1668` — `ToolManager.set_invocation_observer`: `def set_invocation_observer(self, observer: Optional[Any]) -> None:`
- `packages/ai-parrot/src/parrot/tools/manager.py:1737` — `ToolManager._observed`: `async def _observed(self, observation: Optional['_Observation'], tool_name: str, call: Any, *, sync: bool=False, gated: bool=False) -> Any:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_attribution.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.conversation",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.invoke",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.cleanup",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.configure",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.get_context_for_query",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_interaction",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager._observed",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.set_invocation_observer"
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

### `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` (CREATE)

```python
"""Admit only runtime-observed evidence for actually delivered memory versions."""
from parrot.memory.dynamics.models import MemoryCitation, MemoryExposure
from .models import MemoryEvent, MemoryRequestScope
from .runtime import bind_memory_exposure, reset_memory_exposure

def validate_citation(citation: MemoryCitation, exposure: MemoryExposure,
                      *, scope: MemoryRequestScope) -> MemoryCitation:
    """Reject cross-scope and non-delivered references before outcome admission."""
    # FILL IN: namespace/version/subset checks with non-leaking failures — AC11.
    raise NotImplementedError

async def record_tool_event(event: MemoryEvent) -> None:
    """Record an actual execution attempt once; review only through accepted evidence adapters."""
    # FILL IN: request-local manager/exposure binding and trusted G3 checks — AC11/AC12.
    # Transport success/default status alone is execution evidence, never domain success.
    raise NotImplementedError
```

**Why:** Observing the executed body after guards preserves FEAT-538 evidence and avoids grading calls that never ran.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- '    async def _observed(' packages/ai-parrot/src/parrot/tools/manager.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/tools/manager.py:1737:     async def _observed(
# Compose memory capture with existing task observer.
# FILL IN: AC11: bind exposure only after final packing into the model request; trimmed refs, arbitrary citations and cancelled/provider-failed responses earn no review.
# FILL IN: AC05/AC11: publish final exposure ID through runtime.bind_memory_exposure and restore it in finally; invocation entry clears inherited IDs, and durable manifests—not the ID alone—authorize citations.
# FILL IN: AC11: ToolManager._observed preserves FEAT-538 observer/guards and execution exceptions; use request-local capture, not replacement instance observer.
```

**Why:** Observing the executed body after guards preserves FEAT-538 evidence and avoids grading calls that never ran.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class BaseBot(AbstractBot):' packages/ai-parrot/src/parrot/bots/base.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/bots/base.py:137: class BaseBot(AbstractBot):
# Mint exposure at final prompt delivery and record provider outcomes.
# FILL IN: AC11: bind exposure only after final packing into the model request; trimmed refs, arbitrary citations and cancelled/provider-failed responses earn no review.
# FILL IN: AC05/AC11: publish final exposure ID through runtime.bind_memory_exposure and restore it in finally; invocation entry clears inherited IDs, and durable manifests—not the ID alone—authorize citations.
# FILL IN: AC11: ToolManager._observed preserves FEAT-538 observer/guards and execution exceptions; use request-local capture, not replacement instance observer.
```

**Why:** Observing the executed body after guards preserves FEAT-538 evidence and avoids grading calls that never ran.

### `packages/ai-parrot/src/parrot/memory/unified/manager.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class UnifiedMemoryManager:' packages/ai-parrot/src/parrot/memory/unified/manager.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/manager.py:57: class UnifiedMemoryManager:
# Connect delivered manifests and reviews to event routing.
# FILL IN: AC11: bind exposure only after final packing into the model request; trimmed refs, arbitrary citations and cancelled/provider-failed responses earn no review.
# FILL IN: AC05/AC11: publish final exposure ID through runtime.bind_memory_exposure and restore it in finally; invocation entry clears inherited IDs, and durable manifests—not the ID alone—authorize citations.
# FILL IN: AC11: ToolManager._observed preserves FEAT-538 observer/guards and execution exceptions; use request-local capture, not replacement instance observer.
```

**Why:** Observing the executed body after guards preserves FEAT-538 evidence and avoids grading calls that never ran.

### `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'def _normalize_signature(value: str | None) -> str | None:' packages/ai-parrot/src/parrot/memory/dynamics/grade.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/dynamics/grade.py:13: def _normalize_signature(value: str | None) -> str | None:
# FILL IN: spec E6 — cut the normalized memory signature to 200 characters before the AGAIN comparison; no other grade rule changes.
```

**Why:** `ReviewSignal` caps its signature at 200 characters; without the same cut on the memory side a long error message can never match.

### `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` (CREATE)

```python
"""Behavioral acceptance tests for Final delivery exposure and trusted tool attribution."""
import pytest

def test_final_packing_controls_citable_refs() -> None:
    """Verify final packing controls citable refs."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_guard_denial_and_cancellation_no_success() -> None:
    """Verify guard denial and cancellation no success."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_task_observer_and_memory_capture_coexist() -> None:
    """Verify task observer and memory capture coexist."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_structural_recovery_and_citation_channel() -> None:
    """Verify structural recovery and citation channel."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Observing the executed body after guards preserves FEAT-538 evidence and avoids grading calls that never ran.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` — Citation checks and request-local runtime tool events; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/tools/manager.py` — Compose memory capture with existing task observer; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/bots/base.py` — Mint exposure at final prompt delivery and record provider outcomes; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/unified/manager.py` — Connect delivered manifests and reviews to event routing; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` — Delivered-version, recovery, guard and cancellation tests; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` and `packages/ai-parrot/tests/memory/dynamics/test_core.py` — 200-character signature comparison and its test (spec E6).
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC11: bind exposure only after final packing into the model request; trimmed refs, arbitrary citations and cancelled/provider-failed responses earn no review.
- [ ] AC05/AC11: publish final exposure ID through runtime.bind_memory_exposure and restore it in finally; invocation entry clears inherited IDs, and durable manifests—not the ID alone—authorize citations.
- [ ] AC11: ToolManager._observed preserves FEAT-538 observer/guards and execution exceptions; use request-local capture, not replacement instance observer.
- [ ] AC11/G3 (spec E3–E5, E8, E10): a normal tool return is `incomplete` and earns no review; only a raised or explicitly reported failure builds a `failure` signal, and it can only select AGAIN; `passed_check_ids` is always empty for `tool_runtime`; `cited` is the only attribution mode and overlap cannot be enabled; citations never enter user-visible prose.
- [ ] E6: `select_grade` compares on the first 200 normalized characters, so a cited episode whose stored error message is longer than 200 characters still receives AGAIN.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_attribution.py -q`
- `pytest packages/ai-parrot/tests/memory/dynamics/test_core.py -q`

## Test Specification

- `final_packing_controls_citable_refs`: AC11: bind exposure only after final packing into the model request; trimmed refs, arbitrary citations and cancelled/provider-failed responses earn no review.
- `guard_denial_and_cancellation_no_success`: AC05/AC11: publish final exposure ID through runtime.bind_memory_exposure and restore it in finally; invocation entry clears inherited IDs, and durable manifests—not the ID alone—authorize citations.
- `task_observer_and_memory_capture_coexist`: AC11: ToolManager._observed preserves FEAT-538 observer/guards and execution exceptions; use request-local capture, not replacement instance observer.
- `structural_recovery_and_citation_channel`: AC11/G3 (spec E3–E5, E10): a default `ToolResult` is `incomplete` with no review; an explicit `success=False` and a raised exception each give `failure` with the normalized signature, and a cited episode with that signature receives AGAIN exactly once; a citation of a trimmed ref, another scope or a stale exposure id is rejected without revealing content; citations never enter user-visible prose.
- `test_core.py` — long-signature case (spec E6): a memory signature longer than 200 characters matches a signal cut to 200 and selects AGAIN.
- Two concurrent invocations on one `ToolManager` never see each other's attempt records (spec E2).

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
