# TASK-2262: PerlScanner test suite

**Feature**: FEAT-432 — Wikitoolkit Perl Scanner
**Spec**: `sdd/specs/wikitoolkit-perl-scanner.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2260, TASK-2261
**Assigned-to**: unassigned

---

## Context

With the PerlScanner fully implemented (heuristic in TASK-2260,
tree-sitter in TASK-2261), this task creates the comprehensive test
suite covering both extraction modes, import resolution, edge cases,
and the never-raise contract.

Implements spec Module 5.

---

## Scope

- Create `tests/knowledge/wiki/languages/test_perl.py`
- Test both heuristic and tree-sitter extraction modes
- Test import extraction and resolution
- Test edge cases: garbage input, empty files, multiple packages per file,
  nested subs, Corinna OO, Moose `has`
- Test scanner registration and suffix claiming
- Test `mode` property

**NOT in scope**: Implementation changes (TASK-2259/2260/2261).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/languages/test_perl.py` | CREATE | Full test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages.perl import PerlScanner  # perl.py (TASK-2260)
from parrot.knowledge.wiki.languages.base import LanguageOutline  # base.py:21
from parrot.knowledge.wiki.languages import scanner_for, scanned_suffixes  # __init__.py:46,69
from parrot.knowledge.wiki.languages import treesitter  # treesitter.py
```

### Existing Test Patterns

```python
# tests/knowledge/wiki/languages/ — existing test files for reference:
# test_rust.py, test_php.py, test_javascript.py follow the same pattern:
# - fixtures with source strings
# - test_outline_* for each construct type
# - test_never_raises with garbage input
# - test_mode_property
# - test_import_resolution
```

### Does NOT Exist

- ~~`PerlScanner.parse()`~~ — method is `outline()`, not `parse()`
- ~~`LanguageOutline.functions`~~ — no such field; use `.outline` (list[str])
- ~~`scanner_for("perl")`~~ — takes a suffix, not a name: `scanner_for(".pm")`

---

## Implementation Notes

### Test Structure

Follow existing test files. Group by concern:

```python
import textwrap
import pytest
from parrot.knowledge.wiki.languages.perl import PerlScanner
from parrot.knowledge.wiki.languages.base import LanguageOutline
from parrot.knowledge.wiki.languages import scanner_for, scanned_suffixes

@pytest.fixture
def scanner():
    return PerlScanner()

# --- Registration ---
class TestRegistration:
    def test_scanner_for_pm(self): ...
    def test_scanner_for_pl(self): ...
    def test_scanner_for_t(self): ...
    def test_suffixes_in_scanned(self): ...

# --- Heuristic mode (always available) ---
class TestHeuristic:
    def test_package_statement(self, scanner): ...
    def test_sub_declaration(self, scanner): ...
    def test_moose_has(self, scanner): ...
    def test_corinna_class(self, scanner): ...
    def test_pod_summary(self, scanner): ...
    def test_multiple_packages(self, scanner): ...
    def test_nested_sub_indentation(self, scanner): ...
    def test_use_require_imports(self, scanner): ...

# --- tree-sitter mode (skip if not installed) ---
@pytest.mark.skipif(...)
class TestTreeSitter:
    def test_sub_declaration(self, scanner): ...
    def test_corinna_class(self, scanner): ...
    def test_moose_has(self, scanner): ...

# --- Import resolution ---
class TestImportResolution:
    def test_resolve_module_name(self, scanner): ...
    def test_resolve_in_lib_dir(self, scanner): ...
    def test_resolve_unresolvable(self, scanner): ...
    def test_resolve_relative_require(self, scanner): ...

# --- Safety contract ---
class TestSafety:
    def test_never_raises_garbage(self, scanner): ...
    def test_never_raises_empty(self, scanner): ...
    def test_never_raises_binary(self, scanner): ...
