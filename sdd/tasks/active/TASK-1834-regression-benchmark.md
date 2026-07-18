# TASK-1834: Full regression, neutrality grep guard, and FEAT-177 benchmark

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1833
**Assigned-to**: unassigned

---

## Context

Module 9 of spec §3 — the closing gate. Run the full test suite across all
three packages, prove no lingering references to the deleted modules remain,
verify the editable install resolves cleanly, and confirm the FEAT-177
emit-overhead budget (< 0.1% LLM-latency) is not regressed by the migration.

---

## Scope

- Run the full test suite:
  `pytest` for `ai-parrot`, `ai-parrot-server`, `ai-parrot-integrations`.
  Triage and fix any residual import/rewiring failures (small mechanical fixes
  are in scope; a genuine design gap gets a note back to the spec, not a redesign).
- **Neutrality/lingering-reference grep guard** (must all be empty except the
  `parrot.core.hooks.__init__` / `parrot.core.events.lifecycle.__init__`
  facades and this feature's own SDD docs):
  ```bash
  grep -rn "from parrot.core.events.bus\|import parrot.core.events.bus" packages/*/src
  grep -rn "from parrot.core.events.evb\|import parrot.core.events.evb" packages/*/src
  grep -rn "from parrot.core.hooks.base\|from parrot.core.hooks.models\|from parrot.core.hooks.manager" packages/*/src | grep -v "core/hooks/__init__.py"
  ```
- Confirm deleted paths are gone:
  `parrot/core/events/{evb.py,bus/}`,
  `parrot/core/events/lifecycle/{base,trace,meta,registry,global_registry,provider,mixin}.py`,
  `parrot/core/events/lifecycle/subscribers/{logging,webhook}.py`,
  `parrot/core/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py`,
  `parrot/core/hooks/brokers/`.
- Clean-venv install proof:
  ```bash
  uv venv /tmp/feat317-verify && source /tmp/feat317-verify/bin/activate
  uv pip install -e /home/jesuslara/proyectos/navigator-eventbus
  uv pip install -e packages/ai-parrot
  python -c "from navigator_eventbus import EventBus; from parrot.core.events.lifecycle.events import BeforeInvokeEvent; from parrot.core.hooks import BaseHook; print('OK')"
  ```
- **FEAT-177 benchmark**: run the emit-overhead script and compare against the
  FEAT-310 baseline. Locate the script first (spec references
  `scripts/bench/feat310_emit_overhead.py`; if the path differs, find it with
  `find . -path '*bench*emit*'` / `grep -rl "emit_overhead" scripts`). Confirm
  < 0.1% overhead / no regression (same machine, within noise).
- Run `ruff` (and `mypy` where the project runs it) on the full set of changed
  files.
- Record evidence under `artifacts/logs/` (test summary, grep-guard output,
  benchmark numbers).

**NOT in scope**: new features; PyPI publication; touching `navigator-eventbus`
source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (source, as needed) | MODIFY | small mechanical fixes for residual failures only |
| `artifacts/logs/feat317-regression.md` | CREATE | test/grep/benchmark evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified commands / paths

```bash
# per-package pytest roots — VERIFIED present 2026-07-18:
packages/ai-parrot/tests/         packages/ai-parrot-server/tests/
packages/ai-parrot-integrations/  (integration tests as present)

# benchmark script — VERIFY exact path before running:
#   spec cites scripts/bench/feat310_emit_overhead.py
find . -path '*bench*' -name '*emit*'  ;  grep -rl "emit_overhead\|feat310" scripts 2>/dev/null
```

### Import invariants to assert (post-migration)

```python
# MUST fail:
import parrot.core.events.bus         # ModuleNotFoundError
import parrot.core.events.evb         # ModuleNotFoundError
import parrot.core.hooks.base         # ModuleNotFoundError
import parrot.core.hooks.models       # ModuleNotFoundError
# MUST succeed (facades + local + package):
from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext
from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from parrot.core.hooks import BaseHook, HookManager, HookEvent
from navigator_eventbus import EventBus, EventEnvelope, Severity
```

### Does NOT Exist
- ~~a FEAT-310 baseline number embedded in this repo~~ — capture the current
  package run and compare against the FEAT-310 spec/benchmark record; if no
  stored baseline exists, record the absolute overhead and assert it is
  < 0.1% (the FEAT-177 budget), noting the absence of a delta baseline.

---

## Implementation Notes

### Key Constraints
- `source .venv/bin/activate` before any python/uv/pytest command.
- If a test failure reveals a MISSING rewire (a file TASK-1830–1833 forgot),
  fix the import here and note which task under-covered it — do NOT redesign.
- Keep the clean-venv verify isolated in `/tmp` so it does not disturb `.venv`.

### References in Codebase
- Spec §3 Module 9, §5 "Acceptance Criteria", §4 Integration Tests.

---

## Acceptance Criteria

- [ ] Full `pytest` green across ai-parrot, ai-parrot-server, ai-parrot-integrations.
- [ ] All three grep-guard commands return empty (excluding the two `__init__.py` facades and SDD docs).
- [ ] All deleted paths confirmed absent.
- [ ] Clean-venv install + smoke import succeeds.
- [ ] FEAT-177 emit-overhead benchmark < 0.1% / no regression; numbers recorded.
- [ ] `ruff check` clean across changed files.
- [ ] Evidence written to `artifacts/logs/feat317-regression.md`.

---

## Test Specification

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests -q
pytest packages/ai-parrot-server/tests -q
# grep guards (expect empty)
grep -rn "parrot.core.events.bus\|parrot.core.events.evb" packages/*/src || echo "clean: no bus/evb refs"
grep -rn "from parrot.core.hooks.base\|from parrot.core.hooks.models\|from parrot.core.hooks.manager" packages/*/src | grep -v "core/hooks/__init__.py" || echo "clean: no old hooks refs"
```

---

## Agent Instructions

1. Verify TASK-1833 completed.
2. Update index → `in-progress`.
3. Run full suite + grep guards + clean-venv verify + benchmark.
4. Fix only residual mechanical failures; record evidence.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
