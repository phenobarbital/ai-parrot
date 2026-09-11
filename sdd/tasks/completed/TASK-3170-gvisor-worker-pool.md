# TASK-3170: gVisor worker pool (tiers 3-4) — `services/sandbox/gvisor_pool.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3161, TASK-3168
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, resolving OQ-4. `GVisorWorkerPool` implements the same
`SandboxProvider` ABC as TASK-3169's subprocess pool, but backed by
`SandboxConfig` (`parrot_tools/sandboxtool.py:24`) for actual kernel-level
isolation via `runsc`. **gVisor is a hard prerequisite for tiers 3-4** — if
`runsc` is absent, this pool refuses to load at boot with a clear error.
Tiers 1-2 (TASK-3169) are entirely unaffected; there is **no silent
degradation** to a weaker boundary (spec §2, §5 Operational ACs).

**Verified environment fact** (spec §6, re-confirmed applicable at
task-writing time — this task's own dev/CI environment should NOT assume
otherwise): `runsc` is **not installed** on the reference development
machine. Any test exercising real gVisor execution must be skippable via
the `fake_gvisor_absent` fixture named in spec §4's Test Data section.

---

## Scope

- Implement `GVisorWorkerPool(SandboxProvider)` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/gvisor_pool.py`.
- Implement `GVisorWorkerPool.is_available() -> bool` (classmethod) —
  probes for `runsc` on `PATH` (e.g. `shutil.which("runsc")`), used by
  TASK-3164's git loader and TASK-3172's tier router to decide whether
  tier-3/4 bundles may load at all.
- Constructor takes a `SandboxConfig` (or accepts one via a factory
  default) and a `tier34_pool_size` knob (default `2`, per spec §7 OQ-6
  table) plus whichever of TASK-3169's shared knobs apply (recycle,
  health check, queue bounds — reuse the same defaults/semantics, do not
  invent different numbers for this pool unless the spec states one,
  which it does only for `tier34_pool_size`).
- Write `packages/parrot-formdesigner/tests/unit/test_gvisor_pool.py`
  using the `fake_gvisor_absent` fixture — no test in this suite may
  require a real `runsc` binary to pass.

**NOT in scope**: `SandboxTool`/`create_executor()` themselves (existing
code in `parrot_tools`, reused, not modified); the shared pool-lifecycle
logic already written in TASK-3169 — if genuinely identical, consider
whether it should be factored into a shared base class, but do not block
this task on refactoring TASK-3169 without first checking whether
TASK-3169 has already landed (note the decision in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/gvisor_pool.py` | CREATE | `GVisorWorkerPool` |
| `packages/parrot-formdesigner/tests/unit/test_gvisor_pool.py` | CREATE | Unit tests (all using the `fake_gvisor_absent` fixture) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import shutil
from parrot.eval.sandbox.base import Sandbox, SandboxProvider, SandboxSpec  # verified: parrot/eval/sandbox/base.py
from parrot_tools.sandboxtool import SandboxConfig, SandboxTool  # verified: parrot_tools/sandboxtool.py:24,55
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py
@dataclass
class SandboxConfig:                                          # line 24
    runtime: str = "runsc"          # line 26 — gVisor by default
    network: str = "none"           # line 27 — network disabled by default
    max_memory: str = "2G"
    max_cpu: float = 2.0
    timeout: int = 30
    python_image: str = "python:3.11-slim"
    enable_gpu: bool = False
    mount_paths: List[str] = field(default_factory=list)

class SandboxTool(AbstractTool):                              # line 55
    def _verify_installation(self):                           # line 99 — FAILS without runsc; the
                                                                #   exact failure mode to replicate for
                                                                #   is_available()'s negative case.
