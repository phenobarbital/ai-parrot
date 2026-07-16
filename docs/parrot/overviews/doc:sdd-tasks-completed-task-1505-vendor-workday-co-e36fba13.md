---
type: Wiki Overview
title: 'TASK-1505: Vendor the Workday composable + rebase onto parrot core'
id: doc:sdd-tasks-completed-task-1505-vendor-workday-composable-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. A mature composable Workday interface
  lives
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.http
  rel: mentions
- concept: mod:parrot.interfaces.soap
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday.config
  rel: mentions
- concept: mod:parrot_tools.interfaces.workday.service
  rel: mentions
---

# TASK-1505: Vendor the Workday composable + rebase onto parrot core

**Feature**: FEAT-230 — Workday Composable Interface + Toolkit Homologation
**Spec**: `sdd/specs/workday-tooling-composable-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. A mature composable Workday interface lives
in the sibling `flowtask` repo at `flowtask/interfaces/workday/` (63 `.py` files).
This task vendors it verbatim into a new `parrot_tools/interfaces/workday/`
package and rebases it onto ai-parrot core: `WorkdayService` must subclass
`parrot.interfaces.soap.SOAPClient` (NOT the flowtask base), and `config.py` must
read credentials from `parrot.conf` (NOT `flowtask.conf`).

Vendoring + rebase are **inseparable**: the source `service.py` imports
`from flowtask.interfaces.SOAPClient import SOAPClient` — that module does NOT
exist in ai-parrot, so a clean import is only possible once the base is rebased
in the same task.

---

## Scope

- CREATE the package `packages/ai-parrot-tools/src/parrot_tools/interfaces/__init__.py`
  and `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` by copying the
  source tree verbatim: `__init__.py`, `service.py`, `config.py`, `handlers/`,
  `models/`, `parsers/`, `utils/`.
- Rewrite EVERY intra-package import `flowtask.interfaces.workday.*` →
  `parrot_tools.interfaces.workday.*` (mechanical, exhaustive — ~63 files).
- Rebase the SOAP base in `service.py`: replace
  `from flowtask.interfaces.SOAPClient import SOAPClient` with
  `from parrot.interfaces.soap import SOAPClient`. Reconcile the `__init__`
  `super().__init__(credentials=..., timeout=..., **kwargs)` call against the
  core `SOAPClient.__init__` signature (it already passes
  `credentials`/`timeout`/`**kwargs`, which matches).
- Rebase `config.py`: replace `from flowtask.conf import (...)` with
  `from parrot.conf import (...)`.
- ADD the three missing WSDL constants to `parrot.conf` (see Codebase Contract) so
  the vendored `config.py` import resolves:
  `WORKDAY_WSDL_INTEGRATIONS`, `WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT`,
  `WORKDAY_WSDL_TIME_BLOCK_REPORT`.
- Replace any `logging.getLogger("flowtask.workday")` label with a
  `parrot_tools`-scoped logger name.

**NOT in scope**: touching `parrot_tools/workday/tool.py` (Module 2 / TASK-1506);
building new handlers (Modules 4/5); changing handler internals beyond import
rewrites; pushing anything back to flowtask.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/__init__.py` | CREATE | Namespace package init |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/**` | CREATE | Vendored composable (service, config, handlers/, models/, parsers/, utils/) |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add 3 missing `WORKDAY_WSDL_*` constants |
| `packages/ai-parrot-tools/tests/workday/test_vendor_rebase.py` | CREATE | Rebase + no-flowtask-import tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified by reading the source on 2026-06-08.

### Verified Imports
```python
# Core SOAP base (lives in CORE ai-parrot):
from parrot.interfaces.soap import SOAPClient   # verified: packages/ai-parrot/src/parrot/interfaces/soap.py:50

# parrot.conf already exposes (verified packages/ai-parrot/src/parrot/conf.py):
#   WORKDAY_WSDL_PATH (599), WORKDAY_WSDL_TIME (603), WORKDAY_WSDL_HUMAN_RESOURCES (607),
#   WORKDAY_WSDL_FINANCIAL_MANAGEMENT (611), WORKDAY_WSDL_RECRUITING (615),
#   WORKDAY_WSDL_ABSENCE_MANAGEMENT (619), WORKDAY_DEFAULT_TENANT, WORKDAY_CLIENT_ID,
#   WORKDAY_CLIENT_SECRET, WORKDAY_TOKEN_URL, WORKDAY_REFRESH_TOKEN, WORKDAY_REPORT_USERNAME,
#   WORKDAY_REPORT_PASSWORD, WORKDAY_REPORT_OWNER, WORKDAY_URL, WORKDAY_WSDL_PATHS (636)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/soap.py:50
class SOAPClient(ABC):
    def __init__(self, *, credentials: dict, httpx_client=None,        # line 88
                 redis_url=None, redis_key="soap:access_token",
                 timeout: int = 30, **kwargs): ...
    async def start(self) -> None: ...                                 # line 149
    async def run(self, operation: str, **kwargs) -> Any: ...          # line 237
    async def close(self) -> None: ...                                 # line 250

# SOURCE (flowtask/interfaces/workday/service.py) — vendor & rebase base:
class WorkdayService(SOAPClient):                                      # line 111
    def __init__(self, *, config=None, operation_type="get_workers", **kwargs): ...  # line 127
    # super().__init__(credentials=creds, timeout=config.timeout, **kwargs)  (line 177) — matches core base
    async def call_operation(self, operation, **kwargs): ...           # line 251 -> super().run(...)
    async def fetch(self, operation_type, **params) -> pd.DataFrame: ... # line 266
    async def fetch_models(self, operation_type, **params) -> list: ... # line 291
    async def start(self, **_kwargs): ...                              # line 451
    async def close(self): ...                                         # line 455

# SOURCE service.py imports to REWRITE (flowtask.* -> parrot_tools.interfaces.workday.*):
#   line 34: from flowtask.interfaces.workday.config import WorkdayConfig, get_wsdl_path
#   line 39-84: handlers/*, models/* imports
# SOURCE service.py line 33: from flowtask.interfaces.SOAPClient import SOAPClient
#   -> from parrot.interfaces.soap import SOAPClient
# SOURCE config.py line 29: from flowtask.conf import (...)  -> from parrot.conf import (...)
```

### Does NOT Exist
- ~~`flowtask.interfaces.SOAPClient`~~ — not importable in ai-parrot. Rebase onto `parrot.interfaces.soap.SOAPClient`.
- ~~`parrot.conf.WORKDAY_WSDL_INTEGRATIONS`~~ — MISSING; must be added.
- ~~`parrot.conf.WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT`~~ — MISSING; must be added.
- ~~`parrot.conf.WORKDAY_WSDL_TIME_BLOCK_REPORT`~~ — MISSING; must be added.
- ~~`parrot_tools/interfaces/`~~ — directory does not exist yet (this task creates it).

---

## Implementation Notes

### Pattern to Follow
- Copy the source tree exactly; rewrite imports mechanically (a scripted
  `grep -rl 'flowtask.interfaces.workday' | xargs sed` pass, then a manual review
  of `service.py` line 33 and `config.py` line 29 for the two base/conf rebases).
- The source `config.py` `_WSDL_MAP` (config.py:54) keys operation_types to WSDL
  constants; keep it intact after the conf import rebase.

### Key Constraints
- `grep -r "flowtask" parrot_tools/interfaces/workday` MUST return empty after the rewrite.
- Async-first; do not alter handler logic, only imports.
- Use a `parrot_tools`-scoped logger name (not `flowtask.workday`).

### References in Codebase
- `flowtask/interfaces/workday/` — verbatim source.
- `packages/ai-parrot/src/parrot/interfaces/soap.py` — new base class.
- `packages/ai-parrot/src/parrot/conf.py:595-642` — WORKDAY_* block to extend.

---

## Acceptance Criteria

- [ ] `parrot_tools/interfaces/workday/` exists with service/config/handlers/models/parsers/utils.
- [ ] `WorkdayService` is a subclass of `parrot.interfaces.soap.SOAPClient`.
- [ ] `grep -r "flowtask" parrot_tools/interfaces/workday` returns nothing.
- [ ] Vendored `config.py` resolves all `WORKDAY_*` from `parrot.conf` (3 new consts added).
- [ ] `from parrot_tools.interfaces.workday.service import WorkdayService` imports cleanly.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_vendor_rebase.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday`

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_vendor_rebase.py
import importlib
import subprocess

from parrot.interfaces.soap import SOAPClient
from parrot_tools.interfaces.workday.service import WorkdayService


def test_workdayservice_rebased_soapclient():
    """WorkdayService subclasses the CORE SOAPClient, not the flowtask base."""
    assert issubclass(WorkdayService, SOAPClient)


def test_no_flowtask_import_remains():
    """No vendored file references flowtask."""
    out = subprocess.run(
        ["grep", "-rl", "flowtask",
         "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday"],
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == ""


def test_config_reads_parrot_conf():
    """Vendored config resolves WORKDAY_* from parrot.conf."""
    cfg = importlib.import_module("parrot_tools.interfaces.workday.config")
    assert hasattr(cfg, "WorkdayConfig")
    assert hasattr(cfg, "get_wsdl_path")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (esp. §2, §3 Module 1, §6).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `SOAPClient.__init__` signature and the
   `parrot.conf` WORKDAY block before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** the vendor + rebase.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-08
**Notes**: Copied 63 files verbatim from flowtask/interfaces/workday/. All imports
rewritten (flowtask.interfaces.workday → parrot_tools.interfaces.workday). Two
special cases handled: service.py base class rebased to parrot.interfaces.soap.SOAPClient;
config.py conf import rebased to parrot.conf. HTTPService in 3 handlers changed from
relative import (....interfaces.http) to absolute (parrot.interfaces.http). 3 missing
WORKDAY_WSDL_* constants added to parrot.conf. Pre-existing ruff lint issues in vendored
files fixed (106 auto-fixed + 12 manual). 4/4 acceptance tests pass.

**Deviations from spec**: HTTPService import path was `....interfaces.http` (relative) in
the flowtask source — rebased to `parrot.interfaces.http` (absolute). This is the correct
parrot-core equivalent and was not documented in the Codebase Contract.
