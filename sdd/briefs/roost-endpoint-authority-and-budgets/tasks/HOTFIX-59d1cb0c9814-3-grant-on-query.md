# HOTFIX-59d1cb0c9814-3: Enforce the inter-agent grant on query(receiver=…)

**Feature**: BRIEF-59d1cb0c9814 — Roost endpoint: caller authority, grant enforcement and runtime budget gates
**Spec**: `sdd/briefs/roost-endpoint-authority-and-budgets.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-59d1cb0c9814-2
**Assigned-to**: unassigned

---

## Context

Closes `issue:59d1cb0c9814` part (2).

AC-12 requires the inter-agent grant to be fail-closed on the send path.
Commit `8ffec9c10` delivered that for `request(receiver=…)`
(`endpoint.py:318`) when it closed `issue:58b536bd9809`, but
`query(receiver=…)` (`endpoint.py:372`) still performs **no** grant check —
and `RoostToolkit.send(performative="query", receiver=…)` (`toolkit.py:39`)
hands a model-chosen receiver straight into it. A model can therefore address
any agent in the registry with a query, bypassing the grant entirely.

---

## Scope

- Add a grant check to `RoostEndpoint.query()`, mirroring `endpoint.py:318`,
  raising `GrantDenied` before any conversation is opened or message sent.
- Decide and document what the query checks the grant *against*: `query()`
  takes a free-form `question`, not a `cap_id`. Use the receiver's name as the
  scope probe (e.g. `self.grant.allows(self.config, receiver.name)`), so a
  grant of `["hr.*"]` admits a query to `hr` and denies one to `payroll`.
  State the choice in the Completion Note; do NOT invent a new grant model.
- Cover the `RoostToolkit.send("query", …)` path with a test proving a
  model-chosen receiver outside the grant is refused.
- `query()` already documents no `Raises:` entry — add one, matching the
  wording of `request()`'s docstring (`endpoint.py:315-317`).

**NOT in scope**:
- `request()`'s check (already correct).
- `GrantPolicy.attenuate` and the Contract Net path — tracked by `issue:d09c6c185547`.
- `RoostToolkit.send`'s malformed-conversation defect — tracked by `issue:d05df48f68fe`.
- Changing `GrantPolicy` itself (`grant.py` is correct and tested).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | grant check + `Raises:` in `query()` |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | query grant-denial test |
| `packages/ai-parrot/tests/roost/test_toolkit.py` | MODIFY | toolkit query path denial test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .grant import GrantDenied, GrantPolicy  # verified: packages/ai-parrot/src/parrot/roost/endpoint.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:318 — the pattern to mirror
        if receiver is not None and not self.grant.allows(self.config, cap_id):
            raise GrantDenied(cap_id)

# packages/ai-parrot/src/parrot/roost/endpoint.py:372
    async def query(self, question: Any, *, receiver: AgentAddress, timeout: Optional[float] = None,
                    expected_schema: Optional[dict] = None, hops: int = 0) -> Any:
        del expected_schema  # line 382

# packages/ai-parrot/src/parrot/roost/grant.py:14
class GrantDenied(Exception): ...

# packages/ai-parrot/src/parrot/roost/grant.py:24
    def allows(self, config: Optional[RoostAgentConfig], cap_id: str) -> bool:
        """True iff a scope of ``config.grant`` fnmatch-es *cap_id*; False when config/grant is missing."""

# packages/ai-parrot/src/parrot/roost/messages.py:42
class AgentAddress(BaseModel):
    name: str  # line 45

# packages/ai-parrot/src/parrot/roost/toolkit.py:38-40
        if performative == "query":
            result = await self._endpoint.query(content, receiver=address)
            return {"status": "done", "result": result}
```

### Does NOT Exist
- ~~`GrantPolicy.allows_agent(...)`~~ — the only scope check is `allows(config, cap_id)`
- ~~`AgentAddress.cap_id`~~ — an address has `name`, `carrier`, `endpoint`
- ~~`RoostEndpoint.query(cap_id=...)`~~ — the first parameter is `question`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/endpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_endpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.query",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.request",
    "sym:packages/ai-parrot/src/parrot/roost/grant.py#GrantPolicy.allows",
    "sym:packages/ai-parrot/src/parrot/roost/grant.py#GrantDenied",
    "sym:packages/ai-parrot/src/parrot/roost/toolkit.py#RoostToolkit.send"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The check must come **before** `self.engine.open(opener)` and before any
  `self._pending` entry is created, so a denial leaves no orphan conversation
  state — this is why `request()` checks at the very top of the method.
