# TASK-4616: Publish the configure no-op decision on `AbstractBot`

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:81fa838a18c1`

---

## Context

Implements spec §3 Module 1. This is the root of the feature graph: every other
code task reads one of the two members this task adds.

FEAT-721 made `AbstractBot.configure()` idempotent per instance, but the guard
protects only the **base** pipeline. Subclass overrides do their own work around
`await super().configure(app)` and are unguarded, so the base no-ops while the
subclass body runs again (`issue:81fa838a18c1`).

The recipe currently written in `docs/agent-configure-lifecycle.md` §6 and in
the `configure()` docstring (`abstract.py:1587-1588`) — `if self.configure_count
> 1: return` — **is wrong**. The base's no-op condition is
`_configure_count > 1 AND (resolved_app is None or resolved_app is
previous_app)` (`abstract.py:1604`). On the CLI-then-server path, where an app
arrives where none was bound before, `_configure_count` is 2 **and the base runs
its full pipeline**. An override guarded on `configure_count > 1` would skip its
own setup on a configure that genuinely ran — trading a double-run bug for a
silent missing-setup bug.

An override cannot re-derive that decision, because it depends on
`resolved_app is previous_app`, resolved inside the base. So the base must
**publish** it. This task adds the two signals and expresses the no-op condition
exactly once.

---

## Scope

- Add `_configure_skipped: bool` to `AbstractBot.__init__`, initialized `False`,
  beside the existing `_configure_count` (`abstract.py:370`).
- Extract the app resolution currently inlined in `configure()`
  (`abstract.py:1600-1602`) into `_resolve_configure_app(app)` and call it from
  `configure()`, so `configure()` and `configure_is_noop()` can never diverge.
- Set `self._configure_skipped = True` on the early-return branch and `False` on
  the branch that runs the pipeline.
- Add the `configure_skipped` property (post-super signal).
- Add the `configure_is_noop(app=None)` **sync** predicate (pre-super signal).
- Correct the `configure()` docstring at `abstract.py:1587-1588` to prescribe
  `configure_skipped` instead of `configure_count > 1`.
- Create `packages/ai-parrot/tests/bots/test_configure_override_guards.py` with
  the Module 1 signal tests.

**NOT in scope**:
- Guarding any override site — post-super sites are TASK-4617, pre-super sites
  are TASK-4618.
- Changing `configure()`'s no-op *condition*, its `try/except/finally` contract,
  or its `None` return type. This task publishes the existing decision; it does
  not redefine it.
- Changing `reconfigure()` (`abstract.py:1891`). It already resets
  `_configure_count` to 0; the pipeline branch then sets `_configure_skipped =
  False` on its own.
- Rewriting `docs/agent-configure-lifecycle.md` — that is TASK-4621. Only the
  in-code docstring is corrected here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `_configure_skipped` init, `_resolve_configure_app`, both branches set the flag, `configure_skipped`, `configure_is_noop`, docstring fix |
| `packages/ai-parrot/tests/bots/test_configure_override_guards.py` | CREATE | Module 1 signal tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Every anchor below re-confirmed `grep -c` = 1.

### Verified Imports

```python
from aiohttp import web                              # verified: used by abstract.py configure() at :1602
from parrot.bots.abstract import AbstractBot         # verified: packages/ai-parrot/src/parrot/bots/abstract.py:201
```

Test file imports — reuse the FEAT-721 helpers rather than inventing new ones:

```python
import pytest                                        # verified: packages/ai-parrot/tests/bots/test_double_configure.py
# packages/ai-parrot/tests/bots/test_double_configure.py defines _stub_bot / _app helpers (FEAT-721);
# read that file first and reuse its construction pattern.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:201
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):
    self._configure_count: int = 0                        # line 370
    self._configured: bool                                # set False/True inside configure()

    async def configure(self, app=None) -> None:          # line 1575
        # current body, lines 1600-1609:
        #     previous_app = getattr(self, "app", None)                            # 1600
        #     resolved_app = None                                                  # 1601
        #     if app:                                                              # 1601-1602
        #         resolved_app = app if isinstance(app, web.Application) else app.get_app()
        #     self._configure_count = getattr(self, "_configure_count", 0) + 1     # 1603
        #     if self._configure_count > 1 and (resolved_app is None
        #             or resolved_app is previous_app):                            # 1604
        #         self.logger.info(                                                # 1605
        #             "configure() already ran for '%s' (entry #%d); skipping. "
        #             "Use reconfigure() to force a re-run.",
        #             getattr(self, "name", self.__class__.__name__),
        #             self._configure_count,
        #         )
        #         return                                                           # 1609
        #     self._configured = False                                             # 1610

    @property
    def is_configured(self) -> bool: ...                  # line 1882

    @property
    def configure_count(self) -> int:                     # line 1887
        return getattr(self, "_configure_count", 0)       # line 1889 — tolerant getattr pattern to copy

    async def reconfigure(self, app=None) -> None:        # line 1891
        self._configure_count = 0                         # line 1901
        await self.configure(app if app is not None else getattr(self, "app", None))
