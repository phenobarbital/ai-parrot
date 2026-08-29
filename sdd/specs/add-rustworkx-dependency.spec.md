---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Add rustworkx (and the wikitoolkit import-path deps) as real core dependencies

**Feature ID**: FEAT-471
**Date**: 2026-08-28
**Author**: Jesus Lara
**Status**: draft
**Target version**: next ai-parrot patch release
**Proposal**: `sdd/proposals/add-rustworkx-dependency.proposal.md` (research audit: `sdd/state/FEAT-471/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` — the console script that backs the codebase knowledge graph, the
`/parrotwiki` command and the `wikitoolkit` MCP server in `.mcp.json` — ships in
core `ai-parrot` (`project.scripts`, `packages/ai-parrot/pyproject.toml:147`) but
crashes with `ModuleNotFoundError: rustworkx` on **every** subcommand after a
plain `uv pip install ai-parrot`, and again after a bare `uv sync`.

`rustworkx` is not a transitive dependency: it is declared exactly once, in the
optional `graphindex` extra (`pyproject.toml:213`, re-exported by `wiki`), and
nothing else in `uv.lock` depends on it. `uv sync` produces an *exact*
environment and the workspace root declares no default extras, so it removes
the package. The runtime import chain that pulls it in is
`wiki/cli.py:49 → wiki/documents.py:31 → graphindex/__init__.py:31 →
graphindex/signals.py:30 (import rustworkx)`.

Research for this spec found the same defect for two sibling packages on the
same import path: `networkx` (`graphindex/communities.py:31`, only pulled by
the `flowtask` extra) and `pathspec` (`graphindex/builder.py:26`, only pulled
by `black`/`mypy` in the dev group). Promoting `rustworkx` alone would move the
`ModuleNotFoundError` one import further down.

Additionally, `ai-parrot-tools` hard-imports `rustworkx` in
`parrot_tools/graphindex/toolkit.py:52` without declaring it.

### Goals

- `wikitoolkit status|query|page|related|mcp|build` import cleanly after a plain
  `uv pip install ai-parrot` (no extras).
- A bare `uv sync` in the workspace no longer removes `rustworkx`, `networkx`
  or `pathspec`.
- `ai-parrot-tools` declares every third-party package it imports at module
  level in `parrot_tools/graphindex/`.
- A regression test guards the bare-core importability of
  `parrot.knowledge.wiki.cli`.

### Non-Goals (explicitly out of scope)

- Moving the heavy, deliberately optional packages into core: `tree-sitter*`,
  `tree-sitter-languages`, `leidenalg`, `python-igraph`, `pymupdf` stay in the
  `graphindex` / `wiki-languages` / `leiden` / `wiki` extras. The probe confirmed
  `wiki.cli` imports fine without `tree_sitter`.
- Refactoring `graphindex/__init__.py` to lazy/guarded imports across the nine
  `import rustworkx` sites (the "guarded import" alternative, proposal U1-b) —
  rejected in favour of the simpler core-dependency fix; see §8.
- Changing the workspace root `dev` dependency group to include `ai-parrot[wiki]`
  (proposal U2-a) — rejected for now; the runbook documents
  `uv sync --extra wiki` instead; see §8.
- Fixing the `.mcp.json` `${CLAUDE_PROJECT_DIR}` expansion problem noted in the
  proposal — separate ticket.

---

## 2. Architectural Design

### Overview

This is a dependency-metadata fix with no runtime code changes:

1. Promote `rustworkx>=0.15`, `networkx>=3.0`, `pathspec>=0.12` from the
   `graphindex` extra into core `dependencies` of `packages/ai-parrot/pyproject.toml`,
   with a comment explaining that `wikitoolkit` ships in core and imports them
   unconditionally. Also declare `aiosqlite>=0.17` and `orjson>=3.9` in core:
   both are already installed transitively (via `asyncdb` and `navconfig`) and
   imported unguarded in `graphindex/sqlite_reader.py:23-24`, so declaring them
   makes the contract explicit instead of accidental.
2. Remove the five promoted entries from the `graphindex` extra (keeping only
   the tree-sitter grammars there) so there is one declaration per package.
   The `wiki` extra is unchanged (it composes `graphindex,wiki-languages,leiden`).
3. Declare `rustworkx>=0.15` in `packages/ai-parrot-tools/pyproject.toml`
   `dependencies` (the toolkit also uses `numpy` and `faiss`, both already
   pulled by core `faiss-cpu>=1.9.0`, `pyproject.toml:138`).
4. Regenerate `uv.lock` with `uv lock` and commit it.
5. Add a pytest that imports `parrot.knowledge.wiki.cli` in a subprocess and
   asserts every third-party module imported at module level along the chain is
   declared in core `dependencies` (a static "declared vs. imported" check that
   does not need a separate bare venv in CI).
6. Update `docs/graphindex.md` §Installation and `CLAUDE.md` wiki section to
   state that the retrieval CLI works on a core install, and that `build`
   accuracy features need `uv sync --extra wiki`.

### Component Diagram

```
uv pip install ai-parrot ──→ core dependencies ──┬─→ rustworkx   (NEW in core)
                                                 ├─→ networkx   (NEW in core)
                                                 ├─→ pathspec   (NEW in core)
                                                 ├─→ aiosqlite  (now explicit)
                                                 └─→ orjson     (now explicit)
                                                          │
wikitoolkit ─→ wiki/cli.py ─→ wiki/documents.py ─→ graphindex/__init__.py ─→ signals.py / communities.py / builder.py
                                                          │
ai-parrot[wiki] ──→ graphindex extra (tree-sitter*) + wiki-languages + leiden + pymupdf   (unchanged, optional)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` `dependencies` | modifies | adds 5 entries |
| `packages/ai-parrot/pyproject.toml` `graphindex` extra | modifies | removes the 5 promoted entries |
| `packages/ai-parrot-tools/pyproject.toml` `dependencies` | modifies | adds `rustworkx>=0.15` |
| `uv.lock` | regenerates | `uv lock` |
| `tests/knowledge/` | adds | bare-core import regression test |
| `docs/graphindex.md`, `CLAUDE.md` | modifies | install guidance |

### Data Models

None — no Python code paths change.

### New Public Interfaces

None.

---

## 3. Module Breakdown

### Module 1: Promote wikitoolkit import-path deps to core
- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: add `rustworkx>=0.15`, `networkx>=3.0`, `pathspec>=0.12`,
  `aiosqlite>=0.17`, `orjson>=3.9` to `dependencies` (after `faiss-cpu`, line 138,
  before the closing `]` at line 140) with an explanatory comment; remove those
  five entries from the `graphindex` extra (lines 212-220), leaving
  `tree-sitter>=0.23` and `tree-sitter-languages>=1.10` and the FEAT-187 comment.
- **Depends on**: none

### Module 2: Declare rustworkx in ai-parrot-tools
- **Path**: `packages/ai-parrot-tools/pyproject.toml`
- **Responsibility**: add `"rustworkx>=0.15"` to `dependencies` (lines 28-32).
- **Depends on**: none

### Module 3: Regenerate lock
- **Path**: `uv.lock`
- **Responsibility**: `source .venv/bin/activate && uv lock`; verify with
  `uv sync` (no extras) that `rustworkx`, `networkx`, `pathspec` remain installed
  and `wikitoolkit status` runs; then `uv sync --extra wiki` to restore the full
  dev environment.
- **Depends on**: Module 1, Module 2

### Module 4: Regression test
- **Path**: `tests/knowledge/test_wiki_cli_core_deps.py`
- **Responsibility**: (a) subprocess `python -c "import parrot.knowledge.wiki.cli"`
  exits 0; (b) parse `packages/ai-parrot/pyproject.toml` with `tomllib`, walk the
  module-level `import`/`from` statements (via `ast`) of the files on the chain
  listed in §6, and assert each top-level third-party module
  (`rustworkx`, `networkx`, `pathspec`, `aiosqlite`, `orjson`) maps to an entry in
  core `dependencies` — not only in an extra.
- **Depends on**: Module 1

### Module 5: Documentation
- **Path**: `docs/graphindex.md` (§Installation, line ~405), `CLAUDE.md`
  (Codebase Knowledge Graph section)
- **Responsibility**: state that `wikitoolkit` retrieval commands work on a core
  install; `uv sync --extra wiki` for tree-sitter grammars + Leiden.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_wiki_cli_imports_in_subprocess` | Module 4 | `python -c "import parrot.knowledge.wiki.cli"` returns exit 0 |
| `test_wiki_chain_third_party_imports_are_core_deps` | Module 4 | every third-party module-level import on the chain is declared in core `dependencies` |
| `test_graphindex_extra_has_no_duplicates_of_core` | Module 4 | no package appears in both core `dependencies` and the `graphindex` extra |

### Integration Tests
| Test | Description |
|---|---|
| Manual (Module 3 acceptance) | `uv sync` (no extras) → `wikitoolkit status` exits 0 |

### Test Data / Fixtures
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

---

## 5. Acceptance Criteria

- [ ] `rustworkx>=0.15`, `networkx>=3.0`, `pathspec>=0.12`, `aiosqlite>=0.17`, `orjson>=3.9` appear in core `dependencies` of `packages/ai-parrot/pyproject.toml` and are removed from the `graphindex` extra.
- [ ] `packages/ai-parrot-tools/pyproject.toml` declares `rustworkx>=0.15`.
- [ ] `uv.lock` regenerated; `uv pip show rustworkx` lists `ai-parrot` and `ai-parrot-tools` under Required-by.
- [ ] After `uv sync` with no extras, `rustworkx`, `networkx`, `pathspec` are still installed and `wikitoolkit status` exits 0.
- [ ] `python -c "import parrot.knowledge.wiki.cli"` succeeds in the bare-core environment.
- [ ] `pytest tests/knowledge/test_wiki_cli_core_deps.py -v` passes.
- [ ] `tree-sitter*`, `leidenalg`, `python-igraph`, `pymupdf` remain extras only (no new heavy core deps).
- [ ] `docs/graphindex.md` and `CLAUDE.md` install guidance updated.
- [ ] No Python source files under `packages/*/src` are modified.

---

## 6. Codebase Contract

> Verified 2026-08-28 against `dev` @ `23d816f5e`.

### Verified Imports (module-level, unguarded — the reason these must be core deps)
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:49
from parrot.knowledge.wiki.documents import ...
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:31
from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS
# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:31
from parrot.knowledge.graphindex.signals import (SignalRelevance, ...)
# packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py:30
import rustworkx
# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:31-32
import networkx as nx
import rustworkx
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py:26
import pathspec
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:16
import pathspec
# packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py:37
import pathspec
# packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:23-25
import aiosqlite
import orjson
import rustworkx as rx
# packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py:17, analytics.py:18,
# inter_community.py:19, retriever.py:32
import rustworkx
# packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py:42  (function-local — fine)
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:51-52
import numpy as np
import rustworkx
```

### Existing Declarations
```toml
# packages/ai-parrot/pyproject.toml
[project.scripts]                       # line 147
wikitoolkit = "parrot.knowledge.wiki.cli:main"

dependencies = [                        # lines 36-140; "faiss-cpu>=1.9.0" at 138, closing "]" at 140
    ...
]

graphindex = [                          # lines 212-220
    "rustworkx>=0.15",
    "networkx>=3.0",
    "tree-sitter>=0.23",
    "tree-sitter-languages>=1.10",
    "pathspec>=0.12",
    "aiosqlite>=0.17",
    "orjson>=3.9",
]
wiki = [                                # lines 251-254
    "ai-parrot[graphindex,wiki-languages,leiden]",
    "pymupdf>=1.27",
]

# packages/ai-parrot-tools/pyproject.toml   lines 28-32
dependencies = [
    "ai-parrot>=0.28.0",
    "PyGithub>=2.1",
    "ddgs>=9.5.2",
]

# pyproject.toml (workspace root) — no default extras / default-groups; `wiki = ["ai-parrot[wiki]"]` at line ~42
```

### Verified runtime facts (probes run 2026-08-28)
| Probe | Result |
|---|---|
| `sys.modules['rustworkx']=None; import parrot.knowledge.wiki.cli` | `ModuleNotFoundError` at `signals.py:30` |
| same with `networkx` | fails (`communities.py:31`) |
| same with `pathspec` | fails (`builder.py:26`) |
| same with `tree_sitter` / `tree_sitter_languages` | imports OK → stay optional |
| `uv pip show rustworkx` Required-by | (empty) |
| `uv pip show networkx` Required-by | alphashape, flowtask, osmnx, scikit-image, torch (all extras) |
| `uv pip show pathspec` Required-by | black, mypy (dev group only) |
| `uv pip show aiosqlite` / `orjson` Required-by | asyncdb / navconfig, navigator-session, python-datamodel (core-transitive) |
| Locked versions | rustworkx 0.18.1 (needs numpy only, abi3 wheels), networkx 3.4.2, pathspec 1.1.1 |

### Does NOT Exist (Anti-Hallucination)
- ~~`[tool.uv] default-groups` / default extras in the workspace root `pyproject.toml`~~ — not present; do not assume `uv sync` installs `wiki`.
- ~~`tests/knowledge/test_wiki_cli_core_deps.py`~~ — does not exist yet (Module 4 creates it).
- ~~any try/except guard around `import rustworkx` in `graphindex/`~~ — none exist; do not add one (Non-Goal).
- ~~`rustworkx` in `packages/ai-parrot-tools/pyproject.toml`~~ — absent today.
- ~~a `parrot/` directory at the repo root~~ — source root is `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Dependency comments in `packages/ai-parrot/pyproject.toml` explain *why* a
  package is core (see the `tenacity` and `semantic-text-splitter` entries,
  lines 47-50 / 60-63). Add the same style of comment for the promoted block.
- Precedent commit `e7f1dfccf fix(deps): add networkx and pymupdf to wiki/graphindex extras`.
- Always `source .venv/bin/activate` before `uv lock` / `uv sync` / `pytest`.

### Known Risks / Gotchas
- `uv sync` **without** `--extra wiki` will uninstall tree-sitter grammars and
  leiden from the developer env while verifying Module 3 — restore with
  `uv sync --extra wiki` afterwards.
- `uv lock` may touch unrelated lock entries if upstream released new versions;
  review `git diff --stat uv.lock` and prefer `uv lock` (not `uv lock --upgrade`).
- `numpy` is not in core `dependencies` explicitly either (pulled via `pandas`);
  `rustworkx` requires it, so the lock will satisfy it — no action needed.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `rustworkx` | `>=0.15` (locked 0.18.1) | `PyDiGraph` backbone of graphindex; imported by `wikitoolkit` on every subcommand |
| `networkx` | `>=3.0` | `communities.py` Louvain fallback, module-level import |
| `pathspec` | `>=0.12` | gitignore matching in `builder.py` / `extractors/code.py` |
| `aiosqlite` | `>=0.17` | already transitive via asyncdb; made explicit |
| `orjson` | `>=3.9` | already transitive via navconfig; made explicit |

---

## 8. Open Questions

- [x] **U1 — Core dependency vs. guarded import?** — *Resolved by default (proposal recommendation, autonomous run)*: **core dependency**. `wikitoolkit` ships in core, the wheels are small and numpy-only, and a guard would need a choke point across nine import sites. Override by editing §1 Non-Goals / §2 before approval. — *Owner: Jesus Lara*
- [x] **U2 — Should developer `uv sync` include `ai-parrot[wiki]` by default?** — *Resolved by default*: **no**; document `uv sync --extra wiki` (Module 5). Adding it to the `dev` group would force tree-sitter grammars + igraph on every contributor. — *Owner: Jesus Lara*
- [ ] Should `numpy` also be declared explicitly in core (currently only transitive via `pandas`)? Decide during Module 1; harmless either way. — *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: per-spec — a single worktree `feat-471-add-rustworkx-dependency`,
  tasks sequential (Modules 1-2 → 3 → 4-5).
- **Parallelizable**: Module 4 (test) and Module 5 (docs) can proceed in parallel
  after Module 1, but the feature is small enough that sequential execution is
  simpler.
- **Cross-feature dependencies**: none. Any other in-flight feature that edits
  `packages/ai-parrot/pyproject.toml` or `uv.lock` (e.g. FEAT-470) will conflict
  on merge — rebase this branch last or first, not mid-way.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-28 | Jesus Lara (via Claude Code) | Initial draft from proposal FEAT-471 |
