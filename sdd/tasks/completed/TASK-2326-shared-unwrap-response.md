# TASK-2326: Shared `_unwrap_response()` helper + populate `NodeExecutionInfo.client`

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3) and fixes **G1 + G5**.

`build_node_metadata()` is the single metadata seam shared by BOTH executors:
`AgentCrew` calls it 5 times (`crew/crew.py:1346,1398,1968,2035,2323`) and
`AgentsFlow` calls it once (`flow/flow.py:988`), as do the decision nodes
(`flow/nodes.py:399,1129`). It only knows how to mine `AgentResponse` and
`AIMessage` instances. `AgentNode.execute()` returns an **envelope dict**
instead (`core/node.py:321-325`), so every AgentsFlow node falls through to
the `elif response is not None:` branch (`core/result.py:680`) where
`getattr(dict, "model", None)` is `None`. Result: `usage is None` and
`tool_calls == []` for every node of every flow run, while identical crews
report them correctly.

Fixing it here — rather than in `_aggregate_result` — is the whole point of
G5: one seam, so the two executors cannot drift apart again.

This task also revives `NodeExecutionInfo.client`, which is declared
(`core/result.py:304`) and serialised (`core/result.py:342`) but never
assigned by the constructor call at `core/result.py:698` — dead for crews
AND flows.

**This task lands FIRST and ALONE.** It is the only change in FEAT-447 that
can silently break AgentCrew, so it ships gated on the crew regression suites.

---

## Scope

- Add module-private `_unwrap_response(response: Optional[Any]) -> Optional[Any]`
  to `packages/ai-parrot/src/parrot/bots/flows/core/result.py`.
  - A `dict` containing a `"response"` key → return `dict["response"]`,
    resolving recursively so a nested envelope collapses.
  - Anything else (`AgentResponse`, `AIMessage`, `str`, `None`, arbitrary
    objects, a dict WITHOUT a `"response"` key) → return unchanged.
  - Bound the recursion with an explicit small depth cap; never raise.
- Call it once at the top of `build_node_metadata`'s body, BEFORE the
  existing `isinstance` ladder (i.e. before the locals at `core/result.py:644-648`).
- Populate `client=` in the `NodeExecutionInfo(...)` constructor call
  (`core/result.py:698`) with the concrete client class name derived from the
  agent, reusing the `client_obj` already resolved at `core/result.py:693`.
- Write unit tests in `packages/ai-parrot/tests/test_flow_primitives/test_result.py`.

**NOT in scope**:
- Touching `_aggregate_result` or anything in `flow/flow.py` — that is TASK-2328.
- Touching `FlowResult.node_results` — that is TASK-2327.
- Rewriting the `isinstance` ladder itself. Feed it the right object; leave it alone.
- Rewriting the `output` argument. `_aggregate_result` passes `output=resp`
  (non-`None`), which means the `if output is None` recovery branches
  (`core/result.py:666,675`) never fire. Do NOT "helpfully" also unwrap
  `output` — `NodeExecutionInfo` semantics would change (breaking, violates G6).
- `parrot.models.crew.build_agent_metadata` (`models/crew.py:322`) — legacy,
  called by no flows/crew path. Do not fix it, do not route through it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | MODIFY | Add `_unwrap_response()`; call it in `build_node_metadata`; pass `client=` |
| `packages/ai-parrot/tests/test_flow_primitives/test_result.py` | MODIFY | Add the 7 unit tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22. Line numbers WILL drift
> once you edit the file — re-check with `grep -n` before relying on a number.
> Treat the NAMES and SHAPES as authoritative.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:652
from parrot.models.responses import AIMessage, AgentResponse

# verified: packages/ai-parrot/src/parrot/bots/flows/core/__init__.py:38,72
from parrot.bots.flows.core import build_node_metadata

# verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:270,619
from parrot.bots.flows.core.result import NodeExecutionInfo, build_node_metadata
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class NodeExecutionInfo:                       # line 270
    node_id: str                               # line 280
    node_name: str                             # line 283
    provider: Optional[str] = None             # line 286
    model: Optional[str] = None                # line 289
    execution_time: float = 0.0                # line 292
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # line 295
    status: Literal["completed","failed","pending","running"] = "pending"  # line 298
    error: Optional[str] = None                # line 301
    client: Optional[str] = None               # line 304  ← NEVER ASSIGNED
    usage: Optional[Dict[str, Any]] = None     # line 307
    def to_dict(self) -> Dict[str, Any]: ...   # line 324 (emits "client" @ line 342)

def _serialise_tool_calls(tool_calls: Any) -> List[Any]: ...   # line 589
def _normalise_status(status: str) -> Literal[...]: ...        # line 604

def build_node_metadata(                       # line 619  ← THE SHARED SEAM
    node_id: str,
    agent: Optional[Any],
    response: Optional[Any],
    output: Optional[Any],
    execution_time: float,
    status: str,
    error: Optional[str] = None,
) -> NodeExecutionInfo: ...
    # body locals                       @644-648
    # try: import responses             @651-652
    # isinstance(response, AgentResponse) @654
    #   if output is None: ...          @666-667
    #   usage_obj = ...; if usage_obj:  @668-670  (usage_obj.model_dump())
    # elif isinstance(response, AIMessage) @671
    #   if output is None: ...          @675-676
    #   usage_obj = ...; if usage_obj:  @677-679
    # elif response is not None:        @680   ← where dicts wrongly land today
    # except ImportError:               @684
    # agent fallback for provider/model @690-694
    #   client_obj := agent.llm or agent._llm  @693   ← REUSE for client=
    # node_name = ...                   @696
    # return NodeExecutionInfo(...)     @698   ← ADD client= HERE
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class AgentNode(Node):                                     # line 193
    async def execute(self, ctx, deps, **kwargs) -> Any:   # line 281
        # returns THE ENVELOPE, lines 321-325:
        #   {"response": <AgentResponse>, "output": <Any>,
        #    "execution_time": <float>, "prompt": <str>}
```

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                # line 72
    input: str; output: Any
    model: str; provider: str              # REQUIRED fields
    usage: CompletionUsage                 # REQUIRED — has .model_dump()
    tool_calls: List[ToolCall] = []

class AgentResponse(BaseModel):            # line 1119
    response: Optional[AIMessage]          # ← nested AIMessage carries usage
    output: Optional[Any]
    agent_name: Optional[str] = "Agentic"
```

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — REFERENCE, DO NOT EDIT
build_node_metadata(agent_id, agent, response, result, execution_time, 'completed')  # @1968
# `response` here is a bare AgentResponse → _unwrap_response must pass it through
# UNCHANGED so crew output stays bit-identical.
```

### Does NOT Exist

- ~~`parrot.bots.flows.core.result._unwrap_response`~~ — **you are creating it**.
- ~~`NodeExecutionInfo.status == "skipped"`~~ — not a valid literal (line 298).
- ~~`AgentNode.execute()` returning an `AgentResponse` directly~~ — it returns
  the envelope dict. That is the entire bug.
- ~~`NodeExecutionInfo.client` being set anywhere today~~ — it is not.
- ~~`FlowResult.outputs`~~ (plural) — no such field, and FEAT-447 does not add one.
- ~~`AgentsFlow._build_result`~~ — the method is `_aggregate_result`
  (`flow/flow.py:955`). Not this task's file anyway.

---

## Implementation Notes

### Pattern to Follow

```python
def _unwrap_response(response: Optional[Any], _depth: int = 0) -> Optional[Any]:
    """Normalise a node/agent return value to its metadata-bearing object.

    ``AgentNode.execute()`` returns an envelope dict
    (``{"response", "output", "execution_time", "prompt"}``) rather than the
    ``AgentResponse`` itself. Crews pass the ``AgentResponse`` directly. This
    helper collapses the former to the latter and leaves the latter untouched,
    so ``build_node_metadata`` sees one shape from both executors.

    Args:
        response: Any node/agent return value.
        _depth: Internal recursion guard.

    Returns:
        The metadata-bearing object, or ``response`` unchanged.
    """
