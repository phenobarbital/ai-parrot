---
kind: brief
slug: roost-endpoint-authority-and-budgets
key: 59d1cb0c9814
base_branch: dev
source:
  type: ledger
  ref: issue:59d1cb0c9814
  url: null
jira_issue_key: null
ledger_issue: issue:59d1cb0c9814
created: "2026-10-29"
---

# Brief: Roost endpoint — caller authority, grant enforcement and runtime budget gates

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

Covers two ledger issues, folded by owner decision:

| Ledger issue | Kind / severity | Title |
|---|---|---|
| `issue:59d1cb0c9814` | vulnerability / critical | Roost endpoint does not propagate the caller PermissionContext and does not enforce the grant on explicit-receiver paths (AC-12/13/35) |
| `issue:5e3bcfe4ea4b` | bug / critical | Roost endpoint never enforces hop limit, token budget or deadline at runtime (AC-5) |

Both were found by the FEAT-747 code review (`spec:FEAT-747`, completed 2026-10-27)
and both land in `packages/ai-parrot/src/parrot/roost/endpoint.py`.

## Problem

Roost (FEAT-747) is the local inter-agent sub-protocol: one `RoostEndpoint` per
agent, speaking performatives over a carrier. The serving side of an endpoint
executes real tools on behalf of a remote caller. Two gates that were specified
to guard that path do not actually run.

**Security (issue:59d1cb0c9814).** Quoting the source:

> nothing under roost/ sets RoostMessage.permission_context or auth_token on
> outbound messages (only the codec/bridge read them), so _run_tool calls
> execute_tool(..., permission_context=None) for every inbound request — under
> PBAC every Roost call is denied, otherwise it runs unguarded. […]
> request(receiver=...) and query(receiver=...) skip find_capability and
> GrantPolicy […] _run_tool takes content['tool'] from the wire without checking
> it against the endpoint's advertised capabilities, and request() builds
> {'tool': ..., **args} so args['tool'] can override the capability's tool.

The source's disjunction is resolved by research below: the real behaviour is
**fail-open**, not denial. Every inbound Roost request executes its tool with
PBAC enforcement skipped.

**Budgets (issue:5e3bcfe4ea4b).** The conversation budget — hop limit, token
budget, deadline — is implemented and unit-tested in `ProtocolEngine` but was
not wired end-to-end from the endpoint. Part of it has since been wired (see
"Already fixed on dev"); the rest still is not.

## Root cause

**1 — No authority is ever put on the wire.** `RoostMessage` carries
`permission_context` and `auth_token` fields (`messages.py:75-76`), and the
serving side already reads them: `_run_tool` passes
`squawk_bridge.resolve_authority(msg)` into `ToolManager.execute_tool`
(`endpoint.py:180`). But no code path in `roost/` ever *sets* either field on an
outbound message — `RoostEndpoint.send()` builds its `RoostMessage` without them
(`endpoint.py:263`), and so do the `request()` and `query()` openers
(`endpoint.py:334`, `endpoint.py:389`). `RoostMessage.reply()` propagates
whatever it received (`messages.py:117-118`), which is `None`. A grep for
`permission_context`/`auth_token` across `roost/` finds only readers (codec, bus
carrier, squawk_bridge) and the model fields — no writer.

Consequently `resolve_authority(msg)` returns `None` for every inbound message,
and `PBACToolCallGuardrail` **passes** on `None` rather than denying:

```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py:250-254
permission_context: PermissionContext | None = ctx.extras.get("permission_context")
if permission_context is None:
    # Programmatic/test invocation with no session — enforcement is
    # session-scoped, mirroring `enforce_agent_access()` (resolved Q6/§8).
    return GuardrailResult(action=GuardrailAction.PASS)
```

