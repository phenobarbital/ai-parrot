# TASK-2552: Update wikitoolkit install guidance (docs/graphindex.md, CLAUDE.md)

**Feature**: FEAT-471 — Add rustworkx (and the wikitoolkit import-path deps) as real core dependencies
**Spec**: `sdd/specs/add-rustworkx-dependency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2549
**Assigned-to**: unassigned

---

## Context

After TASK-2549 the `wikitoolkit` retrieval commands (`status|query|page|
related|mcp`) work on a plain core install; only `build`'s accuracy features
(tree-sitter grammars, Leiden) need the `wiki` extra. Documentation should say
so, and tell contributors that a bare `uv sync` removes those extras.
Implements spec §3 Module 5 (open question U2 resolved: document
`uv sync --extra wiki`, do not change the dev group).

---

## Scope

- `docs/graphindex.md` §Installation (heading at line 405): add a short
  paragraph/table stating:
  - core install (`uv pip install ai-parrot`) is enough for the wikitoolkit
    retrieval CLI and the MCP server (`rustworkx`, `networkx`, `pathspec` are
    core deps as of FEAT-471);
  - `pip install ai-parrot[wiki]` / `uv sync --extra wiki` for `wikitoolkit build`
    with tree-sitter language grammars and Leiden communities;
  - a bare `uv sync` in the workspace uninstalls those extras — re-run
    `uv sync --extra wiki`.
- `CLAUDE.md` "Codebase Knowledge Graph (LLM Wiki)" section: add one sentence
  after the `wikitoolkit build` bullet noting that query/page/related/status work
  on a core install and that `build` needs `uv sync --extra wiki`.

**NOT in scope**: pyproject/lock/test changes (other tasks); the `.mcp.json`
`${CLAUDE_PROJECT_DIR}` expansion issue (separate ticket); rewriting the
graphindex docs beyond the Installation section.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/graphindex.md` | MODIFY | §Installation — core vs `wiki` extra guidance |
| `CLAUDE.md` | MODIFY | one-line note in the LLM Wiki section |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-28 against `dev` @ `d172e4d56`.

### Anchors
```markdown
# docs/graphindex.md:405
## Installation

# CLAUDE.md (section "## Codebase Knowledge Graph (LLM Wiki)")
- `wikitoolkit build` — refresh the graph after large changes
  (a git post-commit hook may already keep it fresh).
```

### Extras that stay optional (do not document them as core)
```toml
graphindex      = tree-sitter>=0.23, tree-sitter-languages>=1.10   # after TASK-2549
wiki-languages  = per-language tree-sitter scanners (FEAT-394)
leiden          = leidenalg / python-igraph
wiki            = ai-parrot[graphindex,wiki-languages,leiden] + pymupdf>=1.27
# workspace root pyproject.toml:41   wiki = ["ai-parrot[wiki]"]  → `uv sync --extra wiki`
```

### Does NOT Exist
- ~~`uv sync` installing the `wiki` extra by default~~ — no default extras/groups in the root pyproject.
- ~~`ai-parrot[all]` including `wiki`~~ — verify before claiming; do not mention `[all]` unless checked in `packages/ai-parrot/pyproject.toml`.
- ~~a `docs/wikitoolkit.md` page~~ — the wiki CLI docs live in `docs/graphindex.md`; do not create a new page.

---

## Implementation Notes

### Key Constraints
- Match the existing tone/format of `docs/graphindex.md` (fenced bash blocks,
  short prose).
- Keep the `CLAUDE.md` addition to 1-2 lines — that file is loaded into every
  session's context.
- Mention FEAT-471 once as the reason, no changelog prose.

### References in Codebase
- `docs/graphindex.md:405` — Installation section
- `CLAUDE.md` — "Codebase Knowledge Graph (LLM Wiki)" section

---

## Acceptance Criteria

- [ ] `docs/graphindex.md` §Installation states core install suffices for retrieval CLI + MCP, and `uv sync --extra wiki` / `ai-parrot[wiki]` for `build`
- [ ] `docs/graphindex.md` warns that bare `uv sync` removes the wiki extras
- [ ] `CLAUDE.md` LLM Wiki section carries the 1-2 line note
- [ ] no files under `packages/*/src` modified; only the two docs files in the diff

---

## Test Specification

Documentation-only; verify by reading the diff:

```bash
git diff --stat            # exactly docs/graphindex.md and CLAUDE.md
grep -n "uv sync --extra wiki" docs/graphindex.md CLAUDE.md
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2549 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the section anchors still exist
4. **Update status** in `sdd/tasks/index/add-rustworkx-dependency.json` → `"in-progress"`
5. **Implement** following the scope
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2552-wikitoolkit-install-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
