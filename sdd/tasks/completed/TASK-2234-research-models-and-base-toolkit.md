# TASK-2234: Research models, BaseResearchToolkit mixin & packaging

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-426 (spec §3 Module 1). Every other task in this
feature imports the models and the mixin created here, so this task **blocks
all others**. It also adds the `research` optional extra to the satellite
`pyproject.toml` up front, so that Tasks 2235-2241 can install and run their
own dependencies immediately.

The mixin design was empirically validated against the real `AbstractToolkit`
during spec review — the MRO, `auto_open` lifecycle, and tool auto-generation
all work as described here. Do not redesign it.

---

## Scope

- Create `parrot_tools/research/models.py` with `Citation`, `IndicatorValue`,
  `PaperResult`, `DatasetResult`, `ResearchResult` (exact fields in spec §2
  "Data Models").
- Create `parrot_tools/research/base.py` with `BaseResearchToolkit` as a
  **cooperative mixin** implementing: `auto_open = True`, `_open()` /
  `_close()`, `_make_api_request()`, `_run_sync_in_executor()`,
  `_build_citation()`, `_failure()`.
- Create `parrot_tools/research/__init__.py` as a **stub** (docstring only —
  final exports are TASK-2243's job, to avoid parallel-worktree conflicts).
- Add the `research` extra to `packages/ai-parrot-tools/pyproject.toml` and
  append `research` to the aggregate `all` extra.
- Create `packages/ai-parrot-tools/tests/research/conftest.py` with the
  shared fixtures (`load_fixture`, `mock_aiohttp_session`).
- Write unit tests for the models and the mixin.

**NOT in scope**: any concrete toolkit (`open_data.py`, `academic.py`), the
router, `TOOL_REGISTRY` regeneration, final `research/__init__.py` exports,
or documentation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/__init__.py` | CREATE | Stub only — docstring, no exports yet |
| `packages/ai-parrot-tools/src/parrot_tools/research/models.py` | CREATE | 5 Pydantic models |
| `packages/ai-parrot-tools/src/parrot_tools/research/base.py` | CREATE | `BaseResearchToolkit` cooperative mixin |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Add `research` extra; append to `all` |
| `packages/ai-parrot-tools/tests/research/__init__.py` | CREATE | Empty package marker |
| `packages/ai-parrot-tools/tests/research/conftest.py` | CREATE | Shared fixtures |
| `packages/ai-parrot-tools/tests/research/test_models.py` | CREATE | Model unit tests |
| `packages/ai-parrot-tools/tests/research/test_base.py` | CREATE | Mixin unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-08-17 on `dev`. Entries marked **[probe]** were
> confirmed by executing code in the project venv.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit          # [probe] instantiates OK
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot_tools.cache import ToolCache, DEFAULT_TOOL_CACHE_TTL  # DEFAULT = 300
import aiohttp          # core dep
import backoff          # backoff==2.2.1
from pydantic import BaseModel, Field
from navconfig.logging import logging
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    auto_open: bool = False
    exclude_tools: tuple[str, ...] = ()
    def __init__(self, **kwargs)   # sets: _opened, _open_lock, logger,
                                   #       _tool_cache, _tools_generated
    async def _open(self) -> None          # no-op default
    async def _close(self) -> None         # resets self._opened = False
    async def _ensure_open(self) -> None   # Lock-guarded, calls _open() once
    def _generate_tools(self) -> None      # skips names starting with "_"

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):               # line 199
    success: bool = True                   # line 201 — INDEPENDENT of `status`
    status: str = "success"                # line 202
    result: Any                            # line 203
    error: Optional[str] = None            # line 204
    metadata: Dict[str, Any] = {}          # line 205

# packages/ai-parrot-tools/src/parrot_tools/cache.py
class ToolCache:
    def __init__(self, prefix="tool_cache", ttl=300, redis_url=None)
    async def get(self, tool_name: str, method: str, **params) -> Optional[Any]
    async def set(self, tool_name: str, method: str, value: Any,
                  ttl: int = None, **params) -> None
    async def close(self) -> None
```

### Verified Framework Behaviour **[probe]**

```text
class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
  MRO: OpenDataToolkit -> BaseResearchToolkit -> AbstractToolkit -> ABC -> object
  __init__ OK          auto_open = True
  _opened present: True      logger present: True
  get_tools() -> ['search_world_bank']    leaked private tools: none
  execute() fires _open(); returns ToolResult(result=<ResearchResult>)
  _close() -> _opened = False

A method returning ResearchResult(status="error") yields
  ToolResult.status == 'success'   -> ToolManager does NOT raise.   ✅ G7
```

### Does NOT Exist

- ~~`parrot_tools.research`~~ — this task creates it
- ~~`ResearchResult.scrape_status`~~ — the field is `.status`
- ~~`ToolCache._build_key()` as public API~~ — private; use `.get()` / `.set()`
- ~~`ToolResult(status="error")` implying `success=False`~~ — it does **not** **[probe]**
- ~~`parrot.interfaces.HTTPService`~~ — exists but is **FORBIDDEN** here
  (`requests`/`httpx`-backed, blocks the loop — see `interfaces/http.py:15,31`)

---

## Implementation Notes

### Pattern to Follow — cooperative mixin

```python
class BaseResearchToolkit:
    """Mixin. MUST be listed BEFORE AbstractToolkit in the bases list."""
    auto_open: bool = True

    def __init__(self, *, cache_ttl: int = 3600, **kwargs):
        super().__init__(**kwargs)          # ← MANDATORY: reaches AbstractToolkit
        self._cache = ToolCache(prefix="research_cache", ttl=cache_ttl)
        self._session = None

    async def _open(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ai-parrot-research/1.0"},
        )

    async def _close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        await super()._close()              # ← MANDATORY: resets _opened
```

Omitting either `super()` call leaves the toolkit half-initialised or
permanently "open" — both were flagged in spec review.

### `_make_api_request` must never raise

```python
async def _make_api_request(self, url, params=None, headers=None
                            ) -> tuple[Optional[dict], Optional[str]]:
    """Returns (payload, error). NEVER raises."""
```
Wrap with `backoff.on_exception(backoff.expo, aiohttp.ClientError, max_tries=3)`
and treat HTTP 429 as retryable. Catch `asyncio.TimeoutError` and
`aiohttp.ClientError`, returning `(None, "<reason>")`.

### `_failure` factory

```python
def _failure(self, query, source, result_type, status, message) -> ResearchResult:
    """Canonical no_data / error result. citation stays None."""
```

### Key Constraints

- `status` values: `success` | `partial` | `no_data` | `error`.
- `ResearchResult.citation` is `Optional` so failures need not fabricate one —
  but every `status="success"` result MUST carry a complete `Citation`.
- **Every helper must stay underscore-prefixed.** `_generate_tools()` turns
  any public async method into an LLM-callable tool.
- `access_date` = `datetime.now(timezone.utc).date().isoformat()`.
- Async throughout, Google-style docstrings, `self.logger`.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — backoff + executor pattern
- `packages/ai-parrot-tools/src/parrot_tools/cache.py` — ToolCache usage
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — the base being extended

---

## Acceptance Criteria

- [ ] All 5 models exist in `research/models.py` with the exact fields from spec §2.
- [ ] `ResearchResult.status` defaults to `"success"`; `citation` is `Optional`.
- [ ] `BaseResearchToolkit.__init__` forwards via `super().__init__(**kwargs)` —
      a subclass exposes `_opened`, `_open_lock`, `logger`, `_tool_cache`.
- [ ] `_close()` calls `await super()._close()` and resets `_opened` to `False`.
- [ ] A probe subclass with one public async method exposes exactly that one
      tool via `get_tools()` — no mixin helper leaks.
- [ ] `_make_api_request()` returns `(None, "...")` on 500/timeout — never raises.
- [ ] `_failure()` returns a `ResearchResult` with `citation is None` and a
      populated `error_message`.
- [ ] `research` extra present in `pyproject.toml` with all 5 packages and
      appended to the `all` extra.
- [ ] `pytest packages/ai-parrot-tools/tests/research/ -v` passes offline.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/research/` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/research/test_base.py
import pytest, aiohttp
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.research.base import BaseResearchToolkit
from parrot_tools.research.models import ResearchResult, Citation


class _Probe(BaseResearchToolkit, AbstractToolkit):
    async def do_thing(self, query: str) -> ResearchResult:
        """Do a thing."""
        return ResearchResult(query=query, source="probe", result_type="papers")


class TestBaseResearchToolkit:
    def test_mro_and_init(self):
        tk = _Probe()
        for attr in ("_opened", "_open_lock", "logger", "_tool_cache"):
            assert hasattr(tk, attr), f"{attr} missing — super().__init__ not called"

    def test_only_public_method_becomes_a_tool(self):
        assert [t.name for t in _Probe().get_tools()] == ["do_thing"]

    async def test_lifecycle(self):
        tk = _Probe()
        await tk._ensure_open()
        assert tk._opened is True and tk._session is not None
        await tk._close()
        assert tk._opened is False and tk._session is None

    async def test_failure_factory(self):
        r = _Probe()._failure("q", "probe", "papers", "no_data", "nothing found")
        assert r.status == "no_data" and r.citation is None
        assert "nothing found" in r.error_message

    async def test_make_api_request_never_raises(self, mock_aiohttp_session):
        payload, err = await _Probe()._make_api_request("http://x/500")
        assert payload is None and err
```

---

## Agent Instructions

1. **Read the spec** — especially §2 "Error Contract", §2 "Data Models", and §7.
2. **Verify the Codebase Contract** before writing code.
3. Update `sdd/tasks/index/research-tools-for-agents.json` → `"in-progress"`.
4. **Implement** per scope.
5. **Verify** all acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update the index → `"done"`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: All 5 models, `BaseResearchToolkit` cooperative mixin, `research`
extra + `all` aggregation, and shared `conftest.py` fixtures
(`load_fixture`, `mock_aiohttp_session`) implemented per spec §2/§3/§7.
`_make_api_request` splits the network call into an inner
`_request_with_retry` (backoff-decorated, raises on HTTP 429 to trigger a
retry) wrapped by an outer try/except so even backoff-exhausted retries
are caught and returned as `(None, "...")` — never raised. 19/19 tests
pass offline; `ruff check` clean.
**Deviations from spec**: none
