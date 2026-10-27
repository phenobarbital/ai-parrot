# TASK-4597: AbstractBot.configure() idempotency + reconfigure()

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. A second `configure()` on the same instance currently re-runs the
whole pipeline: a second LLM client, a second store warm-up, a second
`AgentConfiguredEvent`, and a second `post_configure()` — which is where toolkits get
re-registered and `ToolNameCollisionError` fires (`abstract.py:1727`, errors re-raised
at `1728-1733`). This task makes `configure()` idempotent per instance with an entry
counter, keeps an app that arrives later a genuine reconfiguration, and adds
`reconfigure()` as the only explicit way to force a re-run.

---

## Scope

- Add `self._configure_count: int = 0` in `AbstractBot.__init__`.
- At the top of `configure()`: resolve the incoming app, increment the counter, and
  return early (INFO log) on a re-entry that brings no new app.
- Add the `configure_count` property and `async def reconfigure(self, app=None)`.
- Rewrite the `configure()` and `post_configure()` docstrings per the spec skeleton.
- Create `packages/ai-parrot/tests/bots/test_double_configure.py` with the M2 unit tests.

**NOT in scope**:
- `ToolManager` changes (TASK-4596) — this task does not import or call them.
- Agent `post_configure()` bodies (TASK-4598/4599/4600).
- The integration tests in the same file (TASK-4601 appends them later).
- Changing any `configure()` signature — 20+ subclass overrides declare `configure(self, app=None)`; do NOT add a keyword.
- The `finally` contract (`_configured = True` always) stays exactly as is.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | counter, entry guard, `configure_count`, `reconfigure()`, docstrings |
| `packages/ai-parrot/tests/bots/test_double_configure.py` | CREATE | M2 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot  # verified: tests/interfaces/test_configure_applies_tooling.py:7
from aiohttp import web                       # verified: bots/abstract.py:18 (already imported there)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    self._configured: bool = False                          # line 368 (__init__)
    async def configure(self, app=None) -> None:            # line 1564
        #   1576: self._configured = False
        #   1577: self.app = None
        #   1578: if app:
        #   1579:     self.app = app if isinstance(app, web.Application) else app.get_app()
        #   1580:     if self.tool_manager._server_param_source is None:
        #   1581:         self.tool_manager.set_server_param_source(self.app)
        #   1582: try:
        #   1588:     await self.apply_tooling_specs()      (self-guarded via _tooling_applied)
        #   1727:     await self.post_configure()           (errors logged + re-raised 1728-1733)
        #   1735+:    AgentConfiguredEvent emitted via self.events.emit_nowait(...)
        #   1765: finally: self._configured = True
    async def post_configure(self) -> None:                 # line 1767 (body: `return None`, line 1780)
    @property
    def is_configured(self) -> bool:                        # line 1842
        return self._configured                             # line 1844
