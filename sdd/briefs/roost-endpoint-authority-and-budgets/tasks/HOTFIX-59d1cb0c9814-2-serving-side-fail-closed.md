# HOTFIX-59d1cb0c9814-2: Fail closed without authority and pin the served tool to an advertised capability

**Feature**: BRIEF-59d1cb0c9814 — Roost endpoint: caller authority, grant enforcement and runtime budget gates
**Spec**: `sdd/briefs/roost-endpoint-authority-and-budgets.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-59d1cb0c9814-1
**Assigned-to**: unassigned

---

## Context

Closes the consumer half of `issue:59d1cb0c9814` — parts (1) and (3).

Two defects on the serving path:

1. `PBACToolCallGuardrail` **passes** when `permission_context is None`
   (`pbac.py:250-254`), so an inbound message with no authority runs its tool
   unguarded. AC-35 assumes PBAC fails closed there; it does not. Per the
   brief's Decision 2, Roost enforces this itself rather than changing PBAC's
   global session-scoped semantics.
2. `_run_tool` reads the tool name straight off the wire
   (`content.get("tool")`, `endpoint.py:175`) and never checks it against the
   endpoint's advertised `config.capabilities`. The caller side makes this
   trivially reachable: `request()` builds `{"tool": cap_id…, **args}`
   (`endpoint.py:353`), so `args["tool"]` overrides the capability whose grant
   was just checked at `endpoint.py:318`.

Depends on task 1: without authority on the wire, failing closed would reject
every message.

---

## Scope

- In `_run_tool`, resolve authority once via `squawk_bridge.resolve_authority(msg)`;
  when it is `None`, send `msg.reply(Performative.FAILURE, failure=FailureInfo(code=FailureCode.POLICY, …))`
  and return without calling `execute_tool`.
- Derive the served tool from `msg.capability_filter` only (Decision 3): stop
  reading `content["tool"]`. Refuse with `FailureCode.POLICY` when
  `msg.capability_filter` is `None`, or when no entry of `self.config.capabilities`
  matches it. Reuse the comparison `GatingDispatcher.addressed` already uses —
  `fnmatch.fnmatchcase(capability, msg.capability_filter)` (`gating.py:90`,
  Assumption A2) — so a broadcast and a direct request agree on "advertised".
- An endpoint with `config is None` or empty `capabilities` therefore serves
  nothing (Assumption A3). Update the affected test fixtures rather than
  weakening the gate.
- In `request()`, stop `args` from overriding the tool name: build the wire
  content so the capability wins (e.g. `{**args, "tool": cap_id.replace(".", "_")}`
  or pass args under their own key) and keep `capability_filter=cap_id` on the
  wire message so the serving side can derive the tool — note the current call
  passes `capability_filter=None` at `endpoint.py:352`.
- Replace the `test_endpoint.py:77` assertion that pins the bug.

**NOT in scope**:
- The grant check on `query()` — HOTFIX-59d1cb0c9814-3.
- Budget gates — HOTFIX-59d1cb0c9814-4.
- Changing `PBACToolCallGuardrail` or any file under `bots/guardrails/`.
- Minting or verifying `auth_token`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | `_run_tool` fail-closed + capability pin; `request()` wire content |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | replace line-77 assertion; refusal + pinning tests; fixture gains capabilities |
| `packages/ai-parrot/tests/roost/test_salary_flow_end_to_end.py` | MODIFY | end-to-end fixture must supply authority and advertise its capability |

> Also check and, if they build a serving endpoint that now serves nothing,
> update: `test_gate_ls1_wakes.py`, `test_gate_ls2_inform_no_reply.py`,
> `test_gate_ls4_by_reference.py`, `test_agent_tool_roost.py`, `test_toolkit.py`.
> Add any file you actually change to the table above before committing.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import fnmatch  # stdlib; already used this way at packages/ai-parrot/src/parrot/roost/gating.py:5
from .performatives import FailureCode, Performative  # verified: endpoint.py:18
from .messages import FailureInfo  # verified: endpoint.py:17
from . import squawk_bridge  # verified: endpoint.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:172
    async def _run_tool(self, msg: RoostMessage) -> None:
        content = msg.content if isinstance(msg.content, dict) else {}                      # line 174
        tool_name = content.get("tool") or (msg.capability_filter or "").replace(".", "_")  # line 175
        result = await self.tool_manager.execute_tool(
            tool_name, content, permission_context=squawk_bridge.resolve_authority(msg),    # lines 177-181
        )

# packages/ai-parrot/src/parrot/roost/gating.py:84
    def addressed(self, msg: RoostMessage) -> bool:
        return any(fnmatch.fnmatchcase(capability, msg.capability_filter)
                   for capability in self.config.capabilities)  # line 90

# packages/ai-parrot/src/parrot/roost/directory.py:28
class RoostAgentConfig(BaseModel):
    capabilities: list[str] = Field(default_factory=list)  # line 31
    backing: Literal["deterministic", "llm_backed"] = "llm_backed"  # line 38

# packages/ai-parrot/src/parrot/roost/messages.py:88
    def reply(self, performative: Performative, *, content: Any = None,
              body: Optional[str] = None, failure: Optional[FailureInfo] = None) -> "RoostMessage": ...

# packages/ai-parrot/src/parrot/roost/performatives.py — FailureCode members include POLICY
# (verified in use: endpoint.py:184 `code = FailureCode.POLICY if isinstance(exc, PermissionError) ...`)
```

