# TASK-5692: Load techwiki packages without inspection and report native modules

**Feature**: FEAT-900 — Techwiki static-only Griffe loading — FEAT-801 review follow-up
**Spec**: `sdd/specs/fixgroup-d908bfcc4d62.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:5af0e518b2e8`

---

## Context

Spec §2 / §3 Modules 1 and 2 (`issue:5af0e518b2e8`, opened from `spec:FEAT-801`).

`load_packages` calls `griffe.load(module_root, search_paths=[source_root])`. griffe 2.4.1 defaults
`allow_inspection` to `True`, so a compiled extension under a configured root (for example
`parrot/utils/types.cpython-312-x86_64-linux-gnu.so`) is loaded by runtime inspection — griffe imports
it. FEAT-801 requires static analysis only ("no imports") and a skip policy for native code: "the module
is skipped and listed in the report; not an error". Neither holds today: the module is imported when a
built `.so` exists, and is never listed in `skipped_modules`.

---

## Scope

- Pass `allow_inspection=False` to the single `griffe.load` call.
- Add `_native_modules(cfg, root)` and extend `skipped` with its entries in `_generate`.
- Add `strict_failures(skipped)` and use it for the `--strict` exit code in both CLIs
  (`techwiki api`, `techwiki bundle`); update the two `--strict` help strings and the bundle `main` docstring.
- Tests: the six tests of spec §4.

**NOT in scope**: pages for native modules or new `.pyi` stubs; `_root_exists` and missing configured
roots (`issue:b9829d5f3a2b`); sourceless `.pyc` modules; templates, golden files,
`.github/workflows/techwiki.yml`, `bundle.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `allow_inspection=False`, `_native_modules`, `strict_failures`, constants |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py` | MODIFY | strict exit through `strict_failures`; help string |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py` | MODIFY | strict exit through `strict_failures`; help string; docstring |
| `packages/ai-parrot/tests/sdd/test_techwiki_api.py` | MODIFY | five new tests |
| `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` | MODIFY | one new test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `02cab9b604`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/techwiki/api.py — present today
import ast, importlib.resources, logging, re                     # lines 5-8
from dataclasses import dataclass, replace                        # line 9
from pathlib import Path                                          # line 10
from typing import TYPE_CHECKING, Any                             # line 11
from parrot.sdd.techwiki.config import TechwikiConfig             # line 13
# add (stdlib):
from collections.abc import Mapping, Sequence

# packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py — lazy import inside main()
from parrot.sdd.techwiki.api import GriffeUnavailable, generate   # line 29
# packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py — lazy import inside main()
from parrot.sdd.techwiki.api import GriffeUnavailable             # line 39

# packages/ai-parrot/tests/sdd/test_techwiki_api.py
from parrot.sdd.scripts.techwiki_api import main                                                       # line 13
from parrot.sdd.techwiki.api import GriffeUnavailable, RenderedPage, _unlink_pageless_refs, generate   # line 14
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage                                 # line 15
# packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
from parrot.sdd.scripts.techwiki_bundle import main               # line 12
from parrot.sdd.techwiki.config import load_techwiki_config       # line 14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/techwiki/api.py
logger = logging.getLogger(__name__)                                                       # line 19
def _import_griffe() -> "griffe":                                                          # line 36
def _root_exists(source_root: Path, module_root: str) -> bool:                             # line 85
def load_packages(cfg: TechwikiConfig, root: Path) -> "list[griffe.Module]":               # line 91
#   `                modules.append(griffe_module.load(module_root, search_paths=[source_root]))`   # line 114
def _syntax_errors(cfg: TechwikiConfig, root: Path) -> list[dict[str, str]]:               # line 118
#   loop: `for package in cfg.packages:` / `source_root = root / package.src` /
#         `for module_root in package.roots:` / `base = source_root.joinpath(*module_root.split("."))`
#   entry: `{"module": ".".join(parts), "reason": reason}`; returns `sorted(skipped, key=lambda item: item["module"])`
def _module_all(module: Any) -> set[str] | None:                                           # line 157
def _generate(cfg, root, release) -> tuple[list[RenderedPage], list[dict[str, str]]]:      # line 647
#   `    skipped.extend(_syntax_errors(cfg, root))`                                        # line 662

# packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py
#   `    parser.add_argument("--strict", action="store_true", help="Exit 4 when any module is skipped")`   # line 26
#   `    return 4 if args.strict and skipped else 0`                                       # line 53
# packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py
#   docstring: `absent, or four with ``--strict`` when a module was skipped.`              # line 27
#   `    parser.add_argument("--strict", action="store_true", help="Exit 4 when any module was skipped")`  # line 36
#   `    return 4 if args.strict and report.skipped_modules else 0`                        # line 75

# packages/ai-parrot/tests/sdd/test_techwiki_api.py
def _require_griffe() -> None:                                                             # line 21 — skip/fail when the extra is absent
def bad_repo(tmp_path: Path) -> Path:                                                      # line 33 — fixture: src/badpkg + sdd/config.json
# packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
def api_repo(techwiki_repo: Path) -> Path:                                                 # line 171 — fixture: git repo, wiki, package `samplepkg` under packages/sample/src

# griffe 2.4.1
griffe.load(objspec, /, *, search_paths=None, allow_inspection: bool = True, force_inspection: bool = False, ...)
```

