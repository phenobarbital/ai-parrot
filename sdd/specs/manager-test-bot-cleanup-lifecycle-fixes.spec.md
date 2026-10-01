---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [test-infrastructure, conftest, sys-modules, merge-gate, collection-errors]
---

# Feature Specification: Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)

**Feature ID**: FEAT-617
**Date**: 2026-10-01
**Author**: Jesus Lara (via /sdd-fix, ledger issue:c3c59277ef77)
**Status**: draft
**Target version**: 0.29.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:c3c59277ef77` (critical, opened 2026-09-22 from FEAT-590) reports that
sdd-coder **merge-tier validation** cannot reach a clean `completed` outcome for
any feature touching widely-reached core files: the selector's import-impact
sweep pulls in `packages/ai-parrot/tests/`, which fails collection wholesale.

Re-verified on `dev` @ `72e238df2` (2026-10-01): **18 collection errors**
(down from the 25 originally reported, none of the remainder fixed by accident).

The errors are **not** evidence of broken product code. Partitioning each failing
file by collecting it in isolation, and re-checking every "missing" symbol with a
plain `python -c` import, gives:

| Bucket | Count | Nature |
|---|---|---|
| **A. Stub poisoning** | 14 | The symbol/module exists and imports fine standalone. `tests/conftest.py` installs ~40 `types.ModuleType` stubs via `sys.modules.setdefault()` at *conftest import time*. `setdefault` pre-empts the real module whenever that module has not been imported *yet* — so the real symbols vanish for the rest of the process. The tell is `(unknown location)` in the ImportError (a `ModuleType` stub has no `__file__`). |
| **B. Genuinely stale tests** | 4 | Reference code or fixture files that really are gone. |

Bucket A root cause, verified:
- `_install_navconfig_stub()` (`conftest.py:89`) and `_install_navigator_stubs()`
  (`conftest.py:173`) are invoked **unconditionally** at module scope
  (`conftest.py:719-720`).
- They `sys.modules.setdefault(...)` ~40 names, including first-party ones:
  `parrot.interfaces.file{,.abstract,.s3,.gcs,.local,.tmp}`,
  `parrot.tools.filemanager` (stub carries only `FileManagerFactory`, so the real
  `FileManagerTool` disappears), `parrot.conf`, `parrot.plugins`, plus
  `navconfig*`, `navigator*`, `navigator_auth*`, `asyncdb*`, `querysource*`.
- Shadowing `aiohttp`-dependent navigator modules is what makes unrelated files
  report `module 'aiohttp.web' has no attribute 'Application'` and
  `cannot import name 'FormData' from 'aiohttp' (unknown location)` — `aiohttp`
  3.14.3 is installed and healthy (`aiohttp.web.Application` resolves fine).

FEAT-268/TASK-1689 already fixed exactly this class of bug once, for
`_install_parrot_stubs()`, by converting it into the opt-in `fake_parrot_bots`
fixture using `monkeypatch.setitem` (`conftest.py:464-465`, note at
`conftest.py:722-727`). The two remaining installers were never converted.
**This feature finishes that job.**

The issue also reports a second symptom: a **hang** ~40% through
`packages/ai-parrot-integrations/tests` with no log growth for 3+ minutes. That
suite collects cleanly today (2354 tests, 0 errors); a full bounded run is being
reproduced as part of this feature's evidence (see M3).

### Goals

- G1 — `pytest --collect-only packages/ai-parrot/tests/` reports **0 errors**.
- G2 — No test stub may shadow a module that is genuinely importable; stubs stay
  only as a fallback for genuinely-absent optional dependencies.
- G3 — Retire or repair the 4 genuinely stale test files.
- G4 — A hung test in a broad sweep fails loudly within a bounded time instead of
  stalling a merge gate indefinitely.
- G5 — A regression guard so the stub-poisoning class of bug cannot silently return.

### Non-Goals (explicitly out of scope)

- Changing the sdd-coder merge-tier **selector** or its scoring. The gate is
  unblocked by making the tests collect, not by reshaping validation.
- Fixing the ~247 collection errors across *all* of `packages/` — this feature is
  scoped to `packages/ai-parrot/tests/` (the tree the issue names) plus the
  integrations hang.
- Making the stubbed third-party packages (`navigator`, `asyncdb`, `querysource`)
  real install-time dependencies.
- Rewriting the 4 stale tests into new feature coverage beyond restoring what they
  were originally asserting.

---

## 2. Architectural Design

### Overview

One behavioural change carries the whole of Bucket A: **a stub must never replace a
module that can actually be imported.**

Today:

```python
sys.modules.setdefault("parrot.tools.filemanager", _stub)   # wins if not yet imported
```

`setdefault` tests "is it already in `sys.modules`?", which is a question about
import *order*, not about availability. The correct question is "is the real module
*resolvable*?" — `importlib.util.find_spec()`.

After:

```python
_stub_if_absent("parrot.tools.filemanager", _stub)          # real module always wins
```

`_stub_if_absent()` installs the stub **only** when the real module cannot be
resolved, preserving the installers' legitimate purpose (keeping tests importable
when an optional third-party dep is missing) while removing their ability to
shadow healthy modules.

### Component Diagram

```
packages/ai-parrot/tests/conftest.py
  ├── _stub_if_absent(name, module)      ← NEW single choke point
  │        │
  │        ├── already in sys.modules ───────────→ no-op
  │        ├── find_spec(name) resolves ─────────→ no-op  (real module wins)
  │        └── ModuleNotFoundError / None ───────→ sys.modules[name] = stub
  │
  ├── _install_navconfig_stub()    (conftest.py:89)   ─┐
  └── _install_navigator_stubs()   (conftest.py:173)  ─┴→ all setdefault sites routed through it
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `tests/conftest.py::_install_navconfig_stub` | modifies | every `sys.modules.setdefault` → `_stub_if_absent` |
| `tests/conftest.py::_install_navigator_stubs` | modifies | same; ~40 call sites |
| `tests/conftest.py::fake_parrot_bots` | pattern source | FEAT-268 precedent, left untouched |
| sdd-coder merge-tier validation | unblocks | consumes a now-collectable tree; no code change |

