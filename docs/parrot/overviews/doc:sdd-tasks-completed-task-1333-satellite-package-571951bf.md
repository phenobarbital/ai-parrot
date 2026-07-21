---
type: Wiki Overview
title: 'TASK-1333: Scaffold the ai-parrot-embeddings satellite package (PEP 420)'
id: doc:sdd-tasks-completed-task-1333-satellite-package-scaffold-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 1** of the spec — scaffolds the empty
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.version
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
---

# TASK-1333: Scaffold the ai-parrot-embeddings satellite package (PEP 420)

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements **Module 1** of the spec — scaffolds the empty
satellite package. Every other task depends on this one because they
either move files into the satellite or modify the satellite's
pyproject. Critically, this is where the **pure PEP 420** decision
(resolved question U3) gets locked into the wheel layout.

Reference: spec §2 Architectural Design, §3 Module 1, §5 Acceptance
Criteria (rows 1-4, 23-24).

---

## Scope

- Create `packages/ai-parrot-embeddings/` with:
  - `pyproject.toml` declaring `name = "ai-parrot-embeddings"`,
    `dependencies = ["ai-parrot"]`,
    `[tool.setuptools.packages.find]` with
    `where = ["src"]`, `include = ["parrot*"]`, `namespaces = true`,
    `[tool.uv.sources] ai-parrot = { workspace = true }`.
  - `README.md` (1-paragraph stub; Module 9 will expand it).
  - `src/parrot/` (empty directory, **no `__init__.py`**)
  - `src/parrot/embeddings/` (empty, **no `__init__.py`**)
  - `src/parrot/stores/` (empty, **no `__init__.py`**)
  - `src/parrot/rerankers/` (empty, **no `__init__.py`**)
  - `tests/` (empty test root)
- Verify `uv sync --all-packages` from repo root succeeds and installs
  both `ai-parrot` and `ai-parrot-embeddings` in editable mode.
- Verify `python -c "import parrot; print(parrot.__file__)"` still
  resolves to the **host** `parrot/__init__.py` (not the satellite —
  the satellite has no `__init__.py`).

**NOT in scope**:
- Moving any backend code (Modules 2-4 will do that).
- Declaring per-backend extras (Modules 2-4 add them as their backends
  arrive).
- Wheel-content verification test (Module 6 / TASK-1338).
- Touching the root `pyproject.toml` — it already declares
  `[tool.uv.workspace] members = ["packages/*"]` (line 43-44) so the
  new package is **auto-discovered**.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/pyproject.toml` | CREATE | Satellite project metadata + namespace-aware setuptools config |
| `packages/ai-parrot-embeddings/README.md` | CREATE | 1-paragraph stub describing the package and the install pattern |
| `packages/ai-parrot-embeddings/src/parrot/` | CREATE | Empty directory (no `__init__.py`) |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/` | CREATE | Empty directory (no `__init__.py`) |
| `packages/ai-parrot-embeddings/src/parrot/stores/` | CREATE | Empty directory (no `__init__.py`) |
| `packages/ai-parrot-embeddings/src/parrot/rerankers/` | CREATE | Empty directory (no `__init__.py`) |
| `packages/ai-parrot-embeddings/tests/__init__.py` | CREATE | Empty marker so pytest treats `tests/` as a package |

> Note: directories under `src/parrot/` MUST NOT contain any
> `__init__.py`. If you need a placeholder, use a `.gitkeep` file —
> NEVER `__init__.py`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (for reference; not used in this task)

```python
# Host package metadata version source — satellite pyproject does NOT
# reuse this; satellite has its own dynamic version
from parrot.version import __version__  # verified: packages/ai-parrot/src/parrot/version.py
```

### Verified Existing Files (model the satellite after these)

```toml
# packages/ai-parrot-tools/pyproject.toml — closest precedent
# Reuse this shape EXCEPT for the [tool.setuptools.packages.find] block
# which must use parrot* + namespaces=true instead of parrot_tools*

[build-system]
requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-tools"
dynamic = ["version"]
requires-python = ">=3.11"
dependencies = [
    "ai-parrot>=0.24.56",
    "PyGithub>=2.1",
]

[tool.setuptools.dynamic]
version = {attr = "parrot_tools.__version__"}     # ← SATELLITE DIFFERS: see Implementation Notes

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot_tools*"]                       # ← SATELLITE DIFFERS: include = ["parrot*"] + namespaces = true

[tool.uv.sources]
ai-parrot = { workspace = true }
```