### Does NOT Exist
- ~~`_native_modules`, `strict_failures`, `NATIVE_SKIP_KIND`, `NATIVE_SKIP_REASON`, `_NATIVE_SUFFIXES`~~ — added by this task.
- ~~a `kind` key on syntax-error or render-failure skipped entries~~ — they keep only `module` and `reason`.
- ~~a second `griffe.load` call (in `bundle.py`, `check.py` or elsewhere)~~ — `api.py:114` is the only one.
- ~~a `TechwikiConfig` option for inspection~~ — the behaviour is not configurable.
- ~~`griffe.load(..., static=True)`~~ — the parameter is `allow_inspection`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/techwiki/api.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_techwiki_api.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#load_packages",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#_syntax_errors",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#_generate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No test may put a fixture source root on `sys.path` or import a fixture module.
- The native scan uses the file system only (no griffe), like `_syntax_errors`.
- One entry per module name, whatever the number of matching files; entries sorted by module name.
- Existing skipped entries are not changed (no `kind` key added to them).
- The golden pages and `test_generate_satellite_coverage` (`assert not skipped`) must stay green unchanged.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import, the three constants and `allow_inspection=False` — *why*: griffe's default lets it
   import compiled modules, which FEAT-801 forbids.
2. Add `_native_modules` and call it from `_generate` — *why*: with inspection off griffe only logs a
   compiled module at debug level, so the report has to come from our own scan.
3. Add `strict_failures` and use it in both CLIs — *why*: a native module is "not an error"; the release
   workflow runs `--strict` and must not exit 4 because two Cython modules are listed.
4. Add the six tests, run the Validation Commands, `ruff check --fix` the five files.

### `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` (MODIFY) — block 1
```python
# occurrences: 1 (verified: grep -cF 'from typing import TYPE_CHECKING, Any' …/api.py)
# BEFORE — insert above `from dataclasses import dataclass, replace` (verified: api.py:9)
from collections.abc import Mapping, Sequence

# occurrences: 1 (verified: grep -cF 'logger = logging.getLogger(__name__)' …/api.py)
# AFTER — insert below `logger = logging.getLogger(__name__)` (verified: api.py:19)
NATIVE_SKIP_KIND = "native"
NATIVE_SKIP_REASON = "native module without Python sources or stubs (static analysis only)"
_NATIVE_SUFFIXES = frozenset({".so", ".pyd", ".pyx"})

# occurrences: 1 (verified: grep -cF 'modules.append(griffe_module.load(module_root, search_paths=[source_root]))' …/api.py)
# REPLACE that line (verified: api.py:114)
                modules.append(griffe_module.load(module_root, search_paths=[source_root], allow_inspection=False))
```
**Why**: also add one sentence to the `load_packages` docstring: inspection is disabled, so a configured
module is never imported; a compiled module without a source or stub is reported by `_native_modules`.

