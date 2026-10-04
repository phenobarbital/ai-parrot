# TASK-3976: Tool scope contract — Protocols, ToolScopeUnavailable, require/ensure_tool_scope, tenant_bound (M3a)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Wave**: 1 (spec §9) · **Module**: M3a tool-scope-contract

---

## Context

Spec §1 P2: a tool cannot learn the agent's tenant or its caller; `PermissionContext.tenant_id` is
untrustworthy and toolkit instances are shared. Spec §2 "Overview" item 2, "Data Models" and "Scope rules"
define the read-only contract: `ToolScopeView` Protocols over `current_context().kwargs["studio_scope"]`
(produced by FEAT-605 v0.2), the accessor pair `current_tool_scope()` / `require_tool_scope()`, the standard
refusal `ToolScopeUnavailable`, `is_tenant_bound()` and `ensure_tool_scope()`. M3a adds **no call sites**:
enforcement is M3b (TASK-3989/TK-16), binding is M5 (TASK-3991).

---

## Scope

- Create `parrot/tools/scope.py` with `ToolAccess`, `CallerView`, `AgentScopeView`, `ToolScopeView`
  (`typing.Protocol`, `runtime_checkable` not required), `ScopeRefusal`, `ToolScopeUnavailable`,
  `current_tool_scope()`, `require_tool_scope()`, `is_tenant_bound()`, `ensure_tool_scope()` — signatures
  exactly as spec §2 "Data Models" / "New Public Interfaces".
- `require_tool_scope` order (spec "Scope rules"): no context or `ctx.request is None` → `no_context`;
  `studio_scope` absent → `no_scope`; `caller.tenant is None` → `no_tenant`; agent present with
  `tenant is None` → `agent_tenant_unset`; `agent.tenant != caller.tenant` → `tenant_mismatch`; else
  return `(caller.tenant, scope)`.
- `is_tenant_bound(cls_or_instance)`: effective flag = `tenant_bound` is True **or** any
  `server_managed_params` value has `source in {"tenant","caller","agent"}` (read with `getattr`, works
  before M4 exists); a `ToolkitTool` instance inherits its owning toolkit's flag
  (`bound_method.__self__`).
- `ensure_tool_scope(cls_or_instance, *, tool_name=None)`: no-op when not tenant-bound, otherwise
  `require_tool_scope(tool_name=...)`.
- Add `tenant_bound: ClassVar[bool] = False` to `AbstractToolkit` and to `AbstractTool`.
- Unit test `test_require_scope_refusals`.

