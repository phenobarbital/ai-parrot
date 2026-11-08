---
id: FG-006
query_id: Q047
type: git_log
intent: "History of Squawk — is the local inter-agent transport landed and stable enough to be a bus for work.completed?"
executed_at: 2026-11-07T01:19:11Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-006 — ai-parrot-squawk: 15+ commits 2026-10-29/30 (FEAT-746 inter-agent-protocol), heavy review churn, none since

## Summary

`packages/ai-parrot-squawk/` has at least 15 commits in 60 days, all on 2026-10-29 and 2026-10-30 under FEAT-746 (inter-agent-protocol): coder deliverables (TASK-4736, 4747, 4733) followed by ~10 review/fix commits in one day (capability bijection, per-owner blob records, expiry, size caps, G5/G6 gates — `c1b1327d7c` "G6 passes over real Redis Streams"). The package is landed and CI-registered (`823d5e9a88` in FG-003) but is capability-grant / Redis-Streams oriented and was under intense correction a week ago; it is a plausible v2 bus, not a v1 dependency for a host-local escrow trigger.

## Citations

- path: `packages/ai-parrot-squawk/`
  symbol: `c1b1327d7c`
  excerpt: |
    c1b1327d7c 2026-10-30 Jesus fix(inter-agent-protocol): TASK-4736 G6 passes over real Redis Streams
    3dc9441cdd 2026-10-30 Jesus fix(inter-agent-protocol): TASK-4735 G5 derive the capability prefix from the token
    9975d7e75f 2026-10-30 Jesus fix(inter-agent-protocol): G1 reproducible at the descriptor cap; spec gate outcome
- path: `packages/ai-parrot-squawk/`
  symbol: `916ee78ae5`
  excerpt: |
    916ee78ae5 2026-10-30 Jesus feat(inter-agent-protocol): TASK-4733 — engine-committed coder deliverable
    f7d65534ab 2026-10-29 Jesus feat(inter-agent-protocol): TASK-4747 — engine-committed coder deliverable
    20c943e3e5 2026-10-29 Jesus feat(inter-agent-protocol): TASK-4736 — engine-committed coder deliverable
- path: `packages/ai-parrot-squawk/`
  symbol: `717316d78e`
  excerpt: |
    717316d78e 2026-10-30 Jesus docs(inter-agent-protocol): G3/G6 raw results; G5 report and expiry tests
    77693b8bd3 2026-10-30 Jesus fix(inter-agent-protocol): private staging file, size cap, no grant on expired
    bb7cf719dd 2026-10-30 Jesus fix(inter-agent-protocol): promotion may not change policy or stay llm_backed
    620f4e169b 2026-10-30 Jesus fix(inter-agent-protocol): make cap_id <-> tool name a bijection
    ea863fbeb3 2026-10-30 Jesus fix(inter-agent-protocol): per-owner blob records, robust sweep, no temp leaks
    defa729a42 2026-10-30 Jesus fix(inter-agent-protocol): FEAT-746 review follow-ups

## Notes

- Memory (MEMORY.md) says FEAT-746 PR #1879 was open and FEAT-747 Roost (local inter-agent) tasks TASK-4711..4730 were pending as of the last note; git shows no `roost` commits in this window. Squawk is a Redis-Streams capability protocol, not a plain pub/sub bus.
