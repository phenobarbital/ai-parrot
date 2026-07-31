# TASK-2019: Resolve tree-sitter grammar callables for multi-grammar wheels

**Feature**: FEAT-396 — Svelte / hardened-TypeScript support in the wiki repo scanner
**Spec**: `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3). `_build_parser` calls
`grammar_module.language()` unconditionally (`treesitter.py:69`). That is correct for
**single-grammar** wheels, but **multi-grammar** wheels expose named variants instead —
and two of the four languages in `_GRAMMAR_MODULES` are multi-grammar. The resulting
`AttributeError` is swallowed by the `except Exception` at `treesitter.py:71` (correct
behaviour for an optional dependency), so `get_parser("typescript")` and
`get_parser("php")` silently return `None` **even with the extra installed**, and every
`.ts`/`.tsx`/`.php` file in the repo takes the regex heuristic path.

This is a pre-existing defect that affects current PHP/TypeScript users, independent of
Svelte. It is Module 1 because Module 3 (`lang`-based grammar selection) is inert until
the TypeScript grammar actually loads.

This task is **self-contained, independently mergeable and independently revertable** —
per spec §"Worktree Strategy", if the rest of FEAT-396 stalls, this module should still
land on its own.

---

## Scope

- Modify `_build_parser` in `treesitter.py` to resolve the grammar callable by trying,
  in order:
  1. `language()` — **first, always**. This is the single-grammar convention and must
     keep working unchanged for `javascript`, `rust` and `python`.
  2. The named variant(s) for multi-grammar wheels: `language_typescript()` for
     `typescript`, `language_php()` for `php`.
- Log at `debug` level which callable was used, so the resolved grammar is auditable.
- Extend `tests/knowledge/wiki/languages/test_treesitter.py` with the two unit tests
  from spec §4 (`test_build_parser_uses_language_variant`,
  `test_build_parser_unknown_language_none`).

**NOT in scope**:
- Anything touching `javascript.py` — no suffix changes, no `outline()` changes, no
  `mode` changes (those are TASK-2020 / TASK-2021 / TASK-2023).
- Adding `tree_sitter_svelte` to `_GRAMMAR_MODULES` — **no such wheel is used by this
  feature**; Svelte is parsed with the typescript/javascript grammars (spec §6).
- Changing `get_parser`'s caching behaviour or its never-raising contract.
- Adding or bumping any dependency. `tree-sitter-typescript>=0.23` and
  `tree-sitter-php>=0.23` are already in the `wiki-languages` extra.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` | MODIFY | Resolve the grammar callable across both wheel conventions in `_build_parser` |
| `tests/knowledge/wiki/languages/test_treesitter.py` | MODIFY | Add the two new unit tests (existing three must keep passing) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-07-31 (branch `dev`, commit
> `349a184c3`). Re-verify before writing code if time has passed.

### Verified Imports

```python
# verified: languages/treesitter.py:14-19
import importlib
import logging
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tree_sitter import Parser

# verified: languages/treesitter.py:66 — imported INSIDE the try block, not module level
from tree_sitter import Language, Parser

# test-side, verified: tests/knowledge/wiki/languages/test_treesitter.py:3-4
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.treesitter import get_parser
```

### Existing Signatures to Use

```python
# languages/treesitter.py
_PARSER_CACHE: dict[str, Parser | None] = {}          # line 25 — CACHES None TOO
_GRAMMAR_MODULES: dict[str, str] = {                  # lines 30-35
    "php": "tree_sitter_php",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "rust": "tree_sitter_rust",
}
def get_parser(language: str) -> Parser | None: ...   # line 38 — do NOT change
def _build_parser(language: str) -> Parser | None: ...# line 60 — THE function to change

# the exact body being replaced, lines 62-76:
#   module_name = _GRAMMAR_MODULES.get(language)
#   if module_name is None:
#       return None
#   try:
#       from tree_sitter import Language, Parser
#       grammar_module = importlib.import_module(module_name)
#       ts_language = Language(grammar_module.language())     # <-- line 69, the defect
#       return Parser(ts_language)
#   except Exception as exc:  # noqa: BLE001 - optional dependency, never raise
#       logger.debug(
#           "tree-sitter grammar for %s unavailable, falling back to "
#           "heuristic extraction: %s", language, exc,
#       )
#       return None
```

### Verified wheel behaviour (measured 2026-07-31 against `~/.venvs/parrot-lite`)

```
tree_sitter_typescript: ['language_tsx', 'language_typescript']   has_language()=False
tree_sitter_php:        ['language_php', 'language_php_only']     has_language()=False
tree_sitter_javascript: ['language']                              has_language()=True
tree_sitter_rust:       NOT INSTALLED in this venv (ModuleNotFoundError)
```

### Does NOT Exist

- ~~`tree_sitter_typescript.language()`~~ — **does not exist in any released version**.
  Verified against 0.23.0 and 0.23.2 (the only versions satisfying the extra's `>=0.23`
  pin). Not resolvable via the module's dynamic `__getattr__` either. There is no version
  to upgrade to.