```toml
# packages/ai-parrot/pyproject.toml:529-532 — host already declares namespaces=true
[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

```toml
# pyproject.toml (repo root) lines 43-44 — workspace auto-discovers
[tool.uv.workspace]
members = ["packages/*"]
```

### Does NOT Exist (Anti-Hallucination)

- ~~`packages/ai-parrot-embeddings/src/parrot/__init__.py`~~ — MUST
  NOT be created. Pure PEP 420 (resolved question U3).
- ~~`packages/ai-parrot-embeddings/src/parrot/embeddings/__init__.py`~~,
  ~~`.../stores/__init__.py`~~, ~~`.../rerankers/__init__.py`~~ — same.
- ~~`packages/ai-parrot-embeddings/src/parrot_embeddings/`~~ — the new
  package does NOT use a separate top-level. Unlike `ai-parrot-tools`
  (which ships under `parrot_tools.*`), FEAT-201 contributes directly
  to `parrot.*` via PEP 420.
- ~~`tool.setuptools.dynamic` reading from `parrot_embeddings.__version__`~~
  — won't work because there's no `parrot_embeddings` module. Use a
  different version-source (see Implementation Notes).

---

## Implementation Notes

### Version source for the satellite

The satellite has no top-level `__init__.py` to attach `__version__`
to. Options (pick one in the spec — recommended: literal string
initially, dynamic via VCS later):

```toml
# OPTION A (recommended for first cut): literal string
[project]
name = "ai-parrot-embeddings"
version = "0.1.0"
# (and remove dynamic = ["version"])

# OPTION B (later): setuptools_scm
# Adds a build-system req on setuptools_scm; pulls version from git tags
```

### Suggested README.md content (stub)

```markdown
# ai-parrot-embeddings

Concrete backend implementations for the AI-Parrot retrieval stack:
embedding models, vector stores, and rerankers.

This package contributes modules directly to the `parrot.*` namespace
(via PEP 420 implicit namespace packages), so existing imports such as
`from parrot.stores.pgvector import PgVectorStore` continue to work
byte-identically once installed.

## Install

```bash
# Core framework only (no backends)
pip install ai-parrot

# Add specific backends
pip install ai-parrot-embeddings[pgvector,milvus,huggingface]

# Everything
pip install ai-parrot-embeddings[all]
```

See `docs/migration/feat-201-ai-parrot-embeddings.md` for the migration
guide.
```

### Suggested pyproject.toml shape

```toml
[build-system]
requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-embeddings"
version = "0.1.0"
description = "Concrete embedding, vector-store, and reranker backends for AI-Parrot"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [
    {name = "Jesus Lara", email = "jesuslara@phenobarbital.info"}
]
keywords = ["ai", "rag", "embeddings", "vector-store", "rerankers"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Operating System :: POSIX :: Linux",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3 :: Only",
    "Framework :: AsyncIO",
    "Typing :: Typed",
]
dependencies = [
    "ai-parrot",      # satellite needs base/registries/abstracts from core
]

[project.optional-dependencies]
# Per-backend extras are added by Modules 2/3/4 (TASK-1334/1335/1336).
# `all` will aggregate them.

[project.urls]
Homepage = "https://github.com/phenobarbital/ai-parrot"
Source = "https://github.com/phenobarbital/ai-parrot"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true

[tool.uv.sources]
ai-parrot = { workspace = true }
```

### Constraints

- Do NOT create any `__init__.py` under `src/parrot/`. Use `.gitkeep`
  if you need git to track empty directories.
- Do NOT touch the root `pyproject.toml`. Workspace membership is
  auto-discovered.
- Do NOT touch the host `packages/ai-parrot/pyproject.toml` — that's
  TASK-1337's job.

### References in Codebase

- `packages/ai-parrot-tools/pyproject.toml` — closest precedent
  (per-backend extras + workspace dep). Reuse the shape, diverge on
  package-discovery to enable PEP 420.
- `packages/ai-parrot/pyproject.toml:529-532` — proof that
  `namespaces = true` is the right setuptools incantation.
- `pyproject.toml:43-44` (repo root) — workspace member glob.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-embeddings/pyproject.toml` exists and is
  valid TOML.
