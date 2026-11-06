---
type: feature
base_branch: dev
feature_id: FEAT-827
projects: [ai-parrot-integrations]
tags: [roost, matrix, bugfix, ledger]
discovered_from: issue:2c7a156eb239
---
# FEAT-827 — Matrix crew: carry Roost hop depth on the serving side (wake adapter + carrier field)

**Status**: approved · **Parent**: FEAT-825 (merged, PR #2007) / FEAT-747 · **Issue**: `issue:2c7a156eb239`

## Problem
FEAT-825 made the *calling* side of `AgentSwarmToolkit.ask_agent` over Roost carry the hop budget:
`_ask_via_roost` passes `ctx.current_hops`, `RoostEndpoint.query()` sends `hops + 1`, and the serving
endpoint refuses a message past its hop limit. Two gaps remain on the *serving* side, both in
`packages/ai-parrot-integrations/src/parrot/integrations/matrix/` (checked on `origin/dev` @ `50204a4543`):

1. **No wake adapter seeds the hop depth.** The tunnel path seeds the served agent's depth in
   `MatrixCrewAgentWrapper.handle_task` (`ctx.current_hops.set(task.hops)`, crew_wrapper.py:194). The Roost
   path has no equivalent: nothing in the package implements a `WakeCallback`, and `MatrixCrewTransport`
   builds `AgentSwarmToolkit` without `endpoint=` (transport.py:235). An integrator who wires Roost must
   write the wake; one that does not set `ctx.current_hops` from the inbound `RoostMessage.hops` restarts
   every onward `ask_agent` at depth 0, so an A→B→A chain over Roost is never cut by the hop limit.
2. **`MatrixCarrier` drops `hops`.** `RoostEventContent` (events.py:285) has no `hops` field and
   `MatrixCarrier.to_content` / `from_content` (roost/carrier.py:185, :220) neither write nor read it, so
   every Roost message that crosses a Matrix room arrives with `hops == 0`: the receiving dispatcher's
   `engine.check_hops` can never trip, and a wake adapter would have nothing to seed from.

## Design
- **M1 carrier field.** `RoostEventContent` gains `hops: int = Field(default=0, ge=0)`; `to_content` writes
  `msg.hops`, `from_content` passes it to `RoostMessage`. Events written before this change have no field
  and parse as `0` — the behaviour they had.
- **M2 wake adapter.** `MatrixCrewAgentWrapper.handle_roost_wake(msg, dispatch) -> Optional[RoostMessage]`
  satisfies `parrot.roost.endpoint.WakeCallback`. For a `QUERY` it sets `ctx.current_hops` to `msg.hops`
  for the duration of the agent turn (reset in `finally`), marks the agent `busy` / `ready` in the
  registry like `handle_task`, resolves the bot through `BotManager`, runs
  `agent.ask("A peer agent (<sender>) asks you: <content>")` under a timeout (the envelope's `budget_ms`
  when present, else 120 s) and returns `msg.reply(INFORM, content=<answer text>, tokens=<usage.total_tokens>)`.
  It never raises: a timeout returns `reply(FAILURE, FailureInfo(TIMEOUT))`, any other error
  `reply(FAILURE, FailureInfo(INTERNAL))` (the detail is the exception class name only — no message text
  crosses agents). Any other performative is not served: it logs at debug and returns `None`.
- **M3 transport seam (opt-in).** `MatrixCrewTransport(config, *, roost_endpoint_factory=None)` and
  `from_yaml(path, *, roost_endpoint_factory=None)`. The factory is
  `Callable[[str, WakeCallback], RoostEndpoint]`: it receives the agent name and that agent's
  `handle_roost_wake` and returns an endpoint the integrator has configured (engine, dispatcher,
  carriers, `RoostAgentConfig` / grant, ledger, permission context — all policy stays with the
  integrator). When a factory is given, the transport builds one endpoint per agent that gets an
  `AgentSwarmToolkit`, `start()`s it, passes it as `endpoint=`, and `stop()`s every endpoint on shutdown.
  A factory or `start()` error propagates out of `MatrixCrewTransport.start()`: degrading to the tunnel
  path would silently drop the grant checks the integrator asked for. With no factory nothing changes.
- **M4 docs.** A short "Matrix crew wiring" section in `wiki/mcp/roost/carriers.md`.

## Acceptance Criteria
- [ ] AC-1 A `RoostMessage` with `hops=3` survives `MatrixCarrier.to_content` → `from_content` with `hops == 3`; content without a `hops` key parses with `hops == 0`; a negative `hops` is rejected by `RoostEventContent`.
- [ ] AC-2 During `handle_roost_wake` for a `QUERY` with `hops=4`, the bot's `ask` observes `ctx.current_hops.get() == 4`; after it returns (success or failure) `ctx.current_hops` is back to its previous value.
- [ ] AC-3 `handle_roost_wake` returns an `INFORM` reply carrying the answer text and `tokens` from `usage.total_tokens` (0 when the response has no usage); a bot error returns `FAILURE`/`INTERNAL`, a timeout `FAILURE`/`TIMEOUT`, a missing bot `FAILURE`/`INTERNAL`; it never raises; a non-`QUERY` message returns `None` without calling the bot.
- [ ] AC-4 Over two real in-process endpoints whose wakes are `handle_roost_wake` and whose bots re-ask the peer through their own `AgentSwarmToolkit`, an A→B→A→… chain ends with `status == "hop_limit"` after a bounded number of wakes (≤ the engine hop limit).
- [ ] AC-5 With `roost_endpoint_factory`, the transport calls it once per attached agent with `(agent_name, wrapper.handle_roost_wake)`, awaits `endpoint.start()`, hands the endpoint to that agent's `AgentSwarmToolkit`, and stops every endpoint in `stop()`; a factory error propagates; without a factory no endpoint is built and the toolkit has none.
- [ ] AC-6 Existing `packages/ai-parrot-integrations/tests/test_matrix_*.py` stay green; `ruff check` clean on the changed files.

## Out of scope
- Declaring Roost endpoints in the crew YAML (`MatrixCrewConfig`): carrier choice, per-agent grants and
  capabilities are deployment policy; the seam is programmatic only.
- Serving `REQUEST` / `CFP` / addressed `INFORM` wakes; `expected_schema` on the serving side (`query()`
  validates on the caller only — the served agent is not told the schema).
- Carrying `tokens`, `permission_context` or `auth_token` across the Matrix carrier.
- `ctx.current_session` on the Roost path (a `RoostMessage` has no originating-session field).

## Worktree Strategy
- **Isolation**: one feature worktree, `feat-FEAT-827-fixgroup-742a9ada6cba`, off `origin/dev`.
- **Module dependency graph**: M3 → M2 (the transport passes `wrapper.handle_roost_wake`); M4 documents
  M2/M3. M1 has no edge to the others (the AC-4 chain test runs on the in-process carrier).
- **Shared files**: none between M1 and M2–M4.
- **Exclusive resources**: none.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:c55f606882c4aaf8d7deb0436baddb6307f61a8fc5072780e8114f7b2e3fdac4 evaluation_digest=sha256:2bfd6a449631d05373884a0e3d35ac969c71b6dea96b3635988e057673f73c45 rules_version=1 status=pass -->

## Consequences

<!-- decision-audit: input_digest=sha256:c55f606882c4aaf8d7deb0436baddb6307f61a8fc5072780e8114f7b2e3fdac4 evaluation_digest=sha256:2bfd6a449631d05373884a0e3d35ac969c71b6dea96b3635988e057673f73c45 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-742a9ada6cba.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: integrations
- Unmapped tags: bugfix, ledger, matrix, roost
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "integrations"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "bugfix",
      "ledger",
      "matrix",
      "roost"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-742a9ada6cba.spec.md"
    }
  ],
  "evaluation_digest": "sha256:2bfd6a449631d05373884a0e3d35ac969c71b6dea96b3635988e057673f73c45",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:c55f606882c4aaf8d7deb0436baddb6307f61a8fc5072780e8114f7b2e3fdac4",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```
