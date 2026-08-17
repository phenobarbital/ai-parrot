---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fix `generate_tool_registry.py` AnnAssign Blindspot

**Feature ID**: FEAT-427
**Date**: 2026-08-17
**Author**: Jesus (filed as a follow-up from FEAT-426 code review)
**Status**: approved
**Target version**: n/a (internal dev tooling)

---

## 1. Motivation & Business Requirements

### Problem Statement

`scripts/generate_tool_registry.py` scans `parrot_tools/` and
`parrot_loaders/` for `*Tool`/`*Toolkit`/`*Loader` classes and keeps
`TOOL_REGISTRY` / `LOADER_REGISTRY` in each package's `__init__.py` in
sync. `--check` mode is meant to be wired into CI as the drift gate for
these registries.

Both registry variables are declared as **annotated assignments**:

```python
TOOL_REGISTRY: dict[str, str] = { ... }      # packages/ai-parrot-tools/src/parrot_tools/__init__.py:12
LOADER_REGISTRY: dict[str, str] = { ... }    # packages/ai-parrot-loaders/src/parrot_loaders/__init__.py:9
```

which the Python AST represents as `ast.AnnAssign`, not `ast.Assign`.
Three functions in the script only pattern-match `ast.Assign`:

- `scan_exports()` — `scripts/generate_tool_registry.py:170`
- `read_existing_registry()` — `scripts/generate_tool_registry.py:224`
- `update_init_file()` (the in-place rewrite branch) — `scripts/generate_tool_registry.py:290`

Consequence, verified during FEAT-426 (research-tools-for-agents) review:

1. `read_existing_registry()` always returns `None` for both
   `__init__.py` files → treated as `existing = {}`.
2. `update_init_file()` therefore reports **every** scanned entry as
   newly `added` (never `changed`/`unchanged`), so `--check` unconditionally
   reports both registries as stale — a permanent false positive for the
   *entire monorepo*, not specific to any one feature's tools.
3. The write branch (no `--check`/`--dry-run`) walks the same AST via
   `ast.Assign` at line 290, finds no match, and silently falls through to
   `return bool(diff), diff` **without ever writing the file** — so even a
   plain `python scripts/generate_tool_registry.py` (no flags) reports
   changes but does not apply them.

This was discovered as a known issue while implementing FEAT-426: the
generator's own scan output for the 3 new research-tools entries had to
be hand-verified and hand-added to `parrot_tools/__init__.py` because
neither `--check` nor the plain write mode worked.

### Goals
- `read_existing_registry()` recognizes `TOOL_REGISTRY: dict[str, str] = {...}`
  / `LOADER_REGISTRY: dict[str, str] = {...}` (an `ast.AnnAssign` whose
  `target` is an `ast.Name` matching `var_name`) exactly as it already
  recognizes the unannotated form.
- `update_init_file()`'s rewrite branch (line ~290) finds and replaces the
  same annotated assignment in place, preserving the `: dict[str, str]`
  annotation in the rewritten source (matching `format_registry()`'s own
  output shape at line 192, which already emits the annotated form).
- `scan_exports()` recognizes annotated constant exports the same way, for
  parity (`LOADER_MAPPING`, or any future annotated export named in the
  `names` list).
- After the fix, `python scripts/generate_tool_registry.py --check` exits
  `0` against the current (already-correct) contents of both
  `parrot_tools/__init__.py` and `parrot_loaders/__init__.py` — i.e. it
  stops reporting a stale registry when the file is actually up to date.
- The plain write mode (no flags) successfully rewrites the registry
  in place when entries genuinely differ, instead of silently no-op'ing.

### Non-Goals (explicitly out of scope)
- No change to `TOOL_BASE_CLASSES` / `LOADER_BASE_CLASSES` exclusion lists.
- No change to the naming-convention scanning (`scan_classes`,
  `_class_to_key`) — this spec is only about the `Assign` vs `AnnAssign`
  parsing blindspot.
- No change to CI workflow wiring (this fixes the script itself; whether
  `--check` is actually invoked from a GitHub Actions workflow is a
  separate concern, not addressed here).
- Not retroactively re-validating every existing package's registry
  contents beyond the two affected here (`parrot_tools`, `parrot_loaders`)
  — if other `__init__.py` files in the monorepo use annotated registry
  assignments and are affected the same way, they are fixed for free by
  this change but are not individually audited by this spec.

---

## 2. Architectural Design

### Overview