### Does NOT Exist
- ~~`RoostEndpoint._advertised(...)`~~ — no such helper yet; create it if you want one
- ~~`RoostAgentConfig.tools`~~ — the field is `capabilities`
- ~~`FailureCode.UNAUTHORIZED`~~ — not verified to exist; use `FailureCode.POLICY`, which `endpoint.py:184` already uses
- ~~`GatingDispatcher.addressed` being reachable from the endpoint~~ — the endpoint holds `self.dispatcher`, but do not reach into its private state; duplicate the one-line `fnmatch` comparison

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
      "path": "packages/ai-parrot/tests/roost/test_salary_flow_end_to_end.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint._run_tool",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.request",
    "sym:packages/ai-parrot/src/parrot/roost/gating.py#GatingDispatcher.addressed",
    "sym:packages/ai-parrot/src/parrot/roost/directory.py#RoostAgentConfig",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#RoostMessage.reply",
    "sym:packages/ai-parrot/src/parrot/roost/squawk_bridge.py#resolve_authority"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Both refusals must be typed `failure` acts on the wire, never raised
  exceptions — `_run_tool` is called from `_on_message`, and an escaping
  exception would hang the caller's future until its timeout. The existing
  `except` block at `endpoint.py:182-188` shows the shape to match.
- `msg.reply(...)` raises `ValueError` when the message has no explicit receiver
  (`messages.py:104`). A `RUN_TOOL` dispatch can be reached by a
  capability-filtered broadcast, so guard the refusal path the same way the
  existing code does, or log and return rather than crash the inbound loop.
- Log every refusal at WARNING with the conversation id and the offending
  capability — this is a security gate and must be observable.
- Do not change the success path's result handling (`endpoint.py:189-191`).

### References in Codebase
- `packages/ai-parrot/src/parrot/roost/endpoint.py:182-188` — typed-failure pattern to copy
- `packages/ai-parrot/src/parrot/roost/gating.py:84-90` — capability matching
- `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py:250-254` — why Roost must fail closed itself

---

## Implementation Blueprint

### Steps (in order)
1. Extract `authority = squawk_bridge.resolve_authority(msg)` at the top of `_run_tool` and refuse on `None` — *why*: Decision 2.
2. Derive and validate the tool from `msg.capability_filter`; refuse when unadvertised — *why*: Decision 3.
3. Fix `request()`'s wire content and `capability_filter` so args cannot override the tool — *why*: closes the caller-side half.
4. Update the test suite, starting with the assertion at `test_endpoint.py:77` — *why*: it currently pins the bug.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'tool_name = content.get("tool")' packages/ai-parrot/src/parrot/roost/endpoint.py)
# REPLACE endpoint.py:174-181 (the content/tool_name lines and the execute_tool call) with:
        content = msg.content if isinstance(msg.content, dict) else {}
        authority = squawk_bridge.resolve_authority(msg)
        if authority is None:
            self.logger.warning(
                "Roost refused an unauthenticated request on conversation %s", msg.conversation_id
            )
            # FILL IN: reply FAILURE/POLICY ("no caller authority on the message") and return
            raise NotImplementedError
        tool_name = self._advertised_tool(msg)
        if tool_name is None:
            self.logger.warning(
                "Roost refused capability %r not advertised by %s", msg.capability_filter, self.agent_name
            )
            # FILL IN: reply FAILURE/POLICY ("capability not advertised") and return
            raise NotImplementedError
        try:
            result = await self.tool_manager.execute_tool(tool_name, content, permission_context=authority)
