---
type: Wiki Overview
title: 'TASK-1376: Update host pyproject.toml — extras redistribution'
id: doc:sdd-tasks-completed-task-1376-update-host-pyproject-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 12. After all moves are complete, the host `pyproject.toml`
  must be updated to remove server-only extras and add the satellite reference.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.cli
  rel: mentions
---

# TASK-1376: Update host pyproject.toml — extras redistribution

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1369, TASK-1370, TASK-1371, TASK-1372, TASK-1373, TASK-1374, TASK-1375
**Assigned-to**: unassigned

## Context
Implements Module 12. After all moves are complete, the host `pyproject.toml` must be updated to remove server-only extras and add the satellite reference.

## Scope
- Remove `scheduler` optional extra (lines 163-165: `apscheduler==3.11.2`) from host
- Remove `parrot-fs` from `[project.scripts]`
- Add `server = ["ai-parrot-server[all]"]` convenience extra
- Rewrite `all` meta-extra to include `ai-parrot-server[all]`
- Audit and optionally remove server-only deps from core `[project.dependencies]`: candidates are `aioquic==1.3.0` and `pylsqpack==0.3.23` — verify no core consumer remains
- Verify `uv sync --all-packages` succeeds after changes

**NOT in scope**: Modifying satellite pyproject.toml (done in TASK-1365).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Extras redistribution |

## Codebase Contract (Anti-Hallucination)

### Verified Structure
```toml
# pyproject.toml [project.optional-dependencies]
# scheduler extra (lines 163-165):
scheduler = [
    "apscheduler==3.11.2",
]

# pyproject.toml [project.scripts] (lines 97-99):
[project.scripts]
parrot = "parrot.main:main"
parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"

# pyproject.toml all meta-extra (lines 473-478):
# aggregates all extras + satellite packages

# pyproject.toml [project.dependencies]:
# aioquic==1.3.0 (line 75)
# pylsqpack==0.3.23 (line 76)
```

### Does NOT Exist
- ~~`server` extra~~ — does not exist yet; created by this task
- ~~`ai-parrot-server` reference in host pyproject.toml~~ — added by this task

## Implementation Notes

### Step-by-Step Procedure
1. Read the full host `pyproject.toml` to understand current structure
2. Remove the `scheduler` optional extra section:
   ```toml
   # DELETE these lines:
   scheduler = [
       "apscheduler==3.11.2",
   ]
   ```
3. Remove `parrot-fs` from `[project.scripts]`:
   ```toml
   # BEFORE:
   [project.scripts]
   parrot = "parrot.main:main"
   parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"

   # AFTER:
   [project.scripts]
   parrot = "parrot.main:main"
   ```
4. Add `server` convenience extra:
   ```toml
   server = [
       "ai-parrot-server[all]",
   ]
   ```
5. Update `all` meta-extra to include `ai-parrot-server[all]`:
   ```toml
   all = [
       # ... existing extras ...
       "ai-parrot-server[all]",
   ]
   ```
6. Audit `aioquic` and `pylsqpack` — grep the host source tree for imports:
   ```bash
   grep -rn "import aioquic\|from aioquic" packages/ai-parrot/src/parrot/
   grep -rn "import pylsqpack\|from pylsqpack" packages/ai-parrot/src/parrot/
   ```
   If only consumed by moved files (e.g., MCP transports/quic.py), remove from host `[project.dependencies]` and ensure they are in satellite's dependencies instead.
7. Run `uv sync --all-packages` to verify everything resolves

### Key Constraints
- Do NOT modify satellite pyproject.toml — that is TASK-1365
- The `all` meta-extra must continue to pull in all other extras (embeddings, integrations, visualizations, etc.)
- `parrot` console_script must remain in host
- Verify no circular dependency between host and satellite packages

## Acceptance Criteria
- [ ] `scheduler` extra removed from host
- [ ] `parrot-fs` removed from host `[project.scripts]`
- [ ] `server` extra exists: `["ai-parrot-server[all]"]`
- [ ] `all` meta-extra includes `ai-parrot-server[all]`
- [ ] `uv sync --all-packages` succeeds
- [ ] `pip install ai-parrot[all]` pulls ai-parrot-server

## Test Specification
```python
def test_scheduler_extra_removed():
    """scheduler extra no longer in host pyproject.toml."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("packages/ai-parrot/pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    assert "scheduler" not in extras, "scheduler extra should be removed"

def test_parrot_fs_removed_from_scripts():
    """parrot-fs no longer in host [project.scripts]."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("packages/ai-parrot/pyproject.toml").read_text())
    scripts = data.get("project", {}).get("scripts", {})
    assert "parrot-fs" not in scripts, "parrot-fs should be removed"

def test_server_extra_exists():
    """server extra references ai-parrot-server[all]."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("packages/ai-parrot/pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    assert "server" in extras
    assert any("ai-parrot-server" in dep for dep in extras["server"])

def test_all_extra_includes_server():
    """all meta-extra includes ai-parrot-server[all]."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("packages/ai-parrot/pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    all_deps = extras.get("all", [])
    assert any("ai-parrot-server" in dep for dep in all_deps)

def test_parrot_script_remains():
    """parrot console_script still in host."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("packages/ai-parrot/pyproject.toml").read_text())
    scripts = data.get("project", {}).get("scripts", {})
    assert "parrot" in scripts
```

## Agent Instructions
1. Read the full host `pyproject.toml` before making changes.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. Run the `aioquic`/`pylsqpack` audit grep before deciding to remove them.
4. Run `source .venv/bin/activate && uv sync --all-packages` to verify after changes.
5. Commit with message: `sdd: update host pyproject.toml extras for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
