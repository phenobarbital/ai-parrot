---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fix `_prompt_builder` AttributeError in JiraSpecialist under pytest (conftest stub leak)

**Feature ID**: FEAT-268
**Date**: 2026-07-01
**Author**: Jesus Lara (filed from FEAT-265 post-merge code review findings)
**Status**: approved
**Target version**: (next patch)

> Follow-up to **FEAT-265 (jiraspecialist-trigger-agent-orchestrator)** — the
> post-merge code review for FEAT-265 surfaced this as a pre-existing,
> unrelated bug (confirmed present on `dev` *before* the FEAT-265 merge via
> bisection against commit `c2188ddc3`). FEAT-265's own test suite
> (`test_jira_transition_dispatch.py`, 46/46 passing) is unaffected because it
> deliberately bypasses `JiraSpecialist.__init__` (see §6 below) — this bug
> only affects test files that construct `JiraSpecialist` the normal way.

---

## 1. Motivation & Business Requirements

### Problem Statement

Four existing test files raise `AttributeError: 'JiraSpecialist' object has no
attribute '_prompt_builder'` when run under pytest, even though the identical
construction code (same class, same mocks) succeeds when run as a plain
Python script outside pytest:

- `packages/ai-parrot/tests/test_jira_assignment.py` (13 failures)
- `packages/ai-parrot/tests/test_jiratoolkit_defaults.py`
- `packages/ai-parrot/tests/test_jira_ticket_created.py`
- `packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py` (5/7 failing)

**Root cause (fully diagnosed and reproduced during FEAT-265's follow-up
investigation):**