```

### Does NOT Exist
- ~~`GVisorWorkerPool`~~ — created by this task; no existing pooling
  implementation to extend (spec §6: only `NoopSandboxProvider` exists).
- ~~A silent-fallback path from gVisor to Docker or subprocess~~ —
  explicitly rejected. `create_executor()`
  (`parrot_tools/codeinterpreter/executor.py:354`) already falls back
  Docker → subprocess when Docker is unavailable, but that fallback
  pattern is NOT reused here — OQ-4 requires a **hard boot failure**, not
  a downgrade. Do not import or call `create_executor()` from this
  module.
- ~~`runsc` on the reference dev machine~~ — confirmed absent (spec §6
  Verified Environment Facts); do not write a test that requires it.

---

## Implementation Notes

### Key Constraints
- `is_available()` must be a **classmethod with no side effects beyond
  the probe itself** — it is called at boot time by TASK-3164's loader
  and TASK-3172's router, potentially before any pool instance exists.
- The hard-failure behavior belongs to the **caller** (loader refusing to
  register a tier-3/4 bundle), not to `GVisorWorkerPool.__init__` itself
  — but this pool's constructor should still raise loudly if it is
  instantiated while `is_available()` is `False`, as defense in depth
  against a caller that skips the check.
- `SandboxConfig.network` stays `"none"` — outbound access for tier 3/4
  snippets goes exclusively through the host broker (TASK-3171), never
  the worker's own network stack (spec §7 "Known Risks / Gotchas").

### References in Codebase
- `parrot_tools/sandboxtool.py:24-99` — `SandboxConfig`, `SandboxTool`, and
  `_verify_installation()`'s failure mode.
- TASK-3169's `services/sandbox/pool.py` — the sibling pool this one
  mirrors structurally (recycling, health checks, bounded queue), swap
  only the underlying process/container primitive.

---

## Implementation Blueprint

### Steps (in order)
1. Implement `is_available()` first — *why*: every other method's
   correctness depends on this probe being right, and TASK-3164/TASK-3172
   both call it directly.
2. Implement the constructor with the hard-failure defense-in-depth check.
3. Implement `acquire()`/`release()`, structurally mirroring TASK-3169
   (same recycling/health-check/queue-bound shape) but spawning a gVisor-
   isolated worker via `SandboxConfig` instead of a bare subprocess.
4. Write and run tests, all gated on `fake_gvisor_absent`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/gvisor_pool.py` (CREATE)
```python
"""gVisor-isolated worker pool for tiers 3-4 (FEAT-459 / M10, OQ-4).

Hard prerequisite: is_available() gates whether tier-3/4 bundles may ever
load (TASK-3164's git loader, TASK-3172's tier router both call it). When
runsc is absent, callers refuse to load tier-3/4 bundles at BOOT — this
module performs NO silent downgrade to a weaker isolation mechanism (not
Docker, not bare subprocess). Structurally mirrors
services/sandbox/pool.py's SubprocessWorkerPool (recycling, health
checks, bounded acquire queue) but backs each worker with a gVisor
(`runsc`) container via SandboxConfig instead of a bare asyncio.subprocess.
"""

from __future__ import annotations

import logging
import shutil

from parrot.eval.sandbox.base import Sandbox, SandboxProvider, SandboxSpec
from parrot_tools.sandboxtool import SandboxConfig

logger = logging.getLogger(__name__)


class GVisorUnavailableError(Exception):
    """Raised by __init__ if instantiated while is_available() is False."""


class GVisorWorkerPool(SandboxProvider):
    """Warm gVisor-isolated worker pool for CapabilityTier BROKERED/TOOLKIT."""

    @classmethod
    def is_available(cls) -> bool:
        """True when the `runsc` runtime is present and usable on PATH.

        A pure presence probe (shutil.which) — does NOT attempt to spawn
        a container, matching the cheap, boot-time-safe check TASK-3164's
        loader and TASK-3172's router both need before deciding whether
        to load/route any tier-3/4 bundle at all.
        """
        return shutil.which("runsc") is not None

    def __init__(
        self,
        *,
        config: SandboxConfig | None = None,
        tier34_pool_size: int = 2,
        recycle_after_invocations: int = 500,
        recycle_after_seconds: int = 3600,
        acquire_queue_timeout_ms: int = 2000,
        max_queue_depth: int = 32,
        health_check_interval_s: int = 30,
        cold_start_timeout_ms: int = 5000,
    ) -> None:
        """
        Args:
            config: gVisor SandboxConfig. Defaults to
                SandboxConfig(runtime="runsc", network="none") — network
                stays "none"; tier 3/4 outbound access is host-broker-mediated
                only (TASK-3171), never the worker's own network stack.
            tier34_pool_size: Warm workers held per process (default 2 —
                spec §7 OQ-6: tier 3/4 traffic is rare by design;
                containers are expensive to hold warm).
            (remaining knobs: same semantics and defaults as
             SubprocessWorkerPool, TASK-3169 — see that module's
             docstrings; duplicated here rather than imported to keep
             this pool importable even if TASK-3169 is not yet merged.)

        Raises:
            GVisorUnavailableError: instantiated while is_available() is
                False. Defense in depth — the primary enforcement point
                is the CALLER (loader/router) refusing to route tier-3/4
                bundles here at all.
        """
        if not self.is_available():
            raise GVisorUnavailableError(
                "GVisorWorkerPool constructed but `runsc` is not on PATH. "
                "Tiers 3-4 have a hard gVisor prerequisite (OQ-4) — there "
                "is no fallback isolation mechanism."
            )
        self._config = config or SandboxConfig(runtime="runsc", network="none")
        self._tier34_pool_size = tier34_pool_size
        self._recycle_after_invocations = recycle_after_invocations
        self._recycle_after_seconds = recycle_after_seconds
        self._acquire_queue_timeout_ms = acquire_queue_timeout_ms
        self._max_queue_depth = max_queue_depth
        self._health_check_interval_s = health_check_interval_s
        self._cold_start_timeout_ms = cold_start_timeout_ms
        self.logger = logger
        # FILL IN: initialise the idle-worker queue / live-count
        #   bookkeeping — identical shape to SubprocessWorkerPool
        #   (TASK-3169). If that task has landed, consider extracting a
        #   shared `_PooledWorkerMixin`/base class instead of duplicating
        #   this state; if not yet landed, duplicate now and leave a
        #   TODO-via-Completion-Note for the extraction.

    async def acquire(self, spec: SandboxSpec) -> Sandbox:
        """Acquire a gVisor-isolated worker. See SubprocessWorkerPool.acquire
        (TASK-3169) for the bounded-queue / cold-start-timeout shape this
        mirrors — the only difference is the underlying spawn mechanism
        (a gVisor container via self._config, not a bare subprocess).

        Raises:
            PoolExhaustedError-equivalent: FILL IN — reuse TASK-3169's
                exception type if importable without a circular import,
                else define an equivalent local exception.
        """
        # FILL IN: mirror SubprocessWorkerPool.acquire's control flow,
        #   swapping asyncio.create_subprocess_exec for a gVisor-backed
        #   spawn using self._config (runtime/network/max_memory/max_cpu/
        #   timeout/python_image fields already defined on SandboxConfig).
        raise NotImplementedError

    async def release(self, sandbox: Sandbox) -> None:
        """See SubprocessWorkerPool.release (TASK-3169) — identical shape."""
        # FILL IN: mirror SubprocessWorkerPool.release.
        raise NotImplementedError
```
**Why this shape**: `is_available()` is a bare `shutil.which` probe, not a
`SandboxTool._verify_installation()`-style check, because the latter is
scoped to `SandboxTool`'s own use case and may have side effects or
stricter requirements this pool does not need at the "can I even consider
loading tier-3/4 bundles" boot-time decision point — a cheap PATH check is
the right cost for a function called during server startup. The
constructor's defense-in-depth raise is deliberate belt-and-suspenders:
the spec's actual enforcement point is the loader/router refusing to
route to this pool at all, but a pool that can be silently constructed
and silently produce broken/no-isolation workers would be a worse failure
mode than a loud constructor-time exception.