```
```python
# NEW METHOD — add directly above `async def _run_tool` (verified: endpoint.py:172)
    def _advertised_tool(self, msg: RoostMessage) -> Optional[str]:
        """Return the tool name for an inbound message, or ``None`` when it is not advertised.

        The name is derived from ``msg.capability_filter`` alone — never from the
        wire ``content`` — so a caller cannot name a tool this endpoint does not
        advertise (``issue:59d1cb0c9814`` part 3).

        Args:
            msg: The inbound Roost message whose capability is being served.

        Returns:
            The underscore tool name, or ``None`` when no advertised capability matches.
        """
        # FILL IN: None when msg.capability_filter is None or self.config is None;
        # match with fnmatch.fnmatchcase(capability, msg.capability_filter) over
        # self.config.capabilities; return msg.capability_filter.replace(".", "_") on a hit
        raise NotImplementedError
```
```python
# occurrences: 1 each (verified: grep -c on each literal)
# In request(), endpoint.py:352-353 currently read:
#     capability_filter=None,
#     content={"tool": cap_id.replace(".", "_"), **args},
# REPLACE with a form where the capability travels on the wire and args cannot
# shadow the tool, e.g.:
                capability_filter=cap_id,
                content={**dict(args), "tool": cap_id.replace(".", "_")},
```
**Why this shape**: `_deliver_outbound` routes by `capability_filter` when it is
set (`endpoint.py:227-232`) — it broadcasts to every carrier instead of the
explicit receivers. Verify which behaviour you get before settling on this edit:
if setting `capability_filter` on the wire message changes routing for an
explicit receiver, carry the capability another way (e.g. keep
`capability_filter=None` and have `_advertised_tool` fall back to the engine's
opener state for `msg.conversation_id`) and record the choice in the Completion
Note. Do NOT ship a change that turns directed requests into broadcasts.

### FILL IN checklist
- [ ] `_run_tool` — the two refusal replies; bounded by Decision 2 / Decision 3
- [ ] `_advertised_tool` — the match; bounded by Assumption A2
- [ ] `request()` — routing-safe way to carry the capability; bounded by the "Why this shape" warning

---

## Acceptance Criteria

- [ ] An inbound request with no `permission_context`/`auth_token` gets `failure(POLICY)` and `execute_tool` is NOT called
- [ ] An inbound request naming a capability the endpoint does not advertise gets `failure(POLICY)`
- [ ] `args={"tool": "something_else"}` cannot change the tool the serving side runs
- [ ] A directed request still reaches exactly its receiver (no broadcast regression) — assert on the carrier
- [ ] `test_endpoint.py:77`'s `permission_context is None` assertion is gone
- [ ] `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_salary_flow_end_to_end.py -q`
- `pytest packages/ai-parrot/tests/roost/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls1_wakes.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls2_inform_no_reply.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls4_by_reference.py -q`
- `pytest packages/ai-parrot/tests/roost/test_agent_tool_roost.py -q`
- `pytest packages/ai-parrot/tests/roost/test_carriers_inprocess.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/roost/test_endpoint.py (extend)

@pytest.mark.asyncio
async def test_request_without_authority_is_refused() -> None:
    """An unauthenticated inbound request never reaches the tool."""
    # FILL IN: caller built WITHOUT a permission_context; expect RoostFailure with
    # failure.code is FailureCode.POLICY and hr.tool_manager.execute_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_unadvertised_capability_is_refused() -> None:
    """A capability outside config.capabilities is refused with POLICY."""
    # FILL IN: hr advertises ["hr.people.salary"], caller requests "hr.payroll.run"


@pytest.mark.asyncio
async def test_args_cannot_override_the_served_tool() -> None:
    """A 'tool' key in args does not change which tool the serving side runs."""
    # FILL IN: caller.request("hr.people.salary", {"tool": "admin_wipe"}, receiver=...)
    # assert hr.tool_manager.execute_tool.await_args.args[0] == "hr_people_salary"


@pytest.mark.asyncio
async def test_directed_request_is_not_broadcast() -> None:
    """Setting the capability on the wire must not turn a directed request into a broadcast."""
    # FILL IN: a third endpoint advertising the same capability must receive nothing
```

---

## Agent Instructions

1. **Work in the brief worktree** `.claude/worktrees/fix-59d1cb0c9814-roost-endpoint-authority-and-budgets`.
2. **Check the dependency**: HOTFIX-59d1cb0c9814-1 must be `done` in `sdd/briefs/roost-endpoint-authority-and-budgets.index.json`.
3. **Read the brief**, especially Decisions 2–3 and Assumptions A2–A3.
4. **Verify the Codebase Contract** — task 1 has already edited this file; line numbers will have shifted. Re-anchor on the literals, not the numbers.
5. **Update status** to `"in-progress"` in the per-brief index; commit only that file.
6. **Implement**, complete every `# FILL IN:`, then run the Validation Commands and `ruff check --fix`.
7. **Commit only this task's files**: `fix(roost): HOTFIX-59d1cb0c9814-2 — fail closed without authority, pin the served tool`.
8. **Mark `done`**, fill in the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
