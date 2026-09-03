# TASK-2763: Docs — readiness handshake, timeout policy, and the bootstrap-profile procedure (U3b)

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2760
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 / G7 / AC10. `docs/repl-worker-sandbox.md` describes the
worker model, failure modes (§2 table) and `WorkerConfig` (§3 table) but
knows nothing about readiness, the lethal/non-lethal split, or the two new
config fields; its `rlimit_as_bytes` row also wrongly says rlimits are
applied "via `preexec_fn`" (they are applied worker-side in
`worker.main()`). Open question U3b (proposal §5) asks for a host-side
bootstrap measurement; this task documents the procedure and records the
local baseline (finding F018) so the follow-up import-trim spec has a
starting point.

---

## Scope

- `docs/repl-worker-sandbox.md`:
  - §1 Execution model: add a "Readiness handshake" paragraph (worker
    writes `ReadyResponse` after bootstrap; host awaits it before the first
    request; spares count as prewarmed only when ready).
  - §2 Failure modes table: add rows for *bootstrap timeout*
    (`bootstrap_timeout_ms` expired → worker killed → `WorkerBootstrapError`
    / G5 dict on the execute path) and *namespace-API timeout*
    (`namespace_timeout_ms` expired → `NamespaceTimeoutError`, worker
    alive, namespace preserved, reply drained on next call). Add a short
    "which timeouts kill" table: only `deadline_ms` (execute) and
    `bootstrap_timeout_ms`.
  - §3 `WorkerConfig` table: add `bootstrap_timeout_ms` and
    `namespace_timeout_ms` rows; fix the `rlimit_as_bytes` row wording
    (`preexec_fn` → "applied by the worker itself in `main()` before heavy imports").
  - §4 Namespace API: document that calls may raise `NamespaceTimeoutError`
    and that this is non-lethal.
  - New §"Restart-loop warning": what `possible restart loop` means and
    what to check (bootstrap time, host load, `bootstrap_timeout_ms`).
  - New §"Measuring worker bootstrap on your host" (U3b procedure):
    ```bash
    python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool" 2> importtime.log
    sort -t'|' -k2 -n importtime.log | tail -25
    # and, from a running server's logs, for one session id:
    grep -E "spawned worker pid=|repl_worker: ready|worker is dead" server.log
    ```
  - §6 History: add the FEAT-500 entry.
- `artifacts/logs/feat-500-bootstrap-profile.md` (CREATE): record the
  local baseline from finding F018 — total 1.41 s; `parrot.tools` init
  0.90 s (of which `parrot.plugins` → `navconfig.logging` 0.58 s);
  `parrot.security.redaction` → `vault_utils` → `interfaces.documentdb`
  0.28 s; `parrot.tools.abstract` → `core.events.lifecycle` / `parrot.conf`
  → `models.google` → `interfaces.file` → `navigator` → `navigator_auth`
  0.25 s; `pandas` 0.22 s — plus spawn→ready timings (≈2.4 s idle, 12–14 s
  under 3× CPU oversubscription, F015/F016). Leave a filled-in template
  section "Affected host" with the commands above for the user to paste
  results into (U3b). Note that `artifacts/` may be git-ignored — check
  `git check-ignore -v artifacts/logs/` and, if ignored, `git add -f` the
  file (precedent: `artifacts/logs/feat-380-rlimit-as-calibration.md` is
  referenced from the docs).

