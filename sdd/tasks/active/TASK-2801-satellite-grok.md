# TASK-2801: Satellite Package — ai-parrot-client-grok

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `GrokClient` from core into the `ai-parrot-client-grok` satellite
package. Part of spec Module 6 (standalone providers). Single-file satellite.

---

## Scope

- Create `packages/ai-parrot-client-grok/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-grok/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              └── grok.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/grok.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original file from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-grok/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-grok/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-grok/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-grok/src/parrot/clients/grok.py` | CREATE (move) | GrokClient |
| `packages/ai-parrot/src/parrot/clients/grok.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # clients/base.py:230
```

### Existing Signatures to Use
```python
# parrot/clients/grok.py:53
class GrokClient(AbstractClient):
    ...
```

### Does NOT Exist
- ~~`parrot.clients.xai`~~ — the file is named `grok.py`, not `xai.py`

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-grok"
version = "0.1.0"
dependencies = ["ai-parrot", "xai-sdk>=1.12.0"]

[project.entry-points."parrot.clients"]
grok = "parrot.clients.grok:GrokClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-grok/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `grok` entry point
- [ ] `grok.py` moved from core to satellite
- [ ] `from parrot.clients.grok import GrokClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-grok` succeeds

---

## Completion Note

*(Agent fills this in when done)*