**NOT in scope**: any call site (the `AbstractTool.execute` gate, `config_options` wrapper, handler checks:
TASK-3989/TK-16); binding `studio_scope` anywhere (TASK-3991); `server_managed_params` / `ServerParam`
(TASK-3985); `host_tenant_mismatch` raising (host code only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/scope.py` | CREATE | Protocols, refusals, accessors, is_tenant_bound, ensure_tool_scope |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | add `tenant_bound: ClassVar[bool] = False` to AbstractToolkit |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | add `tenant_bound: ClassVar[bool] = False` to AbstractTool |
| `packages/ai-parrot/tests/tools/test_tool_scope.py` | CREATE | M3a unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.utils.helpers import RequestContext, current_context  # utils/helpers.py:7, :58
from parrot.utils.helpers import _current_ctx  # utils/helpers.py:53 — tests set/reset it directly
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:  # :7
    def __init__(self, request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs)  # :21-29
    self.request  # :31
    self.kwargs: dict  # :36 — studio_scope will live in kwargs["studio_scope"]
_current_ctx: ContextVar[Optional[RequestContext]]  # :53
def current_context() -> Optional[RequestContext]  # :58

# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):  # :37 — self.bound_method (:55); owning toolkit = bound_method.__self__ (:162)
class AbstractToolkit(ABC):  # :203
    options_params: ClassVar[frozenset[str]] = frozenset()  # :327  ← anchor (occurrences: 1)

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # :281
    delegate_description: Optional[str] = None  # :342  ← anchor (occurrences: 1)
```

### Does NOT Exist
- ~~`studio_scope` in any `RequestContext` today~~ — FEAT-605 v0.2 W2.1/W3.4/W3.5 and this feature's M5 bind it; `grep -rn studio_scope packages` finds nothing in code.
- ~~`StudioToolScope`, `RequestScope`, `StudioAgentRef`, `build_tool_scope`~~ — FEAT-605 (server `handlers/studio/access.py`); core must NOT import them. Tests here use a test-local frozen dataclass that satisfies the Protocols.
- ~~an agent back-reference on a toolkit instance~~ — none; do not add one.
- ~~a trustworthy `PermissionContext.tenant_id`~~ — defaults to the principal (`auth/permission.py:199-205`); never read it.
- ~~`ServerParam` / `server_managed_params`~~ — TASK-3985; `is_tenant_bound` reads them with `getattr` and duck-typed `.source`.
- ~~`__init_subclass__` on `AbstractToolkit` / `AbstractTool`~~ — does not exist today (`grep -n __init_subclass__` → 0); not added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/scope.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_tool_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#RequestContext",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#current_context",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Structured refusal modelled on `AuthorizationRequired` (`parrot/auth/exceptions.py:12`): an exception
  with a class-level `code` and a `reason` attribute; M3b converts it to a `ToolResult`.
- Per-call state only through the ContextVar (`current_context()`), never on an instance (spec §7).
- `scope.py` must not import `parrot.tools.abstract` / `toolkit` at module top (they will import
  `scope.py` in M3b): detect `ToolkitTool` by duck typing (`getattr(obj, "bound_method", None)`).

### Cross-feature ordering
- None. Wave 1, no sibling dependency. The Protocol attribute names mirror FEAT-605 v0.2's
  `RequestScope` / `StudioAgentRef` (X9, X11); if FEAT-605 renames them, only the Protocol attribute names
  adapt here (spec §8 row 1).

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `scope.py` from the block — *why*: names and the refusal order are fixed by the spec and consumed by FEAT-605 / FEAT-621.
2. Add the `tenant_bound` ClassVar lines to both base classes — *why*: hosts set it declaratively; M3b reads it via `is_tenant_bound`.
3. Write `test_require_scope_refusals` parametrized over every `ScopeRefusal` except `host_tenant_mismatch`, using a real `RequestContext` set on `_current_ctx` (set/reset) — *why*: spec §4 M3a row.

### `packages/ai-parrot/src/parrot/tools/scope.py` (CREATE)
```python
"""Tool scope contract (FEAT-622 M3a): what a tool may read from ``studio_scope``."""
from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from parrot.utils.helpers import current_context

ToolAccess = Literal["read", "write"]
ScopeRefusal = Literal[
    "no_context", "no_scope", "no_tenant", "agent_tenant_unset", "tenant_mismatch", "host_tenant_mismatch",
]
_SCOPE_SOURCES = frozenset({"tenant", "caller", "agent"})


class CallerView(Protocol):
    """Satisfied by FEAT-605 ``RequestScope``."""

    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool


class AgentScopeView(Protocol):
    """Satisfied by FEAT-605 ``StudioAgentRef``."""

    agent_id: UUID | None
    name: str
    owner: str | None
    tenant: str | None
    visibility: str


class ToolScopeView(Protocol):
    """Required shape of ``current_context().kwargs["studio_scope"]``."""

    caller: CallerView
    agent: AgentScopeView | None


class ToolScopeUnavailable(Exception):
    """Standard refusal of a tenant-bound tool / options provider."""

    code: ClassVar[str] = "tool_scope_unavailable"

    def __init__(self, reason: ScopeRefusal, *, tool_name: str | None = None) -> None:
        self.reason: ScopeRefusal = reason
        self.tool_name = tool_name
        super().__init__(f"{self.code}: {reason}" + (f" ({tool_name})" if tool_name else ""))


def current_tool_scope() -> ToolScopeView | None:
    """Return the bound ``studio_scope`` or ``None`` (no request context, or nothing bound)."""
    ctx = current_context()
    if ctx is None or ctx.request is None:
        return None
    return ctx.kwargs.get("studio_scope")


def require_tool_scope(*, tool_name: str | None = None) -> tuple[str, ToolScopeView]:
    """Return ``(tenant, scope)`` or raise :class:`ToolScopeUnavailable` (spec "Scope rules" order)."""
    # FILL IN: the five checks in the exact spec order (no_context, no_scope, no_tenant,
    #   agent_tenant_unset, tenant_mismatch) — bounded by spec §2 "Scope rules"; caller is the principal
    raise NotImplementedError


def is_tenant_bound(cls_or_instance: type | object) -> bool:
    """Effective flag: ``tenant_bound`` or a scope-sourced server-managed param; ToolkitTool inherits."""
    owner = getattr(getattr(cls_or_instance, "bound_method", None), "__self__", None)
    if owner is not None:
        return is_tenant_bound(owner)
    if getattr(cls_or_instance, "tenant_bound", False):
        return True
    params: Any = getattr(cls_or_instance, "server_managed_params", None) or {}
    return any(getattr(param, "source", None) in _SCOPE_SOURCES for param in params.values())


def ensure_tool_scope(cls_or_instance: type | object, *, tool_name: str | None = None) -> None:
    """No-op when not tenant-bound; otherwise :func:`require_tool_scope` (handlers, before construction)."""
    if is_tenant_bound(cls_or_instance):
        require_tool_scope(tool_name=tool_name)
```
**Why this shape**: Protocols keep core free of server imports (spec §7). The scope reader returns
`None` when `ctx.request is None` so scheduler/A2A shapes are `no_context` (RC-5).

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'options_params: ClassVar\[frozenset\[str\]\] = frozenset()' toolkit.py)
# AFTER — insert below `    options_params: ClassVar[frozenset[str]] = frozenset()` (verified: toolkit.py:327)
    #: FEAT-622 — True when this toolkit reads tenant data; tools then refuse without a matching
    #: ``studio_scope`` (enforced by AbstractTool.execute, FEAT-622 M3b). See parrot.tools.scope.
    tenant_bound: ClassVar[bool] = False
