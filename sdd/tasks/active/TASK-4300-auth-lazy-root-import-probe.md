# TASK-4300: Lazy parrot.auth package root + subprocess import-probe harness

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1/§3 M1. `parrot/auth/__init__.py:29-48` eagerly imports `.pbac` (→ `parrot.conf` → navconfig/redis), so `from parrot.auth.exceptions import AuthorizationRequired` costs 1093 modules for a `typing`-only module. It is the biggest gateway on every graph entry point; land it first together with the measurement harness.

---

## Scope

- Turn `parrot/auth/__init__.py` into a PEP 562 lazy root: same `__all__`, `_LAZY_ATTRS` name→submodule map, cached `__getattr__`, `__dir__`.
- Create `tests/knowledge/_support/import_probe.py`: fresh `python -I` subprocess probe returning count + loaded forbidden prefixes (root and dotted) + python/revision/error.
- Create `tests/knowledge/test_import_ceilings.py`: parametrized over the five §1 entry points; only `parrot.auth.exceptions` (≤150) is enforced now, the other four are `xfail(strict=False)` until TASK-4333 activates them.
- Create `tests/knowledge/test_auth_lazy_root.py`: every public name still resolves; `dir()` lists them; importing `parrot.auth.exceptions` leaves `parrot.auth.pbac` and `parrot.conf` out of `sys.modules`.

**NOT in scope**: ontology/stores/graphindex roots (TASK-4301); activating the other ceilings (TASK-4333); changing what any auth name resolves to.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | PEP 562 lazy root |
| `packages/ai-parrot/tests/knowledge/_support/import_probe.py` | CREATE | subprocess import probe |
| `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` | CREATE | five-entry ceiling test |
| `packages/ai-parrot/tests/knowledge/test_auth_lazy_root.py` | CREATE | auth root behaviour |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
# parrot/auth/__init__.py:29-48 — the eager imports being made lazy:
from .context import UserContext
from .permission import PermissionContext, UserSession
from .pbac import setup_pbac  # :38 — pbac.py:30 `from parrot.conf import PARROT_SAAS_MODE`
from .eval_context import build_eval_context
from .userinfo import EmployeeProfile, UserInfoService
from .dataset_guard import DatasetPolicyGuard
from .dataplane_guard import DataPlanePolicyGuard
from .rls_registry import RlsRegistry, RlsRule, RlsPredicate
from .models import PolicyRuleConfig
```

### Existing Signatures to Use
```python
# parrot/auth/__init__.py:29-48 eager imports (+ `.resolver` block at :31-37); __all__ follows
# parrot/auth/exceptions.py — imports only typing; AuthorizationRequired lives here (used by ontology/mixin.py:65)
# packages/ai-parrot/tests/test_minimal_install.py — existing blocked-package subprocess pattern to reuse
```

### Does NOT Exist
- ~~`parrot.auth.__getattr__` (does not exist yet)~~
- ~~an in-process way to measure module counts — always fork~~
- ~~`tests/knowledge/_support/import_probe.py` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/_support/import_probe.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_import_ceilings.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_auth_lazy_root.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/exceptions.py#AuthorizationRequired"
  ]
}
```

---

## Implementation Notes

Precedent for the lazy root: `parrot/knowledge/wiki/__init__.py:56-120` (`_EXPORT_MODULES`, cached `__getattr__`, `__dir__`). Keep `.exceptions` eager only if it is cheap (it is — `typing` only). Run the auth/PBAC consumer suites afterwards: this root is on the request path of the whole server.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Read `parrot/auth/__init__.py` fully and list every exported name and its submodule — *why*: the lazy map must be complete or callers break.
2. Replace the eager imports with `_LAZY_ATTRS` + `__getattr__` + `__dir__`, keeping `__all__` identical — *why*: names stay discoverable, cost moves to first access.
3. Write the probe helper — *why*: every ceiling assertion must fork `python -I`; a warm interpreter silently passes.
4. Write the ceiling test with only the auth row enforced — *why*: other rows need later tasks; xfail keeps CI green and visible.
5. Run the auth/PBAC consumer tests (`grep -rl 'from parrot.auth import' packages/*/tests`) — *why*: behaviour must not change.

### `packages/ai-parrot/src/parrot/auth/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .pbac import setup_pbac' parrot/auth/__init__.py)
# AFTER/AT — anchor `from .pbac import setup_pbac` (verified: __init__.py:38)
# REPLACE the eager import block (lines 29-48) with:
from typing import Any

_LAZY_ATTRS: dict[str, str] = {
    "UserContext": "parrot.auth.context",
    "PermissionContext": "parrot.auth.permission",
    "UserSession": "parrot.auth.permission",
    "setup_pbac": "parrot.auth.pbac",
    "build_eval_context": "parrot.auth.eval_context",
    "EmployeeProfile": "parrot.auth.userinfo",
    "UserInfoService": "parrot.auth.userinfo",
    "DatasetPolicyGuard": "parrot.auth.dataset_guard",
    "DataPlanePolicyGuard": "parrot.auth.dataplane_guard",
    "RlsRegistry": "parrot.auth.rls_registry",
    "RlsRule": "parrot.auth.rls_registry",
    "RlsPredicate": "parrot.auth.rls_registry",
    "PolicyRuleConfig": "parrot.auth.models",
    # FILL IN: every name imported by the `.resolver` block (:31-37) -> "parrot.auth.resolver"
}