```

### Does NOT Exist

Re-verified repo-wide with `git grep` at `36b9847aa` — all introduced by this task:

- ~~`AbstractBot.configure_skipped`~~ — 0 hits anywhere in the repo
- ~~`AbstractBot._configure_skipped`~~ — 0 hits anywhere in the repo
- ~~`AbstractBot.configure_is_noop`~~ — 0 hits as a symbol. The only
  `configure_is_noop` substring in the repo is the **test name**
  `test_second_configure_is_noop` (`tests/bots/test_double_configure.py:83`) —
  do not mistake it for an existing method.
- ~~`AbstractBot._resolve_configure_app`~~ — 0 hits anywhere in the repo
- ~~`packages/ai-parrot/tests/bots/test_configure_override_guards.py`~~ — new file
- ~~`AbstractBot.configure()` returning `bool`~~ — it returns `None`. Do NOT
  change the return type to signal the decision; use the property.
- ~~`BaseBot.configure`~~ — `BaseBot` (`bots/base.py:91`) does not override
  `configure`. Nothing to do there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_configure_override_guards.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_count",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.reconfigure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.is_configured"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Copy the tolerant-`getattr` style already used by `configure_count`
(`abstract.py:1889`) for the new property. It exists because instances built via
`__new__` + manual attribute assignment never run `__init__` — a pattern
`bots/chrome.py:363-366` documents as already used by this repo's tests.

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:1887-1889 — the shape to mirror
@property
def configure_count(self) -> int:
    """How many times :meth:`configure` has been entered on this instance."""
    return getattr(self, "_configure_count", 0)
```

### Key Constraints

- `configure_is_noop` MUST be a plain `def`, not `async def`. Pre-super
  overrides (TASK-4618) must call it before their first `await`; making it a
  coroutine would force them to `await` before doing their own work and defeat
  the purpose.
- `_resolve_configure_app` must be extracted **verbatim** — same `if app:`
  truthiness test (not `if app is not None:`), same `isinstance(app,
  web.Application)` check, same `app.get_app()` fallback. Changing the
  truthiness test would alter behaviour for a falsy-but-not-None app.
- The no-op condition must appear **once**. After this task,
  `configure_is_noop()` is the single place it is written, and `configure()`
  calls it. If you leave the condition duplicated in both, the task has failed
  its purpose.
- Keep the existing INFO log exactly where it is and with the same message —
  TASK-4618's pre-super pattern deliberately still calls
  `super().configure(app)` on the no-op path so this log and the counter
  increment still happen.
- Full type hints and Google-style docstrings; `self.logger`, never `print`.
- 120-column lines (`black`), `ruff check --fix` clean.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/abstract.py:1575-1610` — the method to modify
- `packages/ai-parrot/src/parrot/bots/abstract.py:1882-1902` — where the new members go
- `packages/ai-parrot/tests/bots/test_double_configure.py` — FEAT-721 tests; reuse its `_stub_bot` / `_app` helpers
- `docs/agent-configure-lifecycle.md` §1, §2, §6 — the contract being corrected

---

## Implementation Blueprint

### Steps (in order)

1. Read `abstract.py:1575-1615` and `:1880-1905` in full — *why*: the edit
   touches a 35-line region of a long method and two adjacent property
   definitions; a blind insert will land in the wrong block.
2. Read `packages/ai-parrot/tests/bots/test_double_configure.py` — *why*: it
   already builds a configurable stub bot; reuse those helpers instead of
   writing a new fixture that drifts from FEAT-721's.
3. Add `self._configure_skipped: bool = False` beside `_configure_count` — *why*:
   an instance must have a defined signal before its first `configure()`.
4. Extract `_resolve_configure_app` and call it from `configure()` — *why*: the
   predicate and the method must resolve the app identically; one function is
   the only way to guarantee that.
5. Add `configure_is_noop`, then rewrite `configure()`'s guard to call it —
   *why*: the condition must live in exactly one place.
6. Set `_configure_skipped` on **both** branches — *why*: a stale `True` from a
   previous no-op would make the next genuine configure look skipped, which is
   the exact failure this feature exists to prevent.
7. Add the `configure_skipped` property and fix the docstring at `:1587-1588` —
   *why*: the wrong recipe is what an implementer of TASK-4617/4618 will read.
8. Write the tests, then run the Validation Commands — *why*: the CLI-then-server
   case is the one no existing test covers.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — init)

```python
# occurrences: 1 (verified: grep -c '        self._configure_count: int = 0' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — insert below `        self._configure_count: int = 0` (verified: abstract.py:370)
        self._configure_skipped: bool = False