```

### Test Fixtures

```python
@pytest.fixture
def moose_source():
    return textwrap.dedent("""\
        package MyApp::Model::User;
        use Moose;
        use MyApp::Schema;

        has 'name' => (is => 'ro', isa => 'Str');
        has 'email' => (is => 'rw', isa => 'Str');

        sub validate {
            my ($self) = @_;
            return 1;
        }

        sub to_hashref {
            my ($self) = @_;
            return { name => $self->name, email => $self->email };
        }

        __PACKAGE__->meta->make_immutable;
        1;
    """)

@pytest.fixture
def corinna_source():
    return textwrap.dedent("""\
        use v5.38;
        class Point {
            field $x :param;
            field $y :param;

            method coordinates () {
                return ($x, $y);
            }
        }
    """)

@pytest.fixture
def multi_package_source():
    return textwrap.dedent("""\
        package Foo;
        sub foo_method { }

        package Bar;
        sub bar_method { }
        1;
    """)

@pytest.fixture
def pod_source():
    return textwrap.dedent("""\
        =head1 NAME

        MyApp::Utils - Utility functions for MyApp

        =head1 DESCRIPTION

        This module provides common utilities.

        =cut

        package MyApp::Utils;
        sub helper { }
        1;
    """)

@pytest.fixture
def repo_paths():
    return [
        "lib/MyApp/Model/User.pm",
        "lib/MyApp/Schema.pm",
        "lib/MyApp/Controller/Auth.pm",
        "bin/app.pl",
        "t/model_user.t",
    ]
```

### Heuristic-only Testing

To force heuristic mode for testing when tree-sitter IS installed, mock
`treesitter.get_parser` to return `None`:

```python
def test_heuristic_mode_forced(scanner, moose_source, monkeypatch):
    monkeypatch.setattr(treesitter, "get_parser", lambda lang: None)
    result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
    assert any("sub validate" in line for line in result.outline)
```

### Key Constraints

- Tests must pass with AND without `tree-sitter-perl` installed
- Use `pytest.mark.skipif` for tree-sitter-only tests
- Use `monkeypatch` to force heuristic mode, not conditional imports
- All test functions are synchronous (no async)

### References in Codebase

- `tests/knowledge/wiki/languages/` — existing test files for other scanners

---

## Acceptance Criteria

- [ ] `test_perl.py` created with ≥19 test cases (per spec §4)
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/test_perl.py -v`
- [ ] Tests pass when `tree-sitter-perl` is NOT installed (heuristic tests)
- [ ] Tests pass when `tree-sitter-perl` IS installed (both mode tests)
- [ ] Never-raise contract verified with garbage, empty, and binary input
- [ ] Import resolution tested with realistic repo path fixtures
- [ ] Scanner registration verified (`scanner_for(".pm")` works)
- [ ] No linting errors: `ruff check tests/knowledge/wiki/languages/test_perl.py`

---

## Test Specification

This task IS the test specification. See the fixture and test class
structure in the Implementation Notes above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §4 for the test matrix
2. **Read existing test files** in `tests/knowledge/wiki/languages/` for patterns
3. **Read `perl.py`** to understand the exact method signatures and output format
4. **Implement** all test classes
5. **Run**: `pytest tests/knowledge/wiki/languages/test_perl.py -v`
6. **Verify** both with and without `tree-sitter-perl` if possible

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: Created `tests/knowledge/wiki/languages/test_perl.py` with 37
test cases (≥19 required) across `TestRegistration`, `TestHeuristic`
(14 tests, using the shared `force_heuristic` fixture from
`conftest.py`), `TestTreeSitter` (6 tests, `skipif` guarded on grammar
availability), module-level mode tests, `TestImportResolution` (5 tests),
and `TestSafety` (4 tests: garbage, empty, binary, and a monkeypatched
extraction failure verifying the never-raise degrade-to-empty contract).
All 37 pass; full `tests/knowledge/wiki/languages/` suite passes
(183 passed, no regressions). `ruff check` clean on both the test file
and `perl.py`. Verified locally with `tree-sitter-perl` installed in the
dev venv (temporarily, for cross-checking node types across TASK-2261)
so both `TestHeuristic` (forced) and `TestTreeSitter` (native) paths
actually executed rather than one being skipped.

**Deviations from spec**: none.