def __getattr__(name: str) -> Any:
    """Resolve a public auth export on first access (PEP 562) and cache it."""
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to dir()."""
    return sorted(set(globals()) | set(__all__))
```
**Why**: PEP 562 keeps every name importable (`from parrot.auth import setup_pbac` still works) while `parrot.auth.exceptions` no longer pays for `.pbac`. `__all__` must stay byte-identical.

### `packages/ai-parrot/tests/knowledge/_support/import_probe.py` (CREATE)
```python
"""Fresh-interpreter import probe for the FEAT-540 import ceilings."""
from __future__ import annotations

import json
import subprocess
import sys

from pydantic import BaseModel

FORBIDDEN: tuple[str, ...] = ("navconfig", "parrot.conf", "navigator_eventbus", "asyncdb", "pandas", "faiss", "pyarrow", "redis", "asyncpg")

_PROBE = (
    "import importlib, json, sys\n"
    "err = None\n"
    "try:\n    importlib.import_module(sys.argv[1])\n"
    "except Exception as exc:\n    err = f'{type(exc).__name__}: {exc}'\n"
    "print(json.dumps({'count': len(sys.modules), 'modules': sorted(sys.modules), 'error': err}))\n"
)


class ImportProbeResult(BaseModel):
    """Outcome of importing one module in a fresh interpreter."""

    module: str
    count: int
    loaded_forbidden: list[str]
    python: str
    error: str | None = None


def run_import_probe(module: str, *, forbidden: tuple[str, ...] = FORBIDDEN) -> ImportProbeResult:
    """Import ``module`` in ``python -I`` and report module count and forbidden prefixes (root or dotted)."""
    proc = subprocess.run([sys.executable, "-I", "-c", _PROBE, module], capture_output=True, text=True, timeout=300)
    # FILL IN: parse the LAST stdout line as JSON (packages may print banners); on non-zero exit set error from stderr
    # FILL IN: loaded_forbidden = [f for f in forbidden if any(m == f or m.startswith(f + '.') for m in modules)]
    raise NotImplementedError
```
**Why**: Forking `-I` isolates from cwd/user site so counts are reproducible; `-I` also stops a stray local module shadowing stdlib. A failed import must surface as `error`, never as a low count (spec §5).

### `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (CREATE)
```python
"""FEAT-540 import ceilings (spec §1). TASK-4333 removes the xfail marks."""
import pytest

from ._support.import_probe import run_import_probe

CEILINGS = [
    pytest.param("parrot.auth.exceptions", 150, id="auth.exceptions"),
    pytest.param("parrot.knowledge.ontology.schema", 240, id="ontology.schema", marks=pytest.mark.xfail(strict=False, reason="TASK-4301/4333")),
    pytest.param("parrot.knowledge.graphindex", 800, id="graphindex", marks=pytest.mark.xfail(strict=False, reason="TASK-4333")),
    pytest.param("parrot.knowledge.graphindex.builder", 1200, id="graphindex.builder", marks=pytest.mark.xfail(strict=False, reason="TASK-4333")),
    pytest.param("parrot.knowledge.wiki.cli", 850, id="wiki.cli", marks=pytest.mark.xfail(strict=False, reason="TASK-4333")),
]


@pytest.mark.parametrize(("module", "ceiling"), CEILINGS)
def test_import_ceiling(module: str, ceiling: int) -> None:
    result = run_import_probe(module)
    assert result.error is None, result.error
    assert result.loaded_forbidden == [], result.loaded_forbidden
    assert result.count <= ceiling, result.count
```
**Why**: Import must succeed before counting (spec §5). Relative import works because `tests/knowledge/__init__.py` exists; FILL IN if collection says otherwise.

### `packages/ai-parrot/tests/knowledge/test_auth_lazy_root.py` (CREATE)
```python
"""parrot.auth lazy root keeps every export (FEAT-540 M1)."""
import parrot.auth as auth

from ._support.import_probe import run_import_probe


def test_every_public_name_resolves() -> None:
    for name in auth.__all__:
        assert getattr(auth, name) is not None, name


def test_dir_lists_exports() -> None:
    assert set(auth.__all__) <= set(dir(auth))


def test_exceptions_does_not_load_pbac() -> None:
    # FILL IN: probe 'parrot.auth.exceptions' and assert 'parrot.auth.pbac' and 'parrot.conf' are absent
    ...
```
**Why**: Behavioural proof the root is lazy and complete. The pbac check needs the probe's module list — extend the probe result with a `has(module)` helper if needed.

### FILL IN checklist
- [ ] `auth/__init__.py` — complete `_LAZY_ATTRS` with every `.resolver` name; bounded by `__all__` staying identical
- [ ] `import_probe.py::run_import_probe` — JSON parsing + forbidden matching; bounded by spec §5 (root and dotted prefixes)
- [ ] `test_auth_lazy_root.py::test_exceptions_does_not_load_pbac` — module-presence assertion

---

## Acceptance Criteria

- [ ] `from parrot.auth.exceptions import AuthorizationRequired` loads ≤150 modules with no forbidden prefix (probe)
- [ ] every name in `parrot.auth.__all__` resolves and is listed by `dir(parrot.auth)`
- [ ] auth/PBAC consumer tests still pass
- [ ] `ruff check` clean on changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/test_auth_lazy_root.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_import_ceilings.py -q`

---

## Test Specification

```python
# see blocks: test_import_ceilings.py, test_auth_lazy_root.py
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4300 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