### New Public Interfaces

```python
# packages/ai-parrot/tests/conftest.py  (new helper, test-scope only)
def _stub_if_absent(name: str, module: types.ModuleType) -> bool:
    """Register ``module`` under ``name`` only if the real module is unavailable.

    Returns True when the stub was installed, False when the real module won.
    Never replaces an entry already present in ``sys.modules``, and never
    shadows a module that ``importlib.util.find_spec`` can resolve.
    """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `_stub_if_absent` choke point | yes | Helper signature fixed above; mechanical replacement of every `sys.modules.setdefault(` in the two installers | — |
| M2: stale-test repair | yes | Per-file disposition decided below (fix path / retarget API / skip-guard / delete) | — |
| M3: hang containment | no | Depends on the reproduction's outcome; the offending test is not yet identified | Which test hangs, and whether it is an ungated live call, is unresolved |
| M4: regression guard | yes | Assertion shape fixed below | — |

### Module 1: Stub choke point (`_stub_if_absent`)
- **Path**: `packages/ai-parrot/tests/conftest.py`
- **Responsibility**: Make every stub installation conditional on the real module
  being genuinely unresolvable. Resolves **14 of 18** collection errors.
- **Depends on**: nothing (stdlib `importlib.util`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/conftest.py  (modifies conftest.py:89, :173)
  import importlib.util

  def _stub_if_absent(name: str, module: types.ModuleType) -> bool:
      """Install ``module`` as ``name`` only when the real module is unavailable.

      Returns True if the stub was installed. A name already in sys.modules, or
      one whose spec resolves, is left alone. find_spec() raising
      ModuleNotFoundError (missing parent package) counts as absent.
      """
  ```
- **Notes**: `find_spec()` on a dotted name imports the *parent* package. Parents
  here (`parrot`, `navigator`, `asyncdb`) are already imported by the time the
  installers run, and `parrot` imports cleanly. Wrap in
  `try/except (ImportError, AttributeError, ValueError)` and treat any failure as
  "absent" so the stub still lands — this keeps the fallback behaviour identical
  for genuinely-missing optional dependencies.

### Module 2: Stale-test repair (4 files)
- **Path**: see table
- **Responsibility**: Resolve the 4 Bucket-B errors that survive M1.
- **Depends on**: M1 (verify against a clean collection)

| File | Error | Disposition |
|---|---|---|
| `tests/test_exceptions.py` | `FileNotFoundError: packages/ai-parrot/parrot/exceptions.py` | **Fix path.** Line 17 `Path(__file__).parent.parent / "parrot" / "exceptions.py"` predates the uv-workspace `src/` layout. Real file: `packages/ai-parrot/src/parrot/exceptions.py`. |
| `tests/unit/test_save_learned_skill_tool.py` | `cannot import name 'SaveLearnedSkillTool'` | **Retarget.** The class is genuinely gone from both `parrot.memory.skills.tools` and `parrot.skills.tools`. FEAT-207 folded it into `SkillFileToolkit.save_learned_skill` (`parrot/skills/tools.py:543`). Rewrite the tests against that method; keep the same assertions. |
| `tests/agents/test_expense_approval.py` | `FileNotFoundError: agents/expense_approval.py` | **Skip-guard.** `/agents/` is gitignored (`.gitignore:293`) and the file was deleted (`1fac04add "removed test unused agents"`), so this can never pass in CI or a fresh worktree. Add a module-level `pytest.skip(..., allow_module_level=True)` when `_AGENT_PATH` is absent. |
| `tests/test_cryptoquant_integration.py` | `No module named 'parrot.tools.cryptoquant'` | **Delete.** `find packages -name '*cryptoquant*'` returns nothing — the toolkit it covers no longer exists anywhere in the workspace. A test for deleted code is not coverage. |

### Module 3: Merge-gate hang containment
- **Path**: `packages/ai-parrot/pyproject.toml` (dev extra), `pytest.ini`/`pyproject` pytest config
- **Responsibility**: Bound the second half of the issue — a hung test must fail
  loudly rather than stall a gate. `pytest-timeout` is **not currently installed**.
  Add it as a dev dependency and set a per-test timeout for broad sweeps so the
  hanging test is *named* in the report instead of freezing the run.
- **Depends on**: the reproduction run identifying the offending test (evidence
  attached to the task).
- **Notes**: the timeout default must not be so tight that legitimately slow
  integration tests flake. Scope the default to the sweep invocation, not to every
  developer's `pytest`.

### Module 4: Regression guard
- **Path**: `packages/ai-parrot/tests/test_conftest_stub_isolation.py` (new)
- **Responsibility**: Prevent silent return of the poisoning class of bug.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/test_conftest_stub_isolation.py  (new)
  def test_stubs_never_shadow_real_modules() -> None:
      """Every first-party name the conftest may stub still resolves to a real file.

      Asserts sys.modules[name].__file__ exists (a types.ModuleType stub has
      none) for each module the installers register when it is genuinely
      importable — the '(unknown location)' tell from issue:c3c59277ef77.
      """

  def test_stub_if_absent_does_not_replace_resolvable_module() -> None:
      """_stub_if_absent returns False and leaves sys.modules untouched for a real module."""
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_stub_if_absent_does_not_replace_resolvable_module` | M1 | Returns `False`, `sys.modules` entry unchanged, for an importable name |
| `test_stub_if_absent_installs_for_missing_module` | M1 | Returns `True` and installs the stub for a genuinely absent name |
| `test_stub_if_absent_respects_existing_sys_modules_entry` | M1 | Never overwrites an entry already present |
| `test_stubs_never_shadow_real_modules` | M4 | Each stubbable first-party name has a real `__file__` after conftest import |
| `test_exceptions_loads_from_src_layout` | M2 | `test_exceptions.py` resolves the real `src/parrot/exceptions.py` |
| `test_save_learned_skill_*` (rewritten) | M2 | Same assertions, driven through `SkillFileToolkit.save_learned_skill` |

### Integration Tests

| Test | Description |
|---|---|
| Full-tree collection | `pytest --collect-only -q packages/ai-parrot/tests/` → **0 errors** (was 18) |
| No coverage regression | Collected test count ≥ 22873 (the current count that collects *despite* the errors) plus the tests unlocked by M1/M2 |
| Bounded integrations run | `packages/ai-parrot-integrations/tests/` completes, or names the hanging test, within its timeout |

### Test Data / Fixtures
```python
# No new fixtures. M4's guard introspects sys.modules directly; the existing
# fake_parrot_bots fixture (FEAT-268) is the untouched precedent for opt-in stubs.
```

---

## 5. Acceptance Criteria

- [ ] **AC1** — `pytest --collect-only -q packages/ai-parrot/tests/` exits 0 with **0 collection errors** (baseline: 18 on `72e238df2`).
- [ ] **AC2** — Every `sys.modules.setdefault(` in `_install_navconfig_stub()` and `_install_navigator_stubs()` is replaced by `_stub_if_absent(`; `grep -c 'sys\.modules\.setdefault(' packages/ai-parrot/tests/conftest.py` returns **0**.
- [ ] **AC3** — The 6 symbols named in the issue (`aiohttp.FormData`, `aiohttp.web.Application`, `parrot._imports.load_satellite_attr`, `parrot.registry.agent_registry`, `parrot.tools.filemanager.FileManagerTool`, `parrot.handlers.crew.execution_history_handler`) all resolve to a real `__file__` *during a full-tree pytest collection*, not merely standalone.
- [ ] **AC4** — The 4 Bucket-B files are repaired per the §3 M2 table; no file is deleted except `test_cryptoquant_integration.py`, and that deletion is justified by `find packages -name '*cryptoquant*'` returning empty.
- [ ] **AC5** — Collected test count does not regress: `≥ 22873` tests collected after the fix.
- [ ] **AC6** — The M4 regression guard fails if `_stub_if_absent` is reverted to `sys.modules.setdefault` (demonstrate by temporary revert in the task's Completion Note).
- [ ] **AC7** — `packages/ai-parrot-integrations/tests/` either completes within its bounded budget, or the hanging test is identified by name and gated/timed out; evidence recorded.
- [ ] **AC8** — `ruff check` clean on every touched file.
- [ ] **AC9** — No product (`src/`) code is modified by M1/M2/M4 — this is a test-infrastructure fix. Any `src/` change requires an explicit note.

---

## 6. Codebase Contract

> Verified against `dev` @ `72e238df2` (2026-10-01).

### Verified Imports
```python
import importlib.util                      # stdlib
import sys, types                          # already imported: conftest.py:1-16
from parrot.skills.tools import SkillFileToolkit   # verified: packages/ai-parrot/src/parrot/skills/tools.py:376
```

### Existing Class Signatures
```python
# packages/ai-parrot/tests/conftest.py
def _install_navconfig_stub() -> None: ...      # line 89
def _install_navigator_stubs() -> None: ...     # line 173
@pytest.fixture
def fake_parrot_bots(monkeypatch): ...          # line 464-465  (FEAT-268 precedent)
_install_navconfig_stub()                       # line 719  (unconditional call)
_install_navigator_stubs()                      # line 720  (unconditional call)

# packages/ai-parrot/src/parrot/skills/tools.py
class SkillFileToolkit(AbstractToolkit):
    async def save_learned_skill(self, ...):    # line 543
    # exclude_tools = ("save_learned_skill",) when learned_dir is unset  # line 411
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_stub_if_absent` | `_install_navconfig_stub` | replaces `sys.modules.setdefault` | `conftest.py:168-170` |
| `_stub_if_absent` | `_install_navigator_stubs` | replaces `sys.modules.setdefault` | `conftest.py:219-461` |
| M4 guard | `sys.modules` after conftest import | attribute check on `__file__` | `conftest.py:719-720` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.tools.cryptoquant`~~ — no match anywhere under `packages/` (verified by `find`)
- ~~`parrot.memory.skills.tools.SaveLearnedSkillTool`~~ — module exists, class does not
- ~~`parrot.skills.tools.SaveLearnedSkillTool`~~ — folded into `SkillFileToolkit.save_learned_skill` (FEAT-207)
- ~~`agents/expense_approval.py`~~ — deleted in `1fac04add`; `/agents/` is gitignored (`.gitignore:293`)
- ~~`packages/ai-parrot/parrot/exceptions.py`~~ — pre-workspace path; real file is `packages/ai-parrot/src/parrot/exceptions.py`
- ~~`pytest_timeout`~~ — **not installed** in the current venv; M3 must add it
- ~~`_install_parrot_stubs()`~~ — already removed by FEAT-268; do not resurrect it

### Edit Sites (Blueprint Anchors)

> Verified against: `72e238df2`. `/sdd-task` MUST re-run each `grep -c`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/tests/conftest.py` | MODIFY | `def _install_navconfig_stub() -> None:` | `conftest.py:89` | 1 |
| `packages/ai-parrot/tests/conftest.py` | MODIFY | `def _install_navigator_stubs() -> None:` | `conftest.py:173` | 1 |
| `packages/ai-parrot/tests/conftest.py` | MODIFY | `_install_navconfig_stub()` | `conftest.py:719` | 2 (def at :89 + call at :719 — anchor on the bare call at col 0) |
| `packages/ai-parrot/tests/test_exceptions.py` | MODIFY | `_PY_PATH = Path(__file__).parent.parent / "parrot" / "exceptions.py"` | `test_exceptions.py:17` | 1 |
| `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` | MODIFY | `from parrot.memory.skills.tools import SaveLearnedSkillTool` | `test_save_learned_skill_tool.py:4` | 1 |
| `packages/ai-parrot/tests/agents/test_expense_approval.py` | MODIFY | `_AGENT_PATH = _REPO_ROOT / "agents" / "expense_approval.py"` | `test_expense_approval.py:36` | 1 |
| `packages/ai-parrot/tests/test_cryptoquant_integration.py` | DELETE | `from parrot.tools.cryptoquant import CryptoQuantToolkit` | `test_cryptoquant_integration.py:4` | 1 |
| `packages/ai-parrot/tests/test_conftest_stub_isolation.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- FEAT-268's `fake_parrot_bots` fixture is the house precedent for scoping stubs;
  M1 is the same lesson applied to availability rather than opt-in.
- Tests only. No `src/` changes (AC9).
- `ruff check --fix` on touched files; `black` line-length 120.

### Known Risks / Gotchas
- **R1 — `find_spec()` side effects.** Resolving `a.b.c` imports `a.b`. If a parent
  is itself stubbed earlier in the same installer, `find_spec` may see the stub and
  report the child as absent. *Mitigation*: route parents through `_stub_if_absent`
  too, and order each installer parent-first (it already is). Verify with AC3,
  which checks resolution during a **full-tree** collection, not standalone.
- **R2 — Unmasking.** Letting real modules win may surface *new* failures in tests
  that silently relied on a stub's narrow surface. This is the fix working, not a
  regression — but AC5's count floor is what catches an accidental net loss. Expect
  to repair a handful of newly-honest tests; budget for it.
- **R3 — `parrot.tools.filemanager` stub carries only `FileManagerFactory`.** Tests
  importing `FileManagerFactory` may depend on the *stub's* behaviour. Check each
  consumer when the real module starts winning.
- **R4 — Count floor is a floor, not equality.** M1 unlocks previously-uncollectable
  files, so the total will rise; AC5 only forbids a decrease.
- **R5 — The issue's own advice is now obsolete.** It suggested treating merge-tier
  validation as advisory. Once AC1 holds, that workaround should *not* be codified.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pytest-timeout` | `>=2.3` | M3 — bound a hung test so a merge gate fails loudly instead of stalling |

---

## 8. Open Questions

- [ ] **Q1** — Which test hangs in `packages/ai-parrot-integrations/tests`? Reproduction
  in flight at spec time (past 72% with no stall, vs the reported 40%); the hang may
  be environment- or network-dependent rather than deterministic. If it does not
  reproduce, M3 ships the `pytest-timeout` guard anyway and AC7 is satisfied by the
  completed bounded run. — *Owner: implementer*
- [ ] **Q2** — Should the `pytest-timeout` default live in shared pytest config (every
  developer run) or only in the sweep invocation? Spec leans **sweep-only** to avoid
  flaking slow local integration tests. — *Owner: Jesus*
- [ ] **Q3** — The `navigator`/`asyncdb`/`querysource` stubs exist because those packages
  are not guaranteed installed. If they are in fact always present in CI, the stubs
  could be deleted outright rather than made conditional. Out of scope here; M1 is
  safe either way. — *Owner: Jesus*
