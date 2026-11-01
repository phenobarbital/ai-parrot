# TASK-5085: mcp-local import-failure hint derived from the missing module, not a hard-coded [scraping]/[browsing]

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5084
**Assigned-to**: unassigned
**Discovered-from**: `issue:cd2ac1cb1153`

---

## Context

`create_toolkit_mcp_server` (`parrot/mcp/toolkit_server.py`) appends
`Try: uv pip install ai-parrot-tools[scraping] or ai-parrot-tools[browsing]` to every import
failure of a `parrot_tools` class. `[browsing]` does not exist, and `[scraping]` is wrong for most
toolkits (finance needs `ta-lib`, rss needs `feedparser`). Discovered by FEAT-763; fixed here because
the file is already open on this branch.

## Scope

- Add `_extra_hint(exc: ImportError, class_path: str) -> str` in `mcp/toolkit_server.py`:
  read `importlib.metadata.requires("ai-parrot-tools")`, match the missing top-level module
  (`exc.name`) against each requirement name (normalized: lower-case, `-`/`.` → `_`), and collect the
  `extra == "<x>"` markers (excluding the aggregate `all`). One or more matches →
  `Try: uv pip install "ai-parrot-tools[<x>]"` (alternatives joined with ` or `). No match, no
  metadata or no `exc.name` → a generic hint naming the missing module and pointing at the
  `ai-parrot-tools` extras. Non-`parrot_tools` class paths keep no hint.
- Never mention `[browsing]`.

**NOT in scope**: an import-name ↔ distribution-name alias table (e.g. `talib` vs `ta-lib`) — such
modules fall back to the generic hint.

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
- `tests/mcp/test_toolkit_server.py`

## Codebase Contract

- `create_toolkit_mcp_server(name, root=None, *, login_file=None, **overrides)` — the `except ImportError` branch near the class resolution.
- `packages/ai-parrot-tools/pyproject.toml` — has no `browsing` extra; `rss = ["feedparser>=6.0.11", ...]`.

## Acceptance Criteria

- [ ] A missing `feedparser` yields a hint naming `ai-parrot-tools[rss]`.
- [ ] An unknown missing module yields the generic hint; no hint ever names `[browsing]`.
- [ ] A non-`parrot_tools` class path gets no hint.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest -q tests/mcp/test_toolkit_server.py
```

## Completion Note

Implemented in `224d39b68b`. 7 new tests pass (`-k "extra_hint or derived_hint"`); `ruff check` clean.

- Hint source is the installed `ai-parrot-tools` metadata (`importlib.metadata.requires`), so it
  follows the pyproject extras table with no copy to drift. A dependency listed by several extras
  (e.g. `docker`) lists each one; `[all]` is never suggested.
- Import-name/distribution-name mismatches (`talib` vs `ta-lib`) get the generic hint, as scoped.
- `ruff --fix` rewrote one existing `setattr(mock, "StubToolkit", ...)` line in the test file (B010).
- The file's 12 existing tests that use `mock_import_module` still fail with RecursionError, on `dev`
  too (`issue:203c75e0c1ac`). The new tests do not use that mock.
