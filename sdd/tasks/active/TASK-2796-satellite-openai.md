# TASK-2796: Satellite Package — ai-parrot-client-openai

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract the OpenAI client family from core into the `ai-parrot-client-openai`
satellite package. Implements spec Module 2. After TASK-2795 lands the factory
refactor, this task moves the concrete OpenAI client files and sets up the
PEP 420 package structure with entry-point declarations.

---

## Scope

- Create package directory structure at `packages/ai-parrot-client-openai/`:
  ```
  packages/ai-parrot-client-openai/
  ├── pyproject.toml
  └── src/
      └── parrot/         # NO __init__.py (PEP 420)
          └── clients/    # NO __init__.py (PEP 420)
              ├── gpt.py
              ├── codex_agent.py
              └── codex_tool_bridge.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/gpt.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/codex_agent.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/codex_tool_bridge.py` → satellite
- Create `pyproject.toml` with:
  - `name = "ai-parrot-client-openai"`, `version = "0.1.0"`
  - `dependencies = ["ai-parrot", "openai==3.3.1"]`
  - Entry points: `openai`, `codex-agent`, `openai-codex`, `codex-code`
  - `namespaces = true` in setuptools config
- Place `.gitkeep` files at `src/parrot/` and `src/parrot/clients/` (no `__init__.py`)
- Verify imports still work via namespace merging

**NOT in scope**: modifying `factory.py` (done in TASK-2795), updating core
`pyproject.toml` extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-openai/pyproject.toml` | CREATE | Package metadata, deps, entry points |
| `packages/ai-parrot-client-openai/src/parrot/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-openai/src/parrot/clients/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-openai/src/parrot/clients/gpt.py` | CREATE (move) | OpenAIClient |
| `packages/ai-parrot-client-openai/src/parrot/clients/codex_agent.py` | CREATE (move) | OpenAICodexClient |
| `packages/ai-parrot-client-openai/src/parrot/clients/codex_tool_bridge.py` | CREATE (move) | Codex tool bridge |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/codex_agent.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/codex_tool_bridge.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These imports come FROM the files being moved:
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59

# This is the class being moved:
from parrot.clients.gpt import OpenAIClient  # clients/gpt.py:81
```

### Existing Signatures to Use
```python
# parrot/clients/gpt.py:81 — being moved
class OpenAIClient(OpenAIBaseClient):
    # Inherits from OpenAIBaseClient which stays in core

# parrot/clients/openai_base.py:59 — stays in core
class OpenAIBaseClient(AbstractClient):
    # Shared base for OpenAI-compatible clients
```

### Does NOT Exist
- ~~`parrot/clients/openai.py`~~ — the file is named `gpt.py`, not `openai.py`
- ~~`OpenAIClient` in `openai_base.py`~~ — `openai_base.py` contains `OpenAIBaseClient` (abstract base)

---

## Implementation Notes

### Pattern to Follow
```toml
# pyproject.toml — follow ai-parrot-embeddings pattern
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-openai"
version = "0.1.0"
dependencies = ["ai-parrot", "openai==3.3.1"]

[project.entry-points."parrot.clients"]
openai = "parrot.clients.gpt:OpenAIClient"
codex-agent = "parrot.clients.codex_agent:OpenAICodexClient"
openai-codex = "parrot.clients.codex_agent:OpenAICodexClient"
codex-code = "parrot.clients.codex_agent:OpenAICodexClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- NO `__init__.py` at `src/parrot/` or `src/parrot/clients/` — PEP 420 namespace merging
- All imports from `AbstractClient` and `OpenAIBaseClient` must reference core (these stay in core)
- The moved files must not change their internal import paths for core dependencies
- Entry-point keys must match what was in `SUPPORTED_CLIENTS`

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — reference satellite pyproject.toml
- `packages/ai-parrot-embeddings/src/parrot/` — reference PEP 420 directory structure

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-openai/` exists with correct structure
- [ ] `pyproject.toml` declares entry points for `openai`, `codex-agent`, etc.
- [ ] Source files moved from core to satellite
- [ ] `from parrot.clients.gpt import OpenAIClient` works when satellite installed
- [ ] No `__init__.py` at namespace levels (PEP 420)
- [ ] `uv pip install -e packages/ai-parrot-client-openai` succeeds

---

## Test Specification

```python
# Verified manually:
# uv pip install -e packages/ai-parrot-client-openai
# python -c "from parrot.clients.gpt import OpenAIClient; print(OpenAIClient)"
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
7. **Move this file** to `sdd/tasks/completed/TASK-2796-satellite-openai.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