- [ ] `packages/ai-parrot-embeddings/src/parrot/` exists.
- [ ] `packages/ai-parrot-embeddings/src/parrot/{embeddings,stores,rerankers}/`
  all exist.
- [ ] **No `__init__.py` exists** at any of:
  `src/parrot/`, `src/parrot/embeddings/`, `src/parrot/stores/`,
  `src/parrot/rerankers/`. Verify with:
  `find packages/ai-parrot-embeddings/src/parrot -name __init__.py | grep .`
  — must produce **zero** lines of output.
- [ ] `packages/ai-parrot-embeddings/README.md` exists (stub OK).
- [ ] `packages/ai-parrot-embeddings/tests/__init__.py` exists.
- [ ] `uv sync --all-packages` from repo root succeeds with no error.
- [ ] Post-sync: `pip show ai-parrot-embeddings` reports the new
  package as installed in editable mode.
- [ ] Post-sync: `python -c "import parrot; print(parrot.__file__)"`
  returns a path inside `packages/ai-parrot/src/parrot/__init__.py`
  (host owns the `__init__.py`).
- [ ] Post-sync: `python -c "import parrot.embeddings; print(parrot.embeddings.__path__)"`
  shows a path list with **at least the host's** embeddings dir; if
  the satellite directory is also in `__path__` even though it has no
  modules yet, that's also acceptable (PEP 420 merging).

---

## Test Specification

A minimal smoke test placed at
`packages/ai-parrot-embeddings/tests/test_scaffold.py`:

```python
# packages/ai-parrot-embeddings/tests/test_scaffold.py
import importlib
from pathlib import Path

import pytest


def test_satellite_pyproject_exists():
    """The satellite's pyproject is present and parses."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    assert pyproject.exists(), f"missing {pyproject}"
    # Sanity: contains the expected name and namespace config
    text = pyproject.read_text(encoding="utf-8")
    assert 'name = "ai-parrot-embeddings"' in text
    assert "namespaces = true" in text
    assert 'include = ["parrot*"]' in text


def test_no_init_at_namespace_levels():
    """U3 (pure PEP 420): satellite has no __init__.py at four namespace levels."""
    src_parrot = Path(__file__).parent.parent / "src" / "parrot"
    forbidden = [
        src_parrot / "__init__.py",
        src_parrot / "embeddings" / "__init__.py",
        src_parrot / "stores" / "__init__.py",
        src_parrot / "rerankers" / "__init__.py",
    ]
    offenders = [p for p in forbidden if p.exists()]
    assert offenders == [], f"unexpected __init__.py files: {offenders}"


def test_parrot_resolves_to_host():
    """The host owns parrot.__init__; satellite does not shadow it."""
    importlib.invalidate_caches()
    import parrot
    assert "ai-parrot/src/parrot/__init__.py" in parrot.__file__
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ai-parrot-embeddings.spec.md` —
   especially §2 (Architectural Design) and §6 (Codebase Contract).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-confirm:
   - `pyproject.toml:43-44` still has the workspace members glob.
   - `packages/ai-parrot/pyproject.toml:529-532` still has
     `namespaces = true`.
4. **Update status** in `sdd/tasks/index/ai-parrot-embeddings.json`
   → `"in-progress"` with your session ID.
5. **Implement** following the scope, contract, and notes above. Use
   `.gitkeep` for empty directories — NEVER `__init__.py`.
6. **Verify** all acceptance criteria. Run `uv sync --all-packages`
   yourself and confirm both packages install. Run the smoke test.
7. **Move this file** to `sdd/tasks/completed/TASK-1333-satellite-package-scaffold.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: Scaffold created successfully. Editable pip install installs both
`ai-parrot` and `ai-parrot-embeddings`. `uv sync --all-packages` from the
workspace root has a pre-existing dependency conflict (google-genai version
mismatch in the `gemma4` extra) unrelated to FEAT-201. All 3 scaffold smoke
tests pass. PEP 420 namespace merging is verified — parrot resolves to host.

**Deviations from spec**: `uv sync --all-packages` has a pre-existing workspace
conflict not caused by this task; used `uv pip install -e` as workaround for
the sync step. PEP 420 namespace merging confirmed working via direct tests.
