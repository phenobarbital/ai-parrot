# TASK-3873: Remove legacy pipeline, AbstractDetector and their exports

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12** (early subtask: "standalone legacy.py/export removals can start earlier") and
AC14. The 2,905-line `planogram/legacy.py` (`RetailDetector`, `PlanogramCompliancePipeline`) and the
YOLO/torch-based `parrot_pipelines/detector.py` (`AbstractDetector`) are no longer part of the
three-stage cycle. They are reachable only through two lazy export tables in `ai-parrot-pipelines`
and two one-line core proxies in `ai-parrot`. This task deletes all four modules, removes their names
from the export tables, and adds positive (surviving names) and negative (removed names) import tests.

The planner verified — and this task re-verified — that nothing else imports these modules, so the task
has no dependency. Spec §2 "Compatibility policy": the core proxy package is **kept**; only the removed
names and obsolete proxy modules go (user-confirmed, spec §8). No compatibility stub may resurrect the
removed classes (Module 12 skeleton: "ImportError is accepted for from-import of removed names").

---

## Scope

- Delete `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` (whole module).
- Delete `packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py` (whole module).
- Delete the core proxy modules `packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py` and
  `packages/ai-parrot/src/parrot/pipelines/detector.py`.
- Remove `"PlanogramCompliancePipeline"` and `"RetailDetector"` from `parrot_pipelines.planogram.__all__`
  and from its `__getattr__` branch (removed names fall through to the existing `raise AttributeError(name)`).
- Remove `"AbstractDetector"`, `"PlanogramCompliancePipeline"`, `"RetailDetector"` entries from
  `PIPELINE_REGISTRY` in `parrot_pipelines/__init__.py`.
- Remove `"PlanogramCompliancePipeline"` and `"RetailDetector"` from the core proxy
  `parrot/pipelines/planogram/__init__.py` `__all__` (keep its `__getattr__` forwarding unchanged).
- Add import tests to `packages/ai-parrot/tests/test_monorepo_imports.py`: surviving names resolve through
  both the package and the core proxy; removed names raise `ImportError`/`AttributeError`; no pipelines
  source file imports `pytesseract`, `torch` or `ultralytics` at module level.

**NOT in scope**:
- `types/legacy_adapter.py`, `grid/detector.py`, `grid/horizontal_bands.py`, `grid/strategy.py`,
  `grid/__init__.py`, `grid/merger.py` and `test_legacy_run_orchestration.py` — TASK-3874.
- Removing `pytesseract` from `packages/ai-parrot-pipelines/pyproject.toml`, `uv.lock`, version bump — TASK-3881.
- `packages/ai-parrot-pipelines/README.md` (still lists `RetailDetector` at line 25) and docs/runbook — TASK-3880.
- `test_vision_kwargs.py` (it reads `legacy.py` by path; see Implementation Notes) — TASK-3876.
- Untracked, git-ignored scripts under `examples/pipelines/` that import `PlanogramCompliancePipeline`
  (not in git; spec §6 "Does NOT Exist") — do not touch them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` | MODIFY | **DELETE the whole file** (`git rm`) — legacy `RetailDetector` / `PlanogramCompliancePipeline` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py` | MODIFY | **DELETE the whole file** (`git rm`) — `AbstractDetector` |
