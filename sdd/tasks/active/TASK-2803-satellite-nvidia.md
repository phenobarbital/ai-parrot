# TASK-2803: Satellite Package — ai-parrot-client-nvidia

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `NvidiaClient` from core into the `ai-parrot-client-nvidia` satellite
package. Part of spec Module 6 (standalone providers). Single-file satellite.
`NvidiaClient` extends `OpenAIBaseClient` (which stays in core) and needs
no new SDK dependency.

---

## Scope

- Create `packages/ai-parrot-client-nvidia/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-nvidia/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              └── nvidia.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/nvidia.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original file from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-nvidia/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-nvidia/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-nvidia/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-nvidia/src/parrot/clients/nvidia.py` | CREATE (move) | NvidiaClient |
| `packages/ai-parrot/src/parrot/clients/nvidia.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
```

### Existing Signatures to Use
```python
# parrot/clients/nvidia.py:222
class NvidiaClient(OpenAIBaseClient):
    # Uses OpenAI-compatible API via OpenAIBaseClient — no separate SDK
    ...
```

### Does NOT Exist
- ~~`nvidia-sdk`~~ — NvidiaClient uses no NVIDIA-specific SDK; it talks via OpenAI-compatible endpoints

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-nvidia"
version = "0.1.0"
dependencies = ["ai-parrot"]

[project.entry-points."parrot.clients"]
nvidia = "parrot.clients.nvidia:NvidiaClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- No extra SDK dependency — NvidiaClient uses OpenAI-compatible endpoints
  through `OpenAIBaseClient` which stays in core

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-nvidia/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `nvidia` entry point
- [ ] `nvidia.py` moved from core to satellite
- [ ] `from parrot.clients.nvidia import NvidiaClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-nvidia` succeeds

---

## Completion Note

*(Agent fills this in when done)*
