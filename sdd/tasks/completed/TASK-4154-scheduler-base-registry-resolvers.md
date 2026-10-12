# TASK-4154: base.py foundations: errors, ScheduleType, TargetResolver, TargetRegistry, RegistryResolver, fire-context injection

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4147
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, first slice. `base.py` must not import `parrot.manager` / `parrot.bots` / `parrot.registry` (AC1),
and `manager.py` will import `base.py` (TASK-4158) — so everything both need lives here: the error types, the
`ScheduleType` enum, the run-now job-id prefix, the async resolver contract (design research S1), the manager-scoped
target registry with a method allowlist (S5), the prompt-to-signature mapping (moved from
`packages/ai-parrot-server/src/parrot/scheduler/manager.py:441-468`) and the `fire_id`/`scheduled_at` injection by signature (spec G6, AC13).

---

## Scope

- Create `base.py` with: `ScheduleType` (copy of manager.py:71 members), `_RUN_NOW_JOB_PREFIX = "run_now:"`, `TargetMissingError`, `SchedulerUnavailableError`, `NotEditableError`, `SchedulerRunNowConflictError`.
- Add the `TargetResolver` Protocol (async `resolve`, `derive_target_id`, `build_call`) exactly as spec §2.
- Add `TargetRegistry` (per-kind dicts; `register` validates `methods` with `clean_method_name`-equivalent rules; `allowed_methods`).
- Add module functions `apply_prompt_signature(method, call_args, call_kwargs, prompt)` (moved logic of manager.py:441) and `inject_fire_context(method, call_kwargs, fire)`.
- Add `RegistryResolver(registry)` for `kind='service'`.
- Re-export `utcnow` from `.models`; write `tests/scheduler/test_base_registry.py`.

