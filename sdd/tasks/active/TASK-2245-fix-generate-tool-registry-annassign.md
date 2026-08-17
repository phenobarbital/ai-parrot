# TASK-2245: Fix `generate_tool_registry.py` to recognize `ast.AnnAssign` registries

**Feature**: FEAT-427 — Fix `generate_tool_registry.py` AnnAssign Blindspot
**Spec**: `sdd/specs/fix-generate-tool-registry-annassign.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`scripts/generate_tool_registry.py` scans `parrot_tools/` and
`parrot_loaders/` for tool/loader classes and keeps `TOOL_REGISTRY` /
`LOADER_REGISTRY` in each package's `__init__.py` in sync. Both variables
are declared as annotated assignments (`TOOL_REGISTRY: dict[str, str] = {...}`),
which Python's AST represents as `ast.AnnAssign`, not `ast.Assign`. Three
functions in the script only match `ast.Assign`, so `--check` mode
unconditionally reports both registries as stale (a permanent false
positive across the whole monorepo) and the plain write mode silently
no-ops instead of rewriting the file. This was discovered as a known
issue during FEAT-426 (research-tools-for-agents) code review. Implements
spec §2 (Architectural Design) and §3 Module 1 + Module 2.

---

## Scope

- Add a private helper `_assign_target_and_value(node)` to
  `scripts/generate_tool_registry.py` that normalizes both `ast.Assign`
  and `ast.AnnAssign` nodes into a `(name, value_node)` tuple (or
  `(None, None)` if the node doesn't match, has a non-`Name` target, or
  — for `AnnAssign` — has no value).
- Rewire `scan_exports()` (line 170), `read_existing_registry()`
  (line 224), and the rewrite-search loop inside `update_init_file()`
  (line 290) to use this helper instead of their inline
  `isinstance(node, ast.Assign)` + `node.targets` iteration.
- Create `tests/scripts/test_generate_tool_registry.py` (new directory
  and file) with the unit tests listed in spec §4, including the
  regression test against the real, current
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py` and
  `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` files.

