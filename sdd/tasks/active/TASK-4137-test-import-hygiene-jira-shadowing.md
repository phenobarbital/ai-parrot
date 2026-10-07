# TASK-4137: Stop test_drive_toolkit.py polluting sys.path / sys.modules (PyPI `jira` shadowing)

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:265b7797ae9b`

---

## Context

Promoted from ledger `issue:265b7797ae9b` (severity `major`, discovered from
`spec:FEAT-637`) by `/sdd-fix`. This is a **test-infrastructure blocker for this
very feature**: every jiratoolkit test module FEAT-637 adds or touches fails to
*collect* on a whole-directory run, so FEAT-637's own merge-tier gate can never
go green until it is fixed.

Two independent import-time side effects in the test tree leak across module
boundaries:

1. `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py:12-13` does a
   module-scope `sys.path.insert(0, <packages/ai-parrot/tests/interfaces>)` to
   reach `_gdrive_fakes`. That directory contains a `jira/` **package** (it has
   an `__init__.py`), so from that moment on `import jira` resolves to the test
   package instead of the PyPI distribution, and every later-collected module
   that reaches `from jira import JIRA` dies with
   `ImportError: cannot import name 'JIRA' from 'jira'`.
2. The root `conftest.py` registers a plain `types.ModuleType` under
   `sys.modules["parrot.interfaces.file"]` (a pre-FEAT-124 navigator shim).
   A `ModuleType` is not a *package*, so any later
   `from parrot.interfaces.file.<sub> import …` fails with
   `'parrot.interfaces.file' is not a package`. Today only
   `test_drive_toolkit.py` pops that stub — which makes correctness depend on
   collection order (it is collected *after* `test_calendar.py`).

Reproduced on clean `origin/dev`:

```
$ pytest packages/ai-parrot-tools/tests --collect-only -p no:randomly -q
ERROR packages/ai-parrot-tools/tests/test_jira_config.py
ERROR packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py
ERROR packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py
ERROR packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py
ERROR packages/ai-parrot-tools/tests/unit/test_jiratoolkit_verify_credentials.py
```

Each of those five files passes when run alone.

---

## Scope

- Load `_gdrive_fakes` in `test_drive_toolkit.py` by **absolute file path**
  (`importlib.util.spec_from_file_location` under a private `sys.modules` key),
  removing the `sys.path` mutation entirely.
- Remove the now-dead `sys.modules.pop("parrot.interfaces.file", None)` line
  from `test_drive_toolkit.py`.
- Guard the root `conftest.py` `parrot.interfaces.file*` stub group so it is
  installed **only when the real `parrot.interfaces.file` package cannot be
  imported**. Leave the `navigator.utils.file` back-fill above it untouched —
  that back-fill is what makes the real package importable.
- Add a regression test asserting the invariant: collecting
  `test_drive_toolkit.py` together with a jiratoolkit test module in one pytest
  process succeeds.

**NOT in scope**:
- The other five pre-existing collection errors in that directory
  (`shell_tool/test_command_rules.py`, `shell_tool/test_command_sanitizer.py`,
  `shell_tool/test_security_policy.py`, `test_alpaca.py`,
  `test_zoom_interface.py`) — unrelated causes, not this issue.
- The three pre-existing `tests/google/test_places.py` runtime failures.
- The `parrot.tools.filemanager` stub further down in `conftest.py`.
- Any other `sys.path.insert` site in the test tree — they point at different
  directories and shadow nothing.
- Everything the FEAT-637 template feature itself implements (TASK-4113..4117).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` | MODIFY | Load `_gdrive_fakes` by path; drop the `sys.path` insert and the `sys.modules.pop` |
| `conftest.py` | MODIFY | Install the `parrot.interfaces.file*` stubs only when the real package is unimportable |
| `packages/ai-parrot-tools/tests/google/test_import_hygiene.py` | CREATE | Regression test for the cross-module collection invariant |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib.util                     # verified: conftest.py:25 (already imported there)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager   # verified: packages/ai-parrot/src/parrot/interfaces/file/gdrive.py
from parrot_tools.google.drive import GoogleDriveToolkit           # verified: packages/ai-parrot-tools/src/parrot_tools/google/drive.py
from _gdrive_fakes import FakeDrive, FakeDriveClient, make_google_client  # verified: packages/ai-parrot/tests/interfaces/_gdrive_fakes.py
```

### Existing Signatures to Use
```python
# conftest.py:33-60 — the established "load by absolute path, not by name" idiom
#   in THIS repository. Reuse its shape; do not invent a new one.
def _load_fspath_guard(repo_root: str):
    name = "parrot_mock_fspath_guard"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = os.path.join(repo_root, "tests", "mock_fspath_guard.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the MagicMock/ guard from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

# packages/ai-parrot-tools/tests/google/test_drive_toolkit.py:1-14 (current head)
"""FEAT-608 TASK-3816 — GoogleDriveToolkit."""
import sys
from pathlib import Path
import pytest
sys.modules.pop("parrot.interfaces.file", None)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager  # noqa: E402
from parrot_tools.google.drive import GoogleDriveToolkit  # noqa: E402
FAKES_DIR = Path(__file__).parents[3] / "ai-parrot" / "tests" / "interfaces"
sys.path.insert(0, str(FAKES_DIR))
from _gdrive_fakes import FakeDrive, FakeDriveClient, make_google_client  # noqa: E402

# packages/ai-parrot/tests/interfaces/_gdrive_fakes.py:1-20
#   Module-level names the test file consumes; the module has NO relative
#   imports, so loading it by file path is safe.
class FakeDrive: ...
class FakeDriveClient: ...
def make_google_client(client) -> GoogleClient: ...
```

### Does NOT Exist
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~ — `_gdrive_fakes.py:3`
  says so explicitly: "Import directly from test modules; there is
  intentionally no conftest.py". Do not create one.
- ~~`_gdrive_fakes` as an installed/importable distribution~~ — it is only a
  file on disk; it is never on `sys.path` after this change.
- ~~a `parrot.interfaces.file` stub that is a package~~ — the conftest stub is a
  bare `types.ModuleType` with no `__path__`. Do not try to fix it by giving it
  a `__path__`; skip it instead.
- ~~`jira` as a first-party `parrot` module~~ — `from jira import JIRA` must
  resolve to the PyPI `jira` distribution in site-packages.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/tests/google/test_drive_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "conftest.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/google/test_import_hygiene.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:conftest.py#_load_fspath_guard",
    "sym:packages/ai-parrot/tests/interfaces/_gdrive_fakes.py#FakeDrive",
    "sym:packages/ai-parrot/tests/interfaces/_gdrive_fakes.py#FakeDriveClient",
    "sym:packages/ai-parrot/tests/interfaces/_gdrive_fakes.py#make_google_client"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No `sys.path` mutation may survive module import.** That is the whole bug.
  Appending instead of inserting is NOT an acceptable fix: the directory would
  still be searched and would still shadow `jira` whenever site-packages is
  later on the path.
- The private `sys.modules` key must be a fixed string (`_gdrive_fakes_tools`),
  so repeated imports share one module instance — same reasoning as
  `_load_fspath_guard`'s `parrot_mock_fspath_guard` key.
- The conftest guard must not change behaviour in an environment where the real
  package genuinely cannot import (old navigator): the stubs must still install
  there.
- `conftest.py` is loaded by every test in the repo — this task is
  **exclusive** (`parallel: false`).

### References in Codebase
- `conftest.py:33-60` — `_load_fspath_guard`, the pattern to copy.
- `conftest.py:160-240` — the navigator back-fill and the stub group to guard.
- `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` — imports
  `_gdrive_fakes` as a plain sibling (same directory), needs no change.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite the head of `test_drive_toolkit.py` to load `_gdrive_fakes` through
   `importlib.util.spec_from_file_location` — *why*: it binds the module by
   absolute path, so nothing is ever added to `sys.path` and the `jira/` test
   package beside it can never shadow the PyPI `jira`.
2. Delete `sys.modules.pop("parrot.interfaces.file", None)` from that file —
   *why*: once step 3 lands there is no bogus stub to pop, and leaving the pop
   makes other modules' correctness depend on this one being collected first.
3. Guard the `conftest.py` `parrot.interfaces.file*` stub group with a real
   import probe — *why*: a `ModuleType` registered under a package name makes
   every `parrot.interfaces.file.<sub>` import fail, order-dependently.
4. Add `test_import_hygiene.py` — *why*: both defects are invisible to
   single-file runs, so only a cross-module assertion can keep them fixed.
5. Re-run the directory collection and confirm the five jiratoolkit errors are
   gone and the five out-of-scope errors are unchanged.

### `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'sys.modules.pop("parrot.interfaces.file", None)' packages/ai-parrot-tools/tests/google/test_drive_toolkit.py)
# occurrences: 1 (verified: grep -c 'sys.path.insert(0, str(FAKES_DIR))' packages/ai-parrot-tools/tests/google/test_drive_toolkit.py)
# REPLACE — the whole header, lines 1-14, becomes:
"""FEAT-608 TASK-3816 — GoogleDriveToolkit."""