```

### Does NOT Exist
- ~~`AbstractBot._configure_count`~~, ~~`configure_count`~~, ~~`reconfigure()`~~ — created by THIS task.
- ~~`AbstractBot._configure_completed`~~ — not used; the spec settled on a counter.
- ~~`configure(app, force=True)`~~ — never add a keyword to `configure()`.
- ~~`AbstractBot.post_configure` doing any work~~ — the base is a no-op; keep it one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_double_configure.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.post_configure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.is_configured"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Read the counter with `getattr(self, "_configure_count", 0)`** — because existing tests
  (`tests/interfaces/test_configure_applies_tooling.py`) build bots with
  `AbstractBot.__new__` and never run `__init__`; a bare attribute read would break them.
- **Guard rule** (refines spec §2 — record it in the Completion Note): short-circuit when
  `count > 1` **and** (`resolved_app is None` **or** `resolved_app is previous_app`).
  So `configure(app); configure(app)` → no-op; `configure(); configure(app)` → runs
  (an app arrived); `configure(app); configure()` → no-op — re-running with no app would
  *unbind* `self.app`, which nobody wants.
- Capture `previous_app = getattr(self, "app", None)` **before** the existing
  `self.app = None` (`:1577`).
- Keep the existing `if app:` truthiness test for resolving the app — do not change it to
  `is not None` (out of scope). Gotcha for tests: an *empty* `web.Application()` is falsy
  (it is a mapping), so tests must pass a truthy app object (see test block).
- The early return happens **before** `try:` — so the `finally` does not run on a skip and
  `_configured` keeps its value from the first call.
- `reconfigure()` resets the counter to `0` and awaits `self.configure(...)` (the subclass
  override, if any) with `app` or, when `None`, the currently bound `self.app`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the counter in `__init__` — *why*: spec §2 Data Models.
2. Replace the app-resolution prologue of `configure()` with the guarded version — *why*: the guard must run before any state is reset.
3. Add `configure_count` + `reconfigure()` after `is_configured` — *why*: lifecycle accessors live together.
4. Update both docstrings — *why*: the post_configure contract is what agent authors read.
5. Create the test file, run it plus the existing configure test.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — `__init__`
```python
# occurrences: 1 (verified: grep -cF '        self._configured: bool = False' abstract.py)
# AFTER — insert below `        self._configured: bool = False` (verified: abstract.py:368)
        # FEAT-721: entries into configure(); a re-entry with no new app is a no-op.
        self._configure_count: int = 0
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — `configure()` prologue
```python
# occurrences: 1 each (verified: grep -cF '        self._configured = False' / '        self.app = None' abstract.py)
# REPLACE lines 1576-1581 (from `        self._configured = False` through
#         `                self.tool_manager.set_server_param_source(self.app)`) with:
        previous_app = getattr(self, "app", None)
        resolved_app = None
        if app:
            resolved_app = app if isinstance(app, web.Application) else app.get_app()
        self._configure_count = getattr(self, "_configure_count", 0) + 1
        if self._configure_count > 1 and (resolved_app is None or resolved_app is previous_app):
            self.logger.info(
                "configure() already ran for '%s' (entry #%d); skipping. Use reconfigure() to force a re-run.",
                getattr(self, "name", self.__class__.__name__),
                self._configure_count,
            )
            return
        self._configured = False
        self.app = resolved_app
        if resolved_app is not None:
            if self.tool_manager._server_param_source is None:  # a Studio build already bound it before its tools
                self.tool_manager.set_server_param_source(self.app)
```
**Why**: the guard sits before `_configured = False` so a skipped call leaves the first
call's state untouched. `resolved_app is not None` is equivalent to the old `if app:` branch
because `resolved_app` is only set inside `if app:`.

Replace the `configure()` docstring (lines 1565-1575) with the spec §3 M2 skeleton text,
keeping its existing paragraph about the `try/except/finally` rationale.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — accessors
```python
# occurrences: 1 (verified: grep -cF '        return self._configured' abstract.py)
# AFTER — insert below `        return self._configured` (verified: abstract.py:1844)

    @property
    def configure_count(self) -> int:
        """How many times :meth:`configure` has been entered on this instance."""
        return getattr(self, "_configure_count", 0)

    async def reconfigure(self, app=None) -> None:
        """Reset the idempotency counter and run :meth:`configure` again.

        The ONLY supported way to re-run the configure pipeline on a live
        instance. ``post_configure()`` runs again, so overrides must adopt
        already-registered toolkits (see ``docs/agent-configure-lifecycle.md``).

        Args:
            app: The aiohttp app to bind; defaults to the currently bound one.
        """
        self._configure_count = 0
        await self.configure(app if app is not None else getattr(self, "app", None))
```

