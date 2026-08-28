# TASK-2551: Regression test — wikitoolkit import chain deps are core

**Feature**: FEAT-471 — Add rustworkx (and the wikitoolkit import-path deps) as real core dependencies
**Spec**: `sdd/specs/add-rustworkx-dependency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2549
**Assigned-to**: unassigned

---

## Context

Guard against the defect recurring (a new module-level third-party import on
the `wikitoolkit` chain declared only in an extra). A static "declared vs.
imported" check runs in the normal CI venv without needing a separate bare
environment. Implements spec §3 Module 4 and §4 Unit Tests.

---

## Scope

- Create `tests/knowledge/test_wiki_cli_core_deps.py` with three tests:
  1. `test_wiki_cli_imports_in_subprocess` — `subprocess.run([sys.executable,
     "-c", "import parrot.knowledge.wiki.cli"])` returns exit code 0.
  2. `test_wiki_chain_third_party_imports_are_core_deps` — parse
     `packages/ai-parrot/pyproject.toml` with `tomllib`; for each file in
     `CHAIN_FILES` walk module-level `ast.Import` / `ast.ImportFrom` nodes
     (top-level statements only, skip anything inside `if TYPE_CHECKING:`,
     `try:` or functions); collect top-level module names; drop stdlib
     (`sys.stdlib_module_names`), relative imports, `parrot`/`parrot_tools`,
     and `navconfig`/`asyncdb`/`datamodel`-style first-party-transitive names
     via an explicit `KNOWN_TRANSITIVE` allow-set only if needed; assert every
     remaining name, normalised via `NAME_MAP` (`{"rustworkx","networkx",
     "pathspec","aiosqlite","orjson"}` map to themselves), appears in core
     `dependencies` — not merely in an extra.
  3. `test_graphindex_extra_has_no_duplicates_of_core` — no package name appears
     in both core `dependencies` and `optional-dependencies["graphindex"]`.
- Normalise requirement strings to a package name: strip version specifiers,
  extras and markers; compare case-insensitively with `-`/`_` folded.

**NOT in scope**: changing any `pyproject.toml` (TASK-2549), `uv.lock`
(TASK-2550), docs (TASK-2552), or any file under `packages/*/src`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/test_wiki_cli_core_deps.py` | CREATE | three regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-28 against `dev` @ `d172e4d56`.

### Chain files (all exist — verified)
```python
CHAIN_FILES = [
    "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
    "packages/ai-parrot/src/parrot/knowledge/wiki/documents.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py",
]
```

### Verified module-level third-party imports on the chain (expected findings)
```python
# signals.py:30, assemble.py:17            import rustworkx
# communities.py:31-32                     import networkx as nx / import rustworkx
# builder.py:26                            import pathspec
# sqlite_reader.py:23-25                   import aiosqlite / import orjson / import rustworkx as rx
```
The chain files ALSO import other third-party packages (e.g. `pydantic`,
`aiohttp`, `numpy`, `navconfig`) — read each file's header before finalising
the allow-list; anything not in core `dependencies` and not transitively
first-party must be surfaced by the test, that is the point.

### pyproject structure (after TASK-2549)
```toml
# packages/ai-parrot/pyproject.toml
[project]
dependencies = [ ..., "rustworkx>=0.15", "networkx>=3.0", "pathspec>=0.12", "aiosqlite>=0.17", "orjson>=3.9" ]
[project.optional-dependencies]
graphindex = [ "tree-sitter>=0.23", "tree-sitter-languages>=1.10" ]
```

### Existing test layout
- `tests/knowledge/pageindex/`, `tests/knowledge/wiki/` exist; `tests/knowledge/` has no `conftest.py` requirement for this test.
- Tests run with `source .venv/bin/activate && pytest tests/knowledge/test_wiki_cli_core_deps.py -v`.

### Does NOT Exist
- ~~`tests/knowledge/test_wiki_cli_core_deps.py`~~ — this task creates it.
- ~~a helper like `parrot.utils.deps.declared_dependencies()`~~ — none; parse with `tomllib` directly.
- ~~`packaging` guaranteed importable~~ — do not depend on it; normalise requirement strings with a small regex (`re.split(r"[<>=!~;\[ ]", req, 1)[0]`).
- ~~`importlib.metadata.packages_distributions()` mapping for every module~~ — not reliable for the check; use the explicit `NAME_MAP`.

---

## Implementation Notes

### Pattern to Follow
```python
# tests/knowledge/test_wiki_cli_core_deps.py
import ast, re, subprocess, sys, tomllib
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "packages/ai-parrot/pyproject.toml"
CHAIN_FILES = [...]                       # from contract above
NAME_MAP = {"rustworkx": "rustworkx", "networkx": "networkx", "pathspec": "pathspec",
            "aiosqlite": "aiosqlite", "orjson": "orjson"}   # import name -> dist name

def _req_name(req: str) -> str:
    return re.split(r"[<>=!~;\[ ]", req.strip(), 1)[0].lower().replace("_", "-")

def _module_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:                 # top-level only: excludes try/if/def bodies
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names
```

### Key Constraints
- Pure-stdlib test (`ast`, `tomllib`, `subprocess`); no new test deps.
- Subprocess test must use `sys.executable` and inherit the venv.
- Keep the test deterministic — no network, no `uv` calls.
- Google-style docstrings on each test.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/test_wiki_cli_core_deps.py -v` — 3 passed
- [ ] the test FAILS if one of the five deps is moved back into the `graphindex` extra (verify manually once, then revert)
- [ ] `ruff check tests/knowledge/test_wiki_cli_core_deps.py` clean
- [ ] no files under `packages/*/src` modified

---

## Test Specification

```python
def test_wiki_cli_imports_in_subprocess():
    """`import parrot.knowledge.wiki.cli` succeeds in a fresh interpreter."""
    r = subprocess.run([sys.executable, "-c", "import parrot.knowledge.wiki.cli"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_wiki_chain_third_party_imports_are_core_deps():
    """Every third-party module-level import on the wikitoolkit chain is a core dep."""
    ...

def test_graphindex_extra_has_no_duplicates_of_core():
    """No package is declared both in core dependencies and the graphindex extra."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2549 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the header of each CHAIN_FILE before writing the allow-list
4. **Update status** in `sdd/tasks/index/add-rustworkx-dependency.json` → `"in-progress"`
5. **Implement** following the scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2551-wiki-cli-core-deps-regression-test.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