Make the three `isinstance(node, ast.Assign)` checks in
`scripts/generate_tool_registry.py` also accept `ast.AnnAssign`, and
extract the assignment target/value uniformly for both node types. An
`ast.AnnAssign` differs from `ast.Assign` in two structural ways that the
fix must account for:

1. `node.targets` (list) vs `node.target` (single node) — `AnnAssign` only
   ever has one target.
2. `node.value` can legitimately be `None` on an `AnnAssign` (a bare
   `x: int` with no value) — the existing code already assumes a
   non-`None` `.value` when calling `ast.literal_eval(node.value)`; guard
   against `None` explicitly rather than letting `ast.literal_eval` raise
   on `None` uncaught (it's already wrapped in
   `except (ValueError, TypeError)` at `read_existing_registry` line 229,
   but the new `AnnAssign` path must route through the same guarded call,
   not bypass it).

The cleanest fix is a small helper that normalizes both node shapes into
`(target_name: str | None, value_node: ast.expr | None)` and is used at
all three call sites, rather than duplicating the `isinstance` branching
three times with subtly different target-extraction logic.

### Component Diagram
```
scan_exports() ──┐
read_existing_registry() ──┼──→ _assign_target_and_value(node) → (name, value_node)
update_init_file() ──┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/generate_tool_registry.py::scan_exports` | modify | add `ast.AnnAssign` branch via shared helper |
| `scripts/generate_tool_registry.py::read_existing_registry` | modify | add `ast.AnnAssign` branch via shared helper |
| `scripts/generate_tool_registry.py::update_init_file` | modify | add `ast.AnnAssign` branch via shared helper in the rewrite-search loop |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | verify only | `TOOL_REGISTRY: dict[str, str] = {...}` at line 12 must round-trip through `--check` as clean after the fix |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | verify only | `LOADER_REGISTRY: dict[str, str] = {...}` at line 9 must round-trip through `--check` as clean after the fix |

### Data Models
Not applicable — this is a script-internal AST-parsing fix, no new data
models.

### New Public Interfaces

```python
# scripts/generate_tool_registry.py — new private helper
def _assign_target_and_value(
    node: ast.AST,
) -> tuple[str, ast.expr] | tuple[None, None]:
    """Normalize an ast.Assign or ast.AnnAssign into (name, value).

    Returns (None, None) for any other node type, or for an AnnAssign
    with no value (bare annotation, no RHS) or a non-Name target.
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: AnnAssign-aware helper + three call-site fixes
- **Path**: `scripts/generate_tool_registry.py`
- **Responsibility**: Add `_assign_target_and_value()` and rewire
  `scan_exports()`, `read_existing_registry()`, and the rewrite-search
  loop inside `update_init_file()` to use it instead of hand-rolled
  `isinstance(node, ast.Assign)` + `node.targets` iteration.
- **Depends on**: none (single-file change).

### Module 2: Regression tests
- **Path**: `tests/scripts/test_generate_tool_registry.py` (new file —
  see §6 Does NOT Exist; no test file currently covers this script)
- **Responsibility**: Cover the annotated-assignment path for all three
  functions against both the unannotated (regression-proof) and
  annotated (bug-fix-proof) forms, plus the "bare annotation, no value"
  edge case.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_read_existing_registry_annassign` | Module 1 | `TOOL_REGISTRY: dict[str, str] = {...}` is parsed correctly |