```

### Key Constraints

- **Defensive by construction.** This runs on arbitrary user objects. Bound
  the recursion with an explicit cap, and on ANYTHING unexpected return the
  input unchanged so `build_node_metadata` degrades exactly as it does today.
  It must never raise.
- **Preserve the `try/except ImportError` guard** around the
  `parrot.models.responses` import (`core/result.py:651,684`) — it keeps
  `build_node_metadata` importable in trimmed installs. `_unwrap_response`
  must NOT need that import (it keys on the dict shape, not on types).
- A plain `{"output": ...}` dict with NO `"response"` key is NOT an envelope —
  return it unchanged. Getting this wrong would break the `else` branch.
- Google-style docstrings + strict type hints (project rule).
- Additive only: no existing parameter removed or reordered; no field retyped.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/crew.py:322` — `build_agent_metadata`,
  the near-duplicate legacy twin. Read for context; do NOT edit.
- `packages/ai-parrot/src/parrot/bots/flows/core/node.py:321` — the envelope
  literal you are unwrapping.

---

## Acceptance Criteria

- [ ] `_unwrap_response()` exists in `core/result.py`, is recursion-bounded, and never raises (spec AC1)
- [ ] `build_node_metadata` calls it before the `isinstance` ladder
- [ ] Envelope input yields non-`None` `usage` and non-empty `tool_calls` (spec AC2)
- [ ] `NodeExecutionInfo.client` is non-`None` when the agent exposes a client (spec AC3)
- [ ] A bare `AgentResponse` produces an IDENTICAL `to_dict()` to pre-change, except `client`
- [ ] All 7 unit tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_result.py -v`
- [ ] **Crew regression suites green** (spec AC13): `pytest packages/ai-parrot/tests/test_crew_sequential_regression.py packages/ai-parrot/tests/test_crew_parallel_regression.py packages/ai-parrot/tests/test_crew_final_regression.py -v`
- [ ] Flow suites still green: `pytest packages/ai-parrot/tests/bots/flows/ packages/ai-parrot/tests/test_flow_primitives/ -v`
- [ ] `ruff check` and `mypy` clean on `core/result.py` (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_result.py
import pytest
from parrot.bots.flows.core.result import build_node_metadata
from parrot.models.responses import AIMessage, AgentResponse


@pytest.fixture
def agent_response_with_usage():
    """AgentResponse whose AIMessage carries REAL usage + tool_calls.

    NOTE: use a real CompletionUsage, NOT a MagicMock — build_node_metadata
    calls usage_obj.model_dump() (core/result.py:670,679) and a Mock returns
    a Mock, making every assertion vacuous.
    """
    ...


@pytest.fixture
def node_envelope(agent_response_with_usage):
    """The exact dict AgentNode.execute() returns (core/node.py:321-325)."""
    return {
        "response": agent_response_with_usage,
        "output": "answer",
        "execution_time": 0.42,
        "prompt": "q",
    }


def test_unwrap_response_envelope(node_envelope, agent_response_with_usage):
    """An envelope resolves to its inner AgentResponse."""

def test_unwrap_response_passthrough(agent_response_with_usage):
    """AgentResponse, AIMessage, str, None pass through unchanged."""

def test_unwrap_response_nested_envelope(agent_response_with_usage):
    """An envelope wrapping an envelope resolves; recursion is bounded."""

def test_unwrap_response_dict_without_response_key():
    """{"output": ...} with no "response" key is NOT an envelope."""

def test_build_node_metadata_from_envelope(node_envelope):
    """Envelope input yields usage is not None and non-empty tool_calls."""

def test_build_node_metadata_crew_shape_unchanged(agent_response_with_usage):
    """A bare AgentResponse still produces the same NodeExecutionInfo."""

def test_build_node_metadata_sets_client():
    """client is the concrete client class name, not None."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§2 Layer 1, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code — re-`grep -n` the line anchors above
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** every acceptance criterion, especially the crew regression suites
7. **Move this file** to `sdd/tasks/completed/TASK-2326-shared-unwrap-response.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-08-24
**Notes**:

