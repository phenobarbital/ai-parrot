---
type: Wiki Overview
title: 'TASK-1378: Write migration guide for FEAT-203'
id: doc:sdd-tasks-completed-task-1378-migration-guide-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 14. Documents the extraction for users and developers,
  following the proven format established by FEAT-201's migration guide.
relates_to:
- concept: mod:parrot.security.credentials_utils
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
---

# TASK-1378: Write migration guide for FEAT-203

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1376
**Assigned-to**: unassigned

## Context
Implements Module 14. Documents the extraction for users and developers, following the proven format established by FEAT-201's migration guide.

## Scope
- Create `docs/migration/feat-203-ai-parrot-server.md` documenting:
  - What moved, what stayed (summary table)
  - Install surface changes (before/after)
  - Backward-compatible import redirects (vault_utils, credentials_utils)
  - Server-only bots (github_reviewer, jira_specialist require ai-parrot-server)
  - `parrot-fs` entry point now in ai-parrot-server
  - vault_utils relocation to `parrot/security/`
  - MCP consolidation (`services/mcp/` merged into `mcp/`)
- Follow the format of `docs/migration/feat-201-ai-parrot-embeddings.md`

**NOT in scope**: Code changes.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `docs/migration/feat-203-ai-parrot-server.md` | CREATE | Migration documentation |

## Codebase Contract (Anti-Hallucination)

### Reference Document
```
# Reference: docs/migration/feat-201-ai-parrot-embeddings.md
# Proven migration doc format — follow this structure
```

### What Moved to Satellite (Summary for Doc)
| Module | Host Location | Satellite Location | Task |
|---|---|---|---|
| MCP server | `parrot/mcp/` (server files) | `parrot/mcp/` | TASK-1369 |
| MCP services | `parrot/services/mcp/` | `parrot/mcp/` (consolidated) | TASK-1369 |
| A2A server | `parrot/a2a/` (server files) | `parrot/a2a/` | TASK-1370 |
| HTTP handlers | `parrot/handlers/` | `parrot/handlers/` | TASK-1371 |
| Bot manager | `parrot/manager/` | `parrot/manager/` | TASK-1372 |
| Services | `parrot/services/` | `parrot/services/` | TASK-1373 |
| Scheduler | `parrot/scheduler/` | `parrot/scheduler/` | TASK-1374 |
| Autonomous | `parrot/autonomous/` | `parrot/autonomous/` | TASK-1375 |

### What Stayed in Host
- `parrot/bots/` — all bot implementations
- `parrot/clients/` — all LLM provider clients
- `parrot/tools/` — all tool definitions
- `parrot/loaders/` — document loaders
- `parrot/memory/` — conversation memory
- `parrot/mcp/client.py`, `parrot/mcp/oauth.py` (client-side only)
- `parrot/a2a/client.py` (client-side only)
- `parrot/security/` — vault_utils relocated here

### Backward-Compatible Redirects
- `from parrot.utils.vault_utils import ...` redirects to `parrot.security.vault_utils`
- `from parrot.utils.credentials_utils import ...` redirects to `parrot.security.credentials_utils`

### Server-Only Bots
- `github_reviewer.py` — imports `@schedule_daily_report` / `@schedule_weekly_report`
- `jira_specialist.py` — imports scheduler decorators

## Implementation Notes

### Step-by-Step Procedure
1. Read the reference migration doc:
   ```bash
   cat docs/migration/feat-201-ai-parrot-embeddings.md
   ```
2. Create `docs/migration/feat-203-ai-parrot-server.md` following the same structure:
   - Title and overview
   - What changed (summary table)
   - Install surface changes (before/after examples)
   - Import path changes
   - Backward compatibility
   - Server-only components
   - FAQ / troubleshooting
3. Ensure all items listed in Scope are covered

### Document Structure (based on FEAT-201 format)
```markdown
# Migrating to ai-parrot-server (FEAT-203)

## Overview
Brief description of the extraction.

## What Changed
Summary table of moved modules.

## Installation
Before/after install commands.

## Import Changes
Any import path changes users need to know.

## Backward Compatibility
Lazy __getattr__ redirects, deprecation timeline.

## Server-Only Components
Bots and features that now require ai-parrot-server.

## MCP Consolidation
services/mcp/ merged into mcp/.

## Security Module
vault_utils relocation.

## FAQ
Common questions and answers.
```

### Key Constraints
- Follow the exact format of `docs/migration/feat-201-ai-parrot-embeddings.md`
- Be accurate about what moved and what stayed — do not guess
- Include concrete `pip install` / `uv add` examples
- Mention that PEP 420 namespace merging makes imports transparent

## Acceptance Criteria
- [ ] Migration guide exists at `docs/migration/feat-203-ai-parrot-server.md`
- [ ] Covers all items listed in Scope (what moved, install changes, redirects, server-only bots, parrot-fs, vault_utils, MCP consolidation)
- [ ] Before/after install examples are correct
- [ ] Server-only bots clearly documented
- [ ] Follows the format of `docs/migration/feat-201-ai-parrot-embeddings.md`

## Test Specification
```python
def test_migration_guide_exists():
    """Migration guide file exists."""
    import pathlib
    guide = pathlib.Path("docs/migration/feat-203-ai-parrot-server.md")
    assert guide.exists(), "Migration guide missing"

def test_migration_guide_covers_key_topics():
    """Migration guide covers required topics."""
    import pathlib
    content = pathlib.Path("docs/migration/feat-203-ai-parrot-server.md").read_text()
    required_topics = [
        "ai-parrot-server",
        "vault_utils",
        "parrot-fs",
        "MCP",
        "schedule",
        "AgentService",
        "BotManager",
        "pip install",
    ]
    for topic in required_topics:
        assert topic in content, f"Migration guide missing topic: {topic}"
```

## Agent Instructions
1. Read `docs/migration/feat-201-ai-parrot-embeddings.md` to understand the reference format.
2. Create the migration guide following the structure outlined in Implementation Notes.
3. Cross-reference all task files (TASK-1365 through TASK-1377) to ensure accuracy.
4. Do not make any code changes — this is a documentation-only task.
5. Commit with message: `sdd: add migration guide for ai-parrot-server (FEAT-203)`

## Completion Note
*(Agent fills this in when done)*
