---
type: feature
base_branch: dev
feature_id: FEAT-825
projects: [ai-parrot, ai-parrot-integrations]
tags: [roost, matrix, bugfix, ledger]
discovered_from: issue:0f5ee739eca8
---
# FEAT-825 — Roost `ask_agent`: carry the conversation id (and lock hop / schema carriage)

**Status**: approved · **Parent**: FEAT-747 (local-inter-agent, merged) · **Issue**: `issue:0f5ee739eca8`

## Problem
`issue:0f5ee739eca8` (opened by the coder of TASK-4728) reported three gaps on the Roost path of
`AgentSwarmToolkit.ask_agent` (`_ask_via_roost`). Re-checked against `origin/dev` @ `159b1993dd`:

1. **Hop budget not carried — already fixed on `dev`.** `RoostEndpoint.query()` / `request()` take
   `hops` (endpoint.py:466, :544), seed `ConversationBudget.hops` through the opener and send
   `hops + 1` on the wire; `_ask_via_roost` passes `hops=ctx.current_hops.get()`
   (swarm_toolkit.py:161). Landed in `8ffec9c103`. Core tests cover the endpoint
   (`test_endpoint.py::test_hop_limit_*`); **no test covers the toolkit seam** — nothing fails if
   `_ask_via_roost` stops forwarding `hops`.
2. **`expected_schema` discarded — already fixed on `dev`** (FEAT-788, TASK-5094). Again no toolkit
   test asserts that `_ask_via_roost` forwards it.
3. **`conversation_id` not returned — still open.** `query()` mints the id internally
   (endpoint.py:576) and returns only the answer, so `_ask_via_roost` returns
   `metadata={"via": "roost", "status": "ok"}` (swarm_toolkit.py:173). TASK-4728 specified
   `metadata={'via': 'roost', 'conversation_id': ...}`. Without the id a caller cannot join an
   `ask_agent` result (or failure) to the Roost audit ledger, which is keyed by conversation id.

FEAT-788 scoped item 3 out explicitly ("`issue:0f5ee739eca8` conversation_id carriage").

## Design
- **M1 caller-supplied conversation id (core).** `RoostEndpoint.query()` gains a keyword-only
  `conversation_id: Optional[str] = None`. When `None` the behaviour is unchanged (a fresh
  `uuid.uuid4().hex`). When given it becomes the conversation id of the opener, the envelope
  `correlation_id`, the wire message and the pending future. It is validated with the same rule
  `trace_id` already uses (non-empty `str`, no whitespace, no `Cc`/`Cf` characters) and raises
  `ValueError` otherwise; validation runs before the grant check, so a malformed id never opens
  anything. An id the engine already knows is rejected by the existing
  `ProtocolEngine.open` → `ConversationExistsError` (a `ValueError`), which is raised **before**
  the id is registered in `_pending` and before anything is sent — the in-flight conversation
  that owns the id is untouched. The return value of `query()` does not change (no breaking
  change for existing callers).
  *Why caller-supplied rather than returned:* the id is then known on the failure path too
  (`RoostFailure` carries no conversation id), and the return type stays the native answer.
- **M2 toolkit carriage (integrations).** `_ask_via_roost` mints `uuid.uuid4().hex`, passes it as
  `conversation_id=` and reports it: success →
  `metadata={"via": "roost", "status": "ok", "conversation_id": <id>}`; `RoostFailure` →
  `{"status": ..., "detail": ..., "conversation_id": <id>}`. `GrantDenied` is unchanged — it is
  raised before a conversation exists, so there is no id to report. The id is never taken from
  tool arguments (it is not LLM-controlled).
- **M3 regression lock for the already-shipped half.** Toolkit tests assert that `_ask_via_roost`
  forwards `hops=ctx.current_hops.get()` and `expected_schema` to `query()`, and one test over two
  real in-process endpoints shows `ask_agent` returning `{"status": "hop_limit", ...}` when the
  caller's `ctx.current_hops` is already at the engine's hop limit.