| `packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py` | MODIFY | **DELETE the whole file** (`git rm`) — core proxy of the legacy module |
| `packages/ai-parrot/src/parrot/pipelines/detector.py` | MODIFY | **DELETE the whole file** (`git rm`) — core proxy of `AbstractDetector` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py` | MODIFY | Drop the two legacy names from `__all__` and `__getattr__` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py` | MODIFY | Drop three registry entries |
| `packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py` | MODIFY | Drop the two legacy names from the proxy `__all__` |
| `packages/ai-parrot/tests/test_monorepo_imports.py` | MODIFY | Positive and negative import tests; heavy-import static guard |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# test file only — all verified on dev (ff2f90213)
import importlib                                               # already at test_monorepo_imports.py:7
import pytest                                                  # already at test_monorepo_imports.py:8
from parrot.pipelines.models import PlanogramConfig            # used at test_monorepo_imports.py:174
from parrot.pipelines.planogram.plan import PlanogramCompliance  # used at test_monorepo_imports.py:175
from parrot_pipelines.planogram.plan import PlanogramCompliance  # planogram/plan.py:48
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # types/abstract.py:36
from parrot_pipelines.planogram.types import InkWall            # types/__init__.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py
PIPELINE_REGISTRY: dict[str, str] = {                                            # line 5
    "AbstractDetector": "parrot_pipelines.detector.AbstractDetector",              # line 7  (REMOVE)
    "PlanogramCompliancePipeline": "parrot_pipelines.planogram.legacy.PlanogramCompliancePipeline",  # line 11 (REMOVE)
    "RetailDetector": "parrot_pipelines.planogram.legacy.RetailDetector",          # line 12 (REMOVE)
    # every other entry (AbstractPipeline, PlanogramConfig, EndcapGeometry, PlanogramCompliance,
    # AbstractPlanogramType and the six types, lines 6, 8-10, 13-21) stays untouched
}
__all__ = ["__version__", "PIPELINE_REGISTRY"]                                   # line 24

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py (27 lines)
__all__ = ("PlanogramCompliancePipeline", "RetailDetector", "PlanogramCompliance",
           "AbstractPlanogramType", "InkWall")                                   # lines 5-11
def __getattr__(name: str):                                                      # line 14
    if name in {"PlanogramCompliancePipeline", "RetailDetector"}:                # lines 15-17 (REMOVE branch)
        mod = import_module(".legacy", __name__)
    ...                                                                          # lines 18-26 stay
    raise AttributeError(name)                                                   # line 27

# packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py (14 lines)
__all__ = ("PlanogramCompliancePipeline", "RetailDetector", "PlanogramCompliance", "AbstractPlanogramType")  # lines 4-9
def __getattr__(name: str):                                                      # line 12
    mod = import_module('parrot_pipelines.planogram')                            # line 13
    return getattr(mod, name)                                                    # line 14

# packages/ai-parrot/src/parrot/pipelines/__init__.py (NOT modified — behaviour the tests rely on)
_CORE_SUBMODULES = frozenset({... *.py stems and package dirs in parrot/pipelines/ ...})   # lines 40-43
class _ParrotPipelinesRedirector(importlib.abc.MetaPathFinder):                 # line 47
    # redirects parrot.pipelines.<x> → parrot_pipelines.<x>, then plugins.pipelines.<x>; a failed
    # redirect raises ImportError (lines 76-88). Once core detector.py is deleted, "detector" is no
    # longer a core submodule, so `import parrot.pipelines.detector` goes through the redirector and
    # ends in ImportError because parrot_pipelines.detector is gone too.
def __getattr__(name: str):                                                      # line 131
    # registry miss → raise ImportError(f"Pipeline '{name}' not found. ...")     # lines 150-153

# packages/ai-parrot/tests/test_monorepo_imports.py (179 lines)
class TestParrotPipelinesPackage:                                                # line 160
    def test_parrot_pipelines_importable(self): ...                              # line 163
    def test_proxy_resolves_pipeline_module(self): ...                           # line 172-179 (last lines of file)