### `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` (MODIFY) — block 2
```python
# occurrences: 1 (verified: grep -cF 'def _module_all(module: Any) -> set[str] | None:' …/api.py)
# BEFORE — insert above `def _module_all(module: Any) -> set[str] | None:` (verified: api.py:157)
def _is_package_dir(path: Path) -> bool:
    """Whether ``path`` is a regular package griffe descends into (it holds an init module or stub)."""
    return (path / "__init__.py").is_file() or (path / "__init__.pyi").is_file()


def _native_modules(cfg: TechwikiConfig, root: Path) -> list[dict[str, str]]:
    """Report public native modules that have neither a Python source nor a stub.

    Inspection is disabled in :func:`load_packages`, so griffe drops a compiled module (it only logs at
    debug level). A Cython source (``.pyx``) and a built extension (``.so`` / ``.pyd``) of the same module
    yield one entry, so the report does not depend on whether the checkout was built.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        One ``{"module", "reason", "kind"}`` entry per native module, sorted by module.
    """
    names: set[str] = set()
    for package in cfg.packages:
        source_root = root / package.src
        for module_root in package.roots:
            base = source_root.joinpath(*module_root.split("."))
            # FILL IN: walk `base` only when `_is_package_dir(base)`; descend only into sub-directories that
            #   are `_is_package_dir` and not `__pycache__`; for each file whose suffix is in `_NATIVE_SUFFIXES`
            #   take `stem = name.split(".", 1)[0]` and drop it when the stem is not an identifier, is
            #   `__init__`, has a sibling `<stem>.py` / `<stem>.pyi` or a sibling package `<stem>/`, or when
            #   the stem or any package name below `source_root` starts with `_`; add the dotted module
            #   name (relative to `source_root`) to `names` — bounded by spec §2 "Native-module report"
    return [{"module": name, "reason": NATIVE_SKIP_REASON, "kind": NATIVE_SKIP_KIND} for name in sorted(names)]


def strict_failures(skipped: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the skipped entries that fail ``--strict``: every entry except native-module ones.

    Args:
        skipped: Skipped-module entries as returned by :func:`generate`.

    Returns:
        The entries whose ``kind`` is not ``"native"``, in input order.
    """
    return [item for item in skipped if item.get("kind") != NATIVE_SKIP_KIND]


# occurrences: 1 (verified: grep -cF '    skipped.extend(_syntax_errors(cfg, root))' …/api.py)
# AFTER — insert below `    skipped.extend(_syntax_errors(cfg, root))` (verified: api.py:662)
    skipped.extend(_native_modules(cfg, root))
```
**Why**: the "private" rule matches `_submodules`, which never gives an underscore-prefixed module a page;
the "sibling" rule matches griffe, which documents the `.py` / `.pyi` file statically.

### `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -cF on the three lines, techwiki_api.py:26, :29, :53)
# REPLACE line 26
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 4 when a module was skipped by a parse or load failure (native modules are listed, not fatal)",
    )
# REPLACE line 29
    from parrot.sdd.techwiki.api import GriffeUnavailable, generate, strict_failures
# REPLACE line 53
    return 4 if args.strict and strict_failures(skipped) else 0
```
**Why**: the report and the stderr lines still list every skipped module; only the exit code changes.

### `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -cF on the four lines, techwiki_bundle.py:27, :36, :39, :75)
# REPLACE line 27 (docstring)
        absent, or four with ``--strict`` when a module was skipped by a parse or load failure (native modules
        are listed in the report but never fail strict mode).
# REPLACE line 36 — same help string as techwiki_api.py
# REPLACE line 39
    from parrot.sdd.techwiki.api import GriffeUnavailable, strict_failures