Module 1 landed as specified, at the single shared seam.

- `_unwrap_response(response, _depth=0)` added to `core/result.py` immediately
  above `build_node_metadata`, with `_MAX_UNWRAP_DEPTH = 5` as the explicit
  recursion cap. It treats a mapping as an envelope only when a `"response"`
  key is present, wraps the membership test in a bare `except Exception` so an
  exotic `__contains__` cannot make it raise, and returns its input unchanged
  in every other case. It needs no `parrot.models.responses` import (it keys on
  dict shape, not on types), so the `try/except ImportError` guard below it is
  untouched.
- `build_node_metadata` now calls it as the first statement of its body,
  before the metadata locals and the `isinstance` ladder. The `output`
  argument is deliberately NOT unwrapped (per Scope / spec G6).
- `client=` is now passed to the `NodeExecutionInfo(...)` constructor, derived
  from the already-resolved `client_obj` as `type(client_obj).__name__`. Added
  guard: when `agent.llm` still holds raw config (a `str`/`dict`/`list`/
  `tuple`/`bytes` — the pre-`configure()` state) `client` stays `None` rather
  than reporting a useless `"str"`. Covered by
  `test_build_node_metadata_client_none_without_agent`.
- Rewrote the walrus `if` into an explicit block to hoist `client`; truthiness
  semantics of the original are preserved exactly.

Tests: 8 added to `tests/test_flow_primitives/test_result.py` (the 7 the task
specified plus `test_build_node_metadata_client_none_without_agent` for the
raw-config guard). `test_build_node_metadata_crew_shape_unchanged` asserts
crew/flow parity the strong way — `flow_info.to_dict() == crew_info.to_dict()`
for a bare `AgentResponse` vs. the same response inside an envelope.

Verification:
- `test_flow_primitives/test_result.py`: 39 passed (31 pre-existing + 8 new).
- Crew regression suites (AC13): 32 passed, unchanged from baseline.
- `tests/bots/flows/` + `tests/test_flow_primitives/`: 707 passed
  (measured baseline on clean `dev` was 699; +8 new).
- `tests/flows/checkpoint/`: 65 passed, 9 skipped.

**Environment notes (not defects introduced by this task)**:
1. pytest hangs at *interpreter exit* (post-summary) in suites that touch
   DocumentDB/`ExecutionWikiRecorder`; reproduced on clean `dev` in the main
   checkout. Worked around with a `timeout`-wrapped runner that reads the
   summary line.
2. Running `tests/bots/flows/` + `tests/test_flow_primitives/` +
   `tests/flows/checkpoint/` in ONE process yields 9 `ContextSnapshot`
   model-identity failures in `flows/checkpoint/`. Reproduced identically on
   clean `dev` in the main checkout (9 failed, 755 passed) — pre-existing
   cross-suite import pollution, unrelated to FEAT-447. Each suite is green in
   isolation. Relevant to AC14, which asks for the three directories in one
   command; recorded for the reviewer rather than fixed (out of scope).

**Deviations from spec**: none.

Notes on AC16 (`ruff`/`mypy` clean): the repo declares no `[tool.ruff]`
config, so `ruff check` runs with defaults and reports 56 pre-existing
findings on `core/result.py` (mostly `UP006`/`UP045` — the file annotates with
`Optional[...]`/`Dict[...]` throughout). My additions add exactly 3 `UP045`
hits, all from `Optional[Any]` annotations that match the surrounding file's
style; converting only my lines to `X | None` would make the new code
inconsistent with the other 17 annotations in the same file, and converting
the whole file is scope creep. The one new `I001` in the test file WAS fixed.
`mypy` reports the same 2 pre-existing errors (lines 36, 616) before and
after — no new type errors.