| `test_read_existing_registry_plain_assign_unchanged` | Module 1 | `TOOL_REGISTRY = {...}` (no annotation) still parses — regression guard |
| `test_read_existing_registry_bare_annotation_no_value` | Module 1 | `TOOL_REGISTRY: dict[str, str]` (no `= {...}`) returns `None`, does not raise |
| `test_update_init_file_rewrites_annassign_in_place` | Module 1 | Rewrite branch replaces an annotated assignment's `{...}` body and preserves the `: dict[str, str]` annotation in the new source |
| `test_scan_exports_annassign` | Module 1 | An annotated module-level constant matching a requested export name is found |
| `test_check_mode_clean_on_current_repo_files` | Module 2 | Running `read_existing_registry` + `scan_classes` + `update_init_file(dry_run=True)` against the real, current `parrot_tools/__init__.py` and `parrot_loaders/__init__.py` reports **no** changes (i.e. reproduces the exact FEAT-426-review false positive and proves it's gone) |

### Integration Tests
| Test | Description |
|---|---|
| `test_check_cli_exits_zero_on_repo` | Invoke `python scripts/generate_tool_registry.py --check` as a subprocess against the actual repo tree and assert exit code `0` |

### Test Data / Fixtures
```python
# tests/scripts/test_generate_tool_registry.py
import ast
import textwrap

ANNASSIGN_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY: dict[str, str] = {
        "foo": "pkg.mod.Foo",
    }
    ''')

PLAIN_ASSIGN_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY = {
        "foo": "pkg.mod.Foo",
    }
    ''')

BARE_ANNOTATION_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY: dict[str, str]
    ''')
```

---

## 5. Acceptance Criteria

- [ ] `_assign_target_and_value()` added to
      `scripts/generate_tool_registry.py`, handling `ast.Assign` (single
      or multiple targets — only `ast.Name` targets matter here),
      `ast.AnnAssign` with a `.value`, and `ast.AnnAssign` with
      `.value is None` (returns `(None, None)` for the last case).
- [ ] `scan_exports()`, `read_existing_registry()`, and the rewrite loop
      in `update_init_file()` all use the helper instead of inline
      `isinstance(node, ast.Assign)` checks.
- [ ] `python scripts/generate_tool_registry.py --check` exits `0`
      against the current repo state (both `parrot_tools/__init__.py`
      and `parrot_loaders/__init__.py` are correctly recognized as
      up to date).
- [ ] `python scripts/generate_tool_registry.py` (plain write mode) with
      no pending changes exits `0` and prints "All registries are up to
      date." (does not silently no-op while claiming there's a diff).
- [ ] The rewrite branch of `update_init_file()`, when there IS a real
      diff, preserves the `VAR_NAME: dict[str, str] = {...}` annotation
      in the file it writes (does not regress to unannotated form).
- [ ] All new unit tests pass:
      `pytest tests/scripts/test_generate_tool_registry.py -v`
- [ ] No regression for the pre-existing unannotated-assignment path
      (covered by `test_read_existing_registry_plain_assign_unchanged`).
- [ ] `ruff check scripts/generate_tool_registry.py` clean.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
import ast          # scripts/generate_tool_registry.py:19
import argparse      # scripts/generate_tool_registry.py:18
import sys           # scripts/generate_tool_registry.py:20
from pathlib import Path              # scripts/generate_tool_registry.py:21
from typing import Optional           # scripts/generate_tool_registry.py:22
```

### Existing Class/Function Signatures
```python
# scripts/generate_tool_registry.py
def scan_exports(
    pkg_dir: Path,
    pkg_name: str,
    names: list[str],
) -> dict[str, str]:  # line 137
    ...
    for node in ast.iter_child_nodes(tree):          # line 167
        if isinstance(node, ast.FunctionDef) and node.name in names:   # line 168
            registry[node.name] = f"{module_path}.{node.name}"
        elif isinstance(node, ast.Assign):            # line 170 — BLINDSPOT
            for target in node.targets:                # line 171
                if isinstance(target, ast.Name) and target.id in names:  # line 172
                    registry[target.id] = f"{module_path}.{target.id}"

def read_existing_registry(init_file: Path, var_name: str) -> Optional[dict[str, str]]:  # line 205
    ...
    for node in ast.walk(tree):                        # line 223
        if isinstance(node, ast.Assign):                # line 224 — BLINDSPOT
            for target in node.targets:                  # line 225
                if isinstance(target, ast.Name) and target.id == var_name:  # line 226
                    try:
                        return ast.literal_eval(node.value)   # line 228
                    except (ValueError, TypeError):
                        return None
    return None                                          # line 231

def update_init_file(
    init_file: Path,
    var_name: str,
    new_registry: dict[str, str],
    dry_run: bool = False,
) -> tuple[bool, list[str]]:  # line 237
    ...
    if not dry_run:
        content = init_file.read_text(encoding="utf-8")   # line 285
        tree = ast.parse(content)                          # line 286
        for node in ast.walk(tree):                         # line 289
            if isinstance(node, ast.Assign):                 # line 290 — BLINDSPOT
                for target in node.targets:                   # line 291
                    if isinstance(target, ast.Name) and target.id == var_name:  # line 292
                        lines = content.splitlines(keepends=True)   # line 294
                        start_line = node.lineno - 1          # line 295 (0-indexed)
                        end_line = node.end_lineno             # line 296 (exclusive)
                        new_lines = [f"{var_name}: dict[str, str] = {{\n"]  # line 299
                        for key, path in merged.items():        # line 300
                            new_lines.append(f'    "{key}": "{path}",\n')
                        new_lines.append("}\n")                  # line 302
                        lines[start_line:end_line] = new_lines    # line 305
                        init_file.write_text("".join(lines), encoding="utf-8")  # line 306
                        return True, diff
    return bool(diff), diff                                    # line 309

def format_registry(name: str, entries: dict[str, str], docstring: str) -> str:  # line 181
    # Already emits the ANNOTATED form:
    lines = [f'"""\n{docstring}\n"""', "", f"{name}: dict[str, str] = {{"]  # line 192
    ...
```

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str] = {   # line 12 — ast.AnnAssign, not ast.Assign
    ...
}
__all__ = ["__version__", "TOOL_REGISTRY"]   # line 152
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py
LOADER_REGISTRY: dict[str, str] = {   # line 9 — ast.AnnAssign, not ast.Assign
    ...
}
__all__ = ["__version__", "LOADER_REGISTRY"]   # line 45
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_assign_target_and_value()` | `scan_exports()` | replaces lines 170-173 | `scripts/generate_tool_registry.py:170` |
| `_assign_target_and_value()` | `read_existing_registry()` | replaces lines 224-230 | `scripts/generate_tool_registry.py:224` |
| `_assign_target_and_value()` | `update_init_file()` rewrite loop | replaces lines 290-292 | `scripts/generate_tool_registry.py:290` |

### Does NOT Exist (Anti-Hallucination)
- ~~`tests/scripts/test_generate_tool_registry.py`~~ — does not exist yet;
  this spec creates it. There is currently NO test file covering
  `scripts/generate_tool_registry.py` anywhere in the repo (verified: no
  `tests/scripts/` directory exists at the time of writing this spec).
- ~~`scripts.sdd.*` helpers~~ — unrelated; `generate_tool_registry.py` is
  a standalone top-level script under `scripts/`, not part of the
  `scripts/sdd/` package used by the SDD tooling itself. Do not import
  from `scripts.sdd`.
- ~~A `--fix-annassign` CLI flag~~ — not part of this spec; the fix is
  transparent (no new flag), the existing `--check`/`--dry-run`/plain
  modes just start working correctly.
- ~~`ast.AnnAssign.targets` (plural)~~ — does not exist; `AnnAssign` has a
  single `.target` (singular), unlike `ast.Assign.targets` (plural list).
  This is the exact structural difference the fix must account for.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the fix minimal and localized to
  `scripts/generate_tool_registry.py` — no new module, no new package.
- The helper should be a plain function (no classes) matching the
  existing script's style (module-level `def`, no framework
  dependencies beyond stdlib `ast`/`argparse`/`pathlib`/`typing`).