# REPLACE line 75
    return 4 if args.strict and strict_failures(report.skipped_modules) else 0
```
**Why**: this is the command the release workflow runs with `--strict`.

### `packages/ai-parrot/tests/sdd/test_techwiki_api.py` (MODIFY)
```python
# AFTER — append at the end of the file; extend the line-14 import with
#   NATIVE_SKIP_KIND, NATIVE_SKIP_REASON, load_packages, strict_failures
@pytest.fixture
def native_repo(tmp_path: Path) -> Path:
    """A repository whose package mixes pure, stubbed, native, private and non-package modules."""
    # FILL IN: build src/nativepkg with __init__.py, pure.py, fast.cpython-311-x86_64-linux-gnu.so,
    #   fast.cpython-312-x86_64-linux-gnu.so, speed.pyx, stubbed.so + stubbed.pyi, _hidden.so and
    #   scripts/tool.so (no __init__.py), plus sdd/config.json like `bad_repo` — bounded by spec §4 row 2;
    #   the "compiled" files hold placeholder bytes


def test_load_packages_disables_inspection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``griffe.load`` is always called with inspection disabled (no griffe needed)."""
    # FILL IN: monkeypatch "parrot.sdd.techwiki.api._import_griffe" to return a fake whose `load`
    #   records (args, kwargs); assert kwargs["allow_inspection"] is False and search_paths == [source root]


def test_generate_reports_native_modules(native_repo: Path) -> None:
    """Native modules without source or stub are listed; stubbed ones render; nothing is imported."""
    # FILL IN: spec §4 row 2


def test_native_report_is_build_state_independent(tmp_path: Path) -> None:
    """A ``.pyx`` alone and a ``.pyx`` next to a built extension give the same pages and report."""
    # FILL IN: spec §4 row 3


def test_strict_failures_excludes_native_entries() -> None:
    """Only parse/load failures fail strict mode."""
    # FILL IN: spec §4 row 4


def test_strict_ignores_native_modules(native_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--strict`` exits 0 when every skipped module is native, 4 once a syntax error joins them."""
    # FILL IN: spec §4 row 5
```

### `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` (MODIFY)
```python
# AFTER — append at the end of the file
def test_bundle_strict_ignores_native_modules(api_repo: Path, tmp_path: Path) -> None:
    """A native module is listed in the bundle report but does not turn ``--strict`` into exit 4."""
    # FILL IN: add `speed.pyx` to packages/sample/src/samplepkg, run main with and without --strict,
    #   assert both exit codes are equal and not 4, and that techwiki-report.json lists
    #   "samplepkg.speed" with kind "native" — bounded by spec §4 row 6
```

### FILL IN checklist
- [ ] `_native_modules` walk — bounded by spec §2 "Native-module report"
- [ ] `native_repo` fixture and six test bodies — bounded by spec §4

---

## Acceptance Criteria

- [ ] `griffe.load` receives `allow_inspection=False`; no fixture module appears in `sys.modules` after `generate`.
- [ ] A native module without source or stub is in `skipped_modules` with `"kind": "native"` and
      `NATIVE_SKIP_REASON`; a stubbed one is rendered and not listed; a private one and one outside a
      regular package are not listed; `.pyx` and built extensions of one module give one entry.
- [ ] `--strict` exits 4 for a syntax-error module and does not exit 4 when every skipped module is native,
      in `techwiki api` and `techwiki bundle`.
- [ ] Every pre-existing test in the two test files still passes, golden pages unchanged.
- [ ] `ruff check` is clean on the five files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py -q`

---

## Test Specification

See the test stubs in the blueprint; spec §4 rows 1–6 state what each asserts.

---

## Agent Instructions

1. Work in the feature worktree `feat-FEAT-900-fixgroup-d908bfcc4d62`.
2. Verify the Codebase Contract, mark the task `in-progress`.
3. Implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the five files listed, close with the close script, fill in the Completion Note.

---

## Completion Note