- ~~`tree_sitter_php.language()`~~ — **does not exist.** 0.24.1 exposes `language_php()`
  and `language_php_only()`.
- Conversely, `tree_sitter_javascript.language()` and `tree_sitter_rust.language()`
  **DO** exist — **do not "fix" those call sites.** `language()` must stay the first
  thing tried.
- ~~`tree_sitter_svelte`~~ — not in `_GRAMMAR_MODULES`, not in the `wiki-languages` extra,
  and not used by this feature at all.
- ~~`treesitter.clear_cache()`~~ / ~~`treesitter.reset()`~~ — no such helper. Tests clear
  the cache with `treesitter._PARSER_CACHE.pop(<lang>, None)`, the pattern already used
  at `test_treesitter.py:13` and `:18`.
- ~~`Language(module, "name")`~~ — the old two-argument tree-sitter API. The installed
  API is `Language(<PyCapsule from the callable>)`, single argument, as at line 69.

---

## Implementation Notes

### Pattern to Follow

Keep the existing structure — one `try`, the same `except Exception` guard, the same
`logger.debug` degradation. Only the callable resolution changes. Suggested shape:

```python
#: Grammar-callable names to try, in order, per language. ``language`` is the
#: single-grammar convention (tree_sitter_javascript / _rust / _python) and is
#: always tried FIRST; multi-grammar wheels expose named variants instead.
_GRAMMAR_CALLABLES: dict[str, tuple[str, ...]] = {
    "php": ("language", "language_php"),
    "javascript": ("language",),
    "typescript": ("language", "language_typescript"),
    "rust": ("language",),
}
```

then inside the `try`, after `importlib.import_module(module_name)`, walk the candidate
names with `getattr(grammar_module, name, None)`, take the first callable found, log
which one at debug, and fall through to the existing `except`/`return None` when none
resolve.

### Key Constraints

- **`language()` MUST be attempted first.** javascript, rust and python expose it and
  must not regress — this is an explicit acceptance criterion of the spec.
- `get_parser` must stay never-raising: a missing wheel, a missing callable, and a
  missing `tree-sitter` package all still degrade to `None`.
- `_PARSER_CACHE` caches `None` (`treesitter.py:25`, `:52-57`). Any test that
  monkeypatches grammar availability **must** clear the cache first, or test ordering
  makes results non-deterministic.
- Google-style docstrings + type hints, per `CLAUDE.md`.

### Testing this task

CI on `dev` has been red since 2026-07-27 for an **unrelated** dependency conflict
(`ai-parrot[all]` wants `pillow-heif>=1.3.0`, `flowtask>=5.12.3` pins
`pillow-heif==0.22.0`; `uv sync` dies before any test runs). Do **not** try to fix it and
do **not** wait for green. Verify locally instead — this suite needs only pytest +
pydantic:

```bash
cd packages/ai-parrot/src
SITE_ROOT=~/.local/share/parrot-site ENV=dev PYTHONPATH=. \
  ~/.venvs/parrot-lite/bin/python -m pytest ../../../tests/knowledge/wiki/languages/ -q
```

`SITE_ROOT` is mandatory — navconfig raises `FileExistsError` without it. Baseline on
clean `dev` is **70 passed in ~0.3s**. That venv already has the
`tree-sitter-typescript`, `tree-sitter-javascript` and `tree-sitter-php` wheels;
**`tree-sitter-rust` is NOT installed there**, so guard any rust assertion with
`pytest.importorskip` / `skipif` rather than asserting a `Parser`.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` — the file to change
- `tests/knowledge/wiki/languages/test_treesitter.py:11-14` — existing monkeypatch +
  cache-clear pattern to copy
- `tests/knowledge/wiki/languages/conftest.py:11-23` — the `force_heuristic` fixture

---

## Acceptance Criteria

- [ ] `treesitter.get_parser("typescript")` returns a `Parser` (not `None`) with the
      grammar wheels installed
- [ ] `treesitter.get_parser("php")` returns a `Parser` (not `None`)
- [ ] `treesitter.get_parser("javascript")` still returns a `Parser` — no regression
- [ ] `treesitter.get_parser("rust")` still resolves via `language()` (assert the
      resolution path, or skip when the wheel is absent — it is absent in `parrot-lite`)
- [ ] `treesitter.get_parser("nonexistent_language")` still returns `None`
- [ ] Nothing raises when the wheels are absent — the never-raising contract holds
- [ ] A debug log records which callable was used
- [ ] The three pre-existing tests in `test_treesitter.py` pass untouched
- [ ] Full suite green: `pytest ../../../tests/knowledge/wiki/languages/ -q`
      (≥ 70 passed, 0 failed)
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_treesitter.py — ADD to the existing file

import pytest
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.treesitter import get_parser


def _wheel_installed(module_name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(module_name) is not None


@pytest.mark.parametrize(
    ("language", "module_name"),
    [("typescript", "tree_sitter_typescript"), ("php", "tree_sitter_php")],
)
def test_build_parser_uses_language_variant(language, module_name):
    """Multi-grammar wheels expose language_<name>(), not language()."""
    if not _wheel_installed(module_name):
        pytest.skip(f"{module_name} not installed")
    treesitter._PARSER_CACHE.pop(language, None)
    parser = get_parser(language)
    assert parser is not None, (
        f"{language} grammar failed to load — the wheel exposes a named "
        "variant, not language()"
    )


def test_build_parser_single_grammar_wheel_unregressed():
    """javascript still resolves through the plain language() convention."""
    if not _wheel_installed("tree_sitter_javascript"):
        pytest.skip("tree_sitter_javascript not installed")
    treesitter._PARSER_CACHE.pop("javascript", None)
    assert get_parser("javascript") is not None


def test_build_parser_unknown_language_none():
    """An unmapped language name still returns None, never raises."""
    treesitter._PARSER_CACHE.pop("klingon", None)
    assert get_parser("klingon") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 1, and §7 "Known risks / gotchas" (the wheel table)
2. **Check dependencies** — none; this task can start immediately
3. **Verify the Codebase Contract** — confirm `treesitter.py:69` still reads
   `Language(grammar_module.language())` before changing it
4. **Update status** in `sdd/tasks/index/wikitoolkit-svelte-typescript-support.json` →
   `"in-progress"`
5. **Implement** per scope
6. **Verify** every acceptance criterion with the local command above
7. **Move this file** to `sdd/tasks/completed/TASK-2019-treesitter-grammar-callable-resolution.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Code session (Opus 5), with Emmanuel Arroyo
**Date**: 2026-07-31