```

**Importer verification (run again before deleting — every hit must be one of these):**
```text
$ grep -rn --include='*.py' -E 'planogram\.legacy|from \.legacy|PlanogramCompliancePipeline|RetailDetector' packages/ | grep -v /build/
packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py:11,12            (registry — edited here)
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py:6,7,15,16  (exports — edited here)
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py:*        (the file itself)
packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py:5,6              (proxy __all__ — edited here)
packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py:2                  (proxy — deleted here)
$ grep -rn --include='*.py' -E 'parrot_pipelines\.detector|pipelines\.detector|from \.\.detector|AbstractDetector' packages/ | grep -v /build/
packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py:7                (registry — edited here)
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py:40,54    (deleted here)
packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py:14               (the file itself)
packages/ai-parrot/src/parrot/pipelines/detector.py:2                          (proxy — deleted here)
$ grep -rn -E 'PlanogramCompliancePipeline|RetailDetector|AbstractDetector|planogram\.legacy|pipelines\.detector' packages/*/tests
(no output)
```
`packages/ai-parrot/build/` and `examples/pipelines/` are untracked (`git ls-files` returns nothing) — ignore them.

### Does NOT Exist
- ~~A replacement API for `PlanogramCompliancePipeline` / `RetailDetector` / `AbstractDetector`~~ — none is
  added (Module 12 skeleton). Do not add a deprecation shim or alias.
- ~~`parrot_pipelines.planogram.detector`~~ — the cycle's LLM detector lives at
  `parrot_pipelines/planogram/identification/detector.py` (`llm_detect_shapes`); it is NOT touched.
- ~~`packages/ai-parrot/src/parrot/pipelines/types/`~~ — the core proxy only has `planogram/types/`.
- ~~A root-level `__all__` entry for these names in core `parrot/pipelines/__init__.py`~~ — root `__all__ = ()` (line 128); do not edit that file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/pipelines/detector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_monorepo_imports.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py#__getattr__",
    "sym:packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py#__getattr__",
    "sym:packages/ai-parrot/src/parrot/pipelines/__init__.py#_ParrotPipelinesRedirector",
    "sym:packages/ai-parrot/src/parrot/pipelines/__init__.py#__getattr__",
    "sym:packages/ai-parrot/tests/test_monorepo_imports.py#TestParrotPipelinesPackage"
  ]
}
```
Note: the complexity parser (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py:193`)
accepts only `CREATE`/`MODIFY`, so the four deleted files are declared `MODIFY` here and in the Files table.

---

## Implementation Notes

### Pattern to Follow
The existing negative-path idiom in this repo is `pytest.raises(ImportError)` around a from-import.
A from-import of a name that a module's `__getattr__` rejects with `AttributeError` surfaces as
`ImportError` ("cannot import name"), so one `pytest.raises(ImportError)` covers both the package table
and the core proxy.

### Key Constraints
- Touch only the eight listed files. Delete with `git rm <path>` so the deletion is staged.
- Keep the core proxy package (`parrot/pipelines/planogram/__init__.py`, `plan.py`, `types/`) — spec §8.
- Keep `PIPELINE_REGISTRY` ordering of surviving entries; only delete lines.
- Tests must skip (not fail) when `parrot_pipelines` is not installed, matching the file's existing
  `try/except ImportError: pytest.skip(...)` style (e.g. lines 164-167).
- **Transitional breakage (accepted, do NOT fix here)**:
  `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py::test_core_files_have_no_literals`
  (line 101-106) opens `planogram/legacy.py` by path and will raise `FileNotFoundError` once this task lands.
  That file is owned by TASK-3876, which rewrites it. Do not edit it and do not list it in Validation Commands.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree
  (the shared venv is editable-installed against the main checkout).

### References in Codebase
- `packages/ai-parrot/src/parrot/pipelines/__init__.py:47-92` — redirector semantics used by the negative tests.
- `packages/ai-parrot/tests/test_monorepo_imports.py:160-179` — existing pipelines test class to extend.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-run the two importer greps in the Codebase Contract — *why*: the deletion is only safe if every hit is one of the listed export/proxy sites.
2. `git rm` the four module files — *why*: they are the obsolete implementations and proxies (Module 12 file list).
3. Rewrite `parrot_pipelines/planogram/__init__.py` (block below) — *why*: `__all__` must not advertise names that no longer resolve.
4. Delete the three registry lines — *why*: core `parrot.pipelines.__getattr__` resolves names through this registry (`_resolve_from_registry`).
5. Edit the core proxy `__all__` — *why*: star-imports of the proxy must not reference removed names.
6. Append the new test class and run Validation Commands — *why*: AC14 needs both positive and negative import evidence.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` (DELETE)
```text
git rm packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py
# anchor proving the right file: `class RetailDetector(AbstractDetector):` (verified: legacy.py:54, grep -Fxc = 1)
```
### `packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py` (DELETE)
```text
git rm packages/ai-parrot-pipelines/src/parrot_pipelines/detector.py
# anchor: `class AbstractDetector(ABC):` (verified: detector.py:14, grep -Fxc = 1)
```
### `packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py` and `packages/ai-parrot/src/parrot/pipelines/detector.py` (DELETE)
```text
git rm packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py packages/ai-parrot/src/parrot/pipelines/detector.py
# each is 2 lines: the docstring `"""Backward-compatible proxy for ai-parrot-pipelines."""` (line 1, grep -Fxc = 1)
# plus `from parrot_pipelines.planogram.legacy import *` / `from parrot_pipelines.detector import *` (line 2)
```
**Why**: the importer greps show no other importer; deleting the proxies makes
`import parrot.pipelines.detector` / `parrot.pipelines.planogram.legacy` fail instead of re-exporting
a module that no longer exists.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py` (MODIFY — full replacement, 27 → 23 lines)
```python
# occurrences: 1 (verified: grep -Fxc '"""Planogram Compliance Pipeline exports."""' planogram/__init__.py)
# REPLACE lines 1-27 (whole file) with:
"""Planogram Compliance Pipeline exports."""

from importlib import import_module

__all__ = (
    "PlanogramCompliance",
    "AbstractPlanogramType",
    "InkWall",
)


def __getattr__(name: str):
    if name == "PlanogramCompliance":
        mod = import_module(".plan", __name__)
        return getattr(mod, name)
    if name == "AbstractPlanogramType":
        mod = import_module(".types", __name__)
        return getattr(mod, name)
    if name == "InkWall":
        mod = import_module(".types", __name__)
        return getattr(mod, name)
    raise AttributeError(name)
```
**Why**: the only change is removing the `legacy` branch and its two `__all__` entries; the three
surviving branches are copied unchanged so lazy import behaviour is identical (Module 12 skeleton:
"removed names raise ordinary AttributeError").

### `packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -Fxc on each line below, __init__.py)
# DELETE line 7:
    "AbstractDetector": "parrot_pipelines.detector.AbstractDetector",
# DELETE lines 11-12:
    "PlanogramCompliancePipeline": "parrot_pipelines.planogram.legacy.PlanogramCompliancePipeline",
    "RetailDetector": "parrot_pipelines.planogram.legacy.RetailDetector",
```
**Why**: the registry is what core `parrot.pipelines.<Name>` resolves through; stale entries would
turn a clean "not found" into an import crash of a deleted module.

### `packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py` (MODIFY — lines 4-9)
```python
# occurrences: 1 (verified: grep -Fxc '"""Backward-compatible proxy for ai-parrot-pipelines."""' → 1 in this file)
# REPLACE lines 4-9 (the __all__ tuple) with:
__all__ = (
    "PlanogramCompliance",
    "AbstractPlanogramType",
)
```
**Why**: keep the proxy (spec §8) but stop advertising removed names; `__getattr__` (lines 12-14) is untouched.

### `packages/ai-parrot/tests/test_monorepo_imports.py` (MODIFY — append at end of file)
```python
# occurrences: 1 (verified: grep -Fxc '        assert PlanogramCompliance is not None' test_monorepo_imports.py)
# AFTER — append below `        assert PlanogramCompliance is not None` (verified: test_monorepo_imports.py:179, last line)


# ---------------------------------------------------------------------------
# FEAT-612: removed legacy planogram pipeline / detector APIs
# ---------------------------------------------------------------------------

_REMOVED_PIPELINE_NAMES = ("PlanogramCompliancePipeline", "RetailDetector")


class TestPlanogramLegacyRemoval:
    """Surviving planogram exports resolve; removed legacy names and proxy modules do not (AC14)."""

    @pytest.fixture(autouse=True)
    def _require_pipelines(self):
        try:
            import parrot_pipelines  # noqa: F401
        except ImportError:
            pytest.skip("parrot_pipelines not installed")

    def test_surviving_package_exports_resolve(self):
        from parrot_pipelines.planogram import AbstractPlanogramType, InkWall, PlanogramCompliance
        # FILL IN: assert each is not None and PlanogramCompliance.__name__ == "PlanogramCompliance"

    def test_surviving_core_proxy_exports_resolve(self):
        from parrot.pipelines.planogram import AbstractPlanogramType, PlanogramCompliance
        # FILL IN: assert both are the SAME objects as the parrot_pipelines.planogram ones (identity, `is`)

    @pytest.mark.parametrize("name", _REMOVED_PIPELINE_NAMES)
    def test_removed_names_not_importable_from_package(self, name):
        import parrot_pipelines.planogram as planogram

        assert name not in planogram.__all__
        with pytest.raises(AttributeError):
            getattr(planogram, name)

    @pytest.mark.parametrize("name", _REMOVED_PIPELINE_NAMES)
    def test_removed_names_not_importable_from_core_proxy(self, name):
        import parrot.pipelines.planogram as proxy

        assert name not in proxy.__all__
        # FILL IN: with pytest.raises(ImportError): exec(f"from parrot.pipelines.planogram import {name}", {})
        #   — from-import converts the AttributeError of __getattr__ into ImportError

    @pytest.mark.parametrize(
        "module",
        [
            "parrot_pipelines.planogram.legacy",
            "parrot_pipelines.detector",
            "parrot.pipelines.planogram.legacy",
            "parrot.pipelines.detector",
        ],
    )
    def test_removed_modules_raise_import_error(self, module):
        with pytest.raises(ImportError):
            importlib.import_module(module)

    def test_registry_has_no_removed_entries(self):
        from parrot_pipelines import PIPELINE_REGISTRY
        # FILL IN: assert "AbstractDetector", "PlanogramCompliancePipeline", "RetailDetector" not in PIPELINE_REGISTRY;
        #   assert every remaining dotted path's module does not contain ".legacy" and is not "parrot_pipelines.detector"

    def test_pipelines_source_has_no_heavy_legacy_imports(self):
        """Static guard: no pipelines module imports pytesseract / torch / ultralytics at any indentation."""
        # FILL IN: root = Path(parrot_pipelines.__file__).parent; for every *.py under root, assert no line
        #   matches re.compile(r"^\s*(import|from)\s+(pytesseract|torch|ultralytics)\b") — bounded by AC14/AC15;
        #   import Path/re locally inside the test (do not add module-level imports the file does not already use)
```
**Why**: AC14 requires surviving imports to resolve and removed ones to fail; the static guard proves the
deleted modules were the last heavy-dependency importers (spec §4 "removal/imports" row) without importing
optional backends at test time.

### FILL IN checklist
- [ ] `test_surviving_package_exports_resolve` — non-None + name check; bounded by AC14
- [ ] `test_surviving_core_proxy_exports_resolve` — identity with the package objects; bounded by spec §8 (proxy kept)
- [ ] `test_removed_names_not_importable_from_core_proxy` — `pytest.raises(ImportError)` on from-import
- [ ] `test_registry_has_no_removed_entries` — three names absent, no `.legacy` / `parrot_pipelines.detector` targets
- [ ] `test_pipelines_source_has_no_heavy_legacy_imports` — regex scan of the installed package source

---

## Acceptance Criteria

- [ ] The four listed modules no longer exist in git (`git ls-files` returns none of them) — AC14.
- [ ] `from parrot_pipelines.planogram import PlanogramCompliance, AbstractPlanogramType, InkWall` and
      `from parrot.pipelines.planogram import PlanogramCompliance, AbstractPlanogramType` still work — AC14.
- [ ] Importing any removed name or module raises `ImportError` / `AttributeError`; no shim exists — AC14.
- [ ] `PIPELINE_REGISTRY` keeps `AbstractPipeline`, `PlanogramConfig`, `EndcapGeometry`, `PlanogramCompliance`,
      `AbstractPlanogramType` and the six types only — Module 12 skeleton.
- [ ] No module under `parrot_pipelines` imports `pytesseract`, `torch` or `ultralytics` — spec §4 removal row.
- [ ] Validation Commands pass; `ruff check` and `black --check` are clean on touched files — AC16.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py packages/ai-parrot/tests/test_monorepo_imports.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py packages/ai-parrot/src/parrot/pipelines/planogram/__init__.py packages/ai-parrot/tests/test_monorepo_imports.py`

## Validation Commands

- `pytest packages/ai-parrot/tests/test_monorepo_imports.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_monorepo_imports.py — new class appended (see blueprint)
class TestPlanogramLegacyRemoval:
    def test_surviving_package_exports_resolve(self): ...          # PlanogramCompliance / AbstractPlanogramType / InkWall import
    def test_surviving_core_proxy_exports_resolve(self): ...       # proxy objects `is` package objects
    def test_removed_names_not_importable_from_package(self, name): ...   # not in __all__, getattr → AttributeError
    def test_removed_names_not_importable_from_core_proxy(self, name): ... # from-import → ImportError
    def test_removed_modules_raise_import_error(self, module): ...  # 4 modules → ImportError
    def test_registry_has_no_removed_entries(self): ...            # 3 keys absent, no ".legacy" targets
    def test_pipelines_source_has_no_heavy_legacy_imports(self): ...  # regex scan finds no torch/pytesseract/ultralytics
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3873 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented by coder seat via sdd-worker orchestration (merge-tier tests green for planogram scope; unrelated ai-parrot-server collection errors due to missing fakeredis in shared env).

