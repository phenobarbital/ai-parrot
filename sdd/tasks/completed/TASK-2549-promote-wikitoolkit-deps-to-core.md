# TASK-2549: Promote wikitoolkit import-path deps to core `dependencies`

**Feature**: FEAT-471 — Add rustworkx (and the wikitoolkit import-path deps) as real core dependencies
**Spec**: `sdd/specs/add-rustworkx-dependency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`wikitoolkit` ships in core `ai-parrot` (`[project.scripts]`) but its import
chain (`wiki/cli.py → wiki/documents.py → graphindex/__init__.py → signals.py`)
imports `rustworkx`, `networkx`, `pathspec`, `aiosqlite`, `orjson` unguarded at
module level. Those are only declared in the optional `graphindex` extra, so a
plain `uv pip install ai-parrot` or a bare `uv sync` leaves the CLI crashing with
`ModuleNotFoundError`. `ai-parrot-tools` has the same defect for `rustworkx`
(`parrot_tools/graphindex/toolkit.py:52`).

Implements spec §3 Module 1 and Module 2. Pure dependency-metadata change.

---

## Scope

- In `packages/ai-parrot/pyproject.toml` `[project] dependencies`, add — after
  `"navigator-eventbus>=0.2.1"` and before the closing `]` — with an explanatory
  comment in the style of the `tenacity` entry:
  ```toml
    # wikitoolkit ships in core (project.scripts) and its import chain
    # (wiki/cli.py → graphindex/__init__.py → signals.py / communities.py /
    # builder.py / sqlite_reader.py) imports these unconditionally at module
    # level, so a bare install must carry them (FEAT-471).
    "rustworkx>=0.15",
    "networkx>=3.0",
    "pathspec>=0.12",
    "aiosqlite>=0.17",
    "orjson>=3.9",
  ```
- Remove those same five entries from the `graphindex` extra, leaving exactly
  `"tree-sitter>=0.23"` and `"tree-sitter-languages>=1.10"` plus the existing
  FEAT-187 comments.
- In `packages/ai-parrot-tools/pyproject.toml` `dependencies`, add
  `"rustworkx>=0.15"` after `"ddgs>=9.5.2"`.
- Decide spec §8 open question: `numpy` is NOT declared in core (pulled via
  `pandas`); `rustworkx` requires it and the resolver satisfies it. Default:
  do **not** add `numpy` explicitly. Record the decision in the Completion Note.

**NOT in scope**: running `uv lock` / `uv sync` (TASK-2550), tests (TASK-2551),
docs (TASK-2552), any change under `packages/*/src`, touching the `wiki`,
`wiki-languages` or `leiden` extras.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | add 5 deps to core; remove them from `graphindex` extra |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | add `rustworkx>=0.15` to `dependencies` |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-28 against `dev` @ `d172e4d56`.

### Verified Imports (the reason these must be core deps — do NOT modify these files)
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:49
from parrot.knowledge.wiki.documents import (...)
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:31
from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS
# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:31
from parrot.knowledge.graphindex.signals import (...)
# graphindex/signals.py:30 / assemble.py:17 / analytics.py:18 / inter_community.py:19 / retriever.py:32
import rustworkx
# graphindex/communities.py:31-32
import networkx as nx
import rustworkx
# graphindex/builder.py:26 / cli.py:37 / extractors/code.py:16
import pathspec
# graphindex/sqlite_reader.py:23-25
import aiosqlite
import orjson
import rustworkx as rx
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:52
import rustworkx
```

### Existing Declarations to Edit
```toml
# packages/ai-parrot/pyproject.toml
dependencies = [                      # starts line 36
    ...
    # Episodic memory default backend (FAISS) — required whenever an agent
    # enables episodic memory without an explicit pgvector DSN.
    "faiss-cpu>=1.9.0",               # ~line 139
    "navigator-eventbus>=0.2.1",      # ~line 140  ← insert new block after this
]

[project.scripts]                     # ~line 143
wikitoolkit = "parrot.knowledge.wiki.cli:main"

# GraphIndex knowledge graph indexing (FEAT-187)
# Note: faiss-cpu is already in core dependencies — not included here
graphindex = [                        # ~lines 212-220
    "rustworkx>=0.15",                # REMOVE
    "networkx>=3.0",                  # REMOVE
    "tree-sitter>=0.23",              # KEEP
    "tree-sitter-languages>=1.10",    # KEEP
    "pathspec>=0.12",                 # REMOVE
    "aiosqlite>=0.17",                # REMOVE
    "orjson>=3.9",                    # REMOVE
]
wiki = [                              # ~lines 251-254 — UNCHANGED
    "ai-parrot[graphindex,wiki-languages,leiden]",
    "pymupdf>=1.27",
]

# packages/ai-parrot-tools/pyproject.toml   lines 28-32
dependencies = [
    "ai-parrot>=0.28.0",
    "PyGithub>=2.1",
    "ddgs>=9.5.2",
]
```

### Comment style to copy (`packages/ai-parrot/pyproject.toml:46-49`)
```toml
    # parrot.clients.base → clients/gpt.py imports tenacity unconditionally,
    # so it must be a core dependency (a bare install could not import
    # parrot.clients without it).
    "tenacity>=8.2",
```

### Does NOT Exist
- ~~`"numpy"` entry in core `dependencies`~~ — absent; only transitive via `pandas`. Do not assume it is declared.
- ~~`[tool.uv] default-groups` / default extras in root `pyproject.toml`~~ — not present; `uv sync` installs no extras.
- ~~any try/except guard around `import rustworkx` in `graphindex/`~~ — none; do NOT add one (spec Non-Goal).
- ~~`rustworkx` in `packages/ai-parrot-tools/pyproject.toml`~~ — absent today.
- ~~a `parrot/` directory at the repo root~~ — source root is `packages/ai-parrot/src/parrot/`.

---

## Implementation Notes

### Key Constraints
- One declaration per package: after this task, none of the five appears in
  both core `dependencies` and the `graphindex` extra.
- Keep the existing `# GraphIndex knowledge graph indexing (FEAT-187)` and
  `# Note: faiss-cpu ...` comments on the extra.
- Do NOT run `uv lock`/`uv sync` here — TASK-2550 does, so the lock diff is a
  separate, reviewable commit.
- Precedent: commit `e7f1dfccf fix(deps): add networkx and pymupdf to wiki/graphindex extras`.

### References in Codebase
- `packages/ai-parrot/pyproject.toml` lines 46-49, 137-139 — comment style
- `sdd/specs/add-rustworkx-dependency.spec.md` §6 — full contract and probes

---

## Acceptance Criteria

- [ ] `rustworkx>=0.15`, `networkx>=3.0`, `pathspec>=0.12`, `aiosqlite>=0.17`, `orjson>=3.9` present in core `dependencies` of `packages/ai-parrot/pyproject.toml`
- [ ] the same five entries absent from the `graphindex` extra; `tree-sitter>=0.23` and `tree-sitter-languages>=1.10` remain
- [ ] `packages/ai-parrot-tools/pyproject.toml` declares `rustworkx>=0.15`
- [ ] `tree-sitter*`, `leidenalg`, `python-igraph`, `pymupdf` still extras-only
- [ ] both files parse: `python -c "import tomllib,sys; [tomllib.load(open(p,'rb')) for p in sys.argv[1:]]" packages/ai-parrot/pyproject.toml packages/ai-parrot-tools/pyproject.toml`
- [ ] `git diff --stat` shows only the two pyproject files
- [ ] no files under `packages/*/src` modified

---

## Test Specification

No new test file in this task (TASK-2551 adds the regression test). Verify with:

```bash
source .venv/bin/activate
python - <<'PY'
import tomllib
core = tomllib.load(open("packages/ai-parrot/pyproject.toml","rb"))
deps = core["project"]["dependencies"]
gi = core["project"]["optional-dependencies"]["graphindex"]
names = lambda xs: {d.split(">")[0].split("=")[0].split("<")[0].strip().lower() for d in xs}
for p in ("rustworkx","networkx","pathspec","aiosqlite","orjson"):
    assert p in names(deps), p
    assert p not in names(gi), p
