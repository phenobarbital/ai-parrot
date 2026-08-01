# TASK-2068: Optional Dependencies, CLI Subcommand & Install Docs

**Feature**: FEAT-401 — Leiden Community Detection & Inter-Community Relations
**Spec**: `sdd/specs/leiden-community-detection-and-inter-community-relations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2065
**Assigned-to**: unassigned

---

## Context

This task adds the `leiden` optional extra to `pyproject.toml`, adds a
`wikitoolkit communities --inter` CLI subcommand for on-demand
inter-community queries, and documents install instructions.

Implements Spec §3 Module 5. Can run in parallel with TASK-2066 and
TASK-2067 since it only depends on the inter-community model (TASK-2065).

---

## Scope

- Add `leiden` optional extra to `packages/ai-parrot/pyproject.toml`
  with `leidenalg>=0.10` and `python-igraph>=0.10`.
- Add a `communities --inter` flag (or `communities-inter` subcommand)
  to the `wikitoolkit` CLI that:
  1. Loads the current `CommunitiesResult` from the built graph state.
  2. Computes `compute_inter_community_graph()` on demand.
  3. Outputs a token-budgeted summary: community pairs, edge counts,
     coupling ratios, density. Format suitable for LLM consumption.
- Add install instructions as a docstring in `communities.py` and/or
  a short section in existing docs.
- Write basic tests for the CLI subcommand.

**NOT in scope**:
- Leiden algorithm (TASK-2064)
- Inter-community model (TASK-2065)
- Builder/analytics integration (TASK-2066)
- HTML export (TASK-2067)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `leiden` optional extra |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Add `communities --inter` CLI subcommand |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` | MODIFY | Add CLI subcommand test (if CLI tests exist) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# pyproject.toml — existing optional extras structure (line 131)
# [project.optional-dependencies]
# graphindex = ["rustworkx>=0.15", "tree-sitter>=0.23", ...]

# CLI
# wikitoolkit CLI is at:
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py

# Inter-community (from TASK-2065)
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityGraph,
    compute_inter_community_graph,
)

from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,
)
```

### Existing Signatures to Use

```python
# pyproject.toml — optional extras pattern (line 131-194):
# [project.optional-dependencies]
# graphindex = [
#     "rustworkx>=0.15",
#     "tree-sitter>=0.23",
#     "tree-sitter-languages>=1.10",
#     "pathspec>=0.12",
#     "aiosqlite>=0.17",
#     "orjson>=3.9",
# ]

# cli.py — wikitoolkit CLI entry point
# Uses argparse or click (verify before implementing)
# parrot-graphindex = "parrot.knowledge.graphindex.cli:main" (pyproject line 126)
# wikitoolkit CLI is separate: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
```

### Does NOT Exist

- ~~`leiden` optional extra in pyproject.toml~~ — does not exist yet
- ~~`wikitoolkit communities --inter` CLI subcommand~~ — does not exist yet
- ~~`leidenalg` in any existing dependency list~~ — not present

---

## Implementation Notes

### Pattern to Follow

```toml
# pyproject.toml — add alongside existing extras:
leiden = [
    "leidenalg>=0.10",
    "python-igraph>=0.10",
]
```

```python
# cli.py — add a communities subcommand (follow existing CLI patterns):
# The exact CLI framework (argparse/click) should be verified by reading
# the existing cli.py. Add --inter flag to an existing communities
# command, or add a new one if none exists.
#
# Output format for LLM consumption:
# Inter-Community Relations (density: 45.0%)
# | Auth ↔ Payment | 12→, 8← | coupling: 0.34 |
# | Auth ↔ Users   |  5→, 3← | coupling: 0.21 |
```

### Key Constraints

- The `leiden` extra should NOT be included in any existing meta-extra
  (like `all`) by default — it's a heavy C dependency. Users opt in.
- The CLI subcommand needs access to the built graph. Check how the
  existing `wikitoolkit` CLI loads graph state (likely from a persisted
  SQLite or ArangoDB store, or from the `.parrot/` directory).
- Keep CLI output token-budgeted — this is consumed by LLM agents, not
  humans. Compact table format, no verbose headers.

### References in Codebase

- `pyproject.toml:131` — `[project.optional-dependencies]` section
- `pyproject.toml:187` — `graphindex` extra (pattern to follow)
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — wikitoolkit CLI

---

## Acceptance Criteria

- [ ] `pip install ai-parrot[leiden]` installs `leidenalg` and `python-igraph`
- [ ] `leiden` extra is NOT pulled by default or by any existing meta-extra
- [ ] `wikitoolkit communities --inter` outputs inter-community relations summary
- [ ] CLI output is token-budgeted (compact table, no verbose prose)
- [ ] CLI gracefully handles case where no communities have been computed
- [ ] No regression in existing pyproject.toml extras
- [ ] No linting errors in modified files

---

## Test Specification

```python
# Basic verification tests

def test_leiden_extra_in_pyproject():
    """The leiden extra is defined in pyproject.toml."""
    import tomllib
    with open("packages/ai-parrot/pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    extras = data["project"]["optional-dependencies"]
    assert "leiden" in extras
    assert any("leidenalg" in dep for dep in extras["leiden"])
    assert any("igraph" in dep for dep in extras["leiden"])

# CLI tests depend on the CLI framework — verify and write accordingly
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2065 is in `sdd/tasks/completed/`
3. **Read** `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` to understand the CLI framework and existing subcommands
4. **Verify the Codebase Contract** — confirm `InterCommunityGraph` exists
5. **Update status** in the per-spec index → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2068-optional-deps-cli-docs.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
