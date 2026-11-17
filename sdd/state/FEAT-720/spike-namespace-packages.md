# FEAT-720 Amendment B — namespace-package identity (strategy (a″))

**Run at**: 2026-10-23, worktree `feat-FEAT-720-tests-test-wheel-layout-tech-debt-2`, pytest 9.1.1
**Supersedes**: `spike-identity-fixpoint.md` (strategy (a′), now abandoned) and the verdict of `spike-collect.md`.

## Two findings
1. **`pytest.ini` is the live pytest config, not `pyproject.toml`.** The repo root has a tracked `pytest.ini` (`[pytest]`),
   and pytest gives it precedence over `[tool.pytest.ini_options]`, which is therefore dead config. The spec (and TASK-4590/4591)
   assumed the opposite. Any `--import-mode` / `consider_namespace_packages` setting must go in **`pytest.ini`**.
   (Verified: the ini value placed in `pyproject.toml` had no effect; the same value in `pytest.ini` does.)
2. **`--import-mode=importlib` + `consider_namespace_packages = true`, with every `__init__.py` kept, is sufficient.**
   Pytest then derives each module's identity from its full path, so the 25 trees that are all named `tests` cannot claim the
   same name. No `__init__.py` is deleted or added (strategy (a) and (a′) both did, at a large and risky blast radius).

## Measurement (live config = `pytest.ini` with both settings; every `__init__.py` kept; test sources untouched)
| Root (standalone `--collect-only`) | collected | errors | baseline |
|---|---:|---:|---:|
| ai-parrot | 25,328 | 0 | 25,328 |
| ai-parrot-integrations | 2,458 | 0 | 2,458 |
| ai-parrot-loaders / embeddings / pipelines / visualizations / navrules / advisors / clients (17) | = baseline | 0 | = |
| parrot-formdesigner | 3,899 | 0 | 3,899 |
| ai-parrot-tools | 6,270 | 2 (`business_automation/test_fixture_site_e2e.py`, `scraping/test_fixture_site_integration.py`: `tests.*` imports) | 6,286 |
| ai-parrot-server | 3,597 | 4 (all pre-existing: `fakeredis` ×2, `unit/e2e` ×2) | 3,588 / 5 pre-existing |

| Session | result |
|---|---|
| embeddings + formdesigner (the reported pair) | **0 identity collisions**; 5 formdesigner errors (class (i) `tests.*` ×4, class (iii) `scripts.*` ×1) |
| all 28 roots in ONE session | 42,978 collected, **0** `Plugin already registered` / `ImportPathMismatchError` / `import file mismatch`; 73 residual errors = class (i)/(iii) import sites + class (xi) test-level `sys.modules` pollution |

Without `consider_namespace_packages` (importlib mode only) the original `ImportPathMismatchError: tests.conftest` returns — both lines are required.

## Residual work (unchanged from the original spec, plus 1)
Class (i) `from tests.<x>` sites (they resolve against whichever tree was imported first in a mixed session), class (v) dotted targets,
class (iii) `scripts.build_snippet_bundles` in formdesigner (needs an explicit owning-package path in its `conftest.py`),
class (vi) `tests/mcp` shadowing the real `mcp`. Class (xi) pollution is out of scope.

## Verdict
STRATEGY (a″) CONFIRMED