assert names(gi) == {"tree-sitter","tree-sitter-languages"}
tools = tomllib.load(open("packages/ai-parrot-tools/pyproject.toml","rb"))
assert "rustworkx" in names(tools["project"]["dependencies"])
print("OK")
PY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the extras block and line numbers before editing; update the contract first if they moved
4. **Update status** in `sdd/tasks/index/add-rustworkx-dependency.json` → `"in-progress"`
5. **Implement** following the scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2549-promote-wikitoolkit-deps-to-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (include the `numpy` decision)

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-08-28
**Notes**: Added the explanatory comment block + five deps
(`rustworkx>=0.15`, `networkx>=3.0`, `pathspec>=0.12`, `aiosqlite>=0.17`,
`orjson>=3.9`) to `packages/ai-parrot/pyproject.toml` core `dependencies`
(after `navigator-eventbus`), removed the same five from the `graphindex`
extra (kept `tree-sitter`/`tree-sitter-languages` + a note pointing at
FEAT-471), and added `rustworkx>=0.15` to
`packages/ai-parrot-tools/pyproject.toml`. Spec §8 open question on
`numpy`: left undeclared in core, per the default resolution — it is
only pulled in transitively via `pandas` today and `rustworkx`'s own
requirement is satisfied by the resolver; no action needed. Verified
both files parse with `tomllib` and the acceptance-criteria assertion
script passes.

**Deviations from spec**: none
