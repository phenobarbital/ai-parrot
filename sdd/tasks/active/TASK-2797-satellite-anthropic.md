# TASK-2797: Satellite Package — ai-parrot-client-anthropic

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract the Anthropic client family from core into the
`ai-parrot-client-anthropic` satellite package. Implements spec Module 3.
After TASK-2795 lands the factory refactor, this task moves the concrete
Anthropic client files and sets up the PEP 420 package structure with
entry-point declarations.

The `bedrock` and `anthropic-aws` entry points map to `AnthropicClient` —
the `PROVIDER_BACKEND` dict in core `factory.py` injects a `backend=` kwarg
before construction, so these entry points resolve to the same class but
with different initialization parameters.

---

## Scope

- Create package directory structure at `packages/ai-parrot-client-anthropic/`:
  ```
  packages/ai-parrot-client-anthropic/
  ├── pyproject.toml
  └── src/
      └── parrot/         # NO __init__.py (PEP 420)
          └── clients/    # NO __init__.py (PEP 420)
              ├── claude.py
              ├── claude_agent.py
              ├── claude_agent_bridge.py
              └── anthropic_backends.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/claude.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/claude_agent.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/anthropic_backends.py` → satellite
- Create `pyproject.toml` with:
  - `name = "ai-parrot-client-anthropic"`, `version = "0.1.0"`
  - `dependencies = ["ai-parrot", "anthropic[aiohttp]>=0.109.0,<1.0.0", "claude-agent-sdk>=0.1.68"]`
  - Entry points: `claude`, `anthropic`, `bedrock`, `anthropic-aws`,
    `claude-agent`, `claude-code`
  - `namespaces = true` in setuptools config
- Place `.gitkeep` files at `src/parrot/` and `src/parrot/clients/` (no `__init__.py`)
- Verify imports still work via namespace merging

**NOT in scope**: modifying `factory.py` (done in TASK-2795), updating core
`pyproject.toml` extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-anthropic/pyproject.toml` | CREATE | Package metadata, deps, entry points |
| `packages/ai-parrot-client-anthropic/src/parrot/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/claude.py` | CREATE (move) | AnthropicClient |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/claude_agent.py` | CREATE (move) | ClaudeAgentClient |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/claude_agent_bridge.py` | CREATE (move) | ClaudeAgentBridge |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic_backends.py` | CREATE (move) | Anthropic backend helpers |
| `packages/ai-parrot/src/parrot/clients/claude.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/anthropic_backends.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These imports come FROM the files being moved:
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59

# This is the class being moved:
from parrot.clients.claude import AnthropicClient  # clients/claude.py:69
```

### Existing Signatures to Use
```python
# parrot/clients/claude.py:69 — being moved
class AnthropicClient(AbstractClient):
    # Direct AbstractClient subclass (NOT OpenAIBaseClient)

# parrot/clients/factory.py:155 — stays in core, NOT modified by this task
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}
# Injects backend= kwarg into AnthropicClient init for bedrock/anthropic-aws keys
```

### Does NOT Exist
- ~~`parrot/clients/anthropic.py`~~ — the file is named `claude.py`, not `anthropic.py`
- ~~`AnthropicClient` in `openai_base.py`~~ — `AnthropicClient` inherits `AbstractClient` directly, NOT `OpenAIBaseClient`

---

## Implementation Notes

### Pattern to Follow
```toml
# pyproject.toml — follow ai-parrot-embeddings pattern
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-anthropic"
version = "0.1.0"
dependencies = [
    "ai-parrot",
    "anthropic[aiohttp]>=0.109.0,<1.0.0",
    "claude-agent-sdk>=0.1.68",
]

[project.entry-points."parrot.clients"]
claude = "parrot.clients.claude:AnthropicClient"
anthropic = "parrot.clients.claude:AnthropicClient"
bedrock = "parrot.clients.claude:AnthropicClient"
anthropic-aws = "parrot.clients.claude:AnthropicClient"
claude-agent = "parrot.clients.claude_agent:ClaudeAgentClient"
claude-code = "parrot.clients.claude_agent:ClaudeAgentClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- NO `__init__.py` at `src/parrot/` or `src/parrot/clients/` — PEP 420 namespace merging
- All imports from `AbstractClient` must reference core (it stays in core)
- The moved files must not change their internal import paths for core dependencies
- Entry-point keys must match what was in `SUPPORTED_CLIENTS`
- `bedrock` and `anthropic-aws` entry points both map to `AnthropicClient` —
  the core `PROVIDER_BACKEND` dict handles the `backend=` kwarg injection
  before the class is instantiated

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — reference satellite pyproject.toml
- `packages/ai-parrot-embeddings/src/parrot/` — reference PEP 420 directory structure
- `packages/ai-parrot/src/parrot/clients/factory.py:155` — PROVIDER_BACKEND dict

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-anthropic/` exists with correct structure
- [ ] `pyproject.toml` declares entry points for `claude`, `anthropic`, `bedrock`, `anthropic-aws`, `claude-agent`, `claude-code`
- [ ] Source files moved from core to satellite
- [ ] `from parrot.clients.claude import AnthropicClient` works when satellite installed
- [ ] No `__init__.py` at namespace levels (PEP 420)
- [ ] `uv pip install -e packages/ai-parrot-client-anthropic` succeeds
- [ ] `PROVIDER_BACKEND` injection for `bedrock`/`anthropic-aws` still works (backend= kwarg injected correctly)

---

## Test Specification

```python
# Verified manually:
# uv pip install -e packages/ai-parrot-client-anthropic
# python -c "from parrot.clients.claude import AnthropicClient; print(AnthropicClient)"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pep-420-llm-clients.spec.md` for full context
2. **Check dependencies** — verify TASK-2795 is completed
3. **Verify the Codebase Contract** — confirm source files still exist at listed paths
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2797-satellite-anthropic.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