```

**Why**: gives every instance a defined post-super signal before its first
`configure()`, so `configure_skipped` is `False` (not missing) on a fresh bot.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — app resolution + guard)

```python
# occurrences: 1 (verified: grep -c '        self._configure_count = getattr(self, "_configure_count", 0) + 1' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE the region from `        previous_app = getattr(self, "app", None)` (abstract.py:1600)
# through `            return` (abstract.py:1609) with the block below.
# The lines after it (`        self._configured = False`, abstract.py:1610) are unchanged.
        self._configure_count = getattr(self, "_configure_count", 0) + 1
        if self.configure_is_noop(app):
            self._configure_skipped = True
            self.logger.info(
                "configure() already ran for '%s' (entry #%d); skipping. Use reconfigure() to force a re-run.",
                getattr(self, "name", self.__class__.__name__),
                self._configure_count,
            )
            return
        self._configure_skipped = False
        resolved_app = self._resolve_configure_app(app)
```

**Why**: the counter still increments on every entry (unchanged observable
behaviour), but the *condition* now lives only in `configure_is_noop`. Note the
ordering: `configure_is_noop` compares `self._configure_count > 1`, so it must be
called **after** the increment — that reproduces the original `:1604` test
exactly. `resolved_app` is still needed by the lines below (`self.app =
resolved_app`), so it is assigned on the surviving path. Do NOT reorder the
increment and the check.

```python
# FILL IN: the original lines 1600-1602 assigned `previous_app` and `resolved_app`
# before the guard. Confirm by reading abstract.py:1610-1625 which of the two the
# code *after* the guard still uses, and keep only those assignments — bounded by
# "configure()'s observable behaviour is unchanged" (AC: no breaking change).
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — new members)

```python
# occurrences: 1 (verified: grep -c '    def configure_count(self) -> int:' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — insert below the `configure_count` property's body (verified: abstract.py:1887-1889),
# i.e. between `configure_count` and `async def reconfigure` (abstract.py:1891)

    @property
    def configure_skipped(self) -> bool:
        """Whether the most recent :meth:`configure` entry was an idempotent no-op.

        ``False`` before the first ``configure()`` and after any entry that ran
        the pipeline — including a genuine reconfiguration (an app arriving
        where none was bound) and :meth:`reconfigure`.

        Overrides that do their own work AFTER ``await super().configure(app)``
        read this and return early when it is ``True``. Do NOT use
        ``configure_count > 1`` for that purpose: it is ``2`` on the
        CLI-then-server path, where the pipeline genuinely DID run.

        Returns:
            True when the last entry skipped the pipeline, else False.
        """
        return getattr(self, "_configure_skipped", False)

    def _resolve_configure_app(self, app) -> Optional[web.Application]:
        """Resolve ``app`` to a :class:`aiohttp.web.Application` or ``None``.

        The single app-resolution used by both :meth:`configure` and
        :meth:`configure_is_noop`, so the two can never disagree about which
        app a call refers to.

        Args:
            app: An ``aiohttp`` application, an object exposing ``get_app()``,
                or ``None``.

        Returns:
            The resolved application, or ``None`` when ``app`` is falsy.
        """
        if not app:
            return None
        return app if isinstance(app, web.Application) else app.get_app()

    def configure_is_noop(self, app=None) -> bool:
        """Whether a :meth:`configure` call with ``app`` would be a no-op.

        Deliberately synchronous: overrides that do their own work BEFORE
        ``await super().configure(app)`` must consult it first, and an
        ``async`` predicate would force them to await before deciding.

        Args:
            app: The app that would be passed to ``configure()``.

        Returns:
            True when ``configure(app)`` would log and return without running
            the pipeline.
        """
        # FILL IN: return the base's no-op condition — the entry count is above 1
        # AND the resolved app is either None or identical (`is`) to the currently
        # bound `self.app`. Mirror abstract.py:1604 exactly, reading the count via
        # the tolerant getattr and the bound app via `getattr(self, "app", None)`
        # — bounded by "configure_is_noop agrees with the branch configure()
        # actually takes, for all three paths" (AC: test_configure_is_noop_matches_configure_decision).
```