```

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'delegate_description: Optional\[str\] = None' abstract.py)
# AFTER — insert below `    delegate_description: Optional[str] = None` (verified: abstract.py:342)
    # FEAT-622: standalone tools that read tenant data set this; see parrot.tools.scope.
    tenant_bound: ClassVar[bool] = False
```
**Why**: declaration only — no behaviour changes in this task (M3a "No call site changes").

### FILL IN checklist
- [ ] `scope.py::require_tool_scope` — check order and returned tuple; bounded by spec §2 "Scope rules".

---

## Acceptance Criteria

- [ ] `from parrot.tools.scope import ToolScopeUnavailable, current_tool_scope, require_tool_scope, is_tenant_bound, ensure_tool_scope` works.
- [ ] Each `ScopeRefusal` (except `host_tenant_mismatch`, host-raised) is produced by the right condition, in the spec order.
- [ ] `ToolScopeUnavailable.code == "tool_scope_unavailable"`; `.reason` carries the refusal.
- [ ] `is_tenant_bound` is True for `tenant_bound=True`, for a scope-sourced server-managed param (duck-typed), and for a `ToolkitTool` of a tenant-bound toolkit.
- [ ] No call site changed; existing tests pass: `pytest packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py -q`.
- [ ] `scope.py` imports nothing from `parrot.tools.abstract`/`toolkit` or from ai-parrot-server.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_tool_scope.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_tool_scope.py
from dataclasses import dataclass, field
import pytest
from aiohttp.test_utils import make_mocked_request
from parrot.utils.helpers import RequestContext, _current_ctx
from parrot.tools.scope import ToolScopeUnavailable, require_tool_scope, is_tenant_bound


@dataclass(frozen=True)
class _Caller:  # Protocol-conforming test double for FEAT-605 RequestScope (real type arrives in Wave 4 tests)
    user_id: str | None = "u1"
    tenant: str | None = "acme"
    groups: frozenset = field(default_factory=frozenset)
    is_superuser: bool = False


@pytest.mark.parametrize("reason", ["no_context", "no_scope", "no_tenant", "agent_tenant_unset", "tenant_mismatch"])
def test_require_scope_refusals(reason):
    """Each ScopeRefusal from a real RequestContext / no context."""
    # FILL IN: build the context for `reason` with make_mocked_request("POST", "/x"); set via _current_ctx.set,
    #   reset in finally; assert ToolScopeUnavailable(...).reason == reason


def test_require_scope_returns_caller_tenant():
    """Happy path returns (caller.tenant, scope); the caller is the principal."""
    # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: scope.py plus tenant_bound ClassVar on AbstractToolkit/AbstractTool; 12 tests pass incl. test_toolkit_config_hooks. No call sites changed.
**Mutation evidence**: Removed agent_tenant_unset/tenant_mismatch checks -> those parametrized cases RED; removed tenant_bound getattr -> is_tenant_bound tests RED.

**Deviations from spec**: none