**NOT in scope**:
- Changing `TOOL_BASE_CLASSES` / `LOADER_BASE_CLASSES` exclusion lists.
- Changing `scan_classes()` / `_class_to_key()` naming-convention logic.
- Wiring `--check` into any GitHub Actions workflow.
- Adding a new CLI flag.
- Modifying `format_registry()` (already emits the correct annotated
  form — see spec §7 Known Risks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/generate_tool_registry.py` | MODIFY | Add `_assign_target_and_value()`; rewire the 3 call sites |
| `tests/scripts/test_generate_tool_registry.py` | CREATE | Unit tests for the fix (new `tests/scripts/` dir) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import ast          # scripts/generate_tool_registry.py:19
import argparse      # scripts/generate_tool_registry.py:18
import sys           # scripts/generate_tool_registry.py:20
from pathlib import Path              # scripts/generate_tool_registry.py:21
from typing import Optional           # scripts/generate_tool_registry.py:22
```

### Existing Signatures to Use
```python
# scripts/generate_tool_registry.py:137
def scan_exports(
    pkg_dir: Path,
    pkg_name: str,
    names: list[str],
) -> dict[str, str]:
    ...
    for node in ast.iter_child_nodes(tree):          # line 167
        if isinstance(node, ast.FunctionDef) and node.name in names:   # line 168
            registry[node.name] = f"{module_path}.{node.name}"
        elif isinstance(node, ast.Assign):            # line 170 — REPLACE with helper call
            for target in node.targets:                # line 171
                if isinstance(target, ast.Name) and target.id in names:  # line 172
                    registry[target.id] = f"{module_path}.{target.id}"

# scripts/generate_tool_registry.py:205
def read_existing_registry(init_file: Path, var_name: str) -> Optional[dict[str, str]]:
    if not init_file.exists():          # line 215
        return None
    try:
        tree = ast.parse(init_file.read_text(encoding="utf-8"))   # line 219
    except SyntaxError:
        return None
    for node in ast.walk(tree):                        # line 223
        if isinstance(node, ast.Assign):                # line 224 — REPLACE with helper call
            for target in node.targets:                  # line 225
                if isinstance(target, ast.Name) and target.id == var_name:  # line 226
                    try:
                        return ast.literal_eval(node.value)   # line 228
                    except (ValueError, TypeError):
                        return None
    return None                                          # line 231

# scripts/generate_tool_registry.py:237
def update_init_file(
    init_file: Path,
    var_name: str,
    new_registry: dict[str, str],
    dry_run: bool = False,
) -> tuple[bool, list[str]]:
    existing = read_existing_registry(init_file, var_name)    # line 254
    if existing is None:                                        # line 255
        existing = {}
    merged = dict(new_registry)                                 # line 259
    for key, val in existing.items():                           # line 260
        if key not in merged:
            merged[key] = val
    if merged == existing:                                       # line 265
        return False, []
    diff: list[str] = []                                          # line 269
    added = set(merged.keys()) - set(existing.keys())             # line 270
    removed = set(existing.keys()) - set(merged.keys())           # line 271
    changed_vals = {                                               # line 272
        k for k in set(merged.keys()) & set(existing.keys()) if merged[k] != existing[k]
    }
    for k in sorted(added):                                        # line 276
        diff.append(f"  + {k}: {merged[k]}")
    for k in sorted(removed):                                      # line 278
        diff.append(f"  - {k}: {existing[k]}")
    for k in sorted(changed_vals):                                 # line 280
        diff.append(f"  ~ {k}: {existing[k]} → {merged[k]}")
    if not dry_run:                                                 # line 283
        content = init_file.read_text(encoding="utf-8")             # line 285
        tree = ast.parse(content)                                    # line 286
        for node in ast.walk(tree):                                   # line 289
            if isinstance(node, ast.Assign):                           # line 290 — REPLACE with helper call
                for target in node.targets:                             # line 291
                    if isinstance(target, ast.Name) and target.id == var_name:  # line 292
                        lines = content.splitlines(keepends=True)         # line 294
                        start_line = node.lineno - 1                       # line 295 (0-indexed)
                        end_line = node.end_lineno                         # line 296 (exclusive)
                        new_lines = [f"{var_name}: dict[str, str] = {{\n"]  # line 299
                        for key, path in merged.items():                    # line 300
                            new_lines.append(f'    "{key}": "{path}",\n')
                        new_lines.append("}\n")                              # line 302
                        lines[start_line:end_line] = new_lines                # line 305
                        init_file.write_text("".join(lines), encoding="utf-8")  # line 306
                        return True, diff
    return bool(diff), diff                                            # line 309

# scripts/generate_tool_registry.py:181 — already emits ANNOTATED form, do NOT modify
def format_registry(name: str, entries: dict[str, str], docstring: str) -> str:
    lines = [f'"""\n{docstring}\n"""', "", f"{name}: dict[str, str] = {{"]   # line 192
    ...
```

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12
TOOL_REGISTRY: dict[str, str] = {   # ast.AnnAssign — the exact shape the fix must parse
    ...
}
__all__ = ["__version__", "TOOL_REGISTRY"]   # line 152

# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py:9
LOADER_REGISTRY: dict[str, str] = {   # ast.AnnAssign — the exact shape the fix must parse
    ...
}
__all__ = ["__version__", "LOADER_REGISTRY"]   # line 45
```

### Does NOT Exist
- ~~`tests/scripts/test_generate_tool_registry.py`~~ — does not exist yet; this task creates it, along with the `tests/scripts/` directory (does not currently exist anywhere in the repo).
- ~~`scripts.sdd.*`~~ — unrelated package; `generate_tool_registry.py` is a standalone top-level script under `scripts/`, do not import anything from `scripts/sdd/`.
- ~~`ast.AnnAssign.targets`~~ (plural) — does not exist. `ast.AnnAssign` has a single `.target` attribute (singular). Only `ast.Assign` has `.targets` (a list).
- ~~A `--fix-annassign` CLI flag~~ — not part of this task; no new argparse flag is added.

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/generate_tool_registry.py — new helper, placed near the top
# of the "AST-based class scanning" section, before scan_exports()
def _assign_target_and_value(
    node: ast.AST,
) -> tuple[Optional[str], Optional[ast.expr]]:
    """Normalize an ast.Assign or ast.AnnAssign into (name, value).

    Handles both the unannotated form (``NAME = {...}``, ``ast.Assign``
    with a ``targets`` list) and the annotated form
    (``NAME: dict[str, str] = {...}``, ``ast.AnnAssign`` with a single
    ``target``). Returns ``(None, None)`` when the node is neither, when
    the target is not a plain ``ast.Name``, or when an ``AnnAssign`` has
    no right-hand-side value (a bare annotation like ``NAME: int``).

    Args:
        node: An AST node encountered while walking a module.

    Returns:
        ``(target_name, value_node)`` or ``(None, None)``.
    """
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id, node.value
        return None, None
    if isinstance(node, ast.AnnAssign):
        if node.value is None or not isinstance(node.target, ast.Name):
            return None, None
        return node.target.id, node.value
    return None, None
```

Use it at each call site, e.g. in `read_existing_registry()`:

```python
for node in ast.walk(tree):
    name, value = _assign_target_and_value(node)
    if name == var_name and value is not None:
        try:
            return ast.literal_eval(value)
        except (ValueError, TypeError):
            return None
return None
```

Apply the analogous rewiring in `scan_exports()` (matching against
`names` instead of a single `var_name`) and in the `update_init_file()`
rewrite loop (same `var_name == name` check, then use `node.lineno` /
`node.end_lineno` exactly as before — both `ast.Assign` and
`ast.AnnAssign` expose these attributes identically).

### Key Constraints
- Do not change the on-disk format `format_registry()` produces — it
  already emits `NAME: dict[str, str] = {...}` and must keep doing so.
- Preserve identical behavior for the plain `ast.Assign` (no annotation)
  case — this is a regression-sensitive change.
- No new third-party dependency; stdlib `ast` only.
- Follow the script's existing style: module-level functions, type
  hints, no classes.

### References in Codebase
- `scripts/generate_tool_registry.py` — the file being fixed, read it in
  full before editing (422 lines).
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — real-world
  annotated registry to validate against.
- `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` — same,
  second real-world file.

---

## Acceptance Criteria

- [ ] `_assign_target_and_value()` added and used by all three call sites
      (`scan_exports`, `read_existing_registry`, `update_init_file`'s
      rewrite loop).
- [ ] `python scripts/generate_tool_registry.py --check` exits `0`
      against the current repo state.
- [ ] `python scripts/generate_tool_registry.py` (no flags, nothing to
      change) exits `0` and prints "All registries are up to date."
- [ ] All new tests pass: `pytest tests/scripts/test_generate_tool_registry.py -v`
- [ ] No linting errors: `ruff check scripts/generate_tool_registry.py`
- [ ] `from scripts.generate_tool_registry import _assign_target_and_value`
      resolves (or equivalent import path used by the new test file).

---

## Test Specification

```python
# tests/scripts/test_generate_tool_registry.py
import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_tool_registry as gtr  # noqa: E402


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


def test_read_existing_registry_annassign(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(ANNASSIGN_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result == {"foo": "pkg.mod.Foo"}


def test_read_existing_registry_plain_assign_unchanged(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(PLAIN_ASSIGN_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result == {"foo": "pkg.mod.Foo"}


def test_read_existing_registry_bare_annotation_no_value(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(BARE_ANNOTATION_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result is None


def test_update_init_file_rewrites_annassign_in_place(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(ANNASSIGN_SOURCE)
    new_registry = {"foo": "pkg.mod.Foo", "bar": "pkg.mod.Bar"}
    changed, diff = gtr.update_init_file(init_file, "TOOL_REGISTRY", new_registry)
    assert changed is True
    new_content = init_file.read_text()
    assert "TOOL_REGISTRY: dict[str, str] = {" in new_content
    assert '"bar": "pkg.mod.Bar"' in new_content


def test_scan_exports_annassign(tmp_path):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "mod.py").write_text(
        'LOADER_MAPPING: dict[str, str] = {"x": "y"}\n'
    )
    result = gtr.scan_exports(pkg_dir, "pkg", ["LOADER_MAPPING"])
    assert result == {"LOADER_MAPPING": "pkg.mod.LOADER_MAPPING"}


def test_check_mode_clean_on_current_repo_files():
    tools_scanned = gtr.scan_classes(
        gtr.TOOLS_PKG_DIR, gtr.TOOL_SUFFIXES, gtr.TOOL_BASE_CLASSES, "parrot_tools"
    )
    changed, _diff = gtr.update_init_file(
        gtr.TOOLS_INIT, "TOOL_REGISTRY", tools_scanned, dry_run=True
    )
    assert changed is False

    loaders_scanned = gtr.scan_classes(
        gtr.LOADERS_PKG_DIR, gtr.LOADER_SUFFIXES, gtr.LOADER_BASE_CLASSES, "parrot_loaders"
    )
    factory_exports = gtr.scan_exports(
        gtr.LOADERS_PKG_DIR, "parrot_loaders", ["get_loader_class", "LOADER_MAPPING"]
    )
    loaders_scanned.update(factory_exports)
    changed, _diff = gtr.update_init_file(
        gtr.LOADERS_INIT, "LOADER_REGISTRY", loaders_scanned, dry_run=True
    )
    assert changed is False


def test_check_cli_exits_zero_on_repo():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "generate_tool_registry.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fix-generate-tool-registry-annassign.spec.md` for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — read `scripts/generate_tool_registry.py`
   in full before editing; confirm line numbers still match (the file may
   have drifted since this task was written).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met, including running the
   `--check` CLI against the real repo tree.
7. **Move this file** to `sdd/tasks/completed/TASK-2245-fix-generate-tool-registry-annassign.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
