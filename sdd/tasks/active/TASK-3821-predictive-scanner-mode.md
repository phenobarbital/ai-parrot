# TASK-3821: Predictive `mode` for the JS/TS, PHP, Rust and Perl scanners

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 1 / §3 Module 1. Each structural-capable scanner reports `mode` from
`_last_mode`, which is the tier that served the **last** file. A `wikitoolkit status` process
has scanned nothing, so it prints `javascript: tree-sitter` whether or not ast-grep is
installed. `mode` must become *predictive*: the tier the **next** file would be served by.
TASK-3824 (the `status` line and the build warning) and TASK-3828 (the extractor fingerprint)
both consume this.

---

## Scope

- In each of `JavaScriptScanner`, `PhpScanner`, `RustScanner` and `PerlScanner`, change `mode`
  so it returns `"ast-grep"` when `structural_enabled()` **and**
  `astgrep.supported_language(<primary>)` are both true. The primary ast-grep language is
  `typescript` for JS, and `php`, `rust`, `perl` for the others (these are the strings each
  scanner passes to `astgrep.extract`).
- Otherwise, keep today's tree-sitter/heuristic rule byte-for-byte.
- Keep `_last_mode` (it is still assigned in `outline`), but stop reading it in `mode`.
- Update each `mode` docstring, and the `LanguageScanner.mode` docstring in `base.py`, to
  include `"ast-grep"`.
- Write tests.

**NOT in scope**: the `status`/warning output (TASK-3824), Python/Luau scanners (they have no
ast-grep tier to predict), and any change to `outline()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | predictive `mode` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` | MODIFY | predictive `mode` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py` | MODIFY | predictive `mode` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` | MODIFY | predictive `mode` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py` | MODIFY | `mode` docstring lists `"ast-grep"` |
| `tests/knowledge/wiki/languages/test_predictive_mode.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, treesitter          # javascript.py:40 (same line in php/rust/perl — verify)
from parrot.knowledge.wiki.languages.render import render_outline, structural_enabled  # javascript.py:42
from parrot.knowledge.wiki.languages.render import set_structural_enabled   # render.py:35
from parrot.knowledge.wiki.languages import scanner_for                    # used by test_outline_parity.py:16
```

### Existing Signatures to Use
```python
# languages/astgrep.py:151
def supported_language(lang: str) -> bool:   # False when ast-grep-py is absent; never raises
# languages/render.py:45
def structural_enabled() -> bool:
# languages/javascript.py:755   (php.py:413, rust.py:420, perl.py:536 are the same shape)
@property
def mode(self) -> str:
    if self._last_mode == "ast-grep":
        return "ast-grep"
    if treesitter.get_parser("typescript") is not None and treesitter.get_parser("javascript") is not None:
        return "tree-sitter"
    return "heuristic"
# languages/base.py:118
@property
@abstractmethod
def mode(self) -> str:
    """Active extraction mode: ``"ast" | "tree-sitter" | "heuristic"``."""
```
```python
# tests/knowledge/wiki/languages/conftest.py:22 — monkeypatches astgrep.is_available -> False
@pytest.fixture
def force_no_astgrep(monkeypatch): ...
# conftest.py — marker
requires_astgrep = pytest.mark.skipif(not _has_astgrep(), reason="ast-grep-py not installed")
```

### Does NOT Exist
- ~~`astgrep.available_languages()`~~: use `supported_language(lang)`.
- ~~A `LanguageScanner.structural_language` attribute~~: hard-code each scanner's primary
  language inside its own `mode`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/languages/test_predictive_mode.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py#JavaScriptScanner.mode",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#supported_language",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py#structural_enabled"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `supported_language` imports ast-grep lazily and never raises, so calling it on every `mode`
  read is safe. `status` reads `mode` twice per scanner (`cli.py:2125`, `cli.py:2129`).
- `perl`: `supported_language("perl")` triggers the one-time dynamic registration
  (`astgrep.py:167-169`). That is acceptable, because `outline` would trigger it on the first
  Perl file anyway.
- Grep every `.mode` consumer before finishing (spec §7, "`mode` is displayed elsewhere"):
  `grep -rn "\.mode\b" packages/ai-parrot/src/parrot/knowledge/wiki`.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `_last_mode` check in `JavaScriptScanner.mode` with the predictive check.
   *Why*: `status` must report what a scan would do (spec M1).
2. Apply the same change in php, rust and perl with their own primary language.
   *Why*: they share the defect (spec §1).
3. Update the `base.py` docstring. *Why*: it still lists only `"ast" | "tree-sitter" | "heuristic"`.
4. Write the tests, run them, and mutation-check one of them.

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if self._last_mode == "ast-grep":' languages/javascript.py)
# REPLACE the two lines starting at `        if self._last_mode == "ast-grep":` inside `def mode` (verified: javascript.py:767-768)
        if structural_enabled() and astgrep.supported_language("typescript"):
            return "ast-grep"
```
**Why**: the TS rule file serves `typescript`/`tsx`/`javascript` through its aliases
(`rules/typescript.yaml:14`), so `typescript` is the representative language.

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if self._last_mode == "ast-grep":' languages/php.py)
# REPLACE inside `def mode` (verified: php.py:416-417)
        if structural_enabled() and astgrep.supported_language("php"):
            return "ast-grep"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if self._last_mode == "ast-grep":' languages/rust.py)