import importlib.util
import sys
from pathlib import Path

import pytest

from parrot.interfaces.file.gdrive import GoogleDriveFileManager
from parrot_tools.google.drive import GoogleDriveToolkit

# `_gdrive_fakes` lives in another distribution's test tree. Load it by
# absolute path instead of putting its directory on sys.path: that directory
# also holds a `jira/` test package, and a sys.path entry would shadow the
# PyPI `jira` distribution for every module collected afterwards
# (issue:265b7797ae9b).
_FAKES_PATH = (
    Path(__file__).parents[3] / "ai-parrot" / "tests" / "interfaces" / "_gdrive_fakes.py"
)


def _load_gdrive_fakes():
    """Load ``_gdrive_fakes`` by file path under a private module name."""
    name = "_gdrive_fakes_tools"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, _FAKES_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the Drive fakes from {_FAKES_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_fakes = _load_gdrive_fakes()
FakeDrive = _fakes.FakeDrive
FakeDriveClient = _fakes.FakeDriveClient
make_google_client = _fakes.make_google_client
```
**Why this shape**: it is `_load_fspath_guard`'s idiom (`conftest.py:33-60`)
applied to the Drive fakes — fixed private `sys.modules` key so the module is
instantiated once, cached lookup first, defensive `spec`/`loader` check. The
three re-exported names must keep their exact spelling: the rest of the file
already calls `FakeDrive()`, `FakeDriveClient(...)` and `make_google_client(...)`
unqualified. Do NOT keep `FAKES_DIR` and do NOT re-add any `sys.path` write.

### `conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    # parrot.interfaces.file shim' conftest.py)
# BEFORE — insert above `    # parrot.interfaces.file shim` (verified: conftest.py:199)
    # issue:265b7797ae9b — only shim parrot.interfaces.file when the REAL
    # package cannot be imported.  The shim is a plain ModuleType, i.e. not a
    # package, so once it is registered every later
    # `from parrot.interfaces.file.<sub> import ...` fails with
    # "'parrot.interfaces.file' is not a package" — and whether it fails
    # depends on pytest's collection order.  The navigator.utils.file
    # back-fill above is what makes the real import succeed, so probe AFTER it.
    try:
        import parrot.interfaces.file as _real_parrot_interfaces_file  # noqa: F401
        _parrot_interfaces_file_is_real = True
    except Exception:  # noqa: BLE001
        _parrot_interfaces_file_is_real = False

# occurrences: 1 (verified: grep -c 'sys.modules.setdefault("parrot.interfaces.file.gcs", _parrot_interfaces_file_gcs)' conftest.py)
# THEN — indent the existing stub group (conftest.py:199-232, from
# `    # parrot.interfaces.file shim` down to and including
# `    sys.modules.setdefault("parrot.interfaces.file.gcs", _parrot_interfaces_file_gcs)`)
# one level, under:
    if not _parrot_interfaces_file_is_real:
        ...  # FILL IN: the existing 34 lines, re-indented verbatim — change
             # nothing but the indentation; bounded by AC-4 (old-navigator
             # environments must still get the stubs)
```
**Why**: the back-fill that precedes this block is what repairs
`navigator.utils.file`, so by the time the probe runs the real package imports
cleanly in any environment where it can at all. The `parrot.tools.filemanager`
stub below the group stays **outside** the new `if` — it is a different module
and out of scope.

### `packages/ai-parrot-tools/tests/google/test_import_hygiene.py` (CREATE)
```python
"""Regression tests for cross-module import hygiene (issue:265b7797ae9b).

Both defects guarded here are invisible to single-file runs: they only
appear when one module's import-time side effects leak into the next
module's imports.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DRIVE_TEST = Path(__file__).with_name("test_drive_toolkit.py")
_JIRA_TEST = _REPO_ROOT / "packages" / "ai-parrot-tools" / "tests" / "test_jira_config.py"


def test_drive_toolkit_does_not_shadow_pypi_jira():
    """Collecting the Drive toolkit tests must not break `from jira import JIRA`."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "--collect-only", "-q",
            "-p", "no:randomly", str(_DRIVE_TEST), str(_JIRA_TEST),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # FILL IN: assert the collection succeeded and name the symptom in the
    # failure message — bounded by AC-1 (returncode 0, and
    # "cannot import name 'JIRA'" absent from stdout+stderr)


def test_drive_toolkit_leaves_sys_path_clean():
    """Importing the Drive toolkit tests adds no directory to sys.path."""
    fakes_dir = _REPO_ROOT / "packages" / "ai-parrot" / "tests" / "interfaces"
    # FILL IN: assert str(fakes_dir) not in sys.path — bounded by AC-2.
    # This module is collected after test_drive_toolkit.py within the same
    # directory, so its import side effects have already run.


def test_parrot_interfaces_file_is_the_real_package():
    """The root conftest must not shadow parrot.interfaces.file with a stub."""
    import parrot.interfaces.file as pif
    # FILL IN: assert the module is a package (has __path__) and that
    # `from parrot.interfaces.file.gdrive import GoogleDriveFileManager`
    # succeeds — bounded by AC-3.
```
**Why this shape**: the first test is the only order-independent proof of the
real regression, so it runs pytest in a child process rather than asserting on
the parent's mutated state. The second and third are cheap in-process guards on
the two side effects individually. Keep the subprocess `timeout=` — an
unbounded child process would hang the suite.

### FILL IN checklist
- [ ] `conftest.py` — re-indent the existing 34-line stub group under
      `if not _parrot_interfaces_file_is_real:`, verbatim apart from indentation;
      bounded by AC-4.
- [ ] `test_import_hygiene.py::test_drive_toolkit_does_not_shadow_pypi_jira` —
      the assertions on `result`; bounded by AC-1.
- [ ] `test_import_hygiene.py::test_drive_toolkit_leaves_sys_path_clean` —
      the `sys.path` assertion; bounded by AC-2.
- [ ] `test_import_hygiene.py::test_parrot_interfaces_file_is_the_real_package` —
      the package/submodule assertions; bounded by AC-3.

---

## Acceptance Criteria

- [ ] **AC-1** — `pytest packages/ai-parrot-tools/tests --collect-only -p no:randomly -q`
      reports **no** `cannot import name 'JIRA' from 'jira'` error. The five
      jiratoolkit collection errors (`test_jira_config.py`,
      `test_jiratoolkit_envelope.py`, `unit/test_jiratoolkit_delegation.py`,
      `unit/test_jiratoolkit_oauth.py`, `unit/test_jiratoolkit_verify_credentials.py`)
      are gone.
- [ ] **AC-2** — `test_drive_toolkit.py` contains no `sys.path` write and no
      `sys.modules.pop`; `grep -c 'sys.path' packages/ai-parrot-tools/tests/google/test_drive_toolkit.py`
      returns 0.
- [ ] **AC-3** — `parrot.interfaces.file` resolves to the real package
      (`__file__` under `packages/ai-parrot/src/`) during a pytest run.
- [ ] **AC-4** — the five out-of-scope collection errors (`shell_tool` ×3,
      `test_alpaca.py`, `test_zoom_interface.py`) are **unchanged** — this task
      neither fixes nor worsens them.
- [ ] **AC-5** — `pytest packages/ai-parrot-tools/tests/google/test_drive_toolkit.py -q`
      still passes with the same test count as before the change.
- [ ] **AC-6** — `ruff check` clean on all three files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/google/test_import_hygiene.py -q`
- `pytest packages/ai-parrot-tools/tests/google/test_drive_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/test_jira_config.py packages/ai-parrot-tools/tests/google/test_drive_toolkit.py -q -p no:randomly`

---

## Test Specification

See the `test_import_hygiene.py` block in the Implementation Blueprint — it is
the test scaffold for this task. The third validation command above is the
minimal two-file reproduction of the original bug: it fails on `origin/dev`
before this task and passes after it.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-template-support --feature-id FEAT-637`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/jiratoolkit-template-support.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks and complete
   every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
8. **Commit the code** — stage only the three files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4137 jiratoolkit-template-support verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state
11. **Do NOT close `issue:265b7797ae9b`** — `/sdd-fix` closes it by evidence.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