- Preserve exact existing behavior for the unannotated-`Assign` case —
  every existing test/usage of `TOOL_REGISTRY = {...}` (plain, no
  annotation) anywhere in the repo must keep working identically.

### Known Risks / Gotchas
- `ast.AnnAssign.value` can be `None` (bare `x: int` annotation with no
  assignment) — must not call `ast.literal_eval(None)` or iterate
  `None.targets`; the helper must return `(None, None)` for this case
  and callers must skip it exactly like they'd skip a non-matching node.
- `ast.AnnAssign.target` is a single node, not a list — do not wrap it in
  a loop mimicking `ast.Assign.targets` iteration; extract the single
  target directly.
- `format_registry()` (line 181-199) already emits `NAME: dict[str, str] = {`
  — i.e. brand-new `__init__.py` files this script has ever *generated*
  are already annotated. This means the bug has silently affected every
  package this script manages since its introduction, not just the two
  touched by FEAT-426. Do not "fix" `format_registry()` — it is already
  correct; only the three *reading*/*rewriting* call sites are behind.

### External Dependencies
None — stdlib `ast` only, no new dependency.

---

## 8. Open Questions

- [x] Should this land as `type: hotfix` (base `main`) given it affects
      every PR's CI gate? — *Resolved by filer*: No. This is internal
      dev tooling (`scripts/generate_tool_registry.py`), not a
      production code path; it is not deployed via `main` releases.
      `type: feature`, `base_branch: dev` is correct — same as any other
      tooling fix that lands through the normal `dev` integration branch.
- [ ] Should `--check` actually be wired into a CI workflow
      (e.g. `.github/workflows/*.yml`) as a blocking gate now that it
      works correctly? — *Owner: repo maintainer* — out of scope for this
      spec (see Non-Goals); worth a separate follow-up once this fix is
      verified in practice.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-17 | Jesus | Initial draft — filed as a follow-up from FEAT-426 code review finding |
