# TASK-3736: AbstractDriver.get_cookies() capability + PlaywrightDriver context-level implementation

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (driver half), design research S8. Session recovery must hand the
browser's authenticated `sid` to the API cookie jar. The existing `exec_get_cookies`
reads `document.cookie` (`session_actions.py:302`), which cannot see HttpOnly cookies —
and a session cookie is almost always HttpOnly. `AbstractDriver` has no cookie API, but
`PlaywrightDriver` owns a browser context (`self._context`, created in `start()`) whose
`cookies()` returns every cookie including HttpOnly ones.

---

## Scope

- Add non-abstract `AbstractDriver.get_cookies(urls=None)` that raises `NotImplementedError` (fail closed for drivers without the capability).
- Implement `PlaywrightDriver.get_cookies(urls=None)` via `await self._context.cookies(...)`; `RuntimeError` if not started.
- Tests in `tests/scraping/test_driver_get_cookies.py` with a mocked context.

**NOT in scope**: Selenium implementation; `set_cookies`; changing `exec_get_cookies`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | MODIFY | add get_cookies() default raising NotImplementedError |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | add get_cookies() over the browser context |
| `packages/ai-parrot-tools/tests/scraping/test_driver_get_cookies.py` | CREATE | unit tests with mocked context |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver                 # verified: browsing/toolkit.py:34
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver      # verified: tests/scraping/test_abstract_driver_extensions.py:12
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig      # verified: tests/scraping/test_abstract_driver_extensions.py:13
# abstract.py already imports: from typing import Any, Callable, List, Literal, Optional   (line 8) — add Dict, Sequence
# playwright_driver.py already imports: from typing import Any, Callable, Dict, List, Optional   (line 9) — add Sequence
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):                                                    # line 11 — docstring: unsupported methods raise NotImplementedError
    @abstractmethod
    async def evaluate(self, expression: str) -> Any                          # lines 231-240
    # line 242: "    # ── Property ─────────────────────────────────────────────────"   (occurrences of '    # ── Property': 1)

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):                                       # line 15
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None     # lines 30-44 — self._context = None
    async def start(self) -> None                                             # lines 48-123 — sets self._context (lines 99 / 113)
    async def evaluate(self, expression: str) -> Any                          # lines 269-271
    #   line 271: "        return await self._page.evaluate(expression)"   (occurrences: 1)
```

### Does NOT Exist
- ~~`AbstractDriver.get_cookies`~~ / ~~`PlaywrightDriver.get_cookies`~~ — new in this task.
- ~~`exec_get_cookies` seeing HttpOnly cookies~~ — it reads `document.cookie`; do not use it for session transfer.
- ~~`PlaywrightDriver.context` public attribute~~ — the context is private `self._context`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_driver_get_cookies.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver.start"
  ]
}
```

---

## Implementation Notes

- Playwright's `BrowserContext.cookies(urls=None)` returns dicts with `name, value, domain, path, expires, httpOnly, secure, sameSite`; return them unchanged as a list.
- Make `get_cookies` non-abstract on `AbstractDriver` so Selenium and other drivers keep instantiating.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the default method to `AbstractDriver` — *why*: callers can rely on the method existing and fail closed.
2. Implement it on `PlaywrightDriver` — *why*: S8, HttpOnly cookies are only visible at context level.
3. Tests with `PlaywrightDriver.__new__` + a mocked `_context` (pattern: `test_abstract_driver_extensions.py`).

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` (MODIFY)
```python
# (a) REPLACE line 8 `from typing import Any, Callable, List, Literal, Optional` WITH:
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence

# (b) occurrences: 1 (verified: grep -c '    # ── Property' abstract.py) — line 242
# BEFORE — insert above `    # ── Property ─────...`:
    async def get_cookies(self, urls: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Return browser-context cookies, HttpOnly included.

        Args:
            urls: Restrict to cookies that would be sent to these URLs; ``None`` = all.

        Returns:
            Cookie dicts (``name``, ``value``, ``domain``, ``path``, ``httpOnly``, ``secure``, ...).

        Raises:
            NotImplementedError: The driver cannot read context-level cookies.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support get_cookies(); use PlaywrightDriver")

```

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` (MODIFY)
```python
# (a) REPLACE line 9 `from typing import Any, Callable, Dict, List, Optional` WITH:
from typing import Any, Callable, Dict, List, Optional, Sequence

# (b) occurrences: 1 (verified: grep -c '        return await self._page.evaluate(expression)' playwright_driver.py) — line 271
# AFTER — insert below that line:

    async def get_cookies(self, urls: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Return the browser context's cookies (HttpOnly included)."""
        if self._context is None:
            raise RuntimeError("PlaywrightDriver.get_cookies() called before start()")
        # FILL IN: return list(await self._context.cookies(list(urls) if urls else None)) — bounded by AC-13
        raise NotImplementedError
```

### `packages/ai-parrot-tools/tests/scraping/test_driver_get_cookies.py` (CREATE)
```python
"""FEAT-602 TASK-3736 — context-level cookie export."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver


async def test_playwright_get_cookies_returns_httponly():
    # FILL IN: drv = PlaywrightDriver.__new__(PlaywrightDriver); drv._context = MagicMock(cookies=AsyncMock(return_value=[
    #          {"name": "sid", "value": "x", "httpOnly": True}])); assert result and urls forwarded


async def test_playwright_get_cookies_before_start_raises():
    # FILL IN


async def test_abstract_driver_get_cookies_default_raises():
    # FILL IN: minimal concrete subclass or call AbstractDriver.get_cookies(MagicMock()) → NotImplementedError
```

### FILL IN checklist
- [ ] `PlaywrightDriver.get_cookies` body
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-13 (spec, driver half): `PlaywrightDriver.get_cookies()` returns context cookies including HttpOnly ones; `AbstractDriver.get_cookies()` raises `NotImplementedError`.
- [ ] Existing driver tests still pass (`test_abstract_driver.py`, `test_abstract_driver_extensions.py`).
- [ ] `ruff check` and `black --check` clean on both drivers.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/scraping/test_driver_get_cookies.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_abstract_driver.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_abstract_driver_extensions.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_playwright_get_cookies_returns_httponly` | context-level export |
| `test_playwright_get_cookies_before_start_raises` | `RuntimeError` |
| `test_abstract_driver_get_cookies_default_raises` | fail closed |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
