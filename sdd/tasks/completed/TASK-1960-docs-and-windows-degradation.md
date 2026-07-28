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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**:
- `docs/repl-worker-sandbox.md` (new, added to `mkdocs.yml` nav under
  "Tools, Loaders & RAG" next to the existing "Sandbox Tool" entry): covers
  §1 execution model (ASCII diagram adapted from the spec, host-gate →
  worker-revalidation flow, `execute_sync()` called out as the one
  unaffected in-process escape hatch), §2 failure modes (table: gate
  denial / timeout / memory / crash / ceiling / TTL, plus the exact
  namespace-loss error JSON shape), §3 every `WorkerConfig` field with its
  REAL current default (all 7 spot-checked against `protocol.py` at
  writing time, including the 12 GiB TASK-1946-calibrated `rlimit_as_bytes`
  with a link to the evidence file) and tuning notes, §4 the namespace API
  (`get_var`/`set_var`/`list_vars`/`snapshot`/`inject_dataframe`, explicit
  "no sync variant, no dict-proxy" framing, and the `WorkingMemoryToolkit`
  snapshot-semantics note from TASK-1944), §5 **Windows degradation as a
  visible, top-level ⚠️-marked section** with an explicit guarantee-by-
  guarantee table (AC16), §6 a brief history note. Opens with an explicit
  Non-Goals framing (resource bounding, not adversarial containment,
  shares kernel/network/FS with host) per the spec's own Non-Goals section.
- Verified every documented symbol against the actual code (not the spec's
  aspiration) via grep spot-checks: all 7 `WorkerConfig` fields + defaults,
  `PythonREPLTool`'s 5 namespace-API method signatures + `worker_config`
  kwarg, `executor_max_workers` default, `WorkerPoolExhaustedError`'s exact
  message wording.
- **Cross-links** (AC: "stale docs/ references... updated"): grepped
  `docs/` for `python_repl`/`PythonREPLTool` and reviewed every hit.
  `docs/CLASSES.md`, `docs/jupyter_mode.md`, `docs/datasetmanager_design.md`,
  `docs/pandas-agent-capabilities.md` needed no changes — they describe
  `PythonREPLTool` at a level of abstraction (class catalog entries,
  LLM-facing behavior) this feature doesn't change. Two files DID need a
  cross-link: `docs/executors/docker-executor.md` (a genuinely different,
  complementary isolation layer — relocates the whole tool call to a
  remote Docker/K8s runtime; added a note distinguishing it from the
  worker-process model) and `docs/sandbox_tool.md` (a gVisor installation
  guide describing kernel-level containment that is **not** what's
  actually implemented — added a note pointing at the real mechanism
  before a reader could be misled into thinking gVisor is wired in).
  `docs/outputs.md`'s `PythonREPLTool(globals_dict=...)` example was
  reviewed but left untouched — see Deviations.

**Deviations from spec**:
1. **`docs/outputs.md`'s `PythonREPLTool(globals_dict={'folium': folium})`
   example was NOT updated**, despite `globals_dict` no longer reaching the
   worker (a real, already-documented TASK-1943 limitation). That file
   imports from a non-existent `aiparrot` package (`from aiparrot import
   Agent`, `from aiparrot.tools import PythonREPLTool` — the real package
   is `parrot`, not `aiparrot`) — it was already aspirational/non-canonical
   before this feature, unrelated to anything this task changed. Editing
   it correctly would require broader context about what that document
   actually is (marketing copy? a different distribution name?) than a
   docs-only task focused on the worker execution model should guess at.
   Flagged here rather than silently skipped.
2. **No mkdocs build/render verification** — `mkdocs.yml` uses
   mkdocs-material's custom Python-object YAML tags
   (`!!python/name:material.extensions.emoji.twemoji`), so it can't be
   parsed with plain `yaml.safe_load` in this environment (no mkdocs
   installed as a dev dependency here); verified the nav entry's
   indentation matches its siblings exactly by inspection instead of a
   full `mkdocs build`.
