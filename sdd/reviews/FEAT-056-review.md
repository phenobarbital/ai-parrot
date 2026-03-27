# Code Review: FEAT-056 — Runtime Dependency Reduction

**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Tasks**: TASK-386 through TASK-397 (12 tasks)
**Branch**: `feat-056-runtime-dependency-reduction`
**Reviewed files**: `parrot/_imports.py`, `tests/test_lazy_imports.py`, `tests/test_minimal_install.py`, `pyproject.toml`, `parrot/clients/base.py`, `parrot/clients/gpt.py`, `parrot/tools/db.py`, `parrot/tools/querytoolkit.py`, `parrot/tools/flowtask/__init__.py`, `parrot/tools/flowtask/tool.py`, `parrot/scheduler/__init__.py`, `parrot/core/hooks/scheduler.py`, `parrot/services/heartbeat.py`
**Review date**: 2026-03-23

**Overall verdict**: ✅ Approved — all critical and major issues resolved in commit `127b0fee`

---

## Summary

The core contribution of FEAT-056 is solid: `parrot/_imports.py` is an exemplary stdlib-only lazy import utility, the `pyproject.toml` restructuring correctly removes the highest-impact packages (weasyprint, ta-lib, pytesseract, pydub, faiss-cpu, matplotlib, seaborn) from core, and the lazy import conversions for client files are correct. However, three scheduler-related files (`parrot/scheduler/__init__.py`, `parrot/core/hooks/scheduler.py`, `parrot/services/heartbeat.py`) were not covered by any task and still import `apscheduler` and `querysource` directly at module level — despite both being moved to optional extras. This creates a real regression that must be fixed before merge.

---

## Findings

### 🔴 Critical (must fix before merge)

- **[parrot/scheduler/__init__.py:18-41]** Nine direct top-level imports from `apscheduler` + `from querysource.conf import default_dsn` — both packages were moved to `[scheduler]` and `[db]` extras respectively. Any app importing `parrot.scheduler` on a bare `pip install ai-parrot` will get a cryptic `ModuleNotFoundError` at import time. This file was not in scope for any task — a gap in the task breakdown. Fix: apply `lazy_import()` at method bodies, or gate the module with a lazy guard.

- **[parrot/core/hooks/scheduler.py:4-6]** Same issue — three direct top-level `apscheduler` imports not caught by any task. Fix: apply `lazy_import()`.

- **[parrot/services/heartbeat.py:5-7]** Same issue — three direct top-level `apscheduler` imports. Fix: apply `lazy_import()`.

- **[parrot/tools/db.py:22-23]** `from parrot._imports import lazy_import` is imported on line 22 but **never called** anywhere in the file. `from asyncdb import AsyncDB` remains as a direct module-level import. The lazy import guard was added but never wired up — a dead import that creates false confidence. While `asyncdb[default]` is in core so this won't fail today, it leaves no guard if asyncdb is ever moved. Fix: remove the dead import or actually use `lazy_import()`.

### 🟡 Major (should fix)

- **[pyproject.toml:80]** `"pandas"` has no version pin while every other core dependency is pinned. A future install could resolve to a breaking pandas major version silently. Fix: add `"pandas>=2.0.0"` (or the appropriate minimum).

- **[pyproject.toml:126,172,238,327]** `pandas-datareader` appears in at least four extras groups. One canonical location with other groups referencing it reduces maintenance burden. Fix: declare it only in `finance` and remove duplicates.

- **[parrot/tools/flowtask/tool.py:20,26]** `import importlib` (old pattern) coexists with `from parrot._imports import lazy_import` (new canonical pattern). The task required standardizing to `lazy_import()`. Fix: remove `import importlib` and replace remaining `importlib.import_module(...)` calls with `lazy_import(...)`.

- **[spec acceptance criterion]** The spec requires "Core dependencies reduced from ~57 to ~25 or fewer." The restructured `pyproject.toml` has ~34 core deps. `aioquic` and `pylsqpack` were identified as candidates for an `http3` extra but remain in core with no documented rationale. Fix: either move them to an `http3` extra to close the gap, or update the spec criterion with documented justification.