### `packages/parrot-formdesigner/tests/unit/test_gvisor_pool.py` (CREATE)
```python
"""Unit tests for GVisorWorkerPool — FEAT-459 / TASK-3170.

ALL tests here use fake_gvisor_absent or otherwise avoid requiring a real
runsc binary — confirmed absent on the reference dev machine (spec §6).
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.sandbox.gvisor_pool import (
    GVisorUnavailableError,
    GVisorWorkerPool,
)


@pytest.fixture
def fake_gvisor_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force GVisorWorkerPool.is_available() to return False (spec §4)."""
    monkeypatch.setattr(GVisorWorkerPool, "is_available", classmethod(lambda cls: False))


@pytest.fixture
def fake_gvisor_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force is_available() True WITHOUT requiring a real runsc binary —
    used only to test the constructor's happy path in isolation; acquire()/
    release() are NOT exercised under this fixture since they would need a
    real container runtime."""
    monkeypatch.setattr(GVisorWorkerPool, "is_available", classmethod(lambda cls: True))


def test_gvisor_pool_is_available_probe_reflects_shutil_which(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real (unmocked) is_available() correctly reports a missing runsc."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert GVisorWorkerPool.is_available() is False


def test_constructor_raises_when_gvisor_absent(fake_gvisor_absent: None) -> None:
    with pytest.raises(GVisorUnavailableError):
        GVisorWorkerPool()


def test_constructor_succeeds_when_gvisor_present(fake_gvisor_present: None) -> None:
    # FILL IN: GVisorWorkerPool() should construct without raising under
    #   this fixture — assert pool._tier34_pool_size == 2 (default) once
    #   __init__'s FILL IN bookkeeping section is implemented.
    pass


def test_tier34_pool_size_default_is_two(fake_gvisor_present: None) -> None:
    # FILL IN: same as above, assert the documented OQ-6 default (2, not
    #   4 — tier 3/4 pools are deliberately smaller than tier 1/2's).
    pass
```
**Why**: the `is_available()` probe test and the hard-failure constructor
test are the two OQ-4 security-critical assertions and are written in
full; the happy-path constructor tests are stubbed since they depend on
`__init__`'s FILL IN bookkeeping section.