### `post_configure()` docstring (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def post_configure(self) -> None:' abstract.py)
# Replace the docstring at abstract.py:1768-1779; keep `return None` (line 1780).
# FILL IN: keep the existing first two paragraphs, then append:
#   "Called once per configure() that actually runs its pipeline, and again by
#    reconfigure(). An override MUST be safe to run more than once per instance:
#    adopt an already-registered toolkit via
#    ``self.tool_manager.find_registered_toolkit(...)`` instead of building a
#    second one. See ``docs/agent-configure-lifecycle.md``."
```

### `packages/ai-parrot/tests/bots/test_double_configure.py` (CREATE)
```python
"""FEAT-721 — AbstractBot.configure() is idempotent per instance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.abstract import AbstractBot


def _stub_bot() -> AbstractBot:
    """AbstractBot with every configure() collaborator stubbed (pattern: test_configure_applies_tooling.py)."""
    bot = AbstractBot.__new__(AbstractBot)
    bot.logger = MagicMock()
    bot.configure_conversation_memory = MagicMock()
    bot.apply_tooling_specs = AsyncMock(return_value=[])
    bot.configure_kb = AsyncMock()
    bot._use_local_kb = False
    bot._llm_model_explicit = False
    bot._llm_raw = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_model = None
    bot._resolve_llm_config = MagicMock(return_value=MagicMock(model=None))
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.tool_manager = MagicMock(_server_param_source=None)
    bot.sync_tools = MagicMock()
    bot.get_tools_summary = MagicMock(
        return_value={"tools_enabled": False, "operation_mode": "", "tools_count": 0,
                      "categories": [], "effective_mode": ""}
    )
    bot._define_prompt = MagicMock()
    bot._prompt_builder = None
    bot.define_store_config = MagicMock(return_value=None)
    bot._use_vector = False
    bot._vector_store = None
    bot._refresh_context_recs_from_store = MagicMock()
    bot.warmup_on_configure = False
    bot.store = None
    bot.use_kb = False
    bot._credentials = []
    bot.post_configure = AsyncMock()
    bot._llm_config = None
    bot.events = MagicMock()
    bot.name = "test-bot"
    return bot


def _app() -> SimpleNamespace:
    """A truthy app wrapper (an empty web.Application is falsy — it is a mapping)."""
    real = object()
    return SimpleNamespace(get_app=lambda: real)


@pytest.mark.asyncio
async def test_second_configure_is_noop() -> None:
    bot, app = _stub_bot(), _app()
    await bot.configure(app)
    await bot.configure(app)
    assert bot.configure_count == 2
    bot.post_configure.assert_awaited_once()
    assert bot.events.emit_nowait.call_count == 1


@pytest.mark.asyncio
async def test_configure_with_new_app_reruns() -> None:
    # FILL IN: configure() then configure(_app()) → post_configure awaited twice, bot.app bound (AC-8)
    ...


@pytest.mark.asyncio
async def test_configure_without_app_after_app_keeps_binding() -> None:
    # FILL IN: configure(app) then configure() → no re-run, bot.app unchanged
    ...


@pytest.mark.asyncio
async def test_reconfigure_reruns_pipeline() -> None:
    # FILL IN: configure(app); reconfigure() → post_configure awaited twice, configure_count == 1 (AC-9)
    ...


@pytest.mark.asyncio
async def test_failed_configure_still_marks_configured() -> None:
    # FILL IN: post_configure = AsyncMock(side_effect=RuntimeError) → configure raises, is_configured True (AC-10)
    ...
```
**Why**: `_stub_bot()` copies the verified stub set of `test_configure_applies_tooling.py:11`
plus `tool_manager`/`sync_tools`, which the app path and the LLM path touch. Note that
`configure()` passes `self.app` (the object from `get_app()`) into `set_server_param_source`.

### FILL IN checklist
- [ ] `post_configure()` docstring paragraph — wording given above
- [ ] `configure()` docstring — spec §3 M2 skeleton
- [ ] four test bodies; bounded by AC-8, AC-9, AC-10 and the guard rule above
- [ ] check that `test_configure_applies_tooling.py` still passes unchanged (it uses `__new__`, so the `getattr` default matters)

---

## Acceptance Criteria

- [ ] AC-7: `configure(app); configure(app)` raises nothing, awaits `post_configure()` once, emits one `AgentConfiguredEvent`.
- [ ] AC-8: `configure(); configure(app)` runs the pipeline again and binds `self.app`.
- [ ] `configure(app); configure()` is a no-op and leaves `self.app` bound.
- [ ] AC-9: `configure_count` reports entries; `reconfigure()` resets it and re-runs the pipeline.
- [ ] AC-10: `configure()` still sets `is_configured` to `True` in `finally` when the body raises.
- [ ] `configure()` / `post_configure()` signatures unchanged.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/abstract.py packages/ai-parrot/tests/bots/test_double_configure.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q`

---

## Test Specification

See the CREATE block above — five tests covering AC-7…AC-10 plus the no-unbind rule.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2 Overview, §3 M2, §7 Known Risks).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run every `grep -cF` above; 0 means drift: stop and report.
5. **Update status** in `sdd/tasks/index/double-configure-agents.json` → `"in-progress"`; commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the two files above.
9. **Close** with `scripts/sdd/close_task.sh TASK-4597 double-configure-agents verified`.
10. **Fill in the Completion Note** (record the guard-rule refinement), commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (attempt 3)

AbstractBot.configure idempotency (_configure_count, configure_count, reconfigure). Same env-caused validation failure; tests/bots/test_double_configure.py pass. tests/interfaces/test_configure_applies_tooling.py fails identically on origin/dev (AbstractBot abstract-instantiation) - pre-existing, not caused by this feature. Deviation: bare configure() re-entry is a no-op and never unbinds self.app.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: the guard also short-circuits a re-entry with NO app (spec §2 only named "same app") so a bare `configure()` cannot unbind `self.app`.
