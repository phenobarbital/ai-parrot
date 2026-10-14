# TASK-3256: Lazy `parrot.auth` package root + import-ceiling test harness

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 identifies `parrot/auth/__init__.py` as **gateway #1**: importing
`parrot.auth.exceptions` (whose only import is `typing`) costs **1178** modules
today (re-measured 2026-09-15 on `dev` @ `2c54cbac2`) because the package root
eagerly imports `.pbac` → `parrot.conf` → navconfig, redis, asyncdb, asyncpg,
aiohttp, faiss and navigator_eventbus. `parrot/knowledge/ontology/mixin.py:65`
imports `AuthorizationRequired` from there, so every graph module that touches
`ontology.schema` pays it.

This task implements spec §3 **Module 1, first step** ("land `parrot/auth` first
and re-measure"): a PEP 562 lazy root for `parrot.auth`, plus the subprocess
import-ceiling harness that every later FEAT-540 task is measured against
(spec §4 `test_import_ceilings`, `test_auth_root_lazy`; spec §5 AC 3).

`parrot/auth/__init__.py` is on the **request path of the whole server**
(spec §7 Known Risks). Laziness must not change *what* callers get — only when
they pay for it. Run the auth + handlers suites, not just the graph tests.

---

## Scope

- Replace the eager imports in `packages/ai-parrot/src/parrot/auth/__init__.py`
  (lines 29-82) with a PEP 562 `_LAZY_ATTRS` name→submodule map, a module-level
  `__getattr__` that imports the submodule, caches the value in `globals()`, and
  returns it, and a `__dir__` returning `sorted(set(globals()) | set(__all__))`.
- Keep `__all__` **byte-identical in content and order** (43 names, lines 84-142),
  and keep the module docstring.
- Create the ceiling harness `packages/ai-parrot/tests/knowledge/test_import_ceilings.py`
  with the `import_ceiling` fixture (subprocess per measurement) and all five
  ceiling cases from design D2. Only the `parrot.auth.exceptions` case is active;
  the other four carry `pytest.mark.xfail(strict=False, reason=...)` naming the
  task that lands them.
- Create `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` with
  `test_auth_root_lazy` (subprocess-based as well).
- Run the full `packages/ai-parrot/tests/auth/` and `packages/ai-parrot/tests/handlers/`
  suites plus `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py`.

**NOT in scope**:
- `parrot/knowledge/ontology/__init__.py`, `parrot/stores/__init__.py`,
  `wiki/documents.py` — TASK-3257.
- Removing the xfail marks from the other ceiling cases — TASK-3257 (ontology.schema)
  and TASK-3268 (the rest).
- Changing any `parrot/auth/*` submodule (`pbac.py`, `conf` usage, etc.).
- The AST scan test — TASK-3268.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Eager imports → PEP 562 lazy root |
| `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` | CREATE | Subprocess ceiling harness, 5 parametrized cases |
| `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` | CREATE | `test_auth_root_lazy` (TASK-3257 appends ontology/stores/documents tests) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.auth.exceptions import AuthorizationRequired   # verified: parrot/auth/exceptions.py:12
from parrot.auth import setup_pbac                         # verified today via eager root; parrot/auth/pbac.py
import importlib                                           # stdlib
import subprocess, sys, os, json                           # stdlib (test harness)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/__init__.py  — EAGER today
# lines 1-27  module docstring (keep verbatim)
from .context import UserContext                                   # line 29
from .permission import PermissionContext, UserSession             # line 30
from .resolver import (AbstractPermissionResolver, AllowAllResolver,
    DefaultPermissionResolver, DenyAllResolver, PBACPermissionResolver)  # lines 31-37
from .pbac import setup_pbac                                       # line 38  ← the expensive one
from .eval_context import build_eval_context                       # line 41
from .userinfo import EmployeeProfile, UserInfoService             # line 44
from .dataset_guard import DatasetPolicyGuard                      # line 45
from .dataplane_guard import DataPlanePolicyGuard                  # line 46
from .rls_registry import RlsRegistry, RlsRule, RlsPredicate       # line 47
from .models import PolicyRuleConfig                               # line 48
from .exceptions import AuthorizationRequired                      # line 49
from .agent_guard import AgentAccessDenied                         # line 50
from .credentials import (CredentialResolver, OAuthCredentialResolver,
    StaticCredentialResolver, StaticCredentials, AuthKind, ProviderCredentialConfig,
    ResolvedCredential, NeedsAuth, CredentialRequired)             # lines 51-62
from .broker import CredentialBroker, CredentialResolverFactory    # line 64
from .grants import (Grant, GrantConfig, GrantStore, InMemoryGrantStore,
    GrantGuard, GuardDecision)                                     # lines 66-73
from .confirmation import (ConfirmationConfig, ConfirmationDecision,
    ConfirmationWindowStore, InMemoryConfirmationWindowStore,
    ConfirmationGuard, compute_args_hash)                          # lines 75-82
__all__ = [ ... 43 names ... ]                                     # lines 84-142

# packages/ai-parrot/src/parrot/auth/exceptions.py — imports ONLY typing
from __future__ import annotations                                 # line 7
from typing import List, Optional                                  # line 9
class AuthorizationRequired(Exception): ...                        # line 12

# packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py
from parrot.auth.exceptions import AuthorizationRequired           # line 65

# Pattern precedent (PEP 562 root) — packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py
_EXPORT_MODULES: dict[str, str] = {...}                            # line 45
__all__ = list(_EXPORT_MODULES)                                    # line 85
def __getattr__(name: str): ...                                    # line 88
def __dir__() -> list[str]: ...                                    # line 113
```

**Complete name → submodule map** (43 names, verified by reading the file):

| submodule | names |
|---|---|
| `.context` | `UserContext` |
| `.permission` | `PermissionContext`, `UserSession` |
| `.resolver` | `AbstractPermissionResolver`, `AllowAllResolver`, `DefaultPermissionResolver`, `DenyAllResolver`, `PBACPermissionResolver` |
| `.pbac` | `setup_pbac` |
| `.eval_context` | `build_eval_context` |
| `.userinfo` | `EmployeeProfile`, `UserInfoService` |
| `.dataset_guard` | `DatasetPolicyGuard` |
| `.dataplane_guard` | `DataPlanePolicyGuard` |
| `.rls_registry` | `RlsRegistry`, `RlsRule`, `RlsPredicate` |
| `.models` | `PolicyRuleConfig` |
| `.exceptions` | `AuthorizationRequired` |
| `.agent_guard` | `AgentAccessDenied` |
| `.credentials` | `CredentialResolver`, `OAuthCredentialResolver`, `StaticCredentialResolver`, `StaticCredentials`, `AuthKind`, `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth`, `CredentialRequired` |
| `.broker` | `CredentialBroker`, `CredentialResolverFactory` |
| `.grants` | `Grant`, `GrantConfig`, `GrantStore`, `InMemoryGrantStore`, `GrantGuard`, `GuardDecision` |
| `.confirmation` | `ConfirmationConfig`, `ConfirmationDecision`, `ConfirmationWindowStore`, `InMemoryConfirmationWindowStore`, `ConfirmationGuard`, `compute_args_hash` |

Measured baseline (2026-09-15, this venv): `import parrot` → 94 modules, no heavy
package; `parrot.auth.exceptions` → 1178 modules with navconfig, parrot.conf,
navigator_eventbus, asyncdb, faiss, redis, asyncpg, aiohttp loaded.

### Does NOT Exist
- ~~`parrot/auth/__init__.py` `__getattr__` / `_LAZY_ATTRS`~~ — created by this task.
- ~~`packages/ai-parrot/tests/knowledge/test_import_ceilings.py`~~ / ~~`test_lazy_package_roots.py`~~ — created by this task.
- ~~A `conftest.py` `import_ceiling` fixture~~ — the fixture lives inside `test_import_ceilings.py`.
- ~~An in-process way to reset `sys.modules`~~ — every count MUST fork a subprocess (spec §7).
- ~~`parrot.auth.exceptions` importing anything framework~~ — it imports only `typing`; do not edit it.

---

## Implementation Notes

### Key Constraints
- `__all__` content and order unchanged; every name in `__all__` must be a key of `_LAZY_ATTRS` and vice versa (add a test).
- `__getattr__` raises `AttributeError(f"module {__name__!r} has no attribute {name!r}")` for unknown names — `hasattr()` and `mock.patch` rely on it.
- Submodule attribute access (`parrot.auth.pbac`) is still resolved by the import system for `import parrot.auth.pbac`; only *implicit* submodule attributes created as side effects of the eager root disappear. Audit (`grep -rn "parrot\.auth\.[a-z_]*\.[A-Za-z]" packages/*/src`) — at /sdd-task time only docstring `:class:` references were found.
- Subprocess must inherit `os.environ` (worktrees set `PYTHONPATH`).
- Count `len(sys.modules)` **before** importing `json` in the child script.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py:44-116` — PEP 562 root pattern to copy.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:117-143` — second precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Measure the baseline in a subprocess (`python -c "import sys, parrot.auth.exceptions; print(len(sys.modules))"`) and paste it into the Completion Note — *why*: spec §3 demands re-measuring before touching the other two roots.
2. Write `test_import_ceilings.py` and `test_lazy_package_roots.py` first and see the auth cases fail — *why*: the harness is the objective gate; TDD proves it measures a cold interpreter.
3. Replace lines 29-82 of `parrot/auth/__init__.py` with the lazy map + `__getattr__` + `__dir__` — *why*: gateway #1 is the eager `.pbac` import.
4. Re-run the auth ceiling test; then run `pytest packages/ai-parrot/tests/auth packages/ai-parrot/tests/handlers packages/ai-parrot/tests/knowledge/test_ontology_mixin.py -q` — *why*: auth is on the server request path (spec §7).
5. Run `ruff check` on the three files.

### `packages/ai-parrot/src/parrot/auth/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from .pbac import setup_pbac$' packages/ai-parrot/src/parrot/auth/__init__.py)
# REPLACE — lines 29-82 (from `from .context import UserContext` through the closing `)` of
# the `.confirmation` import). Keep the docstring (1-27) and `__all__` (84-142) untouched.
# Then APPEND `__getattr__` / `__dir__` after the closing `]` of `__all__` (line 142).
import importlib
from typing import Any

# Name -> defining submodule (PEP 562 lazy root, FEAT-540). Importing any single
# name (e.g. ``parrot.auth.exceptions``) no longer executes ``.pbac`` ->
# ``parrot.conf`` -> navconfig. What callers get is unchanged; only when they pay.
_LAZY_ATTRS: dict[str, str] = {
    "UserContext": ".context",
    "PermissionContext": ".permission",
    "UserSession": ".permission",
    "AbstractPermissionResolver": ".resolver",
    "AllowAllResolver": ".resolver",
    "DefaultPermissionResolver": ".resolver",
    "DenyAllResolver": ".resolver",
    "PBACPermissionResolver": ".resolver",
    "setup_pbac": ".pbac",
    "build_eval_context": ".eval_context",
    "EmployeeProfile": ".userinfo",
    "UserInfoService": ".userinfo",
    "DatasetPolicyGuard": ".dataset_guard",
    "DataPlanePolicyGuard": ".dataplane_guard",
    "RlsRegistry": ".rls_registry",
    "RlsRule": ".rls_registry",
    "RlsPredicate": ".rls_registry",
    "PolicyRuleConfig": ".models",
    "AuthorizationRequired": ".exceptions",
    "AgentAccessDenied": ".agent_guard",
    "CredentialResolver": ".credentials",
    "OAuthCredentialResolver": ".credentials",
    "StaticCredentialResolver": ".credentials",
    "StaticCredentials": ".credentials",
    "AuthKind": ".credentials",
    "ProviderCredentialConfig": ".credentials",
    "ResolvedCredential": ".credentials",
    "NeedsAuth": ".credentials",
    "CredentialRequired": ".credentials",
    "CredentialBroker": ".broker",
    "CredentialResolverFactory": ".broker",
    "Grant": ".grants",
    "GrantConfig": ".grants",
    "GrantStore": ".grants",
    "InMemoryGrantStore": ".grants",
    "GrantGuard": ".grants",
    "GuardDecision": ".grants",
    "ConfirmationConfig": ".confirmation",
    "ConfirmationDecision": ".confirmation",
    "ConfirmationWindowStore": ".confirmation",
    "InMemoryConfirmationWindowStore": ".confirmation",
    "ConfirmationGuard": ".confirmation",
    "compute_args_hash": ".confirmation",
}
```

### `packages/ai-parrot/src/parrot/auth/__init__.py` (MODIFY, second block)
```python
# occurrences: 1 (verified: grep -c '^__all__ = \[$' packages/ai-parrot/src/parrot/auth/__init__.py)
# AFTER — append below the closing `]` of `__all__` (verified: packages/ai-parrot/src/parrot/auth/__init__.py:142)
def __getattr__(name: str) -> Any:
    """Resolve a public export lazily on first attribute access (PEP 562).

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public ``parrot.auth`` export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, __name__), name)
    globals()[name] = value  # cache: subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and IDE completion."""
    return sorted(set(globals()) | set(__all__))
```
**Why this shape**: spec §7 "PEP 562 lazy root — module-level `__getattr__` + a complete `__all__`… Do not delete names." The existing FEAT-comment lines inside the old import block (FEAT-446/406/264/211/235) should be preserved as comments next to the matching map entries — they document provenance. `importlib.import_module(".x", __name__)` names a module, not an object (spec §7 "Lazy imports name modules, not objects").

### `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (CREATE)
```python
"""Import-ceiling gate for FEAT-540 (spec §5).

Module counts are NOT resettable in-process, so every measurement forks a
fresh interpreter (spec §7 Known Risks).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable

import pytest

FORBIDDEN: tuple[str, ...] = (
    "navconfig", "parrot.conf", "navigator_eventbus", "asyncdb",
    "pandas", "faiss", "pyarrow", "redis", "asyncpg",
)

_CHILD = (
    "import sys\n"
    "{stmt}\n"
    "count = len(sys.modules)\n"
    "import json\n"
    "print(json.dumps([count, [p for p in {forbidden!r} if p in sys.modules]]))\n"
)


@pytest.fixture
def import_ceiling() -> Callable[[str], tuple[int, list[str]]]:
    """Run one import statement in a clean subprocess.

    Returns:
        A callable ``(stmt) -> (module_count, heavy_loaded)``.
    """
    def _run(stmt: str) -> tuple[int, list[str]]:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD.format(stmt=stmt, forbidden=FORBIDDEN)],
            capture_output=True, text=True, env=os.environ.copy(), timeout=300, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        # FILL IN: parse the LAST stdout line only — bounded by: some imports print
        # banners to stdout (navconfig side effects, see wiki/mcp_server.py:34-40).
        raise NotImplementedError
    return _run


CASES = [
    pytest.param("from parrot.auth.exceptions import AuthorizationRequired", 150, id="auth.exceptions"),
    pytest.param("import parrot.knowledge.ontology.schema", 240, id="ontology.schema",
                 marks=pytest.mark.xfail(strict=False, reason="FEAT-540: lands in TASK-3257")),
    pytest.param("import parrot.knowledge.graphindex", 800, id="graphindex",
                 marks=pytest.mark.xfail(strict=False, reason="FEAT-540: gate in TASK-3268")),
    pytest.param("import parrot.knowledge.graphindex.builder", 1200, id="graphindex.builder",
                 marks=pytest.mark.xfail(strict=False, reason="FEAT-540: gate in TASK-3268")),
    pytest.param("import parrot.knowledge.wiki.cli", 850, id="wiki.cli",
                 marks=pytest.mark.xfail(strict=False, reason="FEAT-540: gate in TASK-3268")),
]


@pytest.mark.parametrize(("stmt", "ceiling"), CASES)
def test_import_ceilings(import_ceiling, stmt: str, ceiling: int) -> None:
    """Each entry-point import stays under its module ceiling and loads no heavy package."""
    count, heavy = import_ceiling(stmt)
    assert not heavy, f"{stmt!r} loaded forbidden packages: {heavy}"
    assert count <= ceiling, f"{stmt!r} loaded {count} modules (ceiling {ceiling})"
```
**Why this shape**: spec §4 fixture + §5 ceilings verbatim. `strict=False` on later cases because an intermediate task may make a case pass early; TASK-3268 removes every mark. Do not raise a ceiling to make a case pass — ESCALATE instead.

### `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` (CREATE)
```python
"""Lazy package roots keep their public names (FEAT-540, spec §4 Module 1)."""
from __future__ import annotations

import os
import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    """Execute ``code`` in a fresh interpreter (sys.modules must be cold)."""
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=os.environ.copy(), timeout=300, check=False)


def test_auth_root_lazy() -> None:
    """``parrot.auth.exceptions`` imports without ``.pbac`` / ``parrot.conf``; lazy names still resolve."""
    # FILL IN: child asserts 'parrot.auth.pbac' and 'parrot.conf' NOT in sys.modules after
    # `from parrot.auth.exceptions import AuthorizationRequired`, then that
    # `from parrot.auth import setup_pbac` resolves and `parrot.auth.pbac` IS now loaded
    # — bounded by spec §4 `test_auth_root_lazy`.
    raise NotImplementedError


def test_auth_all_matches_lazy_map() -> None:
    """Every ``__all__`` name is lazily resolvable and ``dir()`` exposes it."""
    import parrot.auth as auth

    assert set(auth.__all__) == set(auth._LAZY_ATTRS)
    # FILL IN: getattr every name in __all__ (resolves each), assert set(__all__) <= set(dir(auth))
    raise NotImplementedError
```
**Why**: in-process access to `__all__` is fine for identity checks; only the "absent from sys.modules" assertion needs a subprocess.

### FILL IN checklist
- [ ] `test_import_ceilings.py::import_ceiling._run` — parse the last stdout line as JSON; bounded by stdout banners.
- [ ] `test_lazy_package_roots.py::test_auth_root_lazy` — subprocess assertions; bounded by spec §4.
- [ ] `test_lazy_package_roots.py::test_auth_all_matches_lazy_map` — resolve every name; bounded by "Do not delete names".
- [ ] `auth/__init__.py` — preserve the FEAT provenance comments beside the map entries.

---

## Addendum — repo-root `tests/` tree (review, 2026-09-15)

Note: the repo-root `tests/` tree (CI runs it; root `pyproject.toml` `testpaths=["tests"]`) also consumes `parrot.auth` — e.g. `tests/auth/test_policy_rule_config.py:9,175` (`from parrot.auth import PolicyRuleConfig`). Run `pytest tests/auth/ -v` in addition to the package suites.

---

## Acceptance Criteria

- [ ] `from parrot.auth.exceptions import AuthorizationRequired` loads **≤ 150** modules in a clean subprocess and none of the FORBIDDEN packages (spec §5 AC 3)
- [ ] `from parrot.auth import <every name in __all__>` still resolves to the same objects as `from parrot.auth.<submodule> import <name>`
- [ ] `__all__` content and order unchanged (diff shows no change on lines 84-142)
- [ ] `pytest packages/ai-parrot/tests/knowledge/test_import_ceilings.py packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py -v` — auth cases pass, other ceiling cases XFAIL/XPASS (non-strict)
- [ ] `pytest packages/ai-parrot/tests/auth packages/ai-parrot/tests/handlers packages/ai-parrot/tests/knowledge/test_ontology_mixin.py -q` passes (same failures as baseline on `dev`, if any — record them)
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/__init__.py packages/ai-parrot/tests/knowledge/test_import_ceilings.py packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` clean
- [ ] Google-style docstrings + type hints on `__getattr__`, `__dir__`, fixture and tests
- [ ] Repo-root auth tests pass: `pytest tests/auth/ -v`

---

## Test Specification

See the two CREATE blocks above — they are the scaffold. Minimum passing set:
`test_import_ceilings[auth.exceptions]`, `test_auth_root_lazy`,
`test_auth_all_matches_lazy_map`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-grep `parrot/auth/__init__.py` (new names may have been added since 2026-09-15; every name added to `__all__` must enter `_LAZY_ATTRS`)
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (the shared venv is editable against the main checkout)
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-3256-auth-lazy-root-and-ceiling-harness.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below (include before/after module counts)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