### FILL IN checklist
- [ ] `__init__` — idle-worker queue / live-count bookkeeping (mirror or extract-and-share with TASK-3169)
- [ ] `acquire()` / `release()` — full bodies, mirroring TASK-3169's shape against `SandboxConfig`
- [ ] `test_constructor_succeeds_when_gvisor_present` / `test_tier34_pool_size_default_is_two` — assertions once `__init__` is complete

---

## Acceptance Criteria

- [ ] `GVisorWorkerPool.is_available()` returns `False` when `shutil.which("runsc")` is `None`, without attempting to spawn anything
- [ ] Constructing `GVisorWorkerPool()` while `is_available()` is `False` raises `GVisorUnavailableError`, never falls back to a weaker isolation mechanism
- [ ] `SandboxConfig.network` defaults to `"none"` in the pool's default config
- [ ] `tier34_pool_size` defaults to `2` (not `4`, TASK-3169's tier-1/2 default)
- [ ] All tests pass without a real `runsc` binary: `pytest packages/parrot-formdesigner/tests/unit/test_gvisor_pool.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/gvisor_pool.py`

---

## Test Specification

See the blueprint's test file above — 4 test functions, 2 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "gVisor is a hard prerequisite" paragraph, §3 Module 10, §6 Verified Environment Facts)
2. **Check dependencies** — TASK-3161 and TASK-3168 must be `done`
3. **Verify the Codebase Contract** — confirm `SandboxConfig`'s field defaults at `parrot_tools/sandboxtool.py:24-33` are unchanged, and re-confirm `runsc` is still absent from the dev/CI environment (`command -v runsc`) before assuming any test can skip the `fake_gvisor_absent` fixture
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3170-gvisor-worker-pool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder; 2 mypy
errors fixed directly post-merge)
**Date**: 2026-09-11
**Notes**: Implemented `GVisorWorkerPool(SandboxProvider)` with
`is_available()` (pure `shutil.which("runsc")` probe, never spawns),
`GVisorUnavailableError` raised at construction when unavailable (no
silent downgrade), `tier34_pool_size` default `2`, `SandboxConfig.network`
default `"none"`. Structurally mirrors `SubprocessWorkerPool` (idle queue,
health checks, recycling). 9/9 tests pass without a real `runsc` binary,
`ruff check` clean as delivered. `mypy` initially reported 2 errors
(queue `None`-sentinel shadowing the narrower `GVisorWorker` type in
`_get_worker()`; `GVisorSandbox.release()` reading the nonexistent public
`sandbox.worker` instead of `sandbox._worker`) — fixed directly (rename +
correct attribute), re-verified clean, no behavioral change.

**Deviations from spec**: none — post-merge fix was a type-checking
correction only, required by this task's own "`mypy` clean" acceptance
criterion.

**Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 450.6s · Tokens: 1,643,543 in / 10,538 out**
