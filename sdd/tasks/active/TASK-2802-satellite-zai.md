# TASK-2802: Satellite Package — ai-parrot-client-zai

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `ZaiClient` from core into the `ai-parrot-client-zai` satellite
package. Part of spec Module 6 (standalone providers). Single-file satellite.
Note: the `ZaiClient` import in `parrot/clients/__init__.py` is removed in
TASK-2795 (hard cut, no deprecation shim).

---

## Scope

- Create `packages/ai-parrot-client-zai/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-zai/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              └── zai.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/zai.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original file from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-zai/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-zai/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-zai/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-zai/src/parrot/clients/zai.py` | CREATE (move) | ZaiClient |
| `packages/ai-parrot/src/parrot/clients/zai.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
```

### Existing Signatures to Use
```python
# parrot/clients/zai.py:22
class ZaiClient(OpenAIBaseClient):
    ...
```

### Does NOT Exist
- ~~`from parrot.clients import ZaiClient`~~ — removed from `__init__.py` in TASK-2795

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-zai"
version = "0.1.0"
dependencies = ["ai-parrot", "zai-sdk>=0.2.3"]

[project.entry-points."parrot.clients"]
zai = "parrot.clients.zai:ZaiClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-zai/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `zai` entry point
- [ ] `zai.py` moved from core to satellite
- [ ] `from parrot.clients.zai import ZaiClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-zai` succeeds

---

## Completion Note

*(Agent fills this in when done)*
