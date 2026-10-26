# TASK-4728: Subsume FEAT-463 — AgentSwarmToolkit.ask_agent as a Request/Query over the Roost engine (M12b)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4725
**Assigned-to**: unassigned

---

## Context

Implements the `ask_agent` half of spec §3 **Module 12**. Resolved U2: *subsume* — `ask_agent` becomes a Request
(Query when `expected_schema` is None) over the protocol engine; tunnels stay the room topology; hops, status and
correlation come from one place. `ConversationBudget.hops` is seeded from FEAT-463's `ctx.current_hops`
ContextVar (generalise, don't add a second counter), and engine failures map back to FEAT-463's status strings.
Without an endpoint the tunnel path is byte-for-byte unchanged (AC-26).

---

## Scope

- Add an optional `endpoint` kwarg to `AgentSwarmToolkit.__init__` (stored as `self._endpoint`).
- In `ask_agent`, before the tunnel call, route through `self._endpoint` when set.
- Write `tests/test_matrix_roost_ask_agent.py`.

**NOT in scope**: changing tunnels, AppService or the legacy result shape; the Matrix carrier itself (TASK-4727)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | MODIFY | endpoint kwarg + Roost routing in ask_agent |
| `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py` | CREATE | Routing + status mapping tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit   # verified: matrix/crew/__init__.py:43
from parrot.integrations.matrix.crew import context as ctx                    # verified: swarm_toolkit.py imports `from . import context as ctx`
from parrot.roost.endpoint import RoostEndpoint, RoostFailure                 # TASK-4725 (TYPE_CHECKING + lazy in body)
from parrot.roost.messages import AgentAddress
from parrot.roost.performatives import FailureCode
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py
class AgentSwarmToolkit(AbstractToolkit):                                     # line 24
    def __init__(self, agent_name: str, tunnels: TunnelRegistry, registry: MatrixCrewRegistry, channels: ChannelManager,
                 appservice: MatrixAppService, **kwargs: Any) -> None:        # line 27; body ends `self._as = appservice` then super().__init__(**kwargs)
    async def ask_agent(self, agent: str, question: str, expected_schema: Optional[Dict[str, Any]] = None,
                        timeout: Optional[float] = None) -> dict:             # line 53; statuses documented ~65: "schema_error", "hop_limit", "unknown_agent", ...
        ...
        ans = await tunnel.ask(self._agent_name, agent, question, expected_schema=expected_schema, timeout=timeout,
                               hops=ctx.current_hops.get(), origin_session=ctx.current_session.get())   # line 89 anchor
        return ans.model_dump()
# matrix/crew/context.py: current_hops: ContextVar[int] (default 0); current_session: ContextVar[Optional[str]]
# parrot/roost/endpoint.py (TASK-4725): await endpoint.request(cap_id, args, *, timeout, receiver) / query(question, *, receiver, timeout, expected_schema)
```

### Does NOT Exist
- ~~a second hop counter — reuse `ctx.current_hops`~~
- ~~changing `ans.model_dump()` keys on the legacy path~~
- ~~importing `parrot.roost` at module top of swarm_toolkit.py — import inside the method to keep integrations importable without Roost changes~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py#AgentSwarmToolkit",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py#AgentSwarmToolkit.ask_agent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Place the Roost branch AFTER the existing validation (self-ask rejection, unknown agent, hop limit) and BEFORE `ans = await tunnel.ask(` — so FEAT-463's own pre-checks and statuses stay authoritative; read lines 53-89 and FILL IN the exact insertion if the pre-checks end elsewhere.
- Return shape on the Roost path mirrors the legacy one: success ⇒ `AgentAnswer(answer=<native result>, metadata={'via': 'roost', 'conversation_id': ...}).model_dump()` (AgentAnswer, events.py:165, has fields answer/confidence/sources/metadata and NO status); failure ⇒ a `{'status': ...}` dict like the pre-checks return — HOP_LIMIT→'hop_limit', TIMEOUT→'timeout', POLICY→'refused', other→'error'.
- Hops: pass `hops=ctx.current_hops.get() + 1` into the request's budget (endpoint accepts it via envelope/ConversationBudget — FILL IN the exact seam with TASK-4725's API).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py:165` — `AgentAnswer` shape
- `packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py` — existing ask_agent tests

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Add the kwarg.
2. Add the Roost branch.
3. Tests: endpoint set ⇒ endpoint.query/request awaited and tunnel not called; RoostFailure(HOP_LIMIT) ⇒ status 'hop_limit'; no endpoint ⇒ tunnel path unchanged.

### `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._as = appservice' crew/swarm_toolkit.py)
# AFTER — insert below `        self._as = appservice` (verified: crew/swarm_toolkit.py:50)
        self._endpoint = kwargs.pop("endpoint", None)  # FEAT-747: optional RoostEndpoint — ask_agent becomes a Request

# occurrences: 1 (verified: grep -c '        ans = await tunnel.ask(' crew/swarm_toolkit.py)
# BEFORE — insert above `        ans = await tunnel.ask(` (verified: crew/swarm_toolkit.py:89)
        if self._endpoint is not None:
            return await self._ask_via_roost(agent, question, expected_schema=expected_schema, timeout=timeout)
```
**Why**: `kwargs.pop` before `super().__init__(**kwargs)` keeps the public signature unchanged for every existing caller. Add `async def _ask_via_roost(...) -> dict` right after `ask_agent` (FILL IN per Key Constraints 2-3). Note the `_maybe_echo(agent)` call above the anchor still runs — the human-visible echo is preserved.

### FILL IN checklist
- [ ] `_ask_via_roost`
- [ ] insertion point check vs. pre-checks
- [ ] tests

---

## Acceptance Criteria

- [ ] With an endpoint, `ask_agent` routes through it and never calls `tunnel.ask`
- [ ] Engine failures map to FEAT-463 statuses
- [ ] Without an endpoint behaviour is unchanged; `tests/test_matrix_swarm_toolkit.py` and `test_matrix_tunnel.py` stay green
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_tunnel.py -q`

---

## Test Specification

```python
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit
from parrot.roost.endpoint import RoostFailure
from parrot.roost.messages import FailureInfo
from parrot.roost.performatives import FailureCode


def _toolkit(endpoint):
    # FILL IN: build like tests/test_matrix_swarm_toolkit.py does (mock tunnels/registry/channels/appservice)
    ...


async def test_hop_limit_status():
    ep = MagicMock(); ep.query = AsyncMock(side_effect=RoostFailure(FailureInfo(code=FailureCode.HOP_LIMIT)))
    out = await _toolkit(ep).ask_agent("peer", "q")
    assert out["status"] == "hop_limit"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4728 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Roost branch in ask_agent via optional `endpoint` kwarg; 23 matrix tests green. GAP: hop budget is NOT carried over the Roost path (RoostEndpoint.query has no hops param; editing endpoint.py is outside this task); expected_schema is accepted but discarded by query(); success metadata has no conversation_id. Filed as ledger issue:0f5ee739eca8 (major). Additions: failure dict includes 'detail'; success metadata includes status='ok'.
Seat: opus (native) · Attempts: 1

**Deviations from spec**: hops=ctx.current_hops+1 not passed (see issue:0f5ee739eca8)
