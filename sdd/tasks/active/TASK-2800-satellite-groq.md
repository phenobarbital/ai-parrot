# TASK-2800: Satellite Package — ai-parrot-client-groq

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `GroqClient` from core into the `ai-parrot-client-groq` satellite
package. Part of spec Module 6 (standalone providers). Single-file satellite.

---

## Scope

- Create `packages/ai-parrot-client-groq/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-groq/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              └── groq.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/groq.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original file from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-groq/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-groq/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-groq/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq.py` | CREATE (move) | GroqClient |
| `packages/ai-parrot/src/parrot/clients/groq.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
```

### Existing Signatures to Use
```python
# parrot/clients/groq.py:50
class GroqClient(OpenAIBaseClient):
    ...
```

### Does NOT Exist
- ~~`parrot.clients.groq_base`~~ — no separate base for Groq

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-groq"
version = "0.1.0"
dependencies = ["ai-parrot", "groq==0.33.0"]

[project.entry-points."parrot.clients"]
groq = "parrot.clients.groq:GroqClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-groq/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `groq` entry point
- [ ] `groq.py` moved from core to satellite
- [ ] `from parrot.clients.groq import GroqClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-groq` succeeds

---

## Completion Note

*(Agent fills this in when done)*