- `GrantPolicy.allows` is fail-closed by construction: `config is None` or an
  empty `grant.scopes` returns `False` (`grant.py:34-36`). Existing tests that
  build endpoints with `config=None` and call `query()` will now raise — fix
  the fixture (give it a grant) rather than special-casing the gate.
- `GrantDenied` propagates out of the toolkit to the LLM. That is intended:
  the grant is configuration and "never model-visible" (`grant.py:1`), but the
  *denial* is a legitimate tool error.

### References in Codebase
- `packages/ai-parrot/tests/roost/test_grant.py` — existing `GrantPolicy` coverage
- `packages/ai-parrot/src/parrot/roost/endpoint.py:312-319` — `request()`'s docstring + check

---

## Implementation Blueprint

### Steps (in order)
1. Add the grant check as the first statement in `query()` — *why*: no state before a denial.
2. Add a `Raises:` section to the docstring — *why*: `request()` documents its `GrantDenied`; `query()` must too.
3. Add the two tests — *why*: both the direct and the model-reachable path.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'del expected_schema' packages/ai-parrot/src/parrot/roost/endpoint.py)
# BEFORE — insert above `        del expected_schema` (verified: endpoint.py:382)
        if not self.grant.allows(self.config, receiver.name):
            raise GrantDenied(receiver.name)
```
```python
# Docstring: replace the single line `"""Execute a Query conversation without an agreement phase."""`
# (verified: endpoint.py:381) with a Google-style docstring carrying Args/Raises,
# modelled on request()'s at endpoint.py:306-317. Its Raises entry must read:
#     GrantDenied: *receiver* is outside the caller's grant.
```
**Why this shape**: `receiver` is a required keyword argument of `query()`
(unlike `request()`, where it is optional and a `None` receiver goes through
`find_capability`, which already applies `filter_matches`). So the check needs
no `receiver is not None` guard, and there is no directory path to fall back to.

### FILL IN checklist
- *(none — this task's blueprint is complete)*

---

## Acceptance Criteria

- [ ] `query(receiver=AgentAddress(name="payroll"))` raises `GrantDenied` when the caller's grant is `["hr.*"]`
- [ ] `query(receiver=AgentAddress(name="hr"))` still succeeds with that grant
- [ ] No conversation state and no pending future survive a denial (`endpoint._pending` is empty; `engine.state(...)` is `None`)
- [ ] `RoostToolkit.send("query", receiver="payroll", content=…)` surfaces the denial
- [ ] `query()`'s docstring documents `GrantDenied`
- [ ] `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/roost/test_grant.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls3_directory_lookup.py -q`
- `pytest packages/ai-parrot/tests/roost/test_agent_tool_roost.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/roost/test_endpoint.py (extend)

@pytest.mark.asyncio
async def test_query_outside_grant_is_denied() -> None:
    """A query to an agent outside the caller's grant never leaves the endpoint."""
    carrier = InProcessCarrier()
    caller = make_endpoint("caller", carrier, config=RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"])))
    await caller.start()
    try:
        with pytest.raises(GrantDenied):
            await caller.query("how much?", receiver=AgentAddress(name="payroll"))
        assert not caller._pending
    finally:
        await caller.stop()


@pytest.mark.asyncio
async def test_query_inside_grant_is_allowed() -> None:
    """The same caller may query an agent its grant covers."""
    # FILL IN: scopes=["hr*"], receiver AgentAddress(name="hr"), assert the round trip returns


# packages/ai-parrot/tests/roost/test_toolkit.py (extend)

@pytest.mark.asyncio
async def test_toolkit_query_respects_the_grant() -> None:
    """RoostToolkit.send('query', ...) cannot address an agent outside the grant."""
    # FILL IN
```

---

## Agent Instructions

1. **Work in the brief worktree** `.claude/worktrees/fix-59d1cb0c9814-roost-endpoint-authority-and-budgets`.
2. **Check the dependency**: HOTFIX-59d1cb0c9814-2 must be `done` in the per-brief index.
3. **Verify the Codebase Contract** — tasks 1 and 2 have edited this file; re-anchor on literals, not line numbers.
4. **Update status** to `"in-progress"`; commit only the index file.
5. **Implement**, run the Validation Commands, `ruff check --fix`.
6. **Commit only this task's files**: `fix(roost): HOTFIX-59d1cb0c9814-3 — enforce the grant on query(receiver=…)`.
7. **Mark `done`**, fill in the Completion Note (including which scope probe you used), commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