**NOT in scope**: the `SchedulerManager` class (TASK-4155+); `AgentResolver`/`CrewResolver` (TASK-4158); removing anything from manager.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | CREATE | Errors, ScheduleType, resolver protocol, registry, RegistryResolver, injection helpers |
| `packages/ai-parrot-server/tests/scheduler/test_base_registry.py` | CREATE | Registry, resolver and injection tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.scheduler.models import FireContext, JobDefinition, utcnow   # TASK-4147
import inspect, logging
from enum import Enum
from typing import Any, Optional, Protocol, Sequence, runtime_checkable
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:71 — copy members verbatim into base.ScheduleType
class ScheduleType(Enum):
    ONCE = "once"; DAILY = "daily"; WEEKLY = "weekly"; MONTHLY = "monthly"
    INTERVAL = "interval"; CRON = "cron"; CRONTAB = "crontab"
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:83
class SchedulerRunNowConflictError(Exception): ...
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:95
_RUN_NOW_JOB_PREFIX = "run_now:"
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:441-468 — logic to move into apply_prompt_signature (first positional param ← prompt via setdefault;
#   else *args → append; else **kwargs → setdefault("prompt", prompt)); returns (call_args, call_kwargs)
def _apply_prompt_signature(self, method, call_args, call_kwargs, prompt): ...
```

### Does NOT Exist
- ~~`parrot.scheduler.base`~~ — created here.

- ~~`BotManager`, `parrot.manager`, `parrot.bots`, `parrot.registry` imports in `base.py`~~ — forbidden (spec AC1); agent/crew resolution lives in `manager.py` (TASK-4158).
- ~~`from .manager import ...` in `base.py`~~ — circular (manager imports base). `ScheduleType`, `SchedulerRunNowConflictError` and `_RUN_NOW_JOB_PREFIX` are defined in `base.py` (TASK-4154); `manager.py` re-exports them in TASK-4158.
- ~~`AgentSchedule` in `base.py`~~ — base uses `ServiceSchedule` only.
- ~~`datetime.now()` in `base.py`~~ — use `utcnow()` everywhere (AC7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/base.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_base_registry.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#ScheduleType",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#SchedulerRunNowConflictError",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._apply_prompt_signature"
  ]
}
```

---

## Implementation Notes

### `inject_fire_context(method, call_kwargs, fire)`
`target = inspect.unwrap(method)`; `sig = inspect.signature(target)` (on `TypeError/ValueError` return kwargs
unchanged). For `name in ("fire_id", "scheduled_at")`: inject `getattr(fire, name)` when `name in sig.parameters` or
any parameter is `VAR_KEYWORD`; never overwrite a key already present. A wrapper without `__wrapped__` whose own
signature is `(*args, **kwargs)` DOES accept them — that is fine: the `@schedule` decorator sets `__wrapped__` via
`functools.wraps`, so unwrap reaches the real method.

### `TargetRegistry`
`register(name, obj, *, kind="service", methods=None)`: store `obj` under `(kind, name)`; `methods` → frozenset after
checking each is a public identifier (no leading `_`) — else `ValueError`. `get` returns `None` when absent.

### `RegistryResolver.build_call(target, definition, fire)`
`method_name` required (else `ValueError`); reject `_`-prefixed names; enforce `allowed_methods` when set (else
`ValueError(f"method {name!r} not allowed for service {target_name!r}")`); `getattr(target, method_name)` must be
callable; `call_kwargs = dict(definition.metadata)`; `apply_prompt_signature` when `prompt` is not None; then
`inject_fire_context`. Return `(args, kwargs)` — the spec skeleton fixes this return type. The manager then calls
`getattr(target, definition.method_name or "chat")(*args, **kwargs)`: `build_call` is the validator and argument
builder, `_execute_job` (TASK-4157) is the single place that invokes. (`"chat"` only applies to the agent kind,
whose resolver accepts a prompt-only definition — TASK-4158.)

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Write the module header, `ScheduleType`, prefix and the four error classes — *why*: manager.py re-exports them so handler imports stay stable.
2. Write `TargetResolver` and `TargetRegistry` — *why*: async resolution (S1) and per-manager registration (G1).
3. Move the prompt-signature logic into `apply_prompt_signature` and add `inject_fire_context` — *why*: shared by every resolver.
4. Write `RegistryResolver` with allowlist + private-name rejection (S5).
5. Write the tests and run them.

### `packages/ai-parrot-server/src/parrot/scheduler/base.py` (CREATE)
```python
"""Target-agnostic scheduler base (FEAT-644): resolver contract, registry and the SchedulerManager."""
from __future__ import annotations

import inspect
import logging
from enum import Enum
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from .models import FireContext, JobDefinition, utcnow

__all__ = (
    "ScheduleType", "TargetMissingError", "SchedulerUnavailableError", "NotEditableError",
    "SchedulerRunNowConflictError", "TargetResolver", "TargetRegistry", "RegistryResolver",
    "apply_prompt_signature", "inject_fire_context", "utcnow",
)

logger = logging.getLogger("Parrot.Scheduler")

_RUN_NOW_JOB_PREFIX = "run_now:"
_FIRE_CONTEXT_PARAMS = ("fire_id", "scheduled_at")


class ScheduleType(Enum):
    """Schedule execution types."""
    # FILL IN: the 7 members verbatim from manager.py:71.


class TargetMissingError(LookupError):
    """The resolver returned None or raised: the target is not available in this process."""


class SchedulerUnavailableError(RuntimeError):
    """Coordination backend or jobstore unavailable — mapped to HTTP 503."""


class NotEditableError(ValueError):
    """Mutation of a code-declared or external job — mapped to HTTP 409."""


class SchedulerRunNowConflictError(Exception):
    """A run-now execution is already active for the schedule — mapped to HTTP 409."""


@runtime_checkable
class TargetResolver(Protocol):
    """Strategy resolving a ``target_kind`` to a live object (``resolve`` is async — S1)."""

    kind: str

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None: ...
    def derive_target_id(self, target: Any) -> str | None: ...
    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]: ...
```
**Why**: these names are imported by manager.py, handlers and tests in later tasks; defining them once here is what
lets `base.py` stay free of `manager.py` imports.

```python
# (continued, same file)
class TargetRegistry:
    """Manager-scoped explicit registrations, keyed by ``(kind, name)``."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], Any] = {}
        self._methods: dict[tuple[str, str], frozenset[str]] = {}

    def register(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None:
        """Register ``obj``; ``methods`` is the allowlist (public identifiers only)."""
        # FILL IN: validate methods (ValueError on '_' prefix / non-identifier); store.

    def unregister(self, name: str, *, kind: str = "service") -> None: ...  # FILL IN
    def get(self, name: str, *, kind: str = "service") -> Any | None: ...  # FILL IN
    def allowed_methods(self, name: str, *, kind: str = "service") -> frozenset[str] | None: ...  # FILL IN


def apply_prompt_signature(method: Any, call_args: list[Any], call_kwargs: dict[str, Any],
                           prompt: Any) -> tuple[list[Any], dict[str, Any]]:
    """Inject ``prompt`` into the call (moved from AgentSchedulerManager._apply_prompt_signature)."""
    # FILL IN: exact logic of manager.py:441-468.


def inject_fire_context(method: Any, call_kwargs: dict[str, Any], fire: FireContext) -> dict[str, Any]:
    """Add ``fire_id`` / ``scheduled_at`` only when the innermost signature declares them or takes ``**kwargs``."""
    # FILL IN: Implementation Notes; never overwrite an existing key.


class RegistryResolver:
    """``service`` kind: objects registered via ``register_target``."""

    kind: str = "service"

    def __init__(self, registry: TargetRegistry) -> None:
        self._registry = registry

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Return the registered object or None; never raises."""
        return self._registry.get(name, kind=self.kind)

    def derive_target_id(self, target: Any) -> str | None:
        """Services carry no target id."""
        return None

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """Validate the method (required, public, allow-listed) and build args/kwargs."""
        # FILL IN: Implementation Notes (RegistryResolver.build_call).
```

### FILL IN checklist
- [ ] `ScheduleType` members.
- [ ] `TargetRegistry` methods + allowlist validation (S5).
- [ ] `apply_prompt_signature` — exact move of manager.py:441-468.
- [ ] `inject_fire_context` (AC13).
- [ ] `RegistryResolver.build_call` — method required/public/allow-listed; metadata → kwargs.

---

## Acceptance Criteria

- [ ] `base.py` contains no import of `parrot.manager`, `parrot.bots`, `parrot.registry` or `.manager`.
- [ ] `TargetRegistry.register('svc', obj, methods=['_x'])` raises `ValueError`.
- [ ] `RegistryResolver.build_call` rejects missing, private, and non-allow-listed `method_name`.
- [ ] `inject_fire_context` injects into `def f(prompt, *, fire_id=None)` and `def g(**kw)`, not into `def h(prompt)`; unwraps `functools.wraps` decorators.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_base_registry.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_base_registry.py
def test_registry_register_get_unregister(): ...
def test_registry_rejects_private_methods(): ...
async def test_registry_resolver_resolves_service(): ...
def test_build_call_requires_method_name(): ...
def test_build_call_enforces_allowlist(): ...
def test_private_method_rejected(): ...
def test_fire_context_injected_by_signature(): ...       # declared / **kwargs / neither / @wraps-decorated
def test_apply_prompt_signature_matches_legacy(): ...    # first positional, *args, **kwargs cases
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4154 — base.py foundations: errors, ScheduleType, TargetResolver, TargetRegistry, RegistryResolver, fire-context injection`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4154 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4154 — base.py foundations: errors, ScheduleType, TargetResolver, TargetRegistry, RegistryResolver, fire-context injection`

---

## Completion Note

**Completed by**: sdd-worker (coder seat: gpt-5.6-terra)
**Date**: 2026-10-08
**Notes**: Implemented as specified and merged into the feature branch. Direct run of packages/ai-parrot-server/tests/scheduler passed. The merge-tier validation was red only because of an unrelated pre-existing studio test collection error (ledger issue:d5a7c625fbe7); closed on direct test evidence.

**Deviations from spec**: none
