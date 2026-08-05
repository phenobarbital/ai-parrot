# TASK-2137: SOAP endpoint host rewrite on WorkdayService (`bind_service` override)

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2136
**Assigned-to**: unassigned

---

## Context

Implements the second half of **Module 1** of the spec, and closes the
single highest-severity gap in this feature.

The WSDL files shipped in `env/workday/` hardcode the **production** SOAP
endpoint (`services1.wd501.myworkday.com`). Zeep binds to whatever the WSDL
says. flowtask overrides `bind_service()` to rewrite that endpoint's host to
match the configured `workday_url`. ai-parrot has no such override, so it
inherits the plain `SOAPClient.bind_service()` — meaning **a
sandbox-configured client silently sends both reads AND writes to
production**.

TASK-2136 makes `workday_url` environment-aware; this task makes the SOAP
transport actually honour it.

---

## Scope

- Override `bind_service()` on `WorkdayService`: call `super().bind_service()`,
  then rewrite the bound endpoint's host, then return the service proxy.
- Add `_point_endpoint_at_configured_host(service)` which swaps only the
  **scheme + netloc** of the bound endpoint address for those of
  `self.workday_url`, preserving the URL path verbatim (so both the standard
  `/ccx/service/<tenant>/<Service>/<ver>` form and the longer
  `/ccx/service/customreport2/...` form keep working).
- No-op when the host already matches (the production default).
- Never let an endpoint rewrite break binding: wrap the rewrite in a
  try/except, log a warning, and return the service unchanged on failure.
- Handle absent `_binding_options`, empty `current` address, and empty/
  malformed `workday_url` by returning without changes.
- Log at INFO when the endpoint host is actually changed.
- Write unit tests.

**NOT in scope**:
- `WorkdayConfig` env resolution — TASK-2136.
- Any handler/model/parser change.
- Adding `__aenter__`/`__aexit__` to `parrot.interfaces.soap.SOAPClient`
  (explicitly deferred by the spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py` | MODIFY | Add `bind_service()` override + `_point_endpoint_at_configured_host()` |
| `packages/ai-parrot-tools/tests/workday/test_endpoint_rewrite.py` | CREATE | Unit tests for the rewrite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.interfaces.soap import SOAPClient   # verified: packages/ai-parrot/src/parrot/interfaces/soap.py:50
from urllib.parse import urlparse, urlunparse   # stdlib — needed by the rewrite
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/interfaces/soap.py
class SOAPClient(ABC):                       # line 50
    def get_client(self) -> ZeepAsyncClient:  # line 221
    def bind_service(self) -> Any:            # line 231  <-- THE HOOK TO OVERRIDE
        """Return the bound service proxy from Zeep."""
        return self._client.service
    async def run(self, operation: str, **kwargs) -> Any:  # line 237
    async def close(self) -> None:            # line 250
```

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py
class WorkdayService(SOAPClient):            # line 118
    def __init__(...)                        # line 134
    # self.tenant / self.report_owner / self.workday_url are set in __init__
    # from config.resolved_tenant / resolved_report_owner / resolved_workday_url
    async def start(self, **_kwargs: Any) -> None:   # line 465
    async def close(self) -> None:                   # line 469
```

### The Zeep binding surface (as used by the flowtask original)

```python
options = getattr(service, "_binding_options", None)   # dict | None
current = options.get("address")                        # str — the bound endpoint URL
options["address"] = new_addr                           # write back to redirect
```

### Reference Source (flowtask — READ ONLY)

`../flowtask/flowtask/interfaces/workday/service.py` contains the original
`bind_service()` + `_point_endpoint_at_configured_host()` pair. The logic
ports cleanly; only the import prefix differs.

### Does NOT Exist

- ~~`WorkdayService.bind_service()` override~~ — does not exist yet; ai-parrot inherits the plain hook
- ~~`WorkdayService._point_endpoint_at_configured_host()`~~ — does not exist yet
- ~~`SOAPClient.__aenter__` / `SOAPClient.__aexit__`~~ — flowtask's base class has them (`SOAPClient.py:347,351`), **ai-parrot's does not**. Do NOT write `async with WorkdayService(...)`; use explicit `start()`/`close()`. If you port a docstring containing `async with`, rewrite it.
- ~~`SOAPClient.set_address()` / `SOAPClient.endpoint`~~ — no such helper; the rewrite goes through `service._binding_options["address"]`

---

## Implementation Notes

### Key Constraints
- Preserve the WSDL path verbatim — swap **only** scheme + netloc.
- A failed rewrite must never propagate: log a warning and return the service as-is. Binding is more important than the redirect.
- Production default must be a genuine no-op (same host → return early, no log spam).
- Use `self._logger` (set in `__init__`), never `print`.
- Google-style docstrings and strict type hints.

### Reference Pattern
```python
def bind_service(self) -> Any:
    service = super().bind_service()
    try:
        self._point_endpoint_at_configured_host(service)
    except Exception as exc:          # never break binding over an endpoint rewrite
        self._logger.warning("Could not override SOAP endpoint host: %s", exc)
    return service
```

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/soap.py:221-236` — `get_client()` / `bind_service()` pair
- `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` — mocking pattern

---

## Acceptance Criteria

- [ ] `WorkdayService.bind_service()` calls `super().bind_service()` and returns the (possibly redirected) proxy
- [ ] Sandbox host configured → bound endpoint host is rewritten; WSDL path unchanged
- [ ] Production/matching host → endpoint untouched (no-op)
- [ ] `customreport2`-style long paths survive the rewrite unchanged
- [ ] Missing `_binding_options`, empty address, or malformed `workday_url` → original endpoint intact, no raise
- [ ] A raising rewrite is caught, logged as a warning, and binding still succeeds
- [ ] FEAT-230/232 handler registrations in `_handlers` are untouched by this task
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_endpoint_rewrite.py
import pytest
from unittest.mock import MagicMock


class TestEndpointRewrite:
    def test_rewrites_host_for_sandbox(self):
        """Bound endpoint host swapped to the configured host; path preserved."""

    def test_noop_for_matching_production_host(self):
        """Same host → address left byte-identical."""

    def test_preserves_customreport2_path(self):
        """Long /ccx/service/customreport2/... paths survive unchanged."""

    def test_missing_binding_options_is_safe(self):
        """service without _binding_options → returns without raising."""

    def test_malformed_workday_url_is_safe(self):
        """Empty/garbage workday_url → original address intact."""

    def test_rewrite_failure_does_not_break_binding(self, caplog):
        """An exception during rewrite is caught, warned, and binding still returns."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2136 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2137-workday-soap-endpoint-rewrite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
