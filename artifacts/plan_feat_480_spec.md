# Plan — FEAT-480 Spec: Dev Flow Node Checkpoint Recovery

**Feature ID**: FEAT-480 (ledger-reserved 2026-08-31, commit `f5aef7b86`)
**Research identity**: FEAT-516 (`/sdd-proposal` self-assigned id — never
ledger-reserved; the proposal document keeps it, the spec supersedes it)
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md` (committed `60168e5f3`)
**Proposal**: `sdd/proposals/dev-flow-node-caching.proposal.md` (status: accepted)
**Flow**: type=feature, base_branch=dev

---

## What this feature is

Recover interrupted `dev_loop` / `dev_flow` jobs from durable, run-scoped node
checkpoints instead of re-executing the whole flow. Identity is the
caller-supplied stable `run_id` (namespaced `"<workflow>/<run_id>"`); a
required (awaited, hard-fail) Redis checkpoint barrier gates downstream
routing; resume rebuilds the explicit-edge graph through the original flow
factory and rehydrates typed outputs (`ResearchOutput`, `PlannerOutput`,
`DevelopmentOutput`, briefs) while live objects (`SessionHost`, dispatchers,
toolkits) are always freshly constructed.

## Decisions carried from proposal (resolved, do not reopen)

- **Cache identity scope** — reuse only under the same stable `run_id`;
  a newly generated id is intentionally a cache miss.
- **Redis failure policy** — any checkpoint persistence failure is a hard
  job error before downstream side effects execute.

## Module plan (spec §3, dependency order)

1. **Typed registration + factory resume** — `serializer.py`,
   `checkpoint/__init__.py`, `flow/flow.py`. Adapt precedent commit
   `8d7657b23` (non-ancestor; review its full diff, do not cherry-pick blindly).
2. **Required barrier + fingerprint** — `checkpoint/model.py`, `errors.py`,
   `checkpointer.py`, `core/context.py`, `flow/flow.py`. Awaited post-success /
   post-reset / pre-dispatch write; best-effort default preserved.
3. **Dev recovery adapter** — new `flows/dev_loop/checkpoint.py`
   (`DevCheckpointCoordinator`): fingerprint, fresh/miss/resume selection,
   shared-key projection, worktree/spec/task validation, recovery events.
4. **Dev-loop per-run lifecycle** — `dev_loop/flow.py`, `runner.py`, models.
5. **Dev-flow integration** — `dev_flow/flow.py`, `runner.py`, `models.py`.
6. **Runtime wiring + regression tests** — example servers, CLI bootstrap,
   checkpoint/dev-loop/dev-flow test suites.

## Worktree strategy

Per-spec: one `feat-480-dev-flow-node-caching` worktree, tasks sequential in
the order above (shared protocol changes in `flow.py`/`runner.py` make
parallel worktrees conflict-prone).

## Status / next steps

- [x] Proposal accepted (FEAT-516 research flow)
- [x] FEAT-480 reserved via `reserve_ids.py` (ledger commit pushed)
- [x] Spec written + committed on `dev` (`60168e5f3`), status: review
- [x] Codebase-contract anchors spot-verified (AgentsFlow class anchor
      corrected 209 vs 258)
- [ ] Human review → mark spec `status: approved`
- [ ] `/sdd-task sdd/specs/dev-flow-node-caching.spec.md`
- [ ] Create worktree `feat-480-dev-flow-node-caching` from `dev`, implement