**NOT in scope**: any product code; trimming the import surface (spec
Non-Goal, follow-up spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/repl-worker-sandbox.md` | MODIFY | readiness, timeouts, config rows, restart-loop, measurement procedure |
| `artifacts/logs/feat-500-bootstrap-profile.md` | CREATE | F018 baseline + host template |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
*(docs-only task; the names below must match what TASK-2757/2759/2760 landed — verify with grep before writing)*
```python
from parrot.tools.repl_worker import WorkerConfig, ReadyResponse, NamespaceTimeoutError, WorkerBootstrapError
```

### Existing Signatures to Use
```text
docs/repl-worker-sandbox.md structure (current):
  :1   # PythonREPLTool Sandbox: Worker-Process Execution Model
  :27  ## 1. Execution model            (:67 ### The one exception: execute_sync())
  :78  ## 2. Failure modes              (:86-93 table; :95 ### Namespace-loss error shape)
  :118 ## 3. Deployment configuration (WorkerConfig)   (:124-132 table — rlimit_as_bytes row :126 mentions `preexec_fn` [stale]; deadline_ms :129; prewarm_pool_size :132)
  :153 ### Instantiating a tool with a custom config
  :166 ## 4. Namespace API (for integrators)  (:191 ### DataFrames specifically; :201 ### Snapshot semantics ...)
  :215 ## 5. ⚠️ Windows degradation
  :245 ## 6. History
  :260 ## See also
artifacts/logs/feat-380-rlimit-as-calibration.md — precedent for a measurement log referenced from the docs (:126)
sdd/state/FEAT-518/findings/F018-probe-importtime-profile.md — the numbers to transcribe
sdd/state/FEAT-518/findings/F015-probe-baseline-unloaded.md, F016-probe-death-spiral-under-load.md — spawn→ready timings
```

### Does NOT Exist
- ~~`docs/repl-worker-sandbox.md` sections on readiness / restart loops / measuring bootstrap~~ — you create them.
- ~~`WorkerConfig.preexec_fn`~~ — rlimits are applied in `worker.main()` → `apply_rlimits()` (`worker.py:85-118, 333`); fix the stale wording.
- ~~`scripts/sdd/probe_repl_worker_bootstrap.py`~~ — no probe script exists; the procedure is documented as shell commands (do not create a script unless the user asks).

---

## Implementation Notes

### Pattern to Follow
Mirror the existing tone and table style of `docs/repl-worker-sandbox.md` §2/§3 (one row per failure mode / config field, with the exact error text users will see).

### Key Constraints
- Every documented message string must be copied from the implemented code (grep `handle.py` / `pool.py` after TASK-2759/2760), not from the spec.
- Keep the Windows section accurate: the ready frame is plain pipe I/O and works on Windows; the timeout-kill mapping is unchanged.

### References in Codebase
- `docs/repl-worker-sandbox.md` — target
- `sdd/state/FEAT-518/findings/F015, F016, F018` — measurements

---

## Acceptance Criteria

- [ ] Docs describe the readiness handshake, both new `WorkerConfig` fields, the lethal/non-lethal table, `NamespaceTimeoutError` on the namespace API, the restart-loop warning, and the measurement procedure
- [ ] Stale `preexec_fn` wording fixed
- [ ] `artifacts/logs/feat-500-bootstrap-profile.md` exists with the F018 baseline and an "Affected host" template
- [ ] Every code/message name in the docs resolves (`grep` in `src/`)
- [ ] Spec AC10

---

## Test Specification

Docs-only. Verification is a grep pass:
```bash
grep -n "bootstrap_timeout_ms\|namespace_timeout_ms\|ReadyResponse\|NamespaceTimeoutError\|possible restart loop" docs/repl-worker-sandbox.md
grep -rn "bootstrap_timeout_ms\|namespace_timeout_ms\|class ReadyResponse\|class NamespaceTimeoutError\|possible restart loop" packages/ai-parrot/src/parrot/tools/repl_worker/
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2760 in `sdd/tasks/completed/` (can be drafted earlier; finalize message strings after)
3. **Verify the Codebase Contract** — grep the implemented names before writing them
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2763-docs-and-bootstrap-profile.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-02
**Notes**:
- `docs/repl-worker-sandbox.md` (+161 lines):
  * §1 — new `### Readiness handshake (FEAT-500)` subsection: the 4-step
    mechanism (worker writes `ReadyResponse` first / handle arms the readiness
    future / `_send()` awaits it so every caller benefits / the pool gates
    spares on it), plus a closing paragraph on what the absence of a handshake
    caused.
  * §2 — two new failure-mode rows (**bootstrap timeout** and **namespace-API
    timeout**) and a new `### Which timeouts kill the worker?` table listing
    all four budgets and their lethality.
  * §3 — new `bootstrap_timeout_ms` / `namespace_timeout_ms` rows (defaults,
    lethality, the "don't lower it" rationale, `> 0` validation); the
    `prewarm_pool_size` row now notes spares are only pooled once ready; the
    stale `rlimit_as_bytes` wording is fixed to "Applied by the worker itself
    in `worker.main()` (via `apply_rlimits()`) before any heavy import runs —
    **not** via `Popen(preexec_fn=...)`".
  * §4 — a `NamespaceTimeoutError` block with a `try/except` example, stating
    it is non-lethal, subclasses `TimeoutError`, and never has an empty
    `str()`; `WorkerBootstrapError` mentioned alongside.
  * new `## 4b. Restart-loop warning (FEAT-500)` — the log line,
    `restart_count()`, and a 4-item ordered checklist of what to check
    (bootstrap time, host load, exit code/stderr tail, and the case where the
    loop is *correct* because the LLM keeps submitting non-terminating code).
  * new `## 4c. Measuring worker bootstrap on your host (U3b)` — the
    `-X importtime` procedure, the server-log grep, a healthy-cold-start log
    sample, and the note that `bootstrap_ms` is measured worker-side so it can
    be compared to `bootstrap_timeout_ms` directly.
  * §6 History — a FEAT-500 entry; "See also" now links the profile artifact.
- Created `artifacts/logs/feat-500-bootstrap-profile.md`: the F018 import
  breakdown as a table (total 1.41 s; `parrot.tools` init 0.90 s of which
  `parrot.plugins`→`navconfig.logging` 0.58 s; redaction→vault→documentdb
  0.28 s; `tools.abstract`→events/conf→`navigator` auth 0.25 s; pandas
  0.22 s), the F015/F016 spawn→ready timings (≈2.4 s idle, 12–14 s under 3×
  CPU oversubscription) with F015's raw timeline, a fill-in-the-blanks
  **"4. Affected host — TO BE FILLED IN (U3b)"** section (import profile,
  spawn→ready from logs, host context), and a follow-up section scoping the
  import-trim spec with its ceiling (~0.22 s vs 1.41 s today).
- `artifacts/` IS git-ignored (`git check-ignore -v` → `.gitignore:283`), so
  the profile was staged with `git add -f`, matching the
  `feat-380-rlimit-as-calibration.md` precedent.
- **Message-string fidelity**: every error/log string in the docs was copied
  from the implemented code, not the spec — grepped
  `handle.py:300` (`REPL worker pid=... did not become ready within ... ms
  (...); stderr tail: ...`), `handle.py:459` (`repl_worker[pid=...]: '<op>'
  request did not answer within ...s; the worker is still alive and the late
  reply will be drained on the next call`), `pool.py` (`possible restart loop
  (last worker exit code=..., stderr tail=...)`, `prewarmed worker ready
  (pid=..., bootstrap_ms=..., pool size=...)`) and `worker.py`
  (`repl_worker: ready in <N> ms (...), entering service loop`).
- Verification (the task's grep pass, plus an import check): all documented
  names appear in the docs (`bootstrap_timeout_ms` ×7, `namespace_timeout_ms`
  ×5, `ReadyResponse` ×6, `NamespaceTimeoutError` ×7, `possible restart loop`
  ×3) and all resolve in `src/` — confirmed by actually importing
  `WorkerConfig`, `ReadyResponse`, `NamespaceTimeoutError`,
  `WorkerBootstrapError` and asserting the defaults (30 000/30 000) plus the
  presence of `WorkerHandle.wait_ready`/`is_ready` and
  `WorkerPool.restart_count`.
- The Windows section was left accurate and unchanged: the ready frame is
  plain pipe I/O and the timeout-kill mapping is untouched.
- No product code and no test files were touched by this task.

**Deviations from spec**: none
