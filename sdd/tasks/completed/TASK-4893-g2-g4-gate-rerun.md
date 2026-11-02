# TASK-4893: Rerun gates G2 and G4 with real evidence and amend the spec

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4732, TASK-4734
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:60de633baac2`

## Context

TASK-4732 (G2) and TASK-4734 (G4) closed `partial` without measurements: the
G2 loopback bind was denied in the sandbox and G4's real-provider run was not
authorised. M3/M4 (transport) and M7 (mount policy) depend on these gates, so
their reports must carry real evidence before those modules are built.

## Scope

- Run the G2 spike and its opt-in regression on a host that permits loopback
  listeners; fix whatever keeps the spike from running there.
- Run the G4 spike on at least two real providers (operator-authorised
  `PARROT_TEST_REAL_LLM=1`); fix whatever keeps the spike from measuring.
- Record raw results, rewrite both reports' criteria and amendments, and add
  the gate outcomes to the spec.

**NOT in scope**: implementing M3/M4/M7, changing `parrot/clients/*`, fixing
the OpenAI client `max_tokens` defect found along the way (filed to the ledger).

## Files to Create / Modify

- `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py`, `report.md`, `results.json` (new)
- `sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py`, `report.md`, `results.json` (new)
- `sdd/specs/inter-agent-protocol.spec.md` (gate outcomes + revision history)

## Acceptance Criteria

- [x] G2 report states pass/fail per criterion from a real run, with raw output committed.
- [x] G4 report records turn 1/2/3 cache counters for ≥ 2 providers from cold runs, with raw output committed.
- [x] Spec carries the resulting amendments for M3/M4 and M7.

## Validation Commands

```bash
PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py -q
PARROT_SPIKE=1 PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py -q
```

## Completion Note

Both gates rerun 2026-10-30 (issue:60de633baac2).

- **G2: PASS.** Three full runs: 1.5M rows → 106 Arrow IPC frames ≤ 1 MiB
  (~105 MiB), cancel → `PARTIAL` with 11 valid frames, mTLS SAN + Hello token
  seen server-side, 118–172 MiB/s. The gRPC fallback is withdrawn. Running for
  real exposed three spike bugs (private `AsyncIoStream.protocol` in pycapnp
  2.2.4, a Python ≥ 3.12 `wait_closed` shutdown deadlock, `capnp.run` called
  synchronously) — each is now an M4 requirement in the spec.
- **G4: FAIL for free mounting → M7 premount-only.** Cold runs on Anthropic,
  OpenAI (gpt-4.1-mini) and Google: Anthropic loses the whole cached prefix on
  every mount, OpenAI part or all of it, Google keeps it. The spike had to be
  fixed first (clients never opened; Google silently dropped schema-dict tools,
  so it ran with none; Anthropic never got a `CacheableSegment`, so it never
  cached) and gained a per-run nonce so earlier runs' caches cannot fake a hit.
- pycapnp is not in the shared venv; G2 ran from a throwaway env with
  pycapnp 2.2.4 / pyarrow 26 / pandas 3.1 / cryptography 50.0.2. G4 ran on the
  `dev` client distributions (this branch has no concrete clients).
- Found: `OpenAIClient`'s default model (gpt-5-mini) rejects the `max_tokens`
  `ask()` sends (400) — filed to the ledger, not fixed here.
- Validation: both commands above pass (G2 1 passed; G4 1 passed, 24 s).