**Why**: `configure_skipped` is the post-super signal, `configure_is_noop` the
pre-super one, and `_resolve_configure_app` is what keeps them consistent with
`configure()`. The `FILL IN` is the one line that must mirror `:1604`; it is left
open deliberately so the implementer reads that line rather than trusting this
blueprint's paraphrase of it. `Optional` and `web` must already be imported in
`abstract.py` — verify before use; `web` is used at `:1602`.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — docstring fix)

```python
# occurrences: 1 (verified: grep -c '        ``if self.configure_count > 1: return``.' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE the two docstring lines at abstract.py:1587-1588:
#         Subclass overrides that do their own work AFTER
#         ``await super().configure(app)`` guard it with
#         ``if self.configure_count > 1: return``.
# with:
        Subclass overrides that do their own work AFTER
        ``await super().configure(app)`` guard it with
        ``if self.configure_skipped: return``. Overrides that work BEFORE the
        super() call guard it with ``if self.configure_is_noop(app): ...``.
        Do NOT use ``configure_count > 1``: it is ``2`` on the CLI-then-server
        path, where this method genuinely DOES run its pipeline.
```

**Why**: this docstring is the primary thing an implementer of TASK-4617/4618
reads; leaving the wrong recipe in it would reintroduce the bug through the next
contributor.

### `packages/ai-parrot/tests/bots/test_configure_override_guards.py` (CREATE)

```python
"""FEAT-726 — the configure() no-op decision is published to overrides.

Module 1 signal tests. TASK-4617 appends the post-super guard tests and
TASK-4618 the pre-super ones to this same file.
"""
import pytest

# FILL IN: import/construct the stub bot the same way
# packages/ai-parrot/tests/bots/test_double_configure.py does (its _stub_bot / _app
# helpers, FEAT-721) — bounded by "reuse, do not re-invent" (spec §4 Test Data).


@pytest.mark.asyncio
async def test_configure_skipped_false_before_first_configure() -> None:
    """A fresh instance reports False, not a missing attribute."""
    # FILL IN — bounded by AC "configure_skipped exists with the §2 contract"


@pytest.mark.asyncio
async def test_configure_skipped_false_after_first_configure() -> None:
    """The first configure() runs the pipeline, so the flag stays False."""
    # FILL IN — bounded by AC "configure() sets _configure_skipped on both branches"


@pytest.mark.asyncio
async def test_configure_skipped_true_on_repeat_same_app() -> None:
    """A second configure() with an unchanged app sets the flag True."""
    # FILL IN — bounded by AC "a second configure() with an unchanged app ... no-ops"


@pytest.mark.asyncio
async def test_configure_skipped_false_when_app_arrives_later() -> None:
    """CLI-then-server: an app arriving where none was bound RUNS the pipeline.

    This is the case `configure_count > 1` gets wrong and the reason this
    feature publishes the decision instead.
    """
    # FILL IN: configure() with no app, then configure(app) with a real web.Application;
    # assert configure_skipped is False and configure_count == 2
    # — bounded by AC "the CLI-then-server path still runs every override's own work"


@pytest.mark.asyncio
async def test_configure_skipped_false_after_reconfigure() -> None:
    """reconfigure() resets the counter, so the pipeline runs and the flag is False."""
    # FILL IN — bounded by AC "reconfigure() still re-runs both override shapes"


@pytest.mark.asyncio
async def test_configure_is_noop_matches_configure_decision() -> None:
    """The predicate agrees with the branch configure() actually takes.

    Covers all three paths: first call, repeat with the same app, and an app
    arriving where none was bound.
    """
    # FILL IN: for each path assert configure_is_noop(app) == (configure_skipped after the call)
    # — bounded by AC "the no-op condition is expressed once"


def test_configure_is_noop_is_sync() -> None:
    """configure_is_noop is a plain def — pre-super overrides call it before any await."""
    import inspect

    from parrot.bots.abstract import AbstractBot

    assert not inspect.iscoroutinefunction(AbstractBot.configure_is_noop)
```