- **[TASK-388,389,390,394,395,396 completion notes]** Six of twelve tasks have empty/blank completion note templates. TASK-388 has no completion note at all. This makes auditing impossible and leaves no evidence for future reviewers. Fix: fill in at minimum: date, files changed, one-line summary.

### 🟢 Minor / Suggestions

- **[tests/test_lazy_imports.py:133-155]** `TestLazyImportWithMockedImport` patches `builtins.__import__` but `lazy_import()` uses `importlib.import_module` — these tests only pass because the package names are genuinely nonexistent, making the mock irrelevant to the actual code path. Patch `parrot._imports.importlib.import_module` instead (as `tests/test_minimal_install.py` correctly does).

- **[parrot/scheduler/__init__.py]** When the scheduler files are fixed, consider adding them to a TASK-398 so the scope gap is traceable in SDD history.

---

## Acceptance Criteria Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| flowtask, weasyprint, pytesseract, ta-lib, etc. removed from core | ✅ | pyproject.toml correctly restructured |
| `pip install ai-parrot[all]` installs all | ✅ | `all` meta-extra includes all groups |
| `pip install ai-parrot[db]` installs querysource, psycopg-binary | ✅ | Verified in pyproject.toml |
| `pip install ai-parrot[pdf]` installs weasyprint, fpdf, etc. | ✅ | Verified in pyproject.toml |
| `import parrot` (top-level) without optional deps | ✅ | Core parrot package loads cleanly |
| `parrot.scheduler` importable without optional deps | ❌ | apscheduler + querysource imported directly at top level |
| `lazy_import()` stdlib-only | ✅ | Only importlib + types |
| Tools raise clear ImportError with install hints | ✅ | base.py, gpt.py, flowtask/tool.py verified |
| Core deps reduced from ~57 to ~25 or fewer | ❌ | ~34 remain; spec target was ≤25 |
| All 43 tests pass | ✅ | Reported by agent |
| No `apscheduler` in core install path | ❌ | parrot/scheduler/__init__.py imports directly |
| No `querysource` in core install path | ❌ | parrot/scheduler/__init__.py imports directly |
| Version pins preserved | ⚠ | All pinned except `pandas` (unpinned) |
| Completion notes filled | ❌ | 6 of 12 tasks have blank completion notes |
| Existing extras groups unchanged | ✅ | agents, loaders, embeddings, mcp groups intact |

---

## Positive Highlights

- `parrot/_imports.py` is exemplary: stdlib-only, thread-safety noted, proper exception chaining (`raise ... from exc`), Google-style docstrings with usage examples, zero external dependencies.
- `tests/test_lazy_imports.py` is thorough: 12 unit + 4 integration tests covering edge cases (submodule extraction, chained exceptions, call ordering, empty `require_extra`).
- `tests/test_minimal_install.py` correctly patches `parrot._imports.importlib.import_module` — demonstrating the right approach to testing `lazy_import()` behavior.
- `parrot/clients/base.py` (pydub) and `parrot/clients/gpt.py` (pytesseract) are correctly lazy-loaded inside method bodies, not at class init — the pattern is exemplary.
- `asyncdb` correctly narrowed from `asyncdb[bigquery,mongodb,arangodb,influxdb,boto3]` to `asyncdb[default]` in core — a meaningful reduction in transitive dependencies.
- `parrot/tools/flowtask/__init__.py` docstring clearly communicates optional-extra status.
- `all` meta-extra correctly aggregates all optional groups.

---

## Required Actions Before Merge

1. **Fix scheduler files** — apply `lazy_import()` to `parrot/scheduler/__init__.py`, `parrot/core/hooks/scheduler.py`, and `parrot/services/heartbeat.py` (Findings 1–3). Recommended: create **TASK-398** for this.
2. **Remove dead import** — remove unused `from parrot._imports import lazy_import` from `parrot/tools/db.py` or wire it up (Finding 4).
3. **Standardize flowtask** — remove `import importlib` from `parrot/tools/flowtask/tool.py` (Finding 6).
4. **Pin pandas** — add version constraint to `"pandas"` in `pyproject.toml` (Finding 7).
5. **Document/fix dep count gap** — move `aioquic`/`pylsqpack` to `http3` extra or update spec criterion with rationale (Finding 8).
6. **Fill completion notes** — TASK-388, 389, 390, 394, 395, 396 (Finding 10).