**Notes**:

`_build_parser` now resolves the grammar callable from a new
`_GRAMMAR_CALLABLES` table instead of hardcoding `grammar_module.language()`.
`language` is listed first for every language, so the single-grammar wheels
(`javascript`, `rust`) resolve exactly as before; `typescript` and `php` fall
through to `language_typescript` / `language_php`. `_DEFAULT_GRAMMAR_CALLABLES`
covers any language added to `_GRAMMAR_MODULES` without a table entry. Each
candidate is attempted under its own guard, so a callable that exists but fails
to build (e.g. an ABI mismatch) is skipped rather than aborting the search — one
broken callable can never mask a working one. A debug line records which
callable succeeded; exhausting every candidate raises an `AttributeError` that
the pre-existing outer `except Exception` converts to the usual `None`
degradation, so the never-raising contract is unchanged.

Measured before/after with the wheels installed:

```
                  before        after
typescript        None          <tree_sitter.Parser>
php               None          <tree_sitter.Parser>
javascript        <Parser>      <Parser>          (unchanged)
```

Tests: `test_treesitter.py` goes from 3 to 12 tests. Beyond the two the task
required, the resolution *order* is pinned deterministically
(`test_build_parser_prefers_plain_language` asserts `language()` is called and
`language_typescript()` is not) using a `SimpleNamespace` stand-in injected via
`sys.modules` plus a real capsule borrowed from `tree_sitter_javascript` — this
proves the no-regression guarantee without depending on which wheels happen to
be installed.

Added a `clear_parser_cache` fixture that empties `_PARSER_CACHE` **before and
after** each test. The pre-existing `test_get_parser_missing_dep_returns_none`
leaves `_PARSER_CACHE["php"] = None` behind (monkeypatch restores
`_GRAMMAR_MODULES` but not the cache), which would have made the new php
assertion pass or fail depending on collection order.

Verification (`~/.venvs/parrot-lite`, per the task's local recipe):
- `tests/knowledge/wiki/languages/` — **78 passed, 1 skipped** (baseline on
  clean `dev` was 70 passed)
- the 1 skip is `rust`: `tree-sitter-rust` is **not installed** in that venv, so
  the rust non-regression assertion is guarded by a wheel check rather than
  asserting a `Parser`
- wider `tests/knowledge/wiki/` — 166 failed / 341 passed, **identical failure
  count to clean `dev`** (166 failed / 333 passed). Those failures are
  pre-existing `parrot-lite` environment limits, not regressions; only
  `languages/` is self-contained in that venv.
- `tests/knowledge/wiki/test_integration.py` does not collect —
  `ModuleNotFoundError: pytest_asyncio`, also identical on clean `dev`
- `ruff check` on both changed files — **All checks passed** (run via `uvx`;
  ruff is not installed in `.venv` or `parrot-lite`)

CI was **not** consulted: `dev` has been red since 2026-07-27 on an unrelated
`pillow-heif` conflict (`ai-parrot[all]` wants `>=1.3.0`, `flowtask>=5.12.3`
pins `==0.22.0`) that kills `uv sync` before any test runs.

**Deviations from spec**: none. Scope held to `treesitter.py` + its test file;
`javascript.py` untouched.

**Follow-up for the owner** (spec §7, unchanged by this task): the reported
`mode` for existing PHP/TypeScript repos will change once TASK-2023 tightens
`JavaScriptScanner.mode`, because those files were silently on the regex path
until this fix. That is the correction, not a regression. Worth raising with
Jesús Lara as a FEAT-394 follow-up — lead with the before/after table above,
not the diagnosis.
