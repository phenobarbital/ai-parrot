# TASK-4424: Route the blast collector at the resolved plane root

**Feature**: FEAT-697 — sdd-coder blast collector must read the wiki plane from the main checkout
**Spec**: `sdd/specs/sdd-coder-complexity-collectors-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4423
**Assigned-to**: unassigned
**Discovered-from**: `issue:9448f28680e0`

---

## Context

Implements spec §3 Module 2 — the fix proper. `_collect_wiki_blast` currently
passes the worktree to `--path`, which makes the CLI exit 1 in every linked
worktree (verified: exit 1 in a worktree, exit 0 in the main checkout, same
symbol and flags). That turns `blast_symbols` into a false `unknown`, which
`ComplexityPolicy` routes like `complex` — the cause of ~91% of tasks landing on
strong seats. This task consumes TASK-4423's resolver so the measurement
actually runs.

---

## Scope

- In `_collect_wiki_blast`, call `_resolve_wiki_plane_root(worktree, policy)`
  **once**, before the per-symbol loop.
- When it returns a path, use that path both as the `--path` argument and as the
  `cwd` passed to `_run_subprocess`, replacing both current uses of `worktree`.
- When it returns `None`, return immediately — without spawning any subprocess —
  with the collector's standard 5-tuple carrying
  `MetricEvidence(state="unknown", reason="Wiki plane unavailable (no .parrot/wiki in worktree or main checkout)", source="wiki_collector")`.
- Write tests T3, T4, T5 and T7 from spec §4.

**NOT in scope**: altering the union/stale/truncation/missing-root rules or the
evidence hashes downstream of the subprocess call; changing the returned 5-tuple
shape; changing `ComplexityPolicy`'s `unknown` routing; touching the ruff
collectors; the unrelated open `issue:455ae7a3d8ea` in the same file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` | MODIFY | Wire the resolver into `_collect_wiki_blast` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` | MODIFY | Tests T3, T4, T5, T7 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `MetricEvidence` — already imported and constructed throughout the module.
- `_run_subprocess` — same module, line 1076.
- `_resolve_wiki_plane_root` — added by TASK-4423 in this same module.

### Existing Signatures to Use

- `async def _collect_wiki_blast(worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]`
  — `complexity_collectors.py:591-593`. **Keep this signature and the 5-tuple
  shape exactly as they are.**
- The CLI command list currently built at `complexity_collectors.py:641-659`.
  `--path` is a `symbols blast`-leaf option and must stay **after**
  `"symbols", "blast"` on the command line.

### Does NOT Exist

- No `plane_root` field on `ComplexityPolicy` and no `wiki_plane` setting in
  `conf.py`.
- There is no second wiki CLI call site in this module — `grep '"--path"'`
  returns exactly one hit (line 649). Do not go looking for others.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py#_collect_wiki_blast"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The plane reflects the **main checkout's** indexed state, not the worktree's
  branch. That is intentional and correct for a pre-implementation assessment —
  do not try to compensate for it, and do not invoke `wikitoolkit build`.
- Resolve once per collector call, not once per symbol.
- Fail-closed is preserved: a resolved plane whose CLI still exits 1 must keep
  producing `unknown` with the existing `"… exit {returncode}"` reason.
- The plane-unavailable reason string must be distinct from both
  `"Blast radius incomplete (…)"` and `"… missing root"` so telemetry can tell
  the three apart.

### References in Codebase

- `telemetry.resolve_durable_root` (`telemetry.py:107-157`) — same
  main-checkout derivation, different purpose. Reference only.
- `ComplexityPolicy` routing of `unknown` like `complex` — commit `957c15d96`.

---

## Acceptance Criteria

- AC1. Plane only in the main checkout, CLI stubbed to return valid blast JSON →
  `blast_symbols.state == "ok"` (the regression this feature exists to fix).
- AC2. The spawned command's `--path` value equals the resolved plane root
  whenever it differs from the worktree.
- AC3. No plane anywhere → `state == "unknown"`, plane-unavailable reason, and
  zero subprocesses spawned.
- AC4. Plane resolves but a symbol's CLI call exits 1 → still `unknown`, reason
  still contains `"exit 1"`.
- AC5. A symbol missing from a present plane → still `unknown` via the existing
  missing-root path.
- AC6. `_collect_ruff_cyclomatic` and `_collect_ruff_syntax` are byte-identical
  to `origin/dev` (`git diff origin/dev -- <file>` shows no hunk inside them).
- AC7. Full validation command set below passes; `ruff check` clean.

---

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src timeout -s KILL 900 pytest \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py -q
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py
```

---

## Test Specification

- T3 — no plane anywhere: assert `unknown` + plane-unavailable reason, and
  assert `_run_subprocess` was never awaited.
- T4 — regression: plane only in the main checkout, `_run_subprocess` stubbed to
  return `returncode=0` with a valid `BlastRadiusOutput`-shaped JSON payload
  (`{"root": {...}, "impacted": [{"symbol": {"symbol_id": ..., "stale": false}}], "files": [...], "truncated": false}`)
  → `blast_symbols.state == "ok"` and the captured `cmd` carries the main
  checkout after `--path`.
- T5 — resolved plane, CLI exits 1 → `unknown`, reason contains `"exit 1"`.
- T7 — integration: `collect_complexity` over a temp git worktree whose parent
  checkout holds a fixture plane → `blast_symbols` is not `unknown`. Use the
  suite's existing `_hermetic_durable_root` fixture
  (`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`).

---

## Agent Instructions

TASK-4423 must be `done` first — this task calls the resolver it adds, and both
tasks edit the same file. Verify every Codebase Contract entry in the source
before using it. Touch only the two listed files. Run the validation commands
before committing. Commit as
`fix(sdd-coder-complexity-collectors-fixes): TASK-4424 — route the blast collector at the resolved plane root`.

---

## Completion Note

*(fill in on close)*