# REPLACE inside `def mode` (verified: rust.py:423-424)
        if structural_enabled() and astgrep.supported_language("rust"):
            return "ast-grep"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if self._last_mode == "ast-grep":' languages/perl.py)
# REPLACE inside `def mode` (verified: perl.py:539-540)
        if structural_enabled() and astgrep.supported_language("perl"):
            return "ast-grep"
```
**Why (all three)**: each scanner already imports both `astgrep` and `structural_enabled`
(verified: php.py:34, rust.py:27, perl.py:29), so no import changes are needed.

### `tests/knowledge/wiki/languages/test_predictive_mode.py` (CREATE)
```python
"""FEAT-609 M1: scanner `mode` predicts the tier the NEXT file gets."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.render import set_structural_enabled

from .conftest import requires_astgrep

_SUFFIXES = (".ts", ".php", ".rs", ".pl")


@requires_astgrep
@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_mode_predictive_with_astgrep(suffix: str) -> None:
    """Fresh scanner, no outline() call yet -> already reports ast-grep."""
    scanner = scanner_for(suffix)
    assert scanner is not None
    # FILL IN: reset the scanner's _last_mode to None first — bounded by "scanners are
    # module-level singletons; a previous test may have served a file".
    assert scanner.mode == "ast-grep"


@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_mode_predictive_without_astgrep(force_no_astgrep, suffix: str) -> None:
    scanner = scanner_for(suffix)
    assert scanner.mode in {"tree-sitter", "heuristic"}


@requires_astgrep
def test_mode_honours_kill_switch() -> None:
    set_structural_enabled(False)
    try:
        assert scanner_for(".ts").mode != "ast-grep"
    finally:
        set_structural_enabled(True)
```
**Why**: the first test fails today (it would read `tree-sitter` before any file is served).
That is the mutation proof: revert the javascript.py change and see it go RED.

### FILL IN checklist
- [ ] `test_mode_predictive_with_astgrep`: reset `_last_mode`. Bound: module-level scanner
  singletons (check `scanner_for` in `languages/__init__.py`).
- [ ] Update the `base.py` `mode` docstring to `"ast" | "ast-grep" | "tree-sitter" | "heuristic"`.

---

## Acceptance Criteria

- [ ] In a fresh process with ast-grep installed, `JavaScriptScanner().mode == "ast-grep"`
      before any `outline()` call (spec AC: "`status` reports `javascript: ast-grep`").
- [ ] Under `force_no_astgrep`, all four scanners report a non-`ast-grep` mode.
- [ ] The kill switch (`set_structural_enabled(False)`) is honoured.
- [ ] Mutation-checked: reverting `javascript.py` turns `test_mode_predictive_with_astgrep[.ts]` RED.
- [ ] Existing language tests still pass.

---

## Validation Commands

- `pytest tests/knowledge/wiki/languages/test_predictive_mode.py -q`
- `pytest tests/knowledge/wiki/languages/test_outline_parity.py -q`
- `pytest tests/knowledge/wiki/languages/test_astgrep_seam.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Verify the Codebase Contract, and re-run the `grep -c` for each anchor.
3. Set this task to `"in-progress"` in the per-spec index, implement, validate, and stage only
   the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3821 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