## Acceptance Criteria
- [ ] AC-1 `query(conversation_id="c-1")` opens, sends and resolves the conversation under `"c-1"` (the receiver sees `msg.conversation_id == "c-1"`); without the argument a fresh id is minted as before.
- [ ] AC-2 `query(conversation_id=...)` raises `ValueError` for an empty, non-string, whitespace- or control-character-bearing id, and `ConversationExistsError` for an id the engine already holds; in both cases nothing is sent and `_pending` is unchanged.
- [ ] AC-3 `ask_agent` over Roost returns `metadata["conversation_id"]` equal to the `conversation_id` it passed to `query()`; `metadata["via"] == "roost"` and `metadata["status"] == "ok"` are preserved.
- [ ] AC-4 A `RoostFailure` on the Roost path returns the mapped `status`, `detail` and the same `conversation_id`; `GrantDenied` still returns exactly `{"status": "refused", "detail": "grant denied: <agent>"}`.
- [ ] AC-5 `_ask_via_roost` forwards `hops=ctx.current_hops.get()` and `expected_schema` to `query()` (asserted on the call kwargs), and `ask_agent` over two real in-process endpoints returns `status == "hop_limit"` when `ctx.current_hops` is at the hop limit.
- [ ] AC-6 Existing `packages/ai-parrot/tests/roost/` and `packages/ai-parrot-integrations/tests/test_matrix_roost_*.py` / `test_matrix_swarm_toolkit.py` stay green; `ruff check` clean on the changed files.

## Out of scope
- `RoostEndpoint.request()` / `cfp()` / `inform()` conversation-id injection — `ask_agent` only uses `query()`.
- Changing the return type of `query()`.
- Receiving-side hop seeding: nothing under `parrot/integrations/matrix/` supplies a Roost
  `WakeCallback`, and `MatrixCrewTransport` builds `AgentSwarmToolkit` without `endpoint=`
  (transport.py:235), so the Roost path is opt-in for an integrator. Whoever wires a Matrix wake
  adapter must set `ctx.current_hops` from the inbound `RoostMessage.hops`; that adapter does not
  exist yet and is not created here.
- `issue:c0063cc362a5` (terminal audit during `CancelledError`), same file, separate issue.

## Worktree Strategy
- **Isolation**: one feature worktree, `feat-FEAT-825-fixgroup-e6ea121738c9`, off `origin/dev`.
- **Module dependency graph**: M2 → M1 (`_ask_via_roost` passes the `conversation_id=` keyword M1
  adds to `RoostEndpoint.query`); M3 → M2 (its tests live in the same test module M2 extends).
  The chain is real, so the work is one task.
- **Shared files**: `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py` (M2, M3).
- **Exclusive resources**: none.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:43e035bf5b10a21465d81fbe54a5ce77f25fd7da475cd0a9a1ac1759a64c873c evaluation_digest=sha256:49f31b64ecd0debf1eb7ede6b55ff1dc58af6ee48a1e4afdad2d62a001aad05e rules_version=1 status=pass -->

## Consequences

<!-- decision-audit: input_digest=sha256:43e035bf5b10a21465d81fbe54a5ce77f25fd7da475cd0a9a1ac1759a64c873c evaluation_digest=sha256:49f31b64ecd0debf1eb7ede6b55ff1dc58af6ee48a1e4afdad2d62a001aad05e rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-e6ea121738c9.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, integrations, knowledge-graphindex, knowledge-wiki, memory, skills, tools
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
      "bots",
      "clients",
      "config",
      "flows",
      "integrations",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
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
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-e6ea121738c9.spec.md"
    }
  ],
  "evaluation_digest": "sha256:49f31b64ecd0debf1eb7ede6b55ff1dc58af6ee48a1e4afdad2d62a001aad05e",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:43e035bf5b10a21465d81fbe54a5ce77f25fd7da475cd0a9a1ac1759a64c873c",
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