So the serving endpoint runs the requested tool **unguarded**, for any caller
that can reach the carrier. This contradicts AC-13 and AC-35, and AC-35's own
wording ("neither present ⇒ `execute_tool` receives `None` and PBAC fails
closed") rests on an assumption about PBAC that is not true of the code.
`packages/ai-parrot/tests/roost/test_endpoint.py:77` currently asserts the
broken behaviour as expected:
`assert hr.tool_manager.execute_tool.await_args.kwargs["permission_context"] is None`.

**2 — The grant is enforced on one send path, not both.**
`request(receiver=...)` now checks it (`endpoint.py:318`), but
`query(receiver=...)` (`endpoint.py:372`) performs no grant check at all, and
`RoostToolkit.send(performative="query", receiver=…)` (`toolkit.py:39`) routes a
model-chosen receiver straight into it. AC-12 requires fail-closed on the send
path.

**3 — The served tool name is taken from the wire.** `_run_tool` reads
`content.get("tool")` (`endpoint.py:175`) and never checks the result against
`self.config.capabilities`, so an inbound message may name any tool registered
in the serving agent's `ToolManager`, not only an advertised capability. The
caller side makes this trivially reachable: `request()` builds
`content={"tool": cap_id.replace(".", "_"), **args}` (`endpoint.py:353`), so an
`args` mapping containing a `"tool"` key silently overrides the capability that
the grant was just checked against — defeating gate 2 even after it is fixed.

**4 — Budget gates are partly unwired.** `ProtocolEngine` implements the three
gates (`protocols.py:287` `charge`, `protocols.py:297` `expire`,
`protocols.py:280` `check_hops`). Residual gaps:

- `RoostMessage.tokens` (`messages.py:78`) is never assigned anywhere in
  `roost/` — a grep for `tokens=` in the package returns nothing. The one
  charge site, `self.engine.charge(msg.conversation_id, response.tokens)`
  (`endpoint.py:158`), therefore always charges **0**, so the token budget can
  never be exhausted.
- `_on_message` calls `self.dispatcher.dispatch(msg)` (`endpoint.py:131`)
  without `hops`, so `GatingDispatcher.dispatch`'s `hops` parameter defaults to
  `0` (`gating.py:92`) and `ProtocolEngine.accept(msg, hops=0)`
  (`gating.py:112`) never increments the hop counter for continuation messages.
  Openers are covered (`open()` seeds `hops=opener.hops`, `protocols.py:248`,
  and `check_hops` runs at `gating.py:108`) — mid-conversation growth is not.
- A `DispatchDecision.CLOSED` resolves the pending waiter with the **original**
  inbound message (`endpoint.py:140-142`), not with the failure the transition
  emitted. When that original is an `INFORM`, `_resolve_pending` takes the
  `INFORM` branch and calls `future.set_result(msg.content)` — the caller's
  `request()` returns a successful result for a conversation the engine just
  closed with `HOP_LIMIT` or `TOKEN_BUDGET`.

### Already fixed on dev — do not re-fix

Commit `8ffec9c10` ("review fixes — hop budget on the wire, expiry sweep,
toolkit routing, grant on direct request, cfp scorer") landed after both issues
were filed and closed `issue:58b536bd9809`. It already delivered:

- the grant check on `request(receiver=...)` (`endpoint.py:318`);
- the expiry sweep — `_sweep_loop` / `sweep()` call `engine.expire()`
  (`endpoint.py:101-125`), so sub-claim (3) of `issue:5e3bcfe4ea4b` is **closed**;
- the `charge()` transition being acted on (`endpoint.py:158-161`), so sub-claim
  (2) is **half** closed — the return value is handled, the charged amount is
  still always zero;
- `RoostMessage.tokens` as a real field (`messages.py:78`), contradicting that
  sub-claim's "RoostMessage has no `tokens` field";
- hop seeding and `check_hops` on openers, so sub-claim (1) is **narrowed** to
  continuation messages only.

Both ledger bodies predate this commit. Verify before implementing; the Codebase
Contract in each task file reflects the post-`8ffec9c10` tree.

## Research findings

Verified anchors (each confirmed with `test -e <path> && sed -n '<line>p' <path>`):

| Anchor | Line content | Relevance |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py:175` | `tool_name = content.get("tool") or (msg.capability_filter or "").replace(".", "_")` | wire-chosen tool |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:180` | `permission_context=squawk_bridge.resolve_authority(msg),` | serving-side read, always `None` |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:263` | `msg = RoostMessage(` | outbound build, no authority |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:318` | `if receiver is not None and not self.grant.allows(self.config, cap_id):` | grant on `request` (already fixed) |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:353` | `content={"tool": cap_id.replace(".", "_"), **args},` | `args["tool"]` override |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:372` | `async def query(` | no grant check |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:389` | `opener = RoostMessage(` | query opener, no authority |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:106` | `await self.sweep()` | expire IS wired |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:131` | `dispatch = self.dispatcher.dispatch(msg)` | no `hops=` |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:140` | `if dispatch.decision is DispatchDecision.CLOSED:` | resolves with original msg |
| `packages/ai-parrot/src/parrot/roost/endpoint.py:158` | `exhausted = self.engine.charge(msg.conversation_id, response.tokens)` | always charges 0 |
| `packages/ai-parrot/src/parrot/roost/messages.py:78` | `tokens: int = 0` | never assigned |
| `packages/ai-parrot/src/parrot/roost/messages.py:117` | `permission_context=self.permission_context,` | reply propagates |
| `packages/ai-parrot/src/parrot/roost/grant.py:24` | `def allows(self, config: Optional[RoostAgentConfig], cap_id: str) -> bool:` | fail-closed scope check |
| `packages/ai-parrot/src/parrot/roost/squawk_bridge.py:155` | `def resolve_authority(msg: RoostMessage) -> Any:` | token-over-context resolution |
| `packages/ai-parrot/src/parrot/roost/toolkit.py:39` | `result = await self._endpoint.query(content, receiver=address)` | model-reachable ungated path |
| `packages/ai-parrot/src/parrot/roost/gating.py:108` | `exceeded = self.engine.check_hops(msg)` | opener hop check (already fixed) |
| `packages/ai-parrot/src/parrot/roost/gating.py:112` | `transition = self.engine.accept(msg, hops=hops)` | `hops` defaults to 0 |
| `packages/ai-parrot/src/parrot/roost/protocols.py:248` | `hops=opener.hops,` | opener hop seeding (already fixed) |
| `packages/ai-parrot/src/parrot/roost/protocols.py:287` | `def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:` | token gate |
| `packages/ai-parrot/src/parrot/roost/protocols.py:297` | `def expire(self, *, now: Optional[datetime] = None) -> list[Transition]:` | deadline gate |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py:251` | `if permission_context is None:` | PBAC fail-OPEN, the crux |
| `packages/ai-parrot/src/parrot/auth/context.py:33` | `_pctx_var: contextvars.ContextVar["PermissionContext \| None"] = (` | the propagation mechanism to reuse |
| `packages/ai-parrot/src/parrot/tools/toolkit.py:178` | `hook_kwargs["_permission_context"] = pctx` | per-call pctx reaches a toolkit |
| `packages/ai-parrot/tests/roost/test_endpoint.py:77` | `assert hr.tool_manager.execute_tool.await_args.kwargs["permission_context"] is None` | test pins the bug |

**Prior art for the chosen propagation mechanism.** `_pctx_var`
(`parrot/auth/context.py:33`) is the repository's existing cross-boundary carrier
for a `PermissionContext`. It is already bound by
`packages/ai-parrot-server/src/parrot/mcp/agent_mount.py:172` (`_pctx_var.set(resolved)`,
after principal resolution) and by
`packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:379`
(`token = _pctx_var.set(pctx)` … `_pctx_var.reset(token)` at :459), and read back
by `parrot.semantic.context`. Roost should reuse it rather than invent a second
mechanism.

**Blast radius.** `roost/` is self-contained; `endpoint.py` is imported by
`roost/toolkit.py` and the Roost tests. `parrot.registry` imports
`roost/directory.py` only. No satellite package imports `roost.endpoint`.
Tests live at `packages/ai-parrot/tests/roost/`.

**Related open ledger issues on the same files** (NOT in this brief's scope —
whoever takes them should expect `endpoint.py` to have moved):

- `issue:d09c6c185547` — cfp ignores `scorer`, never applies grant attenuation,
  drops `expected_schema`, audit direction inverted (AC-8/14/26/27). Note the
  `scorer` half appears addressed by `8ffec9c10` (`endpoint.py:457` passes it).
- `issue:d05df48f68fe` — `RoostToolkit.send(request/query)` builds malformed
  conversations (AC-3).
- `issue:94019af6bc24` — `docs/roost` incomplete (AC-31); module-level roost
  imports in registry/AgentTool.

**Audit direction smell (observed, not in scope).** `_on_message` records
`direction="served"` for inbound (`endpoint.py:130`) while `_deliver_outbound`
records `direction="received"` for outbound (`endpoint.py:225`). That inversion
is already covered by `issue:d09c6c185547`; leave it alone here so the two lanes
do not collide.

## Decisions

From the owner's Q&A round (2026-10-29):

1. **PermissionContext source** — read `parrot.auth.context._pctx_var` at send
   time, with an optional `permission_context=` constructor argument on
   `RoostEndpoint` that wins when set (for daemon / deterministic endpoints that
   have no request scope). Matches the `mcp/agent_mount.py` and `msagentsdk`
   precedent.
2. **No authority on an inbound message** — **fail closed inside Roost**:
   `_run_tool` refuses with `FailureCode.POLICY` when
   `squawk_bridge.resolve_authority(msg)` is `None`. This realizes AC-35's intent
   without changing PBAC's global session-scoped semantics. Accepted behaviour
   change: an in-process Roost call made with no bound `PermissionContext` now
   fails instead of running.
3. **Tool pinning** — ignore `content["tool"]` entirely on the serving side;
   derive the tool from `msg.capability_filter` and require it to match an
   advertised `config.capabilities` entry, refusing with `FailureCode.POLICY`
   otherwise. On the caller side, stop `args` from being able to override the
   tool name.
4. **Scope** — fold `issue:5e3bcfe4ea4b` into this brief (task 4) and close both
   ledger issues from this worktree.

## Assumptions

Unresolved decisions, recorded rather than guessed at implementation time:

- **A1 — who fills `RoostMessage.tokens`.** The charge site needs a real token
  count. Assumption: the `wake` callback (`WakeCallback`, `endpoint.py:27`) is
  the only component that knows the LLM usage of its own reply, so the endpoint
  should charge `response.tokens` and the `wake` contract must be documented as
  "set `tokens` on the returned message". Task 4 keeps `charge()` reading
  `response.tokens` and adds the explicit contract + a test that a wake returning
  a tokens-bearing message exhausts the budget. If the implementer finds a usage
  object already reachable at that point, prefer it and note the deviation.
- **A2 — capability matching style.** `GatingDispatcher.addressed` matches an
  advertised capability against `msg.capability_filter` with
  `fnmatch.fnmatchcase(capability, filter)` (`gating.py:90`). Task 2 assumes the
  serving-side pin reuses that exact comparison so a filtered broadcast and a
  direct request agree on what "advertised" means.
- **A3 — endpoints advertising nothing.** Several tests build an endpoint with
  `config=None` or empty `capabilities`. The decision chosen (3) pins strictly,
  so such an endpoint serves nothing. Task 2 must update those fixtures rather
  than weaken the gate.
- **A4 — `auth_token`.** No Biscuit issuer exists in-tree yet (FEAT-746 has not
  landed one). Task 1 stamps `auth_token` only when the caller supplies one;
  it does not mint tokens.

## Fix plan

Four tasks, chained (each depends on the previous) because all four edit
`packages/ai-parrot/src/parrot/roost/endpoint.py`; the per-brief index is
`parallel_semantics: exclusive`.

1. **HOTFIX-59d1cb0c9814-1 — stamp caller authority on every outbound message.**
   Resolve the caller `PermissionContext` from the constructor override, else
   `_pctx_var`; set `permission_context` (and pass through `auth_token`) on the
   messages built by `send()`, `request()` and `query()`. No enforcement change.
2. **HOTFIX-59d1cb0c9814-2 — fail closed on the serving side and pin the tool.**
   `_run_tool` refuses with `POLICY` when no authority resolved; derive the tool
   from `capability_filter` and require an advertised capability; stop `args`
   overriding the tool name in `request()`. Replace the
   `test_endpoint.py:77` assertion that pins the bug.
3. **HOTFIX-59d1cb0c9814-3 — enforce the grant on `query(receiver=…)`.**
   Mirror `endpoint.py:318` in `query()`, raising `GrantDenied`; cover the
   `RoostToolkit.send("query", …)` path.
4. **HOTFIX-59d1cb0c9814-4 — runtime budget gates (folded `issue:5e3bcfe4ea4b`).**
   Thread `hops` from the message into `dispatcher.dispatch(...)`; make the
   token charge carry a real count and document the `wake` contract; resolve a
   `CLOSED` dispatch's pending waiter from the transition's failure instead of
   the original inbound message.

## Validation commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gating.py -q`
- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`
- `pytest packages/ai-parrot/tests/roost/test_squawk_bridge.py -q`
- `ruff check packages/ai-parrot/src/parrot/roost/`

Run with `PYTHONPATH=packages/ai-parrot/src` from inside the worktree.
