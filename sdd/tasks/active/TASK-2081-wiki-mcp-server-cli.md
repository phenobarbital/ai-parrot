# TASK-2081: Create WikiToolkit MCP server + CLI command

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2078, TASK-2080
**Assigned-to**: unassigned

---

## Context

This task creates the entry point that wires wiki tools into a
`StdioMCPServer` and adds a CLI command (`wikitoolkit mcp`) to start it.
This is the glue between the core MCP infrastructure (Phase 1) and
the wiki tools (TASK-2080).

Implements spec Module 6.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` with:
  - `create_wiki_mcp_server(root: Path) -> StdioMCPServer` factory
  - `main()` entry point
- Add `mcp` subcommand to `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- Write integration test (subprocess-based)

**NOT in scope**: Installer integration (TASK-2082). Wiki tools themselves (TASK-2080).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | CREATE | MCP server factory + main |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Add `mcp` subcommand |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Core MCP (from TASK-2078)
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig

# Wiki tools (from TASK-2080)
from parrot.knowledge.wiki.tools import create_wiki_tools

# Wiki infrastructure
from parrot.knowledge.wiki.store import create_wiki_store  # verified: store.py:1217
from parrot.knowledge.wiki.project import find_project_root, load_project_config  # verified: project.py:239,266

# CLI framework
import click  # verified: cli.py uses click throughout
```

### Existing CLI Structure
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
# The main group is `@click.group()` named `wiki`
# Subcommands: build, upsert, query, page, related, communities, status, export
# New `mcp` command goes here

# Entry points (pyproject.toml):
# wikitoolkit = parrot.knowledge.wiki.cli:wiki
# So `wikitoolkit mcp` → the new click command
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.mcp_server`~~ — does not exist yet; this task creates it
- ~~`wikitoolkit mcp` command~~ — does not exist yet; this task adds it

---

## Implementation Notes

### Factory Function
```python
def create_wiki_mcp_server(root: Path) -> StdioMCPServer:
    config = load_project_config(root)
    store = create_wiki_store(
        storage_dir=root / ".parrot",
        wiki_name=config.wiki_name,
        backend=config.backend,
    )
    tools = create_wiki_tools(store)
    server = StdioMCPServer(LocalServerConfig(
        name="wikitoolkit",
        version="1.0.0",
        description="Codebase knowledge graph — query, explore, and remember",
    ))
    server.register_tools(tools)
    return server
```

### CLI Command
```python
@wiki.command()
def mcp():
    """Start wikitoolkit as a local MCP stdio server."""
    from parrot.knowledge.wiki.mcp_server import main as mcp_main
    mcp_main()
```

### main() Entry Point
```python
def main():
    import sys
    root = find_project_root(Path.cwd())
    if root is None:
        print("Error: not inside a git repository with a wiki", file=sys.stderr)
        sys.exit(1)
    server = create_wiki_mcp_server(root)
    asyncio.run(server.start())
```

### Key Constraints
- `main()` must log to stderr only (stdout is the MCP channel)
- Configure logging to stderr before starting the server
- `find_project_root()` returns `None` if not in a git repo — handle gracefully

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server` works
- [ ] `wikitoolkit mcp` starts and responds to JSON-RPC `initialize`
- [ ] `wikitoolkit mcp` responds to `tools/list` with 6 wiki tools
- [ ] `wikitoolkit mcp` responds to `tools/call` with correct results
- [ ] Exits gracefully when stdin closes (EOF)
- [ ] Exits with error if not in a git repo with a wiki
- [ ] Integration test passes
- [ ] No output on stdout except JSON-RPC responses

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py
import pytest
import json
import subprocess
import sys
from pathlib import Path


class TestWikiMCPServerIntegration:
    """Start wikitoolkit mcp as subprocess and send JSON-RPC requests."""

    @pytest.mark.asyncio
    async def test_initialize_and_list_tools(self, tmp_path):
        # This test requires a wiki to be built.
        # For CI, we may need to create a minimal wiki first.
        # Skip if wikitoolkit is not available.
        pass  # implementer: flesh out with subprocess + stdin/stdout pipes

    def test_not_in_repo_exits_with_error(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "parrot.knowledge.wiki.mcp_server"],
            cwd=str(tmp_path),
            capture_output=True, text=True, timeout=5
        )
        assert result.returncode != 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2078 and TASK-2080 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm CLI structure and imports
4. **Read `cli.py`** to understand the click group structure before adding the `mcp` command
5. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2081-wiki-mcp-server-cli.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