`packages/ai-parrot/tests/conftest.py` defines `_install_parrot_stubs()`
(lines 376-434), which builds **fake, minimal stand-ins** for
`parrot.bots.abstract.AbstractBot` and `parrot.bots.agent.Agent`/`BasicAgent`
(for the benefit of *other*, unrelated lightweight AgentCrew-style tests that
don't want to pay the cost of importing the real heavy dependency chain), and
registers them into `sys.modules` via:

```python
sys.modules.setdefault("parrot.bots.abstract", bots_abstract_module)  # line 422
sys.modules.setdefault("parrot.bots.agent", bots_agent_module)        # line 434
```

This call happens **unconditionally at conftest import time** (line 627:
`_install_parrot_stubs()`, executed at module scope, not inside a fixture),
which is *before* pytest imports any test module in `packages/ai-parrot/tests/`.
Because `sys.modules.setdefault(...)` only takes effect if the key is not
already present, and `parrot.bots.abstract` / `parrot.bots.agent` are
typically **not yet imported** at that point in the session, the fake stub
modules win the race and get cached in `sys.modules` for the **entire pytest
process** — not just for the tests that asked for them.

Any test file that subsequently does `from parrot.bots.jira_specialist import
JiraSpecialist` and then really constructs `JiraSpecialist(**kwargs)` (i.e.
does **not** bypass `__init__`) ends up with `JiraSpecialist`'s `Agent` base
class silently resolved to the **fake** `_BasicAgent` (conftest.py:424,
aliased as both `BasicAgent` and `Agent` at conftest.py:432-433) instead of
the real `parrot.bots.agent.Agent`. The fake `_AbstractBot.__init__`
(conftest.py:412-417) only sets `name`, `tool_manager`, `use_llm`, `llm`,
`_llm` — it has no notion of `_prompt_builder` at all, and neither fake class
declares it as a class attribute anywhere (unlike the real
`AbstractBot._prompt_builder: Optional[PromptBuilder] = None` class-level
default at `packages/ai-parrot/src/parrot/bots/abstract.py:187`).

`JiraSpecialist.__init__` (`packages/ai-parrot/src/parrot/bots/jira_specialist.py:228`)
then does an **unguarded** attribute read:

```python
if self._prompt_builder is None:
```

which raises `AttributeError` against the fake MRO. Notably, the real
`Agent.__init__` (`packages/ai-parrot/src/parrot/bots/agent.py:95`) already
uses a **defensive** pattern for exactly this class of risk:

```python
if system_prompt is None and getattr(self, "_prompt_builder", None) is None:
```

`JiraSpecialist.__init__` does not follow that established convention.

### Why this is order-dependent / flaky

Whether a given test file trips this bug depends on whether
`parrot.bots.abstract` / `parrot.bots.agent` have already been really
imported elsewhere in the same pytest session before `_install_parrot_stubs()`
runs (unlikely, since conftest.py loads before any test module) — **and**,
more importantly, whether the *specific* test file constructs
`JiraSpecialist` via its real `__init__` at all. `test_jira_transition_dispatch.py`
(FEAT-265's own suite) is immune because its `_make_specialist()` helper
(`test_jira_transition_dispatch.py:43-62`) explicitly documents bypassing the
constructor:

```python
def _make_specialist(transition_actions=None):
    """... Uses ``object.__new__`` to bypass the heavy ``__init__`` (Redis,
    Jira, LLM client, Telegram) that is irrelevant to the dispatch tests."""
    obj = object.__new__(JiraSpecialist)
    obj._transition_actions = transition_actions or []
    ...
```

This also explains the "order-dependent test pollution" symptom flagged by
the FEAT-265 code review when multiple jira test files were run together in
one large combination — the stub leak's effect is a `sys.modules`-wide,
session-global side effect, not scoped to any one test file.

### Goals

- `JiraSpecialist()` (and any other `AbstractBot`/`Agent` subclass
  constructed the normal way) must work correctly when run under pytest from
  `packages/ai-parrot/tests/`, regardless of collection order or which other
  test files are collected alongside it.
- `_install_parrot_stubs()`'s fake `parrot.bots.abstract` / `parrot.bots.agent`
  modules must remain available to the tests that actually want them, but
  must **not** leak into `sys.modules` for tests that need the real classes.
- Apply the low-risk, in-place defensive fix to `JiraSpecialist.__init__`
  (mirroring the existing `Agent.__init__` pattern) as a safety net, even
  after the conftest leak is fixed, since a bare `self._attr` read against an
  optional attribute is fragile by construction.
- Unskip/re-verify the four affected test files pass cleanly, both in
  isolation and as part of the full `packages/ai-parrot/tests/` suite.

### Non-Goals (explicitly out of scope)

- Any change to FEAT-265's own code or tests (`_types.py`, `jira_specialist.py`'s
  `_action_trigger_agent`, `test_jira_transition_dispatch.py`) beyond the one
  defensive line described above — that feature is already merged and
  verified independently.
- A broader audit/refactor of `_install_parrot_stubs()` or the other stub
  installers (`_install_navconfig_stub`, `_install_navigator_stubs`) beyond
  what's needed to stop this specific leak — do not redesign the fixture
  architecture wholesale.
- Fixing unrelated warnings/collection errors seen in the broader
  `pytest packages/ai-parrot/tests/ -k jira` run (e.g. unrelated
  `test_cmc_fear_greed.py` / `test_botmanager_flags.py` collection errors) —
  those are separate, unrelated issues.

---

## 2. Architectural Design

### Overview

Two independent, complementary changes:

1. **Stop the leak at the source** — scope `_install_parrot_stubs()`'s
   `sys.modules` mutation so it no longer permanently overwrites
   `parrot.bots.abstract` / `parrot.bots.agent` for the whole pytest session.
   The cleanest fix consistent with pytest idioms: convert the unconditional
   module-level calls (conftest.py:625-627) into a `pytest.fixture` (or a
   `monkeypatch.setitem`-based helper) that only the tests actually relying on
   the fake stubs opt into, using `monkeypatch.setitem(sys.modules, ...)` so
   the change is automatically undone at the end of each test/fixture scope
   instead of persisting for the rest of the process.
2. **Defensive hardening in `JiraSpecialist.__init__`** — replace the bare
   `self._prompt_builder` read at `jira_specialist.py:228` with the same
   `getattr(self, "_prompt_builder", None)` guard already used in
   `Agent.__init__` (`agent.py:95`), so a similarly-shaped MRO surprise in the
   future degrades gracefully instead of raising `AttributeError`.

### Component Diagram

```
pytest session start
        │
        ▼
packages/ai-parrot/tests/conftest.py (module-level, TODAY)
        │
        ├─ _install_navconfig_stub()
        ├─ _install_navigator_stubs()
        └─ _install_parrot_stubs()          ← unconditional, leaks into
               │                              sys.modules for whole session
               ▼
     sys.modules["parrot.bots.agent"] = FAKE _BasicAgent   (sticky, global)
               │
               ▼
   any later `from parrot.bots.jira_specialist import JiraSpecialist`
   + real JiraSpecialist(**kwargs) construction
               │
               ▼
   JiraSpecialist(Agent) resolves to FAKE _BasicAgent → no _prompt_builder
   → AttributeError at jira_specialist.py:228

──────────────────────────── AFTER THE FIX ────────────────────────────

_install_parrot_stubs() becomes an opt-in fixture using
monkeypatch.setitem(sys.modules, ...) — scoped, auto-restored;
JiraSpecialist.__init__ also uses getattr(self, "_prompt_builder", None)
as a second line of defense.
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot/tests/conftest.py::_install_parrot_stubs` | refactor | Convert from unconditional module-level call to an opt-in, `monkeypatch`-scoped fixture |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py::JiraSpecialist.__init__` | modify | One-line defensive `getattr` fix, mirroring `agent.py:95` |
| `packages/ai-parrot/tests/test_jira_assignment.py` | consumer (no change expected) | Must pass once the leak is fixed |
| `packages/ai-parrot/tests/test_jiratoolkit_defaults.py` | consumer (no change expected) | Must pass once the leak is fixed |
| `packages/ai-parrot/tests/test_jira_ticket_created.py` | consumer (no change expected) | Must pass once the leak is fixed |
| `packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py` | consumer (no change expected) | Must pass once the leak is fixed |

### New Public Interfaces

None — this is a test-infrastructure bug fix plus a one-line defensive
hardening in existing code. No new public API.

---

## 3. Module Breakdown

### Module 1: Scope the conftest stub leak

- **Path**: `packages/ai-parrot/tests/conftest.py`
- **Responsibility**: Convert `_install_parrot_stubs()` (and its
  module-level invocation at line 627) so the `parrot.bots.abstract` /
  `parrot.bots.agent` fake-module injection is scoped to only the tests that
  request it (via a `pytest.fixture` using `monkeypatch.setitem(sys.modules,
  key, fake_module)`), instead of mutating the global, session-wide
  `sys.modules` cache unconditionally at import time. Identify (via `grep -rl`
  for usages of the fake `_BasicAgent`/`_ToolManager`/etc. symbols this
  function currently provides) which existing tests rely on the fake stubs
  being present, and convert them to request the new fixture explicitly.
- **Depends on**: nothing new.

### Module 2: Defensive hardening in `JiraSpecialist.__init__`

- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Change line 228 from `if self._prompt_builder is None:`
  to `if getattr(self, "_prompt_builder", None) is None:`, matching the
  existing pattern in `agent.py:95`. No other behavior change.
- **Depends on**: nothing new (independent of Module 1; can land in either
  order or in parallel).

### Module 3: Verification

- **Path**: n/a (test execution only)
- **Responsibility**: Confirm the four affected test files pass both in
  isolation and as part of the full `packages/ai-parrot/tests/` collection;
  confirm `test_jira_transition_dispatch.py` (FEAT-265) still passes 46/46
  unaffected; confirm no other test that relied on the fake stubs regressed.
- **Depends on**: Modules 1, 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_jira_assignment.py` (all) | 1, 2 | Must pass under `pytest packages/ai-parrot/tests/test_jira_assignment.py -v` |
| `test_jiratoolkit_defaults.py` (all) | 1, 2 | Must pass under `pytest packages/ai-parrot/tests/test_jiratoolkit_defaults.py -v` |
| `test_jira_ticket_created.py` (all) | 1, 2 | Must pass under `pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v` |
| `test_jiraspecialist_prompt_builder.py` (all) | 1, 2 | Must pass under `pytest packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py -v` |
| Any pre-existing test that consumed the fake `_AbstractBot`/`_BasicAgent`/`_ToolManager` stubs | 1 | Must still pass after converting to the opt-in fixture (identify via grep before changing) |

### Integration Tests

| Test | Description |
|---|---|
| Full suite regression | `pytest packages/ai-parrot/tests/ -k jira -v` should no longer show the `_prompt_builder` `AttributeError` collection/failure pattern |
| FEAT-265 non-regression | `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v` must still show 46/46 passing |

### Test Data / Fixtures

```python
# Example of the fixture-scoped replacement for Module 1
import sys
import types
import pytest


@pytest.fixture
def fake_parrot_bots(monkeypatch):
    """Opt-in fake AbstractBot/Agent stand-ins for lightweight AgentCrew tests.

    Scoped via monkeypatch so sys.modules is restored automatically at
    teardown — unlike the old sys.modules.setdefault() approach, this never
    leaks into unrelated tests that need the real classes.
    """
    # ... build _AbstractBot / _BasicAgent / bots_abstract_module /
    # bots_agent_module exactly as _install_parrot_stubs() does today ...
    monkeypatch.setitem(sys.modules, "parrot.bots.abstract", bots_abstract_module)
    monkeypatch.setitem(sys.modules, "parrot.bots.agent", bots_agent_module)
    yield
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `_install_parrot_stubs()`'s `sys.modules["parrot.bots.abstract"]` /
      `sys.modules["parrot.bots.agent"]` injection no longer happens
      unconditionally at conftest import time — it is scoped to an opt-in
      fixture (or equivalent scoped mechanism) restored via `monkeypatch`.
- [ ] Every existing test that relied on the fake stubs still passes after
      the refactor (identified explicitly, not assumed).
- [ ] `JiraSpecialist.__init__` (`jira_specialist.py:228`) uses
      `getattr(self, "_prompt_builder", None)` instead of a bare
      `self._prompt_builder` read.
- [ ] `pytest packages/ai-parrot/tests/test_jira_assignment.py -v` — all pass.
- [ ] `pytest packages/ai-parrot/tests/test_jiratoolkit_defaults.py -v` — all pass.
- [ ] `pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v` — all pass.
- [ ] `pytest packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py -v` — all pass.
- [ ] `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v` — still 46/46 passing (no FEAT-265 regression).
- [ ] No new files created outside `packages/ai-parrot/tests/conftest.py` and
      `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (plus any test
      files that need updating to request the new fixture explicitly).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `dev` at spec
> time (post FEAT-265 merge, commit `ff85a8330`). Re-verify line numbers
> before editing.

### Verified Imports

```python
# packages/ai-parrot/tests/conftest.py — already imported at top of file
import sys                                    # line 6
import types                                  # line 9
import pytest                                 # line 12
```

### Existing Class Signatures

```python
# packages/ai-parrot/tests/conftest.py
def _install_parrot_stubs() -> None:          # line 376
    class _ToolManager: ...                    # line 380
    class _AbstractBot:                        # line 411
        def __init__(self, name: str = "Agent", **_): ...  # line 412
            # sets: self.name, self.tool_manager, self.use_llm,
            #       self.llm, self._llm — NO _prompt_builder anywhere
    bots_abstract_module = types.ModuleType("parrot.bots.abstract")  # line 419
    bots_abstract_module.AbstractBot = _AbstractBot                 # line 420
    sys.modules.setdefault("parrot.bots.abstract", bots_abstract_module)  # line 422
    class _BasicAgent(_AbstractBot):           # line 424
        async def configure(self): ...          # line 425
        def agent_tools(self): ...              # line 428
    bots_agent_module = types.ModuleType("parrot.bots.agent")  # line 431
    bots_agent_module.BasicAgent = _BasicAgent  # line 432
    bots_agent_module.Agent = _BasicAgent       # line 433
    sys.modules.setdefault("parrot.bots.agent", bots_agent_module)  # line 434

# module-level invocation, unconditional:
_install_navconfig_stub()    # line 625
_install_navigator_stubs()   # line 626
_install_parrot_stubs()      # line 627

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                   EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # line 156
    _prompt_builder: Optional[PromptBuilder] = None  # line 187 (class-level default)

# packages/ai-parrot/src/parrot/bots/agent.py — the established defensive pattern to mirror
class Agent(AbstractBot):
    def __init__(self, ..., **kwargs):
        super().__init__(...)
        if system_prompt is None and getattr(self, "_prompt_builder", None) is None:  # line 95
            self._prompt_builder = PromptBuilder.agent()  # line 96

# packages/ai-parrot/src/parrot/bots/jira_specialist.py — the buggy unguarded read (TO FIX)
class JiraSpecialist(Agent):                    # line 155
    def __init__(self, **kwargs):                # line 205
        ...
        super().__init__(**kwargs)                # line 225
        if self._prompt_builder is None:           # line 228 — CHANGE to getattr(self, "_prompt_builder", None)
            self.prompt_builder = _builder

# packages/ai-parrot/tests/test_jira_transition_dispatch.py — why FEAT-265's own suite is immune
def _make_specialist(transition_actions=None):    # line 43
    """... Uses object.__new__ to bypass the heavy __init__ ..."""
    obj = object.__new__(JiraSpecialist)          # line 57 — never calls __init__, never hits line 228
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `fake_parrot_bots` fixture (Module 1, new) | `sys.modules` | `monkeypatch.setitem` | new, replaces conftest.py:625-627 |
| `JiraSpecialist.__init__` (patched) | `self._prompt_builder` | `getattr(..., None)` guard | `jira_specialist.py:228` |

### Does NOT Exist (Anti-Hallucination)

- ~~`JiraSpecialist._prompt_builder` as an instance attribute set anywhere
  in the fake `_AbstractBot`/`_BasicAgent` stubs~~ — confirmed absent; the
  fakes only set `name`, `tool_manager`, `use_llm`, `llm`, `_llm`
  (conftest.py:412-417).
- ~~A conftest-level `autouse=True` fixture responsible for this~~ — the
  leak is caused by an **unconditional module-level function call**
  (conftest.py:627), not an autouse fixture; there is no autouse fixture in
  this file (`grep -n autouse packages/ai-parrot/tests/conftest.py` returns
  nothing).
- ~~A regression introduced by FEAT-265~~ — confirmed pre-existing via
  bisection against `dev` commit `c2188ddc3` (immediately before the FEAT-265
  merge); FEAT-265 never touches `conftest.py` or this code path.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `monkeypatch.setitem(sys.modules, key, value)` for any `sys.modules`
  mutation in tests/fixtures — this is pytest's built-in, auto-restoring
  mechanism, and is strictly preferable to manual `sys.modules[key] = ...` /
  `sys.modules.setdefault(...)` for anything used inside a test session.
- Preserve the exact fake class bodies/behavior of `_ToolManager`,
  `_AbstractBot`, `_BasicAgent` — only change *how* and *when* they get
  registered into `sys.modules`, not what they do.
- Match the existing `agent.py:95` defensive-`getattr` idiom exactly when
  fixing `jira_specialist.py:228` — do not invent a different pattern (e.g.
  `hasattr` + separate read, or a `try/except AttributeError`).

### Known Risks / Gotchas

- **Before changing `_install_parrot_stubs()`, find every current consumer.**
  Some existing tests almost certainly rely on the *unscoped* leak (i.e. they
  never explicitly request the fake stubs but happen to work because the
  fakes are already sitting in `sys.modules` by the time they run). Run
  `grep -rl "_BasicAgent\|BasicAgent\|parrot.bots.agent\|parrot.bots.abstract" packages/ai-parrot/tests/` first,
  then re-run the **full** `packages/ai-parrot/tests/` suite before and after
  the refactor to confirm nothing that previously passed regresses.
- **Fixture ordering across conftest hierarchy**: `packages/ai-parrot/tests/conftest.py`
  is one of several conftest files in the tree (root `./conftest.py`,
  `packages/ai-parrot/conftest.py`, plus many subdirectory conftests). Scope
  the new fixture at the same level (`packages/ai-parrot/tests/conftest.py`)
  unless a narrower directory-level conftest is more appropriate for the
  specific consuming tests.
- **Do not attempt to also fix** the unrelated collection errors from
  `pytest packages/ai-parrot/tests/ -k jira` (e.g. `test_cmc_fear_greed.py`,
  `test_botmanager_flags.py`) — those are separate, pre-existing issues
  outside this spec's scope.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | Uses pytest's built-in `monkeypatch` fixture; no new deps |

---

## 8. Open Questions

- [ ] **Which existing tests currently depend on the unscoped stub leak?**
      Must be enumerated via `grep` before Module 1 lands, since converting
      to an opt-in fixture will break any test that implicitly relied on the
      global `sys.modules` mutation without requesting it. *Owner: implementer*
- [ ] **Should the fixture be `function`-scoped or `session`-scoped?**
      `function`-scoped is safer (fully isolated per test) but slower if many
      tests need it; `session`-scoped risks reintroducing partial leakage
      across tests within the same session if not carefully torn down.
      Recommend starting with `function`-scoped and only widening if a
      measured performance concern emerges. *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (both modules are small and tightly
  coupled — a worktree adds ceremony disproportionate to the change, but
  follow standard SDD flow since this is a multi-file, testable change).
- **Cross-feature dependencies**: builds on the already-merged FEAT-265
  investigation; no other spec must merge first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-01 | Jesus Lara | Initial draft, filed from FEAT-265 post-merge code review findings (fully diagnosed root cause via manual bisection) |
