# TASK-1960: Documentation — execution model, deployment config, Windows degradation

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1939, TASK-1943, TASK-1944, TASK-1945
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 / AC16. The REPL's execution model changed fundamentally:
LLM code now runs in a per-session worker process with rlimits, deadlines,
and a namespace API. Operators need the deployment knobs; agent/bot authors
need the new failure modes (namespace loss!) and the namespace API; and the
**Windows degradation must be documented visibly** — separate process +
hard timeout + terminate, but **no memory/CPU rlimits** (AC16).

---

## Scope

- Create `docs/repl-worker-sandbox.md` (or the fitting location under the
  existing `docs/` layout — inspect it first and follow its conventions)
  covering:
  - **Execution model**: host gate → worker revalidation → `exec` in the
    worker; per-session isolation; spawn-only; component diagram (adapt the
    spec §2 ASCII diagram).
  - **Failure modes**: timeout → SIGKILL + namespace loss; memory →
    RLIMIT_AS kill; crash; pool ceiling rejection; TTL eviction. Include the
    structured error the LLM sees (cause, lost variables, recreate-state
    instruction).
  - **Deployment configuration**: every `WorkerConfig` field, default, and
    tuning guidance (incl. the calibrated RLIMIT_AS and its evidence link —
    coordinate with TASK-1946 if it has landed; otherwise document the
    provisional default and mark it).
  - **Namespace API** for integrators: `get_var`/`set_var`/`list_vars`/
    `snapshot`; the removal of direct `.locals`/`.globals` access; snapshot
    semantics (frozen at capture).
  - **⚠ Windows degradation (visible, top-level section — AC16)**: worker
    runs as a separate process with hard timeout + `TerminateProcess`, but
    NO memory/CPU rlimits; Job Objects listed as future follow-up.
  - The dedicated-executor palliative (TASK-1939) as a note in the
    changelog/history section.
- Cross-link from any existing docs that describe `PythonREPLTool` or the
  data-analysis agent (grep `docs/` for `python_repl` / `PythonREPLTool` and
  update those mentions).
- Verify every documented API/name against the implemented code (docs are
  written last for a reason — no aspirational content).

**NOT in scope**: code changes (docs-only, except docstring touch-ups if a
public API lacks one); marketing/README overhauls; ShellTool docs (separate
feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/repl-worker-sandbox.md` | CREATE | Execution model, failure modes, config, namespace API, Windows section |
| `docs/**` (grep hits for python_repl) | MODIFY | Update stale references to the in-process model |

---

## Codebase Contract (Anti-Hallucination)

> Docs must describe the code **as merged by TASK-1939–1945**, not the spec's
> aspiration. Verify each item below against the implementation before
> writing it down.

### Verified Imports (to document)

```python
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError
from parrot.tools.repl_worker.handle import WorkerHandle
# PythonREPLTool.get_var / set_var / list_vars / snapshot (async)
```

### Existing Signatures to Use

```python
# WorkerConfig fields to document (confirm final defaults in protocol.py,
# especially rlimit_as_bytes after TASK-1946):
rlimit_as_bytes, rlimit_cpu_seconds, rlimit_nofile,
deadline_ms, max_workers, idle_ttl_seconds, prewarm_pool_size
```

```python
# The G5 contract to document for error consumers:
# success → str
# error → {"status": "error" | "done_with_errors", "result": ..., "error": ...}
# post-kill errors embed: cause (timeout|memory|crash), lost_variables, message
```

### Does NOT Exist

- ~~rlimit enforcement on Windows~~ — that is the point of AC16; document
  the degradation, never imply parity.
- ~~In-process fallback~~ — G8: if the worker cannot start, the tool errors.
  Docs must not suggest any silent fallback exists.
- ~~A dict-proxy for `tool.locals`~~ — rejected; docs must direct
  integrators to the namespace API.
- ~~Container isolation~~ — Option C is future work; do not present the
  worker as an adversarial security boundary (spec Non-Goals: it shares
  kernel/network/FS with the host).

---

## Implementation Notes

### Key Constraints

- The Windows section must be **visible**: own heading near the top with a
  warning admonition, not a footnote (AC16 says "de forma visible").
- Be explicit about what the sandbox is NOT (resource bounding, not
  adversarial containment) — copy the framing from spec Non-Goals.
- Check `docs/` structure first (`ls docs/`) and match the existing format
  (plain markdown vs mkdocs/sphinx conventions).
- Every config default cited must be copied from the code at writing time,
  not from the spec.

### References in Codebase

- `sdd/specs/sandbox-hardening.spec.md` §2 (diagram, protocol table), §5
  (ACs), Non-Goals.
- `artifacts/logs/feat-380-rlimit-as-calibration.md` (TASK-1946 evidence),
  if present.

---

## Acceptance Criteria

- [ ] `docs/repl-worker-sandbox.md` covers execution model, failure modes,
      all `WorkerConfig` fields with real defaults, and the namespace API.
- [ ] Windows degradation documented visibly (own warning section) — AC16.
- [ ] Non-goal framing present: resource bounding, not adversarial
      containment.
- [ ] Stale `docs/` references to the in-process REPL model updated.
- [ ] Every documented symbol exists in the code (spot-check by import).
- [ ] No linting errors on any touched Python docstrings; markdown renders
      cleanly.

---

## Test Specification

Docs task — no test scaffold. Verification is the AC checklist above plus:

```bash
# every documented default matches the code
grep -n "rlimit_as_bytes\|deadline_ms\|idle_ttl_seconds\|prewarm_pool_size" \
  docs/repl-worker-sandbox.md \
  packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1939, TASK-1943, TASK-1944, TASK-1945 must
   be in `sdd/tasks/completed/` (TASK-1946 ideally too; else mark the
   provisional default)
3. **Verify the Codebase Contract** — import-check every symbol you document
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1960-docs-and-windows-degradation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