**Why this shape**: `test_configure_skipped_false_when_app_arrives_later` and
`test_configure_is_noop_matches_configure_decision` are the two tests that make
the wrong `configure_count > 1` recipe fail; they are the point of the file. The
`_is_sync` test is cheap insurance against a later refactor making the predicate
a coroutine and silently breaking TASK-4618's pattern. Do not change the file
path or the test names — TASK-4617 and TASK-4618 append to this file.

### FILL IN checklist

- [ ] `abstract.py::AbstractBot.configure_is_noop` — the no-op condition mirroring `:1604`; bounded by `test_configure_is_noop_matches_configure_decision`
- [ ] `abstract.py::AbstractBot.configure` — which of `previous_app` / `resolved_app` the post-guard code still needs; bounded by "no breaking change to configure()"
- [ ] `test_configure_override_guards.py` — stub-bot construction reused from `test_double_configure.py`; bounded by spec §4 Test Data
- [ ] `test_configure_override_guards.py` — all six test bodies; bounded by the ACs named in each docstring

---

## Acceptance Criteria

- [ ] `AbstractBot.configure_skipped` (property) and
      `AbstractBot.configure_is_noop(app=None)` (plain `def`) exist with the
      spec §2 contracts.
- [ ] `_resolve_configure_app(app)` exists and is the only place the app is
      resolved; `configure()` calls it.
- [ ] The no-op condition appears exactly once in the file (inside
      `configure_is_noop`); `configure()` no longer spells it out.
- [ ] `configure()` sets `_configure_skipped` on BOTH branches.
- [ ] `configure()` keeps its `None` return type, its `try/except/finally`
      contract, its INFO log text and its counter semantics — no breaking change.
- [ ] `reconfigure()` is unmodified and still results in `configure_skipped ==
      False` after it runs.
- [ ] The `configure()` docstring at `abstract.py:1587-1588` prescribes
      `configure_skipped` / `configure_is_noop` and warns against
      `configure_count > 1`.
- [ ] All six tests in the new file pass, including the CLI-then-server case.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_configure_override_guards.py -q`
- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`
- `pytest packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py -q`

---

## Test Specification

See the Implementation Blueprint's CREATE block — it is the test scaffold for
this task. Run inside the worktree with
`PYTHONPATH=packages/ai-parrot/src`; a bare `pytest` imports the main
checkout's `parrot`, not this branch's.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§1 for the
   mechanism, §2 for the design, §6 for the verified contract)
3. **Check dependencies** — none; this is the root task
4. **Verify the Codebase Contract** — re-run each `grep -c` above before editing;
   `abstract.py` is long and moves often
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4616 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented as specified, with one design correction found during
implementation and folded in:

**`configure_is_noop` is prospective, not retrospective.** The blueprint had
`configure()` increment the counter and then call the predicate, which implies
a `> 1` test. But a pre-super override asks the question from *outside*
`configure()`, where the counter has not yet been incremented — after one
completed configure it reads 1, so a `> 1` test would answer `False` and let
the override's pre-super work run a second time. The predicate therefore tests
`configure_count >= 1` and `configure()` calls it BEFORE incrementing. Both
callers now get the same answer. `test_configure_is_noop_is_prospective_before_any_increment`
pins this; without the fix TASK-4618's whole pattern would have been a no-op.

`previous_app` was dropped from `configure()` (it is now read inside the
predicate); `resolved_app` is assigned after the guard, where the surviving
path uses it. Observable behaviour of `configure()` is unchanged: same counter
semantics, same INFO log text, same `None` return, same try/except/finally.

Tests: 11 added in `tests/bots/test_configure_override_guards.py`. The file
duplicates FEAT-721's `_stub_bot`/`_app` helpers rather than importing them —
cross-test-module import (`from test_double_configure import ...`) raises
`ModuleNotFoundError` under this suite's pytest import mode. A comment marks
the two as needing to stay in sync.

Validation: `pytest tests/bots/test_configure_override_guards.py
tests/bots/test_double_configure.py -q` → **17 passed**. `ruff check` clean on
both files.
